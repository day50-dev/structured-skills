# Structured Skills (ss)

**Structured Skills** is a minimal stack-based virtual machine for orchestrating LLM-powered programs. It gives LLMs the equivalent of structured programming—loops, conditionals, variables, function calls—while keeping the model strictly out of control flow decisions.

## 🚀 The Core Insight

LLMs fail at long multi-step tasks not because they lack intelligence, but because they hold too much state and make too many implicit decisions. Structured Skills solves this by making the VM own all control flow. The LLM does only two things:

1. **Decode** one line of "vibe" syntax into a machine opcode (via LLM or regex fallback).
2. **Execute** bounded inference when explicitly asked via the `infer` keyword.

The result is a system where complex research, analysis, and automation tasks can be expressed in 10-20 lines of near-English code and executed reliably on small local models.

## 🏗️ Architecture

The execution pipeline has three stages:

```
.ss file  ──►  Decoder  ──►  Opcodes  ──►  VM
(vibe)          (regex+LLM)     (IR)        (executor)
```

### 1. Decoder (`src/ss/decoder.py`)

Reads a `.ss` file line by line and translates each line into one or more `Opcode` objects.

- **Structural keywords** (`def`, `if`, `for`, `return`, `import`, `end`, `else:`) are parsed via **regex** — deterministic and fast.
- **"Vibe" lines** (assignments, calls, inference) are sent to an **LLM** with the `DECODER_PROMPT` which returns JSON opcodes. If the LLM is unavailable, it falls back to regex.

The decoder collects `import` statements upfront to provide the LLM with context about available MCP tools.

### 2. Opcodes (`src/ss/opcodes.py`)

The instruction set is a 12-opcode IR:

| Opcode   | Params                                     | Purpose                                   |
|----------|--------------------------------------------|-------------------------------------------|
| ASSIGN   | `register`, `value`                        | Store a value in a register               |
| CALL     | `name`, `args`, `register?`                | Call a skill, built-in tool, or MCP tool  |
| INFER    | `prompt`, `register?`                      | Send a prompt to the LLM, store result    |
| LOOP     | `item`, `register`                         | Iterate over a list                       |
| END      | —                                          | End of a block (if/loop/def)              |
| IF       | `condition`                                | Conditional branch                        |
| ELSE     | —                                          | Else branch                               |
| JUMP     | —                                          | Unconditional jump (internal)             |
| JUMPIF   | —                                          | Conditional jump (internal)               |
| DEF      | `name`, `params`                           | Define a skill (function)                 |
| RETURN   | `value`                                    | Return from a skill                       |
| IMPORT   | `name`, `source`                           | Register an MCP server                    |
| HALT     | —                                          | Stop execution                            |

### 3. VM (`src/ss/vm.py`)

A register-based VM with four runtime structures:

- **Registers** (`$var`): Named blobs holding strings, numbers, lists, or JSON. All data lives here.
- **Data stack**: Used internally for expression evaluation.
- **Call stack**: Saves return IP and register snapshots when calling skills (`def` blocks), enabling nested calls and recursion.
- **Loop stack**: Tracks iteration state (current index, item list, item variable) for `for each` loops.

#### Program Loading (`load_program`)

Before execution, the VM makes a single pass to:
1. Record **skill definitions** — mapping skill names to their `(params, start_ip)`.
2. Build **jump targets** — pairing `IF`/`LOOP`/`ELSE` with their matching `END`, and `DEF` with its `END`.

#### Execution Loop (`run`)

Walks `self.ip` through the opcode list, executing each opcode in sequence. The VM owns all control flow — the LLM never decides whether to branch or loop.

#### Key Instruction Behaviors

**ASSIGN**: Resolves the value through `evaluate()` — dereferences `$register` references, parses JSON lists, strips quotes — and stores it in the target register.

**CALL**: Checks if the name matches a defined skill. If so, it pushes a frame onto the call stack (saving registers and return IP), maps arguments to skill parameters, and jumps to the skill body. Otherwise, it resolves the call as an **MCP tool** (if imported) or a **built-in tool** (`read`, `write`, `append_to_file`, `append`, `add`, `sum`, `list_files`).

**INFER**: Replaces `$register` references in the prompt with their current values, then calls the LLM (or a deterministic mock for testing). Stores the response in the target register.

**IF**: Evaluates the condition. If falsy, jumps to the matching `ELSE` or `END` via the precomputed jump target.

**LOOP**: On first visit, evaluates the list and initializes a loop state on the loop stack. On subsequent visits, increments the index. When the list is exhausted, pops the loop state and jumps to the matching `END`.

**END**: If the matching block start is a `LOOP`, jumps back to it (creating the cycle). Otherwise, falls through.

**DEF**: Skips the skill body by jumping to the matching `END`.

**RETURN**: Pops the call stack, restores the caller's registers, stores the return value in the target register, and jumps back to the caller.

## 🚀 Quick Start: Bootstrap an Agent

Two CLI tools turn natural language into reusable ss agents:

