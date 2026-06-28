import sys
import re
import argparse
import logging
from openai import OpenAI
from .config import load_config

logger = logging.getLogger(__name__)

SYNTAX_GUIDE = """ss (Structured Skills) is a scripting language for building LLM-powered agents.

VARIABLES: $varname holds strings, numbers, or lists.
  $greeting = "hello"
  $count = 42
  $items = ["a", "b", "c"]

INPUT DECLARATIONS (declare typed inputs the script expects):
  input $REPO_LIST as file        # runner reads file content on your behalf
  input $USERNAME as string       # plain text input
  input $REPO_URL as repo         # GitHub repo URL (prompts user for a URL)
  input $THRESHOLD as number      # numeric value

PRINTING:
  %print $varname             # prints the value

IMPORT MCP TOOLS:
  import fetch from uvx://mcp-server-fetch
  import github from mcp_servers.json   # or uvx://, npx://

CALL MCP TOOLS with named args:
  $result = %fetch.fetch url=$url max_length=8000

CALL BUILT-IN TOOLS:
  $data = %read $path                # read a file
  %write $path $data                 # write a file
  %append_to_file $path $data        # append to file
  %list_files $dir                   # list files in directory
  $sum = %add $a $b                  # add two numbers
  $total = %sum $list                # sum a list
  %append $list $item                # append to list
  $joined = %join $list $sep         # join list with separator
  $encoded = %urlencode $string      # URL-encode a string

LLM INFERENCE:
  $result = infer "Your instruction here, referencing $variables"

SKILLS (functions):
  def skill_name $param1 $param2:
      $intermediate = infer "Do something with $param1 and $param2"
      return $intermediate
  end

CONDITIONALS:
  if $condition:
      ...
  else:
      ...
  end

LOOPS:
  for each $item in $list:
      ...
  end

COMMENTS: # anything after a hash

Inputs are declared at the top of the script with `input $REG as TYPE`.
The runner prompts for each declared input (or reads them from CLI args).
The script reads from declared $REGISTERS and writes the final answer back to $prompt."""

AGENT_CREATE_PROMPT = """You are an ss (Structured Skills) code generator. Write a complete .ss script that fulfills the user's request.

SYNTAX REFERENCE:
""" + SYNTAX_GUIDE + """

Examples of valid ss scripts:

--- 1. Simple search-and-summarize ---
import fetch from uvx://mcp-server-fetch?--ignore-robots-txt
$encoded = %urlencode $prompt
$url = "https://lite.duckduckgo.com/lite/?q=$encoded"
$results = %fetch.fetch url=$url max_length=8000
$answer = infer "From these search results ($results), extract the key facts about the query. Write a concise summary."
$prompt = $answer

--- 2. Multi-step pipeline with skills ---
import fetch from uvx://mcp-server-fetch?--ignore-robots-txt
def fetch_results $q:
    $encoded = %urlencode $q
    $url = "https://lite.duckduckgo.com/lite/?q=$encoded"
    $results = %fetch.fetch url=$url max_length=8000
    return $results
end
def compare $a $b:
    $analysis = infer "Compare these two sets of results: A: $a B: $b. Find commonalities and differences."
    return $analysis
end
$r1 = %fetch_results $prompt
$r2 = %fetch_results "additional context $prompt"
$prompt = %compare $r1 $r2

--- 3. Input declarations (typed inputs) ---
input $REPO_FILE as file
input $TOKEN as string
$report = infer "Read the repository data from $REPO_FILE and consider the access token $TOKEN. Write an analysis plan."
$prompt = $report

--- 4. File-processing agent with input ---
input $DATA_FILE as file
$content = infer "Read this data: $DATA_FILE. Summarize the key findings."
$prompt = $content

Rules:
- Use $prompt for input and write the final answer back to $prompt
- infer prompts must be imperative, direct, 1-3 sentences
- Use %name.verb key=value syntax for MCP tool calls
- Every def must have a matching end
- Every if/for must have a matching end
- Output ONLY the raw .ss script, no explanations, no markdown formatting

USER REQUEST: {prompt}"""

MODIFY_PROMPT = """Modify the ss script below according to the user's instruction.

SYNTAX REFERENCE:
""" + SYNTAX_GUIDE + """

Rules:
- Use $prompt for input and write the final answer back to $prompt
- infer prompts must be imperative, direct, 1-3 sentences
- Use %name.verb key=value syntax for MCP tool calls
- Every def must have a matching end
- Every if/for must have a matching end
- Output ONLY the complete modified .ss script, no explanations, no markdown formatting

SCRIPT:
{script}

USER INSTRUCTION: {instruction}

OUTPUT ONLY the modified script."""

BUILTIN_TOOLS = {"infer", "read", "write", "append", "join", "list_files", "add", "sum",
                 "True", "False", "None"}


def _fix_script(script: str) -> str:
    lines = script.split("\n")
    fixed = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            fixed.append(line)
            continue
        m = re.match(r"^(\s*\$\w+\s*=\s*)([\w][\w.-]*)(\s+\$.*)", stripped)
        if m:
            name = m.group(2)
            if name not in BUILTIN_TOOLS and not name.startswith("%"):
                indent = line[:len(line) - len(line.lstrip())]
                fixed.append(indent + m.group(1).strip() + " %" + name + m.group(3))
                continue
        fixed.append(line)
    return "\n".join(fixed)


