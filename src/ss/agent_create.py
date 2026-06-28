import sys
import json
import argparse
import logging
from openai import OpenAI
from .config import load_config

logger = logging.getLogger(__name__)

AGENT_CREATE_PROMPT = """
You are the Structured Skills Agent Generator. Your job is to generate `.ss` scripts that implement reusable agents.

The script must follow this structure:
1. Optional `import` lines for MCP servers
2. One or more `def` skills implementing the core logic
3. A final section that calls the main skill with `$prompt` and writes output

CRITICAL RULES:
- The generated script must read input from `$prompt` register.
- The generated script must write its final output to `$prompt` register (so run-agent can display it).
- Use `def`/`end` to define reusable skills.
- Use `infer` for LLM reasoning steps.
- Use `%` prefix for tool calls (MCP or built-in).
- Use `for each`/`end` for iteration.
- Use `if`/`else`/`end` for conditionals.
- Use `return` to return values from skills.
- Each `def` must end with `end`.
- Each `for each` must end with `end`.
- Each `if` must end with `end`.
- Comments start with `#`.

SYNTAX REFERENCE:
- $var = "literal"          # Assign string
- $var = $other             # Copy register
- $var = ["a", "b"]         # JSON list
- $var = %tool arg1 arg2    # Call tool (no registers)
- $var = %tool arg1 -> $reg # Call tool, store in $reg
- $var = infer "prompt"     # LLM inference
- def skill $param: ... end # Define reusable skill
- return $value             # Return from skill
- for each $item in $list: ... end  # Loop
- if $cond: ... else: ... end       # Conditional
- import name from file     # Import MCP server

BUILT-IN TOOLS (no import needed):
- %read $path          # Read file
- %write $path $data   # Write file
- %append $list $item  # Append to list
- %list_files $dir     # List directory
- %add $a $b           # Add numbers
- %sum $list           # Sum list

GENERATED SCRIPT TEMPLATE:
The script should end with something like:
$result = %my_main_skill $prompt
$prompt = $result

Where my_main_skill is the main entry point skill.

USER REQUEST: {prompt}

OUTPUT:
Return ONLY the `.ss` script content. No explanations, no markdown formatting.
Start with imports if needed, then defs, then the main call.
"""

def main():
    parser = argparse.ArgumentParser(description="Generate an ss agent script from a prompt")
    parser.add_argument("prompt", help="Description of the agent to create (e.g. 'make a deep research agent')")
    parser.add_argument("--output", "-o", default=None, help="Output file path (default: derived from prompt)")
    parser.add_argument("--config", default="config.toml", help="Path to config file (default: %(default)s)")

    args = parser.parse_args()
    prompt = args.prompt

    if args.output:
        output_path = args.output
    else:
        name = prompt.lower().replace(" ", "_").replace("make_a_", "").replace("create_a_", "")[:30]
        output_path = f"{name}.ss"

    config = load_config(args.config)["decoder"]
    client = OpenAI(
        base_url=config["base_url"],
        api_key=config["api_key"] or "none"
    )

    print(f"Generating agent: {prompt}")

    try:
        response = client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": AGENT_CREATE_PROMPT.format(prompt=prompt)}
            ]
        )
        usage = getattr(response, "usage", None)
        if usage:
            logger.info("Tokens: %s prompt → %s generated → %s total", usage.prompt_tokens, usage.completion_tokens, usage.total_tokens)
        else:
            logger.info("Tokens: (not reported by API)")
    except Exception as e:
        import os
        config_abspath = os.path.abspath(args.config)
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
        sys.exit(1)

    script = response.choices[0].message.content.strip()
    if script.startswith("```"):
        script = script.split("\n", 1)[1]
    if script.endswith("```"):
        script = script.rsplit("```", 1)[0]
    script = script.strip()

    with open(output_path, "w") as f:
        f.write(script + "\n")

    print(f"Agent written to {output_path}")

if __name__ == "__main__":
    main()
