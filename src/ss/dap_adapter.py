"""Stdio-based DAP adapter for VS Code integration.

VS Code launches this script as a child process and communicates via stdin/stdout
using the Debug Adapter Protocol (JSON-RPC over stdio with Content-Length headers).
"""
import json
import sys
import threading
import traceback
from typing import Any, Dict, Optional

from .decoder import Decoder, preprocess_lines
from .vm import VM


class DAPAdapter:
    def __init__(self):
        self.seq = 1
        self.vm: Optional[VM] = None
        self.vm_thread: Optional[threading.Thread] = None

    def _next_seq(self) -> int:
        self.seq += 1
        return self.seq - 1

    def _send_event(self, event: str, body: Optional[Dict] = None):
        self._send({"type": "event", "event": event, "body": body or {}, "seq": self._next_seq()})

    def _send_response(self, request_seq: int, command: str, success: bool, body: Optional[Dict] = None, message: str = ""):
        self._send({
            "type": "response",
            "request_seq": request_seq,
            "command": command,
            "success": success,
            "message": message,
            "body": body or {},
            "seq": self._next_seq(),
        })

    def _send(self, msg: dict):
        payload = json.dumps(msg)
        sys.stdout.write(f"Content-Length: {len(payload)}\r\n\r\n{payload}")
        sys.stdout.flush()

    def _recv(self) -> Optional[Dict]:
        try:
            line = sys.stdin.readline()
            if not line:
                return None
            if not line.strip():
                line = sys.stdin.readline()
            length = 0
            if line.lower().startswith("content-length:"):
                length = int(line.split(":")[1].strip())
            while line.strip():
                line = sys.stdin.readline()
            body = sys.stdin.read(length)
            return json.loads(body)
        except:
            return None

    def _on_stopped(self, reason: str, line: int, ip: int):
        reasons = {"breakpoint": "breakpoint", "step": "step", "pause": "user request"}
        self._send_event("stopped", {
            "reason": reasons.get(reason, "unknown"),
            "threadId": 1,
            "allThreadsStopped": True,
        })

    def _handle(self, req: Dict):
        cmd = req.get("command", "")
        args = req.get("arguments", {})
        seq = req.get("seq", 0)

        if cmd == "initialize":
            self._send_response(seq, cmd, True, {
                "supportsConfigurationDoneRequest": True,
                "supportsSetVariable": False,
                "supportsStepBack": False,
                "supportsRestartFrame": False,
                "supportsSteppingGranularity": False,
                "supportsExceptionInfoRequest": False,
            })

        elif cmd == "launch":
            config_path = args.get("config", "config.toml")
            script_path = args.get("program", "")
            prompt = args.get("prompt", "")
            self.vm = VM(config_path=config_path)
            self.vm.debug_mode = True
            self.vm.stopped_callback = self._on_stopped
            with open(script_path) as f:
                lines = f.readlines()
            escaped_prompt = prompt.replace("\\", "\\\\").replace("\"", "\\\"")
            all_lines = [f'$prompt = "{escaped_prompt}"\n'] + lines
            decoder = Decoder(config_path=config_path)
            import_lines = [l.strip() for l in all_lines if l.strip().startswith("import ")]
            program = []
            for ln, line in enumerate(preprocess_lines(all_lines), start=1):
                if not line.strip() or line.strip().startswith("#"):
                    continue
                ops = decoder.decode_line(line, imports_context="\n".join(import_lines), line_number=ln)
                program.extend(ops)
            self.vm.load_program(program)
            self._send_response(seq, cmd, True)

        elif cmd == "setBreakpoints":
            source_bps = args.get("breakpoints", [])
            lines_set = [bp["line"] for bp in source_bps]
            if self.vm:
                self.vm.breakpoints = set(lines_set)
            self._send_response(seq, cmd, True, {
                "breakpoints": [{"line": l, "verified": True} for l in lines_set]
            })

        elif cmd == "setExceptionBreakpoints":
            self._send_response(seq, cmd, True)

        elif cmd == "configurationDone":
            if self.vm:
                def run_vm():
                    try:
                        self.vm.run()
                    finally:
                        self._send_event("exited", {"exitCode": 0})
                        self._send_event("terminated")
                self.vm_thread = threading.Thread(target=run_vm, daemon=True)
                self.vm_thread.start()
            self._send_response(seq, cmd, True)

        elif cmd == "continue":
            if self.vm:
                self.vm.continue_run()
            self._send_response(seq, cmd, True, {"allThreadsContinued": True})

        elif cmd == "next":
            if self.vm:
                self.vm.step_over()
            self._send_response(seq, cmd, True)

        elif cmd == "stepIn":
            if self.vm:
                self.vm.step_in()
            self._send_response(seq, cmd, True)

        elif cmd == "stepOut":
            if self.vm:
                self.vm.step_out()
            self._send_response(seq, cmd, True)

        elif cmd == "pause":
            if self.vm:
                self.vm.pause()
            self._send_response(seq, cmd, True)

        elif cmd == "stackTrace":
            frames = []
            if self.vm:
                line = self.vm.current_line()
                frames.append({
                    "id": 0,
                    "name": f"line {line}",
                    "line": line,
                    "column": 1,
                    "source": {"name": "script.ss"},
                })
                for i in range(len(self.vm.call_stack)):
                    frames.append({
                        "id": i + 1,
                        "name": f"call frame {i + 1}",
                        "line": 0,
                        "column": 1,
                        "source": {"name": "script.ss"},
                    })
            self._send_response(seq, cmd, True, {"stackFrames": frames, "totalFrames": len(frames)})

        elif cmd == "scopes":
            scopes = []
            if self.vm:
                scopes.append({"name": "Registers", "variablesReference": 1, "expensive": False})
            self._send_response(seq, cmd, True, {"scopes": scopes})

        elif cmd == "variables":
            variables = []
            if self.vm and args.get("variablesReference") == 1:
                for name, val in sorted(self.vm.registers.items()):
                    sval = str(val)
                    if len(sval) > 1000:
                        sval = sval[:997] + "..."
                    variables.append({"name": name, "value": sval, "type": type(val).__name__, "variablesReference": 0})
            self._send_response(seq, cmd, True, {"variables": variables})

        elif cmd == "evaluate":
            expr = args.get("expression", "")
            result = "<not available>"
            if self.vm:
                if expr.startswith("$"):
                    result = str(self.vm.registers.get(expr, "<not found>"))
                else:
                    try:
                        result = str(self.vm.evaluate(expr))
                    except:
                        result = "<error>"
            self._send_response(seq, cmd, True, {"result": result, "variablesReference": 0})

        elif cmd == "disconnect":
            self._send_response(seq, cmd, True)
            raise SystemExit(0)

        else:
            self._send_response(seq, cmd, False, message=f"unknown command: {cmd}")

    def run(self):
        self._send_event("initialized")
        while True:
            try:
                req = self._recv()
                if req is None:
                    break
                self._handle(req)
            except SystemExit:
                break
            except:
                traceback.print_exc()
                break


def main():
    adapter = DAPAdapter()
    adapter.run()


if __name__ == "__main__":
    main()