def _call_llm(system_prompt: str, config: dict) -> tuple[str, dict | None]:
    client = OpenAI(base_url=config["base_url"], api_key=config["api_key"] or "none")
    response = client.chat.completions.create(
        model=config["model"],
        messages=[{"role": "system", "content": system_prompt}],
    )
    usage = getattr(response, "usage", None)
    tokens = {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens, "total": usage.total_tokens} if usage else None
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    script = raw
    script = _fix_script(script)
    return script, tokens


def _generate_script(prompt: str, config: dict) -> tuple[str, dict | None]:
    system_msg = AGENT_CREATE_PROMPT.format(prompt=prompt)
    return _call_llm(system_msg, config)


def _modify_script(script: str, instruction: str, config: dict) -> tuple[str, dict | None]:
    system_msg = MODIFY_PROMPT.format(script=script, instruction=instruction)
    return _call_llm(system_msg, config)


def _print_script(script: str):
    print()
    print("=" * 60)
    print(script)
    print("=" * 60)
    print()


def _print_api_error(e: Exception, config_abspath: str, config: dict):
    error_str = str(e).lower()
    if "auth" in error_str or "key" in error_str or "401" in error_str or "403" in error_str:
        print(f"Error: LLM API authentication failed — check the api_key in {config_abspath}")
    elif "connect" in error_str or "connection" in error_str or "resolve" in error_str:
        print(f"Error: Could not reach {config['base_url']} — check the base_url in {config_abspath}")
    else:
        print(f"Error: LLM API call failed: {e}")
    print(f"""
How to fix:
  Edit {config_abspath} and ensure these are correct:
    [llm]
    model = "gpt-4o"
    base_url = "https://api.openai.com/v1"
    api_key = "sk-..."   # your real API key
""")


def _derive_output_path(prompt: str, file_path: str | None, output_arg: str | None) -> str:
    if output_arg:
        return output_arg
    if file_path:
        return file_path
    name = prompt.lower().replace(" ", "_").replace("make_a_", "").replace("create_a_", "")[:30]
    return f"{name}.ss"


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Generate or modify an ss agent script")
    parser.add_argument("prompt", nargs="?", default=None,
                        help="Description of the agent to create (or modification instruction with -f)")
    parser.add_argument("--output", "-o", default=None, help="Output file path")
    parser.add_argument("--config", default="config.toml", help="Path to config file (default: %(default)s)")
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Interactive REPL for iterative modification")
    parser.add_argument("--file", "-f", default=None,
                        help="Load existing .ss script for modification (implies non-template mode)")

    args = parser.parse_args()
    config = load_config(args.config)["decoder"]

    # --- Interactive REPL ---
    if args.interactive:
        if args.file:
            with open(args.file) as f:
                script = f.read()
            print(f"Loaded script from {args.file}")
        elif args.prompt:
            print(f"Generating agent: {args.prompt}")
            script, tokens = _generate_script(args.prompt, config)
            if tokens:
                logger.info("Tokens: %s prompt → %s generated → %s total", tokens["prompt"], tokens["completion"], tokens["total"])
        else:
            print("Error: --interactive requires either --file or a prompt")
            sys.exit(1)

        _print_script(script)
        print("Enter modifications, or /exit to quit.")
        print()

        try:
            while True:
                try:
                    instruction = input("modify> ")
                except EOFError:
                    print()
                    break
                if not instruction.strip():
                    continue
                if instruction.strip() == "/exit":
                    break
                try:
                    script, tokens = _modify_script(script, instruction, config)
                    if tokens:
                        logger.info("Tokens: %s prompt → %s generated → %s total", tokens["prompt"], tokens["completion"], tokens["total"])
                    _print_script(script)
                except Exception as e:
                    print(f"Error: {e}")
                    print()
        except KeyboardInterrupt:
            print()

        output_path = _derive_output_path(args.prompt or "", args.file, args.output)
        with open(output_path, "w") as f:
            f.write(script + "\n")
        print(f"Saved to {output_path}")
        return

    # --- Modify existing file ---
    if args.file:
        with open(args.file) as f:
            script = f.read()
        print(f"Loaded script from {args.file}")
        instruction = args.prompt or "modify this script"
        print(f"Modifying: {instruction}")
        try:
            script, tokens = _modify_script(script, instruction, config)
            if tokens:
                logger.info("Tokens: %s prompt → %s generated → %s total", tokens["prompt"], tokens["completion"], tokens["total"])
        except Exception as e:
            _print_api_error(e, args.config, config)
            sys.exit(1)
        _print_script(script)
        output_path = _derive_output_path(instruction, args.file, args.output)
        with open(output_path, "w") as f:
            f.write(script + "\n")
        print(f"Written to {output_path}")
        return

    # --- Generate new script ---
    if not args.prompt:
        print("Error: a prompt is required")
        sys.exit(1)

    prompt = args.prompt
    output_path = _derive_output_path(prompt, None, args.output)

    print(f"Generating agent: {prompt}")

    try:
        script, tokens = _generate_script(prompt, config)
        if tokens:
            logger.info("Tokens: %s prompt → %s generated → %s total", tokens["prompt"], tokens["completion"], tokens["total"])
        else:
            logger.info("Tokens: (not reported by API)")
    except Exception as e:
        import os
        _print_api_error(e, os.path.abspath(args.config), config)
        sys.exit(1)

    _print_script(script)

    with open(output_path, "w") as f:
        f.write(script + "\n")

    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
