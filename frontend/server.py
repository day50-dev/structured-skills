#!/usr/bin/env python3
import os
import sys
import json
import logging
import http.server
import urllib.parse
from pathlib import Path
from openai import OpenAI
from ss.config import load_config
from ss.agent_create import AGENT_CREATE_PROMPT

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SRC = PROJECT / "src"
sys.path.insert(0, str(SRC))

from ss.decoder import Decoder
from ss.vm import VM

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 5555))
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
    script = response.choices[0].message.content.strip()
    if script.startswith("```"):
        script = script.split("\n", 1)[1] if "\n" in script else script[3:]
    if script.endswith("```"):
        script = script.rsplit("```", 1)[0]
    script = script.strip()
    name = prompt.lower().replace(" ", "_").replace("make_a_", "").replace("create_a_", "")[:30]
    return name, script, tokens


def run_agent(name, prompt_text):
    scripts_to_try = [
        AGENTS_DIR / f"{name}.ss",
        PROJECT / "examples" / f"{name}.ss",
        PROJECT / f"{name}.ss",
    ]
    script_path = None
    for p in scripts_to_try:
        if p.exists():
            script_path = p
            break
    if not script_path:
        for rel, info in discover_agents().items():
            if info["name"] == name or info["path"] == name:
                script_path = PROJECT / info["path"]
                break
    if not script_path:
        return None, "Agent not found"

    lines = [f'$prompt = "{prompt_text}"']
    lines.extend(script_path.read_text().splitlines())
    config_path = str(PROJECT / "config.toml")
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
        if not s or s.startswith("#"):
            continue
        program.extend(decoder.decode_line(s, imports_context=ctx))
    vm = VM(config_path=config_path)
    vm.load_program(program)
    vm.run()
    registers = {}
    for reg, val in vm.registers.items():
        sv = str(val)
        registers[reg] = sv
    return registers, vm.token_usage, None


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
        elif parsed.path.startswith("/api/agents/"):
            name = parsed.path[len("/api/agents/"):]
            for rel, info in discover_agents().items():
                if info["name"] == name or info["path"] == name:
                    content = read_agent(info["path"])
                    if content is not None:
                        editable = str(AGENTS_DIR / f"{name}.ss") in str(PROJECT / info["path"]) or str(info["path"]).startswith("agents")
                        self._json(200, {"name": info["name"], "content": content, "path": info["path"], "editable": editable})
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
            try:
                registers, token_usage, err = run_agent(name, prompt)
                if err:
                    self._json(404, {"error": err})
                else:
                    self._json(200, {"registers": registers, "tokens": token_usage})
            except Exception as e:
                logger.error("Run failed: %s", e)
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
    main()
