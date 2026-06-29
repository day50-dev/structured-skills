#!/usr/bin/env python3
import os
import sys
import io
import json
import re
import logging
import contextlib
import http.server
import urllib.parse
from pathlib import Path
from openai import OpenAI
from ss.config import load_config
from ss.agent_create import _fix_script, _name_from_prompt
from ss.decoder import Decoder, parse_input_specs, parse_output_specs, preprocess_lines

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SRC = PROJECT / "src"
sys.path.insert(0, str(SRC))

from ss.vm import VM

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── .env loading ──────────────────────────────────────────────
def _load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("\"'")
        os.environ.setdefault(key, val)

_load_dotenv(PROJECT / ".env")

# ── STRUSKY_OPTS ──────────────────────────────────────────────
_raw_opts = os.environ.get("STRUSKY_OPTS", "")
STRUSKY_OPTS = {opt.strip() for opt in _raw_opts.split(",") if opt.strip()}

def _git_auto_commit(message: str):
    if "git" not in STRUSKY_OPTS:
        return
    try:
        import subprocess
        subprocess.run(["git", "add", "-A"], cwd=str(PROJECT), capture_output=True)
        result = subprocess.run(
            ["git", "commit", "--allow-empty", "-m", message],
            cwd=str(PROJECT), capture_output=True, text=True,
        )
        if result.returncode == 0:
            logger.info("git commit: %s", message)
        elif "nothing to commit" not in result.stderr:
            logger.debug("git commit skipped: %s", result.stderr.strip())
    except Exception as exc:
        logger.warning("git auto-commit failed: %s", exc)

PORT = int(os.environ.get("PORT", 5555))
AGENTS_DIR_ARG = os.environ.get("AGENTS_DIR")
if AGENTS_DIR_ARG:
    AGENTS_DIR = Path(AGENTS_DIR_ARG).resolve()
else:
    AGENTS_DIR = HERE / "agents"
AGENTS_DIR.mkdir(exist_ok=True)

_GUIDE_CACHE = None

def _load_guide() -> str:
    global _GUIDE_CACHE
    if _GUIDE_CACHE is None:
        p = PROJECT / "docs/guide.md"
        if p.exists():
            _GUIDE_CACHE = p.read_text()
        else:
            _GUIDE_CACHE = ""
    return _GUIDE_CACHE

_MODIFY_SYSTEM = """You are modifying an ss (Structured Skills) script.
Output your changes as structured edits. Each edit replaces an exact piece of text in the original script with new text.

Format:
<edit>
<old>
precise text from the ORIGINAL SCRIPT to replace
</old>
<new>
replacement text
</new>
</edit>

Rules:
- <old> must match the ORIGINAL SCRIPT exactly (same whitespace & casing)
- Include enough surrounding lines so <old> matches uniquely
- Make minimal edits — only change what the instruction asks for
- Output multiple <edit> blocks for separate changes
- NEVER output the entire script — only edit blocks
- Preserve all code that should not change

LANGUAGE REFERENCE:
{guide}

ORIGINAL SCRIPT:
{script}

INSTRUCTION: {instruction}"""


def discover_agents():
    agents = {}
    seen = set()
    for d in [AGENTS_DIR, PROJECT / "examples", PROJECT]:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix == ".ss" and f.stem not in seen:
                seen.add(f.stem)
                try:
                    rel = f.relative_to(PROJECT)
                except ValueError:
                    rel = f
                agents[str(rel)] = {
                    "name": f.stem,
                    "path": str(rel),
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                }
    return agents


def _resolve_agent_path(name: str) -> Path | None:
    scripts_to_try = [
        AGENTS_DIR / f"{name}.ss",
        PROJECT / "examples" / f"{name}.ss",
        PROJECT / f"{name}.ss",
    ]
    for p in scripts_to_try:
        if p.exists():
            return p
    for rel, info in discover_agents().items():
        if info["name"] == name or info["path"] == name:
            return PROJECT / info["path"]
    return None


def read_agent(path_str):
    p = PROJECT / path_str
    if not p.exists() or p.suffix != ".ss":
        return None
    return p.read_text()


def write_agent(name, content, *, message=None):
    dest = AGENTS_DIR / f"{name}.ss"
    dest.write_text(content)
    _git_auto_commit(message or f"strusky: add/edit agent {name}")
    return dest


def delete_agent(name):
    dest = AGENTS_DIR / f"{name}.ss"
    if dest.exists():
        dest.unlink()
        _git_auto_commit(f"strusky: delete agent {name}")
        return True
    return False


