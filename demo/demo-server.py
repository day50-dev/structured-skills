#!/usr/bin/env python3
"""Structured Skills Demo Server — chat UI backend with 4-step agent workflow."""

import http.server
import io
import json
import os
import re
import sys
import contextlib
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ss.config import load_config, SETUP_GUIDANCE
from ss.decoder import Decoder, parse_input_specs, parse_output_specs
from ss.vm import VM
from openai import OpenAI

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
PORT = int(os.environ.get("PORT", 8080))

# ── Agent discovery & execution (for /run demo) ───────────
def discover_agents():
    agents = []
    seen = set()
    dirs = [PROJECT / "ss-src", PROJECT / "examples", PROJECT / "frontend" / "agents", PROJECT]
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix == ".ss" and f.stem not in seen:
                seen.add(f.stem)
                try:
                    rel = f.relative_to(PROJECT)
                except ValueError:
                    rel = f
                agents.append({"name": f.stem, "path": str(rel), "size": f.stat().st_size})
    return agents

def read_agent(path_str):
    p = PROJECT / path_str
    if not p.exists() or p.suffix != ".ss":
        return None
    return p.read_text()

def run_code(code_text, inputs=None):
    lines = code_text.splitlines()
    config_path = str(PROJECT / "config.toml")
    specs = parse_input_specs(lines)
    assign_lines = []
    if specs and inputs:
        for spec in specs:
            val = inputs.get(spec.name, "")
            if spec.type == "file" and val:
                val = val
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
    return registers, vm.token_usage, progress

def _escape(s):
    return s.replace("\\", "\\\\").replace("\"", "\\\"")


STRATEGY_PROMPT = """You are the Structured Skills Strategy Advisor. Your job is to analyze a complex user request and explain how Structured Skills can help accomplish it.

Structured Skills is a tiny VM for LLM-powered programs. It uses `.ss` scripts with:
- Registers ($var) for data
- `infer` for LLM reasoning steps
- `%tool` calls for external tools (MCP, built-in)
- `def`/`end` for reusable skills
- `for each`/`end` for loops
- `if`/`else`/`end` for conditionals
- `import` for MCP servers

Built-in tools: %read, %write, %append, %list_files, %add, %sum

The typical workflow:
1. The user describes a complex multi-step task
2. An `.ss` script is generated that decomposes the task into steps
3. The script uses `infer` for LLM reasoning at each step
4. The VM executes the script deterministically, with the LLM only providing values

Analyze this request: {prompt}

Return a concise strategy (2-3 paragraphs) covering:
- What makes this task suitable for structured skills
- How the task would be decomposed into steps
- What tools/registers/skills would be needed"""

GENERATE_SCRIPT_PROMPT = """You are the Structured Skills Agent Generator. Generate a `.ss` script that implements the solution.

CRITICAL RULES:
- The script must read input from `$prompt` register.
- The script must write its final output to `$result` register.
- Use `def`/`end` to define reusable skills.
- Use `infer` for LLM reasoning steps.
- Use `%` prefix for tool calls (built-in only: %read, %write, %list_files, %append, %add, %sum).
- Use `for each`/`end` for iteration.
- Use `if`/`else`/`end` for conditionals.
- Use `return` to return values from skills.
- Each `def` must end with `end`.
- Each `for each` must end with `end`.
- Each `if` must end with `end`.
- Comments start with `#`.
- DO NOT use imports (no MCP servers).
- DO NOT use markdown formatting in the output.

SYNTAX REFERENCE:
- $var = "literal"           # Assign string
- $var = $other              # Copy register
- $var = ["a", "b"]          # JSON list
- $var = %tool arg1 arg2     # Call tool, store result
- $var = infer "prompt"      # LLM inference, store result
- def skill $param: ... end  # Define reusable skill
- return $value              # Return from skill
- for each $item in $list: ... end  # Loop
- if $cond: ... else: ... end       # Conditional

TASK: {prompt}

STRATEGY: {strategy}

OUTPUT: Return ONLY the `.ss` script content. No explanations, no markdown."""

