
<p align="center">
    <img width="400" alt="strusky_400" src="https://github.com/user-attachments/assets/30e50375-4ffd-4b56-b000-fad29d1148d1" /> <br/>
<a href=https://pypi.org/project/strusky><img src=https://badge.fury.io/py/strusky.svg/></a>
</p>

**Structured Skills (ss)** is a stack-based virtual machine for orchestrating LLM-powered programs. It gives LLMs the equivalent of structured programming—loops, conditionals, variables, function calls—while keeping the model strictly out of control flow decisions. MCP (Model Context Protocol) servers provide external tools like web search and fetching.

## Quick Start

```bash
# Generate an agent from a description
./agent-create "make a research agent that searches the web"
# → Generates research_agent_that_searches_t.ss

# Run it with a question
./run-agent research_agent_that_searches_t.ss "what is the tallest mountain in north america"
```

The agent searches DuckDuckGo, extracts key facts via the LLM, and synthesizes a final answer. Progress is shown inline:

```
  Fetching https://lite.duckduckgo.com/lite/?q=what%20is%20the%20tallest%20mountain%20...
  Got 5231 chars from fetch.fetch
  Thinking... (prompt: 5812 chars, "From these DuckDuckGo search results ($results)...")
  Thinking... (prompt: 2104 chars, "Based on the extracted key facts ($info)...")

=== RESULTS ===

$prompt (1287 chars):
The highest mountain peak in North America is Denali. ...

=== TOKENS ===
  Infer 1: 2100 in → 890 out (2990 total)
  Infer 2: 410 in → 430 out (840 total)
  Total: 3830
```

## Language Syntax

ss uses `$registers` for data, `%prefix` for tool/skill calls, and `infer` for LLM inference. MCP tools are imported at the top of the script.

```ss
import fetch from uvx://mcp-server-fetch?--ignore-robots-txt

def research $query:
    $encoded = %urlencode $query
    $url = "https://lite.duckduckgo.com/lite/?q=$encoded"
    $results = %fetch.fetch url=$url max_length=8000
    $entries = infer "From these search results ($results), extract key facts as bullet points."
    return $entries
end

$initial = %research $prompt
$answer = infer "Based on $initial, write a final answer."
```

### MCP Tool Calls with Named Arguments

MCP tools expect named parameters. Use `key=value` syntax:

```ss
%fetch.fetch url=$url max_length=8000 raw=True
```

The decoder detects `=` in arguments and passes them as a named dict to the MCP server. Values are auto-converted: `8000` → int, `True` → bool.

### Server-Level Arguments

Pass flags to MCP servers via query string in the import URI:

```ss
import fetch from uvx://mcp-server-fetch?--ignore-robots-txt
```

Multiple flags: `uvx://package?--flag1&--flag2`

### Built-in Tools

| Tool        | Args                    | Description                    |
|-------------|-------------------------|--------------------------------|
| `read`      | `$path`                 | Read file contents             |
| `write`     | `$path $data`           | Overwrite a file               |
| `append_to_file`| `$path $data`       | Append to a file               |
| `list_files`| `$dir`                  | List files in a directory      |
| `add`       | `$a $b`                 | Add two numbers                |
| `sum`       | `$list`                 | Sum a list of numbers          |
| `append`    | `$list $item`           | Append to an in-memory list    |
| `join`      | `$list $sep`            | Join list items with separator |
| `urlencode` | `$string`               | URL-encode a string            |

### MCP Import Sources

```ss
import fetch from uvx://mcp-server-fetch     # Python/PyPI via uvx
import fetch from npx://@modelcontextprotocol/server-fetch  # Node/npm via npx
import my-server from mcp_servers.json        # JSON config file
```

## Debugging (DAP Protocol)

The VM speaks the **Debug Adapter Protocol** — the same protocol VS Code, Emacs, and other editors use for debugging. You can set breakpoints, step through code, and inspect registers.

### Start the debug server

```bash
./run-agent --debug --debug-port 4711 script.ss "query"
```

Or start a standalone TCP server:

```bash
./ss-debug --port 4711
```

### What you can do

- **Breakpoints** — set by source line number
- **Step Over** — execute next instruction, skip into skill calls
- **Step In** — enter a skill call
- **Step Out** — return from current skill
- **Registers** — inspect any `$var` value
- **Call Stack** — view current frame + call history
- **Pause** — interrupt running execution

### VS Code setup

1. Copy `.vscode/ss-debug-extension/` to `~/.vscode/extensions/` (or symlink)
2. Open your `.ss` file, set a breakpoint, press F5
3. Or run the debug server manually and use `"debugServer": 4711` in `launch.json`

Any DAP-compatible client can connect to the TCP server on port 4711.

## CLI Tools

| Command | Description |
|---------|-------------|
| `./agent-create <prompt>` | Generate an `.ss` agent script from a description |
| `./run-agent <file.ss> <prompt>` | Run an agent with user input |
| `./run-agent --debug <file.ss> <prompt>` | Run with DAP debug server |
| `./ss-debug` | Standalone DAP TCP server |
| `./ss-debug-adapter` | Stdio DAP adapter (for VS Code) |
| `./ss <file.ss>` | Run a script directly |
| `python frontend/server.py` | Web UI on port 5555 |

All output (Fetching, Thinking, results, tokens) goes to stderr/stdout with full visibility — no truncation, no hidden diagnostics.

## Architecture

```
.ss file  ──►  Decoder  ──►  Opcodes  ──►  VM
(vibe)          (regex+LLM)     (IR)        (executor)
```

- **Decoder** (`src/ss/decoder.py`): Regex for structures (`def`/`if`/`for`), LLM fallback for "vibe" lines.
- **Opcodes** (`src/ss/opcodes.py`): 13-opcode IR (ASSIGN, CALL, INFER, LOOP, IF, ELSE, DEF, RETURN, IMPORT, LOAD_SKILL, JUMP, HALT).
- **VM** (`src/ss/vm.py`): Register-based with call stack, loop stack, jump targets, MCP integration, token tracking, and DAP debug support.
- **MCP** (`src/ss/mcp.py`): Manages MCP server processes (launch via uvx/npx/json, call tools, shutdown).
- **Agent Create** (`src/ss/agent_create.py`): Template-based agent generator — LLM fills `INSTRUCTION_N` placeholders in a fixed `.ss` skeleton.

## Frontend

A single-page web app provides a GUI for managing and running agents:

```bash
python frontend/server.py
# → http://localhost:5555
```

Features: agent list, create, view, edit, and run with live output and token display.

## Setup

```bash
pip install -e .
cp config.toml.example config.toml
# Edit config.toml with your LLM provider (model, base_url, api_key)
```

Requires Python 3.11+. For web search via MCP, [uvx](https://docs.astral.sh/uv/) is used automatically.

## Project Structure

```
src/ss/
├── agent_create.py   Template-based agent generator
├── agent_runner.py   Run agent with prepended $prompt
├── cli.py            Direct script runner
├── decoder.py        Regex + LLM decoder
├── vm.py             VM with debug support
├── opcodes.py        Opcode types and models
├── prompts.py        Decoder prompt templates
├── config.py         TOML config loader
├── mcp.py            MCP server manager
├── dap_server.py     DAP protocol TCP server
├── dap_adapter.py    DAP stdio adapter (VS Code)
├── skill_loader.py   Load .ss skill files
frontend/
├── server.py         HTTP API (port 5555)
├── index.html        Single-page web UI
```

## License

MIT
