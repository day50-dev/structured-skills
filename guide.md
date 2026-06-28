# strusky / Structured Skills — Agent Guide

## Overview

ss scripts are LLM-powered programs that run on a register-based virtual machine.
The VM owns all control flow — the LLM only fills in the `infer` prompts.
MCP (Model Context Protocol) servers provide external tools like web search and file access.

```
.ss script → Decoder (regex + LLM) → Opcodes → VM (executor) → Result
```

---

## Input Declarations

Scripts declare what they need at the top with `input`:

```ss
input $REPO_FILE as file       # runner reads the file, stores content in $REPO_FILE
input $USERNAME as string      # plain text
input $THRESHOLD as number     # numeric value
input $REPO_URL as repo        # URL (stores as string)
```

When the script runs, the runner:
- Reads file content for `file`-typed inputs (from the path or uploaded content)
- Prompts for any missing values interactively
- Maps CLI positional args to inputs in order

---

## Output Declarations

Scripts declare what they produce with `output`:

```ss
output $report as report            # structured text output (default)
output $data as json                # JSON data
output $report as file: output.md   # writes register to file
output $result as string            # plain string output
```

The output register is included in the final result. For `file`-typed outputs, the runner
writes the register content to the specified path automatically.

---

## MCP Servers (First-Class Objects)

MCP servers provide tools that the script calls. Import them at the top of the script:

```ss
# From a Python package via uvx
import fetch from uvx://mcp-server-fetch?--ignore-robots-txt

# From an npm package via npx
import github from npx://@modelcontextprotocol/server-github

# From a JSON config file
import brave-search from mcp_servers.json
```

Call them with named arguments:

```ss
$results = %fetch.fetch url=$url max_length=8000 raw=True
$info = %github.get_repo owner=$owner repo=$repo
```

Arguments with `=` are treated as key-value pairs and passed directly to the MCP tool.
Values are auto-converted: `8000` → integer, `True` → boolean.

Server-level flags go in the import URI query string:

```ss
import fetch from uvx://mcp-server-fetch?--ignore-robots-txt&--timeout=30
```

---

## Built-in Tools

| Tool              | Args                          | Description                    |
|-------------------|-------------------------------|--------------------------------|
| `%read`           | `$path`                       | Read file contents             |
| `%write`          | `$path $data`                 | Overwrite a file               |
| `%append_to_file` | `$path $data`                 | Append to a file               |
| `%list_files`     | `$dir`                        | List files in a directory      |
| `%add`            | `$a $b`                       | Add two numbers                |
| `%sum`            | `$list`                       | Sum a list of numbers          |
| `%append`         | `$list $item`                 | Append to an in-memory list    |
| `%join`           | `$list $sep`                  | Join list items with separator |
| `%urlencode`      | `$string`                     | URL-encode a string            |
| `%print`          | `$value`                      | Print to stderr                |

---

## Skills (Functions)

Define reusable blocks with `def` / `end`:

```ss
def search_web $query:
    $encoded = %urlencode $query
    $url = "https://lite.duckduckgo.com/lite/?q=$encoded"
    $results = %fetch.fetch url=$url max_length=8000
    $answer = infer "Extract key facts from: $results"
    return $answer
end

$answer = %search_web $prompt
$prompt = $answer
```

Skills create a new register scope — registers set inside a skill don't leak to the caller
(except the return value).

---

## Inference

The `infer` keyword sends a prompt to the LLM and stores the response:

```ss
$summary = infer "Summarize the following text in one paragraph: $text"
```

Prompts can reference any registers with `$name`. Keep prompts imperative and direct:
- "Extract the key facts from: $results"
- "Write a final answer based on: $info"
- "Compare these two analyses: $a and $b"

---

## Control Flow

Conditionals:

```ss
if $condition:
    $x = infer "Handle the true case with: $data"
else:
    $x = infer "Handle the false case"
end
```

Loops:

```ss
for each $item in $items:
    $analysis = infer "Analyze this: $item"
    %append $all_results $analysis
end
```

---

## Variables and Registers

```ss
$name = "Alice"              # string
$count = 42                  # number (auto-converted)
$items = ["a", "b", "c"]     # list (JSON array)
$flag = True                 # boolean (auto-converted)
$template = "Hello $name"    # string interpolation (evaluated at use)
```

---

## Comments

```ss
# This is a comment
$prompt = $result  # inline comment
```

---

## Debugging (DAP Protocol)

The VM speaks the Debug Adapter Protocol over TCP (port 4711) or stdio.

```bash
./run-agent --debug --debug-port 4711 script.ss "query"
```

Connect any DAP-compatible debugger to set breakpoints, step through code,
inspect registers, and view the call stack.

---

## Agent Creation

Generate an agent from a description:

```bash
./agent-create "a research agent that searches the web, extracts facts, and writes a report"
```

Or in the frontend, click "+ New Agent" and describe what you want.

The generated script includes a `# prompt:` comment at the top recording
the original description, so the file is self-documenting.

Modify an existing agent:

```bash
# CLI — load and modify
./agent-create -f agent.ss "add error handling for missing results"

# CLI — interactive REPL
./agent-create -i agent.ss

# Frontend — Edit tab → type instruction → click Modify
```

---

## Frontend

Start the web UI:

```bash
python frontend/server.py
# → http://localhost:5555
```

Features:
- Browse, create, edit, and run agents
- Type-checked input fields for declared input specs
- Progress display (fetch size, thinking prompts, token usage)
- Syntax-highlighted code view (Python-based highlighting)
- Edit with AI modification prompt
