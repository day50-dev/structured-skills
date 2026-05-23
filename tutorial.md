# Structured Skills Tutorial

Structured Skills (**ss**) is a tiny virtual machine designed to orchestrate LLMs. Unlike other agent frameworks, **the VM owns the control flow**, and the LLM is only used for decoding "vibe" syntax into opcodes and performing bounded inference.

## 1. Core Concepts

### Registers (`$var`)
All data in `ss` is stored in named registers. They are untyped "blobs"—they can hold strings, numbers, JSON objects, or lists.
```ss
$name = "Gemini"
$count = 42
```

### The Sentinel (`%`)
The `%` character marks a routine call. It tells the decoder: "Everything following this is a command to be executed by a tool or a skill."
```ss
%websearch "TEE in kubernetes"
```

### Inference (`infer`)
`infer` is a reserved keyword. It marks the boundary where the program moves from deterministic execution to stochastic LLM reasoning.
```ss
$summary = infer "summarize this result in one sentence"
```

---

## 2. Your First Program

Create a file named `hello.ss`:
```ss
$topic = "The history of the telegraph"
$fact = infer "Tell me one interesting fact about $topic"
%write "fact.txt" $fact
```
Run it:
```bash
strusky hello.ss
```

---

## 3. Skills: Building Reusable Logic

Skills are defined using `def` and closed with `end`. They allow you to compose complex behavior.

```ss
def research $topic:
    $pages = %websearch $topic
    $notes = []
    for each $page in $pages:
        $extract = infer "Extract the key technical claim from $page"
        %append $notes $extract
    end
    return $notes
end

$my_research = %research "Post-quantum cryptography"
```

---

## 4. The "Vibe" Decoder

One of the most powerful features of `ss` is that the syntax is flexible. Because an LLM decodes each line, you don't have to remember perfect grammar. All of these produce the same `CALL` opcode:

- `%websearch "query" -> $result`
- `$result = %websearch for "query"`
- `do %websearch for "query" and save to $result`

The decoder uses the `DECODER_PROMPT` in `ss/prompts.py` to map your intent to the VM's instruction set.

---

## 5. Control Flow

The VM handles `if`, `else`, and `for` loops. The LLM **never** decides whether to loop; it only translates the instruction.

### Conditionals
```ss
$status = %check_server "api.example.com"
if $status:
    %log "Server is up"
else:
    %alert "Server is down!"
end
```

### Iteration
```ss
for each $file in %list_files ./data:
    $content = %read $file
    %analyze $content
end
```

---

## 6. Built-in Tools

The standard library includes:
- `read $path`: Read file contents.
- `write $path $data`: Overwrite a file.
- `append_to_file $path $data`: Append to a file.
- `list_files $dir`: Get a list of files.
- `add $a $b` / `sum $list`: Basic arithmetic.
- `append $list $item`: Add to an in-memory list.

---

## 7. Configuration

Structured Skills requires a `config.toml` file in the root directory. Use the provided template to get started:

```bash
cp config.toml.example config.toml
```

Then edit `config.toml` to connect to your LLM provider:

```toml
[llm]
model = "gpt-4o"
base_url = "https://api.openai.com/v1"
api_key = "your-key"
```
If you are using a local model (like `llama.cpp` or `Ollama`), set the `base_url` to your local endpoint and leave the `api_key` blank.

---

## 8. MCP Integration

MCP (Model Context Protocol) servers can be imported and called directly using `uvx://` or `npx://` URI schemes, or via a JSON config file:

```ss
import brave-search from uvx://@anthropic/brave-search-mcp
$result = %brave-search.search "quantum computing"
```

The URI scheme tells the VM how to launch the server:
- `uvx://<package>` → run `uvx <package>` to install and run a Python/PyPI MCP package
- `npx://<package>` → run `npx <package>` for Node/npm MCP packages

For servers that need arguments (e.g., API keys), use a `mcp_servers.json` file:

```json
{
  "brave-search": {
    "command": "uvx",
    "args": ["@anthropic/brave-search-mcp"]
  }
}
```

Then import from the file:
```ss
import brave-search from mcp_servers.json
$result = %brave-search.search "quantum computing"
```

The server is launched as a subprocess and communicated with via stdin/stdout JSON-RPC. It stays alive for the duration of the script and is automatically cleaned up when the script finishes.

---

## 9. Best Practices

1. **Be Explicit with `infer`:** Only use `infer` when you need reasoning. Use `%tools` for everything else.
2. **Small Skills:** Break complex tasks into small skills. It makes the program easier to audit.
3. **Grep-ability:** Because `infer` is a keyword, you can always run `grep "infer" my_program.ss` to see exactly where your program is non-deterministic.
