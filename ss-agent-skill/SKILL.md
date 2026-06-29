---
name: structured-skills
description: |
  Generate and execute Structured Skills (.ss) programs — a register-based VM for LLM-orchestrated multi-step tasks.
  Use when the user needs multi-step research, data processing pipelines, extraction workflows, batch file operations,
  or any task that requires looping, conditionals, function calls, and LLM inference composed together reliably.
  Do NOT use for single-step Q&A, simple lookups, or tasks that don't benefit from structured control flow.
---

# Structured Skills (ss) Agent Skill

This skill teaches you how to use the **Structured Skills** VM to bootstrap and run reusable agents. The workflow has two stages:

1. **`agent-create`** — one-shot a prompt into an `.ss` agent script
2. **`run-agent`** — invoke the agent script with a concrete input prompt

Both are available as CLI commands and can also be run via `strusky create` / `strusky run`.

## Quick Start

```bash
# From the structured-skills project root:

# Stage 1: Bootstrap an agent from a one-shot prompt
agent-create "make a deep research agent"
# → writes deep-research.ss

# Stage 2: Run it on a real problem
run-agent deep-research.ss "I want to go from NYC to Chicago, Denver, and Miami in June — find the cheapest flights and create an itinerary"
# → executes the deep-research pipeline with that prompt, prints final registers
```

## How It Works

### `agent-create`

Runs an LLM (same config as the ss decoder) with a system prompt that teaches it the ss syntax and conventions. It generates a complete `.ss` file containing:

- Optional `import` statements for MCP servers
- One or more `def` skills implementing the agent logic
- A final section that calls the main skill with `$prompt` and stores the result back in `$prompt`

The convention is: **`$prompt` in, `$prompt` out**.

```bash
agent-create "make a research agent that searches the web, fetches pages, extracts insights, and writes a report"
# → research-agent.ss
```

**Context flag (`-c`):** Pass reference material (URL, file, or directory) that the LLM uses as instructions. Useful for cloning interfaces or following existing specs:

```bash
# Clone an API from its llms.txt
agent-create -c https://example.com/docs/llms.txt "clone this api"

# Build from a local spec
agent-create -c ./design-spec.md "implement the search agent described here"
```

When `-c` is a directory, all files are read recursively with their relative paths as headers. The content is prepended to the generation prompt as "Reference material".

### `run-agent`

Prepends `$prompt = "<user input>"` to the agent script, then runs it through the standard ss pipeline: decoder → opcodes → VM execution.

```bash
run-agent research-agent.ss "Post-quantum cryptography standards 2026"
```

Prints final register state (including `$prompt` with the output).

### Example: End-to-End Flow

**User:** "Make a deep research engine"

```bash
# Claude runs:
agent-create "make a deep research engine"

# This generates something like deep-research.ss:
```

```ss
import brave-search from uvx://@anthropic/brave-search-mcp

def research $topic:
    $queries = infer "Break '$topic' into 4 specific search queries. Return as a JSON list."
    $all_insights = []
    for each $query in $queries:
        $urls = %brave-search.search $query
        for each $url in $urls:
            $page = %brave-search.fetch $url
            $insight = infer "Extract the key technical insight from: $page"
            %append $all_insights $insight
        end
    end
    $report = infer "Synthesize into a markdown report: $all_insights"
    return $report
end

$report = %research $prompt
$prompt = $report
```

**User:** "I need to go from New York to Chicago, Denver, and Miami in June — find the cheapest flights and build an itinerary"

```bash
# Claude runs:
run-agent deep-research.ss "I need to go from New York to Chicago, Denver, and Miami in June — find the cheapest flights and build an itinerary"
```

The agent script searches each leg, extracts prices, has the LLM solve the routing, and returns an itinerary — all through the structured ss pipeline.

## Syntax Reference

### Registers (`$var`)
```ss
$name = "Alice"
$count = 42
$tags = ["rust", "llm", "vm"]
```

### The Sentinel (`%`) — tool and skill calls
```ss
$result = %brave-search.search $topic
%append $list $item
```

### Inference (`infer`) — LLM reasoning
```ss
$summary = infer "summarize $document in one sentence"
```
`$register` references are substituted at runtime.

### Skills (`def` / `end`)
```ss
def research $topic:
    $results = %websearch $topic
    $summary = infer "summarize $results"
    return $summary
end
```

### Conditionals (`if` / `else` / `end`)
```ss
if $status:
    %log "OK"
else:
    %alert "FAILED"
end
```

### Loops (`for each` / `end`)
```ss
for each $item in $items:
    %process $item
end
```

### Imports
```ss
import brave-search from uvx://@anthropic/brave-search-mcp   # via URI
import fetch from mcp_servers.json                            # via config file
```

After import, tools are callable as `%server-name.tool-name`.

### Loading Agent Skills (SKILL.md directories)
```ss
load skill ./skills/my-skill as my
```

This loads a standard Agent Skills directory containing `SKILL.md`, and makes available:

- **`$my_instructions`** — register containing the SKILL.md body (instructions)
- **`$my_meta`** — register with JSON metadata (name, description, available scripts)
- **`%my.<script>`** — call scripts from the skill's `scripts/` directory
- **`%my.instructions`** — retrieve the instructions inline
- **`%my.description`** — retrieve the description inline

Example:
```ss
load skill ./skills/pdf-processing as pdf
$task = "Extract tables from invoice.pdf following these rules: $pdf_instructions"
$result = infer $task
# Or run a bundled script:
%pdf.extract invoice.pdf
```

### Built-in Tools (no import)

| Invocation | Behavior |
|---|---|
| `%read $path` | Read file |
| `%write $path $data` | Write file |
| `%append_to_file $path $data` | Append to file |
| `%list_files $dir` | List directory |
| `%append $list $item` | Append to in-memory list |
| `%add $a $b` | Add two numbers |
| `%sum $list` | Sum numeric list |

## Best Practices for Agent Scripts

1. **`$prompt` in, `$prompt` out** — the script reads its input from `$prompt` and writes its output back to `$prompt`.

2. **Minimize `infer` calls** — each one hits the LLM. Batch items into a single inference where possible.

3. **Prefer built-in tools** — `%read`, `%write`, `%append` are deterministic and fast.

4. **Keep skills small** — one skill = one subtask. Compose them.

5. **Document the script** — use `#` comments so the generated script is readable.

6. **The LLM never decides control flow** — the VM branches on `if` conditions and loops over `for each`. The LLM only provides values via `infer`.