_CREATE_SYSTEM = """You are an ss (Structured Skills) code generator. Write a complete .ss script that fulfills the user's request.

LANGUAGE REFERENCE:
{guide}

Rules:
- Use $prompt for input and write the final answer back to $prompt
- infer prompts must be imperative, direct, 1-3 sentences
- Use %name.verb key=value syntax for MCP tool calls
- Every def must have a matching end
- Every if/for must have a matching end
- Output ONLY the complete .ss script, no explanations, no markdown formatting

USER REQUEST: {prompt}"""

def create_agent_via_llm(prompt):
    config = load_config(str(PROJECT / "config.toml"))["decoder"]
    client = OpenAI(base_url=config["base_url"], api_key=config["api_key"] or "none", timeout=120)
    guide = _load_guide()
    response = client.chat.completions.create(
        model=config["model"],
        messages=[{"role": "system", "content": _CREATE_SYSTEM.format(guide=guide, prompt=prompt)}],
    )
    usage = getattr(response, "usage", None)
    tokens = {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens, "total": usage.total_tokens} if usage else None
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    script = "# prompt: " + prompt.replace("\n", " ") + "\n\n" + _fix_script(raw.strip())
    name = _name_from_prompt(prompt)
    return name, script, tokens


def run_agent(name, prompt_text="", inputs=None):
    script_path = _resolve_agent_path(name)
    if not script_path:
        return None, None, "Agent not found", ""

    original_lines = script_path.read_text().splitlines()
    config_path = str(PROJECT / "config.toml")

    # Parse input specs from the script
    specs = parse_input_specs(original_lines)

    # Build register assignment lines
    assign_lines = []
    if specs and inputs:
        for spec in specs:
            val = inputs.get(spec.name, "")
            if spec.type == "file" and val:
                path = val.strip()
                if os.path.isfile(path):
                    val = Path(path).read_text()
            assign_lines.append(f'${spec.name} = "{_escape(val)}"')
    elif prompt_text:
        assign_lines.append(f'$prompt = "{_escape(prompt_text)}"')
    elif not specs:
        assign_lines.append(f'$prompt = ""')

    lines = assign_lines + original_lines

    decoder = Decoder(config_path=config_path)
    program = []
    imports = []
    for line in lines:
        s = line.strip()
        if s.startswith("import "):
            imports.append(s)
    ctx = "\n".join(imports)
    for line in preprocess_lines(lines):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("input "):
            continue
        program.extend(decoder.decode_line(s, imports_context=ctx))

    vm = VM(config_path=config_path)
    vm.load_program(program)

    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        vm.run()
    progress = buf.getvalue()

    registers = {reg: str(val) for reg, val in vm.registers.items()}
    return registers, vm.token_usage, None, progress


def run_code(code_text, inputs=None):
    lines = code_text.splitlines()
    config_path = str(PROJECT / "config.toml")

    specs = parse_input_specs(lines)

    assign_lines = []
    if specs and inputs:
        for spec in specs:
            val = inputs.get("$" + spec.name, inputs.get(spec.name, ""))
            if spec.type == "file" and val:
                path = val.strip()
                if os.path.isfile(path):
                    val = Path(path).read_text()
            assign_lines.append(f'${spec.name} = "{_escape(val)}"')
    elif inputs and "$prompt" in inputs:
        assign_lines.append(f'$prompt = "{_escape(inputs["$prompt"])}"')
    elif not specs:
        assign_lines.append('$prompt = ""')

    all_lines = assign_lines + lines

    decoder = Decoder(config_path=config_path)
    program = []
    imports = []
    for line in all_lines:
        s = line.strip()
        if s.startswith("import "):
            imports.append(s)
    ctx = "\n".join(imports)
    for line in preprocess_lines(all_lines):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("input "):
            continue
        program.extend(decoder.decode_line(s, imports_context=ctx))

    vm = VM(config_path=config_path)
    vm.load_program(program)

    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        vm.run()
    progress = buf.getvalue()

    registers = {reg: str(val) for reg, val in vm.registers.items()}
    return registers, vm.token_usage, progress


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\"", "\\\"")


_EDIT_BLOCK_RE = re.compile(r'<edit>\s*<old>\s*(.*?)\s*</old>\s*<new>\s*(.*?)\s*</new>\s*</edit>', re.DOTALL)

