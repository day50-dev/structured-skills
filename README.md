
<p align="center">
    <img width="400" alt="strusky_400" src="https://github.com/user-attachments/assets/30e50375-4ffd-4b56-b000-fad29d1148d1" /> <br/>
<a href=https://pypi.org/project/strusky><img src=https://badge.fury.io/py/strusky.svg/></a>
</p>

https://github.com/user-attachments/assets/6f8a37fb-4082-4cf8-99ff-b33a46e77c84

### Agents are context-rich recommender systems with agency and control flow.

Let's break that down. Agents use recommendation systems based on context to take action on someone's behalf. 

Strusky makes building these agents easy:

Control-flow is done through a classical VM using instruction pointers, opcodes, and a set of primitives with a notable exception. Instead of a virtual ALU, the LLM is the ALU and uses structured output to control the program. This allows for primitives not to be classic boolean logic but instead to be language and structure based. MCPs (imported via `import X from uvx://...`) and skills (imported via `import file.md` or `load skill path as alias`) are all first-class objects with register access and `%` callable syntax. The transformer is the foundational unit of computation for the fuzzy tasks.

Recommender systems are specificed using declarative programming paradigms, punting the actual SOTA mechanics to be both out of scope and flexible. It uses structured input and output. Read the [docs](/docs/recommender.md).

The Agency part of the agent is the emergent property of these. Models are fundamentally stateless systems. In the way that the append only context pattern gives rise to state, Strusky exploits the true tabulea rasa nature of models at uses the control flow and context management to give rise to agency.

The programming language is designed to look like existing languages because it is intended to be written with a coding harness. 

This isn't experimental. It works. 

As a more formal introduction, **Strusky** is a stack-based virtual machine for orchestrating LLM-powered programs. It gives LLMs the equivalent of structured programming-loops, conditionals, variables, function calls-while keeping the model strictly out of control flow decisions. MCP servers provide external tools like web search and fetching. This paradigm is called "structured skills".

<img alt="Logic-Based_LLM_Agent_Orchestration" src="https://github.com/user-attachments/assets/4566bee1-b542-4897-9bc5-c21a2c33bef3" />

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

ss uses `$registers` for data, `%prefix` for tool/skill calls, `infer` for LLM generation, and `recommend` for declarative retrieval/reranking. MCP tools are imported at the top of the script.

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

# Declarative reranking — selects relevant items using LLM
$hits = recommend << END
<from>$initial</from>
<match>directly answers $prompt</match>
<reject>tangential or boilerplate</reject>
<rank by="similarity" context="$prompt"/>
<limit>3</limit>
END

$answer = infer "Based on $hits, write a final answer."
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

### Agent Creation with Context

The `-c` / `--context` flag feeds reference material into agent generation:

```bash
# Clone an interface from a URL
./agent-create -c https://some-saas/docs/llms.txt "clone this interface"

# Use a local spec file
./agent-create -c ./specs/api-design.md "build a search agent matching these specs"

# Reference a directory of examples
./agent-create -c ./examples/ "make an agent that follows these patterns"
```

Accepts URLs (fetched via HTTP), file paths (read as text), or directories (recursively walked, each file prefixed with its relative path). Content is prepended to the generation prompt as reference material.

### MCP Import Sources

```ss
import fetch from uvx://mcp-server-fetch     # Python/PyPI via uvx
import fetch from npx://@modelcontextprotocol/server-fetch  # Node/npm via npx
import my-server from mcp_servers.json        # JSON config file
```

### Skill Import

Import markdown files or skill directories as first-class objects:

```ss
import somefile.md                     # simple — alias = filename stem
import somefile.md as myskill          # with explicit alias

$result = %myskill(analyze: $data)     # infer using instructions + args
```

Calling an imported skill runs inference with the file content as instructions and the call arguments as user input. Access raw instructions via `%myskill.instructions`.

For Anthropic-standard skill directories (containing `SKILL.md`, scripts, references):

```ss
load skill ./path/to/skill-dir as my-skill
```

Remote skills via Anthropic registry:

```ss
import skill alias from anthropic://skills/some-skill
```

## Debugging (DAP Protocol)

The VM speaks the **Debug Adapter Protocol** - the same protocol VS Code, Emacs, and other editors use for debugging. You can set breakpoints, step through code, and inspect registers.

### Start the debug server

```bash
./run-agent --debug --debug-port 4711 script.ss "query"
```

Or start a standalone TCP server:

```bash
./ss-debug --port 4711
```

### What you can do

