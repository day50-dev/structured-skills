#!/usr/bin/env python3
import os
import sys
import io
import json
import logging
import contextlib
import http.server
import urllib.parse
from pathlib import Path
from openai import OpenAI
from ss.config import load_config
from ss.agent_create import AGENT_CREATE_PROMPT, _fix_script, _name_from_prompt, _modify_script
from ss.decoder import Decoder, parse_input_specs, parse_output_specs

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SRC = PROJECT / "src"
sys.path.insert(0, str(SRC))

from ss.vm import VM

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 5555))
AGENTS_DIR_ARG = os.environ.get("AGENTS_DIR")
if AGENTS_DIR_ARG:
    AGENTS_DIR = Path(AGENTS_DIR_ARG).resolve()
else:
    AGENTS_DIR = HERE / "agents"
AGENTS_DIR.mkdir(exist_ok=True)


def discover_agents():
    agents = {}
    for d in [AGENTS_DIR, PROJECT / "examples", PROJECT]:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix == ".ss":
                rel = f.relative_to(PROJECT)
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


def write_agent(name, content):
    dest = AGENTS_DIR / f"{name}.ss"
    dest.write_text(content)
    return dest


def delete_agent(name):
    dest = AGENTS_DIR / f"{name}.ss"
    if dest.exists():
        dest.unlink()
        return True
    return False


def create_agent_via_llm(prompt):
    config = load_config(str(PROJECT / "config.toml"))["decoder"]
    client = OpenAI(base_url=config["base_url"], api_key=config["api_key"] or "none")
    response = client.chat.completions.create(
        model=config["model"],
        messages=[{"role": "system", "content": AGENT_CREATE_PROMPT.format(prompt=prompt)}],
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
    for line in lines:
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


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\"", "\\\"")


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
        self.wfile.write(json.dumps(data).encode())

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
        elif parsed.path == "/api/guide":
            guide_path = PROJECT / "guide.md"
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
                write_agent(name, script)
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
                new_script, tokens = _modify_script(current_script, instruction, config)
                self._json(200, {"content": new_script, "tokens": tokens})
            except Exception as e:
                logger.error("Modify failed: %s", e)
                self._json(500, {"error": str(e)})
        else:
            self._json(404, {"error": "Not found"})

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/agents/"):
            name = parsed.path[len("/api/agents/"):]
            body = self._body()
            content = body.get("content")
            if content is None:
                self._json(400, {"error": "content is required"})
                return
            write_agent(name, content)
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
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"  strusky frontend → http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        os.environ["AGENTS_DIR"] = sys.argv[1]
    main()
