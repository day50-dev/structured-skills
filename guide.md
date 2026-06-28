# strusky Language Reference — for Modification Prompts

Use this reference when modifying agents. The LLM knows strusky syntax — your job is to describe what you want clearly. Reference the language features below to be precise.

## Variables & Registers

```ss
$name = "Alice"              # string
$count = 42                  # number
$items = ["a", "b", "c"]     # list (JSON array)
$flag = True                 # boolean
$template = "Hello $name"    # string interpolation
```

## Comments

```ss
# this is a comment
$prompt = $result  # inline comment
```

## Input Declarations

Scripts declare what they need at the top. You can add, remove, or change these:

```ss
input $REPO_FILE as file       # runner reads file content into the register
input $USERNAME as string      # plain text
input $THRESHOLD as number     # numeric value
input $REPO_URL as repo        # URL (stored as string)
```

## Output Declarations

Scripts declare what they produce:

```ss
output $report as report            # structured text (default)
output $data as json                # JSON
output $report as file: output.md   # writer register content to file after run
output $result as string            # plain string
```

## Inference

The `infer` keyword sends a prompt to the LLM and stores the response. Keep prompts imperative:

```ss
$summary = infer "Summarize: $text"
$answer = infer "Compare these two analyses: $a and $b"
```

## Control Flow

Conditional:

```ss
if $condition:
    $x = infer "Handle true case: $data"
else:
    $x = infer "Handle false case"
end
```

Loop:

```ss
for each $item in $items:
    $analysis = infer "Analyze: $item"
    %append $all_results $analysis
end
```

## Skills (Functions)

Define reusable blocks. Registers inside don't leak out (except return):

```ss
def search_web $query:
    $results = %fetch.fetch url=$query max_length=8000
    $answer = infer "Extract key facts from: $results"
    return $answer
end

$answer = %search_web $prompt
```

## MCP Servers

Import servers at the top, then call their tools with named args:

```ss
import fetch from uvx://mcp-server-fetch?--ignore-robots-txt
import github from npx://@modelcontextprotocol/server-github
import brave-search from mcp_servers.json

$results = %fetch.fetch url=$url max_length=8000 raw=True
$info = %github.get_repo owner=$owner repo=$repo
```

Args with `=` are key-value pairs. Values auto-convert (`8000` → int, `True` → bool). Server flags go in the query string.

## Built-in Tools

| Tool | Args | Purpose |
|------|------|---------|
| `%read` | `$path` | Read file contents |
| `%write` | `$path $data` | Overwrite a file |
| `%append_to_file` | `$path $data` | Append to file |
| `%list_files` | `$dir` | List directory |
| `%add` | `$a $b` | Add two numbers |
| `%sum` | `$list` | Sum a list |
| `%append` | `$list $item` | Append to in-memory list |
| `%join` | `$list $sep` | Join list items |
| `%urlencode` | `$string` | URL-encode |
| `%print` | `$value` | Print to stderr |

## Tips for Modification Prompts

- **Be specific about what to change**: "Add an input $FOO as file at the top" not "make it better"
- **Reference existing register names**: "After $results is set, add an inference that extracts links"
- **Add a new skill with def/end**: "Add a skill called summarize that takes $text and returns a summary"
- **Change input or output types**: "Change input $X to number instead of string"
- **Use control flow**: "Wrap the search in an if/else to handle empty $query"
- **The LLM knows your existing code** — just tell it what to modify
