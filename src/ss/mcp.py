import json
import subprocess
import re
from typing import Any, Dict, Optional
from pathlib import Path

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPProcess:
    def __init__(self, name: str, command: list[str]):
        self.name = name
        self.command = command
        self.process: Optional[subprocess.Popen] = None
        self.capabilities: dict = {}
        self._next_id = 1

    def start(self):
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
        )
        self._initialize()

    def _send(self, method: str, params: dict = None, id: int = None) -> dict:
        if id is None:
            id = self._next_id
            self._next_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params or {},
        }
        line = json.dumps(request) + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()
        response_line = self.process.stdout.readline()
        if not response_line:
            raise ConnectionError(f"MCP server {self.name} closed connection")
        return json.loads(response_line)

    def _send_notification(self, method: str, params: dict = None):
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        line = json.dumps(notification) + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()

    def _initialize(self):
        response = self._send("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ss", "version": "0.1.0"},
        })
        self.capabilities = response.get("result", {}).get("capabilities", {})
        self._send_notification("notifications/initialized")

    def call_tool(self, tool_name: str, arguments: dict) -> Any:
        response = self._send("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        result = response.get("result", {})
        content = result.get("content", [])
        texts = [item["text"] for item in content if item.get("type") == "text"]
        if result.get("isError"):
            raise RuntimeError(f"MCP tool error: {'; '.join(texts)}")
        return "\n".join(texts) if texts else result

    def stop(self):
        if self.process:
            self._send_notification("exit")
            try:
                self.process.wait(timeout=5)
            except:
                self.process.kill()
            self.process = None


class MCPManager:
    def __init__(self):
        self.servers: Dict[str, MCPProcess] = {}

    def add_server(self, name: str, source: str):
        if source.startswith("uvx://"):
            package = source[len("uvx://"):]
            command = ["uvx", package]
        elif source.startswith("npx://"):
            package = source[len("npx://"):]
            command = ["npx", package]
        else:
            path = Path(source)
            if not path.exists():
                raise FileNotFoundError(
                    f"MCP server config not found: {path.absolute()}"
                )
            with open(path) as f:
                config = json.load(f)
            server_config = config.get(name)
            if not server_config:
                raise KeyError(
                    f"Server {name!r} not found in {path.absolute()}"
                )
            command = self._build_command(server_config)

        process = MCPProcess(name, command)
        process.start()
        self.servers[name] = process

    def _build_command(self, config: dict) -> list[str]:
        cmd = config.get("command", "")
        args = config.get("args", [])
        if cmd == "uvx":
            return ["uvx"] + args
        elif cmd == "npx":
            return ["npx"] + args
        return [cmd] + args

    def call(self, server_name: str, tool_name: str, args: Dict[str, Any]) -> Any:
        server = self.servers.get(server_name)
        if not server:
            return f"Error: MCP server {server_name!r} not imported"
        return server.call_tool(tool_name, args)

    def stop_all(self):
        for server in self.servers.values():
            server.stop()
        self.servers.clear()
