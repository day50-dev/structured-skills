import json
import sys
import socket
import threading
import traceback
from typing import Any, Dict, List, Optional

from .decoder import Decoder
from .vm import VM
from .opcodes import OpcodeType


class DAPServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 4711):
        self.host = host
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.client_socket: Optional[socket.socket] = None
        self.seq = 1
        self.vm: Optional[VM] = None
        self.vm_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _next_seq(self) -> int:
        self.seq += 1
        return self.seq - 1

    def _send_event(self, event: str, body: Optional[Dict] = None):
        msg = json.dumps({"type": "event", "event": event, "body": body, "seq": self._next_seq()})
        self._send_raw(msg)

    def _send_response(self, request_seq: int, command: str, success: bool, body: Optional[Dict] = None, message: str = ""):
        msg = json.dumps({
            "type": "response",
            "request_seq": request_seq,
            "command": command,
            "success": success,
            "message": message,
            "body": body or {},
            "seq": self._next_seq(),
        })
        self._send_raw(msg)

    def _send_raw(self, msg: str):
        if self.client_socket:
            try:
                self.client_socket.sendall((f"Content-Length: {len(msg)}\r\n\r\n{msg}").encode())
            except:
                pass

    def _recv_message(self) -> Optional[Dict]:
        if not self.client_socket:
            return None
        try:
            data = b""
            while True:
                chunk = self.client_socket.recv(4096)
                if not chunk:
                    return None
                data += chunk
                if b"\r\n\r\n" in data:
                    header, rest = data.split(b"\r\n\r\n", 1)
                    for line in header.decode().split("\r\n"):
                        if line.lower().startswith("content-length:"):
                            length = int(line.split(":")[1].strip())
                    while len(rest) < length:
                        rest += self.client_socket.recv(4096)
                    return json.loads(rest[:length].decode())
        except:
            return None

    def _on_stopped(self, reason: str, line: int, ip: int):
        reasons = {"breakpoint": "breakpoint", "step": "step", "pause": "user request"}
        self._send_event("stopped", {
            "reason": reasons.get(reason, "unknown"),
            "threadId": 1,
            "description": f"Stopped at line {line}",
            "text": f"Hit {reason} at line {line}",
            "allThreadsStopped": True,
        })

    def _handle_request(self, req: Dict):
        cmd = req.get("command", "")
        args = req.get("arguments", {})
        seq = req.get("seq", 0)

        if cmd == "initialize":
            self._send_response(seq, cmd, True, {
                "supportsConfigurationDoneRequest": True,
                "supportsSetVariable": True,
                "supportsStepBack": False,
                "supportsRestartFrame": False,
                "supportsSteppingGranularity": False,
                "supportsExceptionInfoRequest": False,
            })

        elif cmd == "launch":
            self.vm = VM(config_path=args.get("config", "config.toml"))
            self.vm.debug_mode = True
            self.vm.stopped_callback = self._on_stopped
            script_path = args.get("program", "")
            prompt = args.get("prompt", "")
            with open(script_path) as f:
                lines = f.readlines()
            escaped_prompt = prompt.replace("\\", "\\\\").replace("\"", "\\\"")
            all_lines = [f'$prompt = "{escaped_prompt}"\n'] + lines
            decoder = Decoder(config_path=args.get("config", "config.toml"))
            import_lines = [l.strip() for l in all_lines if l.strip().startswith("import ")]
            program = []
            for ln, line in enumerate(all_lines, start=1):
                if not line.strip() or line.strip().startswith("#"):
                    continue
                ops = decoder.decode_line(line, imports_context="\n".join(import_lines), line_number=ln)
                program.extend(ops)
            self.vm.load_program(program)
            self._send_response(seq, cmd, True)

        elif cmd == "setBreakpoints":
            source_breakpoints = args.get("breakpoints", [])
            lines = [bp["line"] for bp in source_breakpoints]
            if self.vm:
                self.vm.breakpoints = set(lines)
            self._send_response(seq, cmd, True, {
                "breakpoints": [{"line": l, "verified": True} for l in lines]
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
                    "source": {"name": args.get("source", {}).get("name", "script.ss"), "path": args.get("source", {}).get("path", "")},
                })
                for i, frame in enumerate(reversed(self.vm.call_stack), start=1):
                    frames.append({
                        "id": i,
                        "name": f"call frame {i}",
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
                    if len(sval) > 500:
                        sval = sval[:497] + "..."
                    variables.append({"name": name, "value": sval, "type": type(val).__name__, "variablesReference": 0})
            self._send_response(seq, cmd, True, {"variables": variables})

        elif cmd == "evaluate":
            expr = args.get("expression", "")
            result = ""
            if self.vm:
                if expr.startswith("$"):
                    val = self.vm.registers.get(expr, "<not found>")
                    result = str(val)
                else:
                    try:
                        result = str(self.vm.evaluate(expr))
                    except:
                        result = "<error>"
            self._send_response(seq, cmd, True, {"result": result, "variablesReference": 0})

        elif cmd == "disconnect":
            self._send_response(seq, cmd, True)
            self._stop_event.set()

        else:
            self._send_response(seq, cmd, False, message=f"Unknown command: {cmd}")

    def serve(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(1)
        self.server_socket.settimeout(1.0)
        print(f"DAP server listening on {self.host}:{self.port}", file=sys.stderr, flush=True)
        while not self._stop_event.is_set():
            try:
                client, addr = self.server_socket.accept()
                self.client_socket = client
                print(f"DAP client connected from {addr}", file=sys.stderr, flush=True)
                self._send_event("initialized")
                while not self._stop_event.is_set():
                    msg = self._recv_message()
                    if msg is None:
                        break
                    self._handle_request(msg)
                self.client_socket = None
                print("DAP client disconnected", file=sys.stderr, flush=True)
            except socket.timeout:
                continue
            except:
                traceback.print_exc()
                continue
        self.server_socket.close()
