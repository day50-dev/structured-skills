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


OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "strusky server",
        "description": "Execute strusky (.ss) scripts remotely. Sends code and optional inputs to the strusky VM and returns the resulting registers, token usage, and stderr progress.",
        "version": "0.2.0",
    },
    "servers": [{"url": "/"}],
    "paths": {
        "/run": {
            "post": {
                "summary": "Execute strusky code",
                "description": "Run a strusky script with optional input parameters and return the final register state.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["code"],
                                "properties": {
                                    "code": {
                                        "type": "string",
                                        "description": "The .ss script source to execute",
                                        "example": "$result = \"hello world\"",
                                    },
                                    "input": {
                                        "type": "object",
                                        "description": "Key-value pairs mapped to input specs or registers",
                                        "example": {"name": "World"},
                                        "additionalProperties": {"type": "string"},
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Execution result",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "registers": {
                                            "type": "object",
                                            "description": "Final VM register values",
                                            "example": {"$result": "hello world"},
                                        },
                                        "tokens": {
                                            "type": "array",
                                            "description": "Per-inference token usage",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "prompt": {"type": "integer"},
                                                    "completion": {"type": "integer"},
                                                    "total": {"type": "integer"},
                                                },
                                            },
                                        },
                                        "progress": {
                                            "type": "string",
                                            "description": "Stderr output captured during execution",
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "400": {
                        "description": "Missing required field",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"error": {"type": "string"}},
                                }
                            }
                        },
                    },
                    "500": {
                        "description": "Execution error",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"error": {"type": "string"}},
                                }
                            }
                        },
                    },
                },
            }
        },
    },
}

SWAGGER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>strusky API — Swagger</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
</head>
<body style="margin:0">
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js" crossorigin></script>
  <script>
    SwaggerUIBundle({
      url: "/openapi.json",
      dom_id: "#swagger-ui",
    });
  </script>
</body>
</html>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    config_path = "config.toml"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status, data):
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _html(self, status, content):
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode()) if length else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/openapi.json":
            self._json(200, OPENAPI_SPEC)
        elif parsed.path == "/docs":
            self._html(200, SWAGGER_HTML)
        elif parsed.path == "/":
            self._json(200, {
                "service": "strusky server",
                "version": "0.2.0",
                "endpoints": {
                    "/": "this info",
                    "/run": "POST — execute strusky code",
                    "/openapi.json": "OpenAPI 3.1 spec",
                    "/docs": "Swagger UI",
                },
            })
        else:
            self._json(404, {"error": "Not found"})

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
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"  strusky server  http://{args.host}:{args.port}")
    print(f"  POST /run      execute strusky code")
    print(f"  GET  /docs     Swagger UI")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