- **Breakpoints** - set by source line number
- **Step Over** - execute next instruction, skip into skill calls
- **Step In** - enter a skill call
- **Step Out** - return from current skill
- **Registers** - inspect any `$var` value
- **Call Stack** - view current frame + call history
- **Pause** - interrupt running execution

### VS Code setup

1. Copy `.vscode/ss-debug-extension/` to `~/.vscode/extensions/` (or symlink)
2. Open your `.ss` file, set a breakpoint, press F5
3. Or run the debug server manually and use `"debugServer": 4711` in `launch.json`

Any DAP-compatible client can connect to the TCP server on port 4711.

## CLI Tools

| Command | Description |
|---------|-------------|
| `./agent-create <prompt>` | Generate an `.ss` agent script from a description |
| `./agent-create -c <url\|file\|dir> <prompt>` | Generate with context (URL, file, or directory) |
| `./run-agent <file.ss> <prompt>` | Run an agent with user input |
| `./run-agent --debug <file.ss> <prompt>` | Run with DAP debug server |
| `./ss-debug` | Standalone DAP TCP server |
| `./ss-debug-adapter` | Stdio DAP adapter (for VS Code) |
| `./ss <file.ss>` | Run a script directly |
| `./start-frontend [agents-dir]` | Web UI on port 5555 |

All output (Fetching, Thinking, results, tokens) goes to stderr/stdout with full visibility - no truncation, no hidden diagnostics.

## Architecture

```
.ss file  ──►  Decoder  ──►  Opcodes  ──►  VM
(vibe)          (regex+LLM)     (IR)        (executor)
```

- **Decoder** (`src/ss/decoder.py`): Regex for structures (`def`/`if`/`for`), LLM fallback for "vibe" lines.
- **Opcodes** (`src/ss/opcodes.py`): 14-opcode IR (ASSIGN, CALL, INFER, RECOMMEND, LOOP, IF, ELSE, DEF, RETURN, IMPORT, LOAD_SKILL, JUMP, HALT).
- **VM** (`src/ss/vm.py`): Register-based with call stack, loop stack, jump targets, MCP integration, token tracking, and DAP debug support.
- **MCP** (`src/ss/mcp.py`): Manages MCP server processes (launch via uvx/npx/json, call tools, shutdown).
- **Agent Create** (`src/ss/agent_create.py`): Free-form agent generator - LLM writes code from scratch using a syntax guide rather than filling placeholders.
- **Frontend** (`frontend/`): Single-page web app for browsing, creating, editing, and running agents with streaming output and syntax highlighting.

## Frontend

A single-page web app provides a GUI for managing and running agents:

```bash
./start-frontend
# → http://localhost:5555
```

Or with a custom agents directory:

```bash
./start-frontend /path/to/agents
```

Features:

- **Agent list** - browse agents from `frontend/agents/`, `examples/`, and project root
- **Create via chat** - describe an agent and the LLM generates it
- **View/Edit tabs** - hash-routed as `#view/agent/<name>` and `#edit/agent/<name>`
- **Syntax highlighting** - highlight.js with greyscale atom-one-dark theme
- **Input specs** - dynamic typed input fields parsed from `input $X as TYPE` declarations
- **Output display** - register table with token usage, progress from inference calls
- **AI modification** - streaming modify with real-time token/reasoning display, auto-saves with git commit when `STRUSKY_OPTS=git` is set
- **Guide** - full language reference at `/#guide`, rendered from `guide.md`
- **`strusky.js`** - client-side library for parsing input/output specs from scripts

## Setup

```bash
pip install -e .
cp config.toml.example config.toml
# Edit config.toml with your LLM provider (model, base_url, api_key)
cp .env.example .env       # optional - see STRUSKY_OPTS below
```

Requires Python 3.11+. For web search via MCP, [uvx](https://docs.astral.sh/uv/) is used automatically.

### STRUSKY_OPTS

Set options in `.env` or the environment (comma-separated):

| Option | Description |
|--------|-------------|
| `git`  | Auto-commit agent creates, edits, and deletes to git |

```bash
# .env
STRUSKY_OPTS=git
```

## Documentation

- [docs/architecture.md](docs/architecture.md) - VM architecture, opcode reference, built-in tools, pipeline diagram
- [docs/server.md](docs/server.md) - API server reference (endpoints, request/response formats, CLI flags)
- [docs/strusky.js.md](docs/strusky.js.md) - Client-side JS library (`parseInputSpecs`, `parseOutputSpecs`, `serve`)
- [docs/guide.md](docs/guide.md) - Syntax Guide. This also gets injected into the LLM.
- [docs/recommender](/docs/recommender.md) - The recommender overview.

## License

MIT