def _apply_edits(script: str, edit_text: str) -> str:
    """Parse <edit> blocks from LLM output and apply them surgically to `script`.
    Falls back to replacing the entire script if no edit blocks are found."""
    text = edit_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    edits = _EDIT_BLOCK_RE.findall(text)
    if not edits:
        return _fix_script(text)

    result = script
    for old, new in edits:
        if old not in result:
            raise ValueError(f"Edit block not found in script (match failed):\n---old---\n{old}\n---")
        idx = result.index(old)
        result = result[:idx] + new + result[idx + len(old):]
    return result


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status, data):
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(json.dumps(data).encode())
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode()) if length else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/agents":
            agents = [{"name": v["name"], "path": v["path"], "size": v["size"], "modified": v["modified"]}
                      for v in discover_agents().values()]
            self._json(200, {"agents": agents})
        elif parsed.path == "/api/config":
            config_path = PROJECT / "config.toml"
            config = load_config(str(config_path))
            self._json(200, config)
        elif parsed.path == "/api/guide":
            guide_path = PROJECT / "docs/guide.md"
            if guide_path.exists():
                self._json(200, {"content": guide_path.read_text()})
            else:
                self._json(404, {"error": "Guide not found"})
        elif parsed.path.startswith("/api/agents/"):
            name = parsed.path[len("/api/agents/"):]
            for rel, info in discover_agents().items():
                if info["name"] == name or info["path"] == name:
                    content = read_agent(info["path"])
                    if content is not None:
                        lines = content.splitlines()
                        in_specs = [{"name": s.name, "type": s.type}
                                     for s in parse_input_specs(lines)]
                        out_specs = [{"name": s.name, "type": s.type, "register": s.register}
                                      for s in parse_output_specs(lines)]
                        editable = str(AGENTS_DIR / f"{name}.ss") in str(PROJECT / info["path"]) or str(info["path"]).startswith("agents")
                        self._json(200, {
                            "name": info["name"],
                            "content": content,
                            "path": info["path"],
                            "editable": editable,
                            "modified": info["modified"],
                            "input_specs": in_specs,
                            "output_specs": out_specs,
                        })
                        return
            self._json(404, {"error": "Agent not found"})
        else:
            if parsed.path == "/":
                self.path = "/index.html"
            return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/agents":
            body = self._body()
            prompt = body.get("prompt", "")
            if not prompt:
                self._json(400, {"error": "prompt is required"})
                return
            try:
                name, script, tokens = create_agent_via_llm(prompt)
                write_agent(name, script, message=prompt)
                self._json(201, {"name": name, "content": script, "tokens": tokens})
            except Exception as e:
                logger.error("Create failed: %s", e)
                self._json(500, {"error": str(e)})
        elif parsed.path.endswith("/run"):
            parts = parsed.path.split("/")
            name = parts[3]
            body = self._body()
            prompt = body.get("prompt", "")
            inputs = body.get("inputs", {})
            try:
                registers, token_usage, err, progress = run_agent(name, prompt, inputs)
                if err:
                    self._json(404, {"error": err})
                else:
                    self._json(200, {"registers": registers or {}, "tokens": token_usage, "progress": progress})
            except Exception as e:
                logger.error("Run failed: %s", e)
                self._json(500, {"error": str(e)})
        elif parsed.path.endswith("/modify-stream"):
            parts = parsed.path.split("/")
            name = parts[3]
            body = self._body()
            instruction = body.get("instruction", "")
            if not instruction:
                self._json(400, {"error": "instruction is required"})
                return
            script_path = _resolve_agent_path(name)
            if not script_path:
                self._json(404, {"error": "Agent not found"})
                return
            current_script = script_path.read_text()
            config = load_config(str(PROJECT / "config.toml"))["decoder"]
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                client = OpenAI(base_url=config["base_url"], api_key=config["api_key"] or "none", timeout=120)
                guide = _load_guide()
                system_msg = _MODIFY_SYSTEM.format(guide=guide, script=current_script, instruction=instruction)
                response = client.chat.completions.create(
                    model=config["model"],
                    messages=[{"role": "system", "content": system_msg}],
                    stream=True,
                )
                full_text = ""
                for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta:
                        rc = getattr(delta, 'reasoning_content', None)
                        if rc:
                            event = json.dumps({"type": "reasoning", "token": rc})
                            try:
                                self.wfile.write(f"data: {event}\n\n".encode())
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionError, OSError):
                                break
                        if delta.content:
                            full_text += delta.content
                            event = json.dumps({"type": "token", "token": delta.content})
                            try:
                                self.wfile.write(f"data: {event}\n\n".encode())
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionError, OSError):
                                break
                usage = getattr(response, "usage", None)
                tokens = {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens, "total": usage.total_tokens} if usage else None
                script = _apply_edits(current_script, full_text)
                new_script = "# modify: " + body.get("instruction", "").replace("\n", " ") + "\n\n" + script
                event = json.dumps({"type": "done", "script": new_script, "tokens": tokens})
                try:
                    self.wfile.write(f"data: {event}\n\n".encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionError, OSError):
                    pass
            except Exception as e:
                logger.error("Modify stream failed: %s", e)
                event = json.dumps({"type": "error", "error": str(e)})
                try:
                    self.wfile.write(f"data: {event}\n\n".encode())
                    self.wfile.flush()
                except Exception:
                    pass
        elif parsed.path == "/api/serve":
            body = self._body()
            code = body.get("code", "")
            inputs = body.get("input", {})
            if not code:
                self._json(400, {"error": "code is required"})
                return
            try:
                registers, token_usage, progress = run_code(code, inputs)
                self._json(200, {"registers": registers or {}, "tokens": token_usage, "progress": progress})
            except Exception as e:
                logger.error("Serve failed: %s", e)
                self._json(500, {"error": str(e)})
        elif parsed.path.endswith("/modify"):
            parts = parsed.path.split("/")
            name = parts[3]
            body = self._body()
            instruction = body.get("instruction", "")
            if not instruction:
                self._json(400, {"error": "instruction is required"})
                return
            script_path = _resolve_agent_path(name)
            if not script_path:
                self._json(404, {"error": "Agent not found"})
                return
            current_script = script_path.read_text()
            config = load_config(str(PROJECT / "config.toml"))["decoder"]
            try:
                guide = _load_guide()
                system_msg = _MODIFY_SYSTEM.format(guide=guide, script=current_script, instruction=instruction)
                client = OpenAI(base_url=config["base_url"], api_key=config["api_key"] or "none", timeout=120)
                response = client.chat.completions.create(
                    model=config["model"],
                    messages=[{"role": "system", "content": system_msg}],
                )
                raw = response.choices[0].message.content.strip()
                if raw.startswith("```"): raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"): raw = raw.rsplit("```", 1)[0]
                script = _apply_edits(current_script, raw.strip())
                usage = getattr(response, "usage", None)
                tokens = {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens, "total": usage.total_tokens} if usage else None
                self._json(200, {"content": script, "tokens": tokens})
            except Exception as e:
                logger.error("Modify failed: %s", e)
                self._json(500, {"error": str(e)})
        else:
            self._json(404, {"error": "Not found"})

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/config":
            body = self._body()
            model = body.get("model", "")
            base_url = body.get("base_url", "")
            api_key = body.get("api_key", "")
            if not model or not base_url:
                self._json(400, {"error": "model and base_url are required"})
                return
            config_path = PROJECT / "config.toml"
            existing = config_path.read_text() if config_path.exists() else ""
            # Collect all sections except [llm] (which we replace)
            other_sections = []
            current = []
            in_llm = False
            for line in existing.splitlines():
                if line.strip().startswith("[") and line.strip().endswith("]"):
                    if in_llm:
                        in_llm = False
                    if line.strip() == "[llm]":
                        in_llm = True
                        continue
                    if current:
                        other_sections.append("\n".join(current))
                        current = []
                if not in_llm:
                    current.append(line)
            if current:
                other_sections.append("\n".join(current))
            new_content = (
                "[llm]\n"
                f'model = "{model}"\n'
                f'base_url = "{base_url}"\n'
                f'api_key = "{api_key}"\n'
            )
            if other_sections:
                new_content += "\n" + "\n\n".join(other_sections) + "\n"
            config_path.write_text(new_content)
            self._json(200, {"ok": True})
        elif parsed.path.startswith("/api/agents/"):
            name = parsed.path[len("/api/agents/"):]
            body = self._body()
            content = body.get("content")
            if content is None:
                self._json(400, {"error": "content is required"})
                return
            message = body.get("message")
            write_agent(name, content, message=message)
            self._json(200, {"name": name, "content": content})
        else:
            self._json(404, {"error": "Not found"})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/agents/"):
            name = parsed.path[len("/api/agents/"):]
            if delete_agent(name):
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "Agent not found"})
        else:
            self._json(404, {"error": "Not found"})

    def log_message(self, fmt, *args):
        logger.debug(fmt, *args)


def main():
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"  strusky frontend → http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        os.environ["AGENTS_DIR"] = sys.argv[1]
    main()
