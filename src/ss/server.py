import io
import json
import os
import sys
import contextlib
import http.server
import urllib.parse
from pathlib import Path

from .decoder import Decoder, parse_input_specs
from .vm import VM


def run_code(code: str, inputs: dict = None, config_path: str = "config.toml") -> dict:
    inputs = inputs or {}
    lines = code.splitlines()

    specs = parse_input_specs(lines)

    assign_lines = []
    if specs:
        for spec in specs:
            val = inputs.get(spec.name, "")
            assign_lines.append(f'${spec.name} = "{_escape(val)}"')
    else:
        for key, val in inputs.items():
            assign_lines.append(f'${key} = "{_escape(str(val))}"')

    all_lines = assign_lines + lines

    decoder = Decoder(config_path=config_path)
    program = []
    imports = []
    for line in all_lines:
        s = line.strip()
        if s.startswith("import "):
            imports.append(s)
    ctx = "\n".join(imports)
    for line in all_lines:
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
    return {
        "registers": registers,
        "tokens": vm.token_usage,
        "progress": progress,
    }


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\"", "\\\"")


class Handler(http.server.SimpleHTTPRequestHandler):
    config_path = "config.toml"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
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

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/run":
            body = self._body()
            code = body.get("code", "")
            inp = body.get("input", {})
            if not code:
                self._json(400, {"error": "code is required"})
                return
            try:
                result = run_code(code, inp, self.config_path)
                self._json(200, result)
            except Exception as e:
                self._json(500, {"error": str(e)})
        else:
            self._json(404, {"error": "Not found"})

    def log_message(self, fmt, *args):
        pass


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Structured Skills server mode")
    parser.add_argument("--port", type=int, default=8081, help="Port (default: 8081)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--config", default="config.toml", help="Config path (default: config.toml)")
    args = parser.parse_args()

    Handler.config_path = args.config
    server = http.server.HTTPServer((args.host, args.port), Handler)
    print(f"  strusky server  http://{args.host}:{args.port}")
    print(f"  POST /run  {{\"code\": \"...\", \"input\": {{...}}}}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