class DemoHandler(http.server.SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/agents":
            agents = discover_agents()
            self._send_json(200, {"agents": agents})
            return
        if parsed.path.startswith("/api/agents/"):
            path = parsed.path[len("/api/agents/"):]
            content = read_agent(path)
            if content is None:
                self._send_json(404, {"error": "Agent not found"})
                return
            lines = content.splitlines()
            in_specs = [{"name": s.name, "type": s.type} for s in parse_input_specs(lines)]
            out_specs = [{"name": s.name, "type": s.type, "register": s.register} for s in parse_output_specs(lines)]
            self._send_json(200, {
                "name": Path(path).stem,
                "path": path,
                "content": content,
                "input_specs": in_specs,
                "output_specs": out_specs,
            })
            return
        if parsed.path.startswith("/api/"):
            self._send_json(404, {"error": "Not found"})
            return
        if parsed.path == "/" or parsed.path == "":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/chat":
            self._handle_chat()
        elif parsed.path == "/api/serve":
            self._handle_serve()
        else:
            self._send_json(404, {"error": "Not found"})

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status, data):
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _check_config(self):
        config_path = str(HERE.parent / "config.toml")
        if not os.path.exists(config_path):
            return False, f"config.toml not found. Run this from the project root or create {config_path}."
        try:
            cfg = load_config(config_path)
            key = cfg["decoder"].get("api_key", "")
            if not key or key == "sk-..." or key == "":
                return False, (
                    "LLM API key not configured.\n\n"
                    f"Edit {config_path} and set:\n"
                    "  [llm]\n"
                    f'  api_key = "sk-your-real-key"'
                )
            return True, cfg
        except Exception as e:
            return False, str(e)

    def _call_llm(self, config, system_prompt, user_prompt, model=None):
        client = OpenAI(
            base_url=config["base_url"],
            api_key=config["api_key"]
        )
        response = client.chat.completions.create(
            model=model or config["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        return response.choices[0].message.content.strip()

    def _step1_strategy(self, config, prompt):
        return self._call_llm(config["decoder"], STRATEGY_PROMPT, prompt)

    def _step2_generate_script(self, config, prompt, strategy):
        content = self._call_llm(
            config["decoder"],
            GENERATE_SCRIPT_PROMPT.format(prompt=prompt, strategy=strategy),
            f"Generate the .ss script for: {prompt}"
        )
        content = re.sub(r"^```(?:ss)?\s*\n?", "", content)
        content = re.sub(r"\n```\s*$", "", content)
        return content.strip()

    def _step3_execute(self, config_path, script, prompt):
        lines = [f'$prompt = "{prompt}"'] + script.split("\n")

        decoder = Decoder(config_path=config_path)
        program = []
        imports = []
        for line in lines:
            if line.strip().startswith("import "):
                imports.append(line.strip())
        imports_context = "\n".join(imports)

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            opcodes = decoder.decode_line(stripped, imports_context=imports_context)
            program.extend(opcodes)

        vm = VM(config_path=config_path)
        vm.load_program(program)
        vm.run()

        registers = {}
        for reg, val in vm.registers.items():
            sval = str(val)
            if len(sval) > 500:
                sval = sval[:497] + "..."
            registers[reg] = sval
        return registers

    def _handle_chat(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            data = json.loads(body)
            prompt = data.get("message", "").strip()
            if not prompt:
                self._send_json(400, {"error": "Message is required"})
                return
        except Exception:
            self._send_json(400, {"error": "Invalid request"})
            return

        ok, cfg_or_err = self._check_config()
        if not ok:
            self._send_json(200, {
                "steps": [{
                    "step": 0,
                    "title": "Configuration Required",
                    "content": cfg_or_err
                }]
            })
            return

        config = cfg_or_err
        config_path = str(HERE.parent / "config.toml")

        result = {"steps": [], "error": None}

        try:
            strategy = self._step1_strategy(config, prompt)
            result["steps"].append({
                "step": 1,
                "title": "Strategy",
                "content": strategy
            })
        except Exception as e:
            result["steps"].append({
                "step": 1,
                "title": "Strategy",
                "content": f"Error generating strategy: {e}"
            })
            result["error"] = str(e)
            self._send_json(200, result)
            return

        try:
            script = self._step2_generate_script(config, prompt, strategy)
            result["steps"].append({
                "step": 2,
                "title": "Structured Skills Script",
                "content": script,
                "is_code": True
            })
        except Exception as e:
            result["steps"].append({
                "step": 2,
                "title": "Structured Skills Script",
                "content": f"Error generating script: {e}"
            })
            result["error"] = str(e)
            self._send_json(200, result)
            return

        try:
            registers = self._step3_execute(config_path, script, prompt)
            result["steps"].append({
                "step": 3,
                "title": "Execution",
                "content": registers,
                "is_registers": True
            })
        except Exception as e:
            result["steps"].append({
                "step": 3,
                "title": "Execution",
                "content": f"Error executing script: {e}"
            })
            result["error"] = str(e)
            self._send_json(200, result)
            return

        final_val = registers.get("$result") or registers.get("$prompt") or ""
        result["steps"].append({
            "step": 4,
            "title": "Result",
            "content": final_val
        })

        self._send_json(200, result)

    def _handle_serve(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode() if length else "{}"
            data = json.loads(body)
        except Exception:
            self._send_json(400, {"error": "Invalid request"})
            return
        code = data.get("code", "")
        inputs = data.get("input", {})
        if not code:
            self._send_json(400, {"error": "code is required"})
            return
        ok, cfg_or_err = self._check_config()
        if not ok:
            self._send_json(500, {"error": cfg_or_err})
            return
        try:
            registers, token_usage, progress = run_code(code, inputs)
            self._send_json(200, {"registers": registers or {}, "tokens": token_usage, "progress": progress})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def log_message(self, format, *args):
        pass


def main():
    os.chdir(str(HERE))
    server = http.server.HTTPServer(("0.0.0.0", PORT), DemoHandler)
    url = f"http://localhost:{PORT}"
    print(f"")
    print(f"  ╔══════════════════════════════════════════╗")
    print(f"  ║   Structured Skills  -  Demo Server     ║")
    print(f"  ╠══════════════════════════════════════════╣")
    print(f"  ║  Open:  {url:<33}║")
    print(f"  ║  Ctrl+C to stop                         ║")
    print(f"  ╚══════════════════════════════════════════╝")
    print(f"")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