```bash
# Step 1: Bootstrap an agent from a one-shot prompt
agent-create "make a deep research engine"
# → Generates deep-research.ss with a reusable def research $prompt: skill

# Step 2: Run the agent on a real problem
run-agent deep-research.ss "I need to go from NYC to Chicago, Denver, and Miami in June — find the cheapest flights and create an itinerary"
# → ss VM executes the multi-step pipeline and returns the result
```

### How it works

**`agent-create`** sends your prompt to an LLM along with a system prompt that teaches it the ss syntax and conventions. The LLM generates a complete `.ss` script with `def` skills, tool calls, loops, and inference. The script reads from `$prompt` and writes its output back to `$prompt`.

```bash
agent-create "make a research agent that searches the web, fetches pages, extracts insights, and writes a report"
# → research-agent.ss
```

**`run-agent`** prepends `$prompt = "<your input>"` to the script and runs it through the standard ss pipeline:

```bash
run-agent research-agent.ss "Post-quantum cryptography standards 2026"
```

### Example: Deep Research Engine

What `agent-create "make a deep research engine"` generates:

```ss
import brave-search from mcp_servers.json

def research $topic:
    $queries = infer "Break '$topic' into 4 search queries. Return as JSON list."
    $all_insights = []
    for each $query in $queries:
        $urls = %brave-search.search $query
        for each $url in $urls:
            $page = %brave-search.fetch $url
            $insight = infer "Extract key insight from: $page"
            %append $all_insights $insight
        end
    end
    $report = infer "Synthesize into a report: $all_insights"
    return $report
end

$result = %research $prompt
$prompt = $result
```

Then use it:

```bash
run-agent deep-research.ss "I need to go from NYC to Chicago, Denver, and Miami in June — find the cheapest flights and create an itinerary"
```

### Run scripts directly

You can also run `.ss` scripts directly:

```bash
python3 -m ss.cli myscript.ss
./ss myscript.ss
```

## 📋 Vibe Syntax

Scripts use `$registers` for data, `%prefix` for tool/skill calls, and `infer` for LLM inference.

```ss
$notes = []
for each $url in $urls:
    $page = %brave-search.fetch $url
    %append $notes $page
end

$summary = infer "summarize $notes in one paragraph"
%write output.md $summary
```

Because the decoder uses an LLM for vibe lines, the syntax is flexible — all of these produce the same `CALL` opcode:

- `%websearch "query" -> $result`
- `$result = %websearch for "query"`
- `do %websearch for "query" and save to $result`

## 🛠️ Built-in Tools

| Tool            | Args                          | Description                    |
|-----------------|-------------------------------|--------------------------------|
| `read`          | `$path`                       | Read file contents             |
| `write`         | `$path $data`                 | Overwrite a file               |
| `append_to_file`| `$path $data`                 | Append to a file               |
| `list_files`    | `$dir`                        | List files in a directory      |
| `add`           | `$a $b`                       | Add two numbers                |
| `sum`           | `$list`                       | Sum a list of numbers          |
| `append`        | `$list $item`                 | Append to an in-memory list    |

## 🔌 MCP Integration

Tools from external MCP servers (declared in `mcp_servers.json`) can be imported and called:

```ss
import brave-search from mcp_servers.json
$result = %brave-search.search "quantum computing"
```

## 🛠️ Setup

### Prerequisites
- Python 3.11+
- [direnv](https://direnv.net/) (recommended)

### Installation
```bash
pip install -e .
cp config.toml.example config.toml
# Edit config.toml with your LLM provider
```

### Commands
```bash
ss <file.ss>                          # Run a script directly
ss create <prompt>                    # Generate an agent script
ss run <file.ss> <prompt>             # Run an agent with input
agent-create <prompt>                 # Generate an agent script
run-agent <file.ss> <prompt>          # Run an agent with input
```

## 🧪 Testing

```bash
./ss tests/test_extraction.ss   # Extracts locations from text files
./ss tests/test_math.ss         # Arithmetic on numbers read from files
```

## 📁 Project Structure

```
ss                    Root entry point (shell wrapper)
src/ss/
├── agent_create.py   LLM-prompted script generator (agent-create)
├── agent_runner.py   Prepend $prompt and run via VM (run-agent)
├── cli.py            CLI: reads file, feeds lines to Decoder, loads Program into VM
├── decoder.py        Regex + LLM decoder: vibe lines → Opcodes
├── vm.py             Register-based VM with call/loop stacks and jump targets
├── opcodes.py        OpcodeType enum and Program model
├── prompts.py        DECODER_PROMPT template for the LLM decoder
├── config.py         TOML config loader with section merging
├── mcp.py            MCP server manager (stdin/stdout-based tool calls)
ss-agent-skill/
└── SKILL.md          Anthropic Agent Skill for using ss via agent-create/run-agent
examples/
└── deep_research.ss  Example output of agent-create "make a deep research engine"
tests/
├── test_extraction.ss
├── test_math.ss
├── data/             5 text files with location data
└── data_math/        3 text files with numbers
config.toml.example   LLM configuration template
tutorial.md           Extended tutorial and best practices
```

## 📄 License

MIT — April 2026
