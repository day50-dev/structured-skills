import sys
import json
import argparse
import logging
from openai import OpenAI
from .config import load_config

logger = logging.getLogger(__name__)

AGENT_CREATE_PROMPT = """
You are a code generator for the `.ss` scripting language. Generate ONLY the script code (no markdown, no explanation).

LANGUAGE RULES:
- `$var = "value"` — string assignment
- `$var = $other` — copy a register
- `$var = ["a", "b"]` — JSON list literal
- `$var = infer "prompt with $vars"` — calls an LLM, result stored in $var
- `$var = %tool arg1 arg2` — calls a tool, result stored in $var
- `%tool arg1 arg2` — calls a tool (discard result)
- `def name $param1, $param2:` ... `end` — skill definition
- `return $value` — return from skill
- `for each $item in $list:` ... `end` — iterate
- `if $cond:` ... `else:` ... `end` — conditional
- Comments start with `#`

BUILT-IN TOOLS (no import needed):
- %read path            # Read file → string
- %write path data      # Write file
- %append list item     # Append to list (mutates in place)
- %join list separator  # Join list items into a string
- %list_files dir       # List files → JSON list
- %add a b              # Add numbers
- %sum list             # Sum a list of numbers

CRITICAL RULES FOR CORRECT SCRIPTS:
1. NEVER hardcode placeholder data. ALL content must come from `infer` calls at runtime.
2. To build a list from infer results: start with `$list = []`, then `%append $list $item`.
3. To join a list into a string for further infer calls, use `%join`.
4. `infer` accepts a prompt string. Reference registers inside it like `"analyze $query"`.
5. The script receives user input in `$prompt`. It MUST write final output back to `$prompt`.
6. Script structure: def skills first, then a main section that calls them.

CRITICAL: `infer` calls an LLM that has NO internet access and NO browsing ability.
Infer prompts MUST:
- Ask the LLM to use its own training knowledge (e.g. "Based on your knowledge, explain...")
- NEVER say "search", "fetch", "browse", "look up", "access", "scrape", "crawl", "retrieve"
- NEVER ask for real-time data or live information
- Instead use: "From your knowledge, describe...", "Analyze...", "List...", "Explain..."

CRITICAL: To call a skill you defined with `def`, use `%` prefix. Always write `$var = %skill_name $args`.
WRONG: `$result = my_skill $input`
RIGHT: `$result = %my_skill $input`

CORRECT EXAMPLE (research agent):
```
def research $topic:
    $info = infer "Based on your knowledge, analyze $topic. Provide key facts and detailed information."
    return $info
end

def write_report $content:
    $report = infer "Write a comprehensive report based on this: $content"
    return $report
end

$findings = %research $prompt
$prompt = %write_report $findings
```

USER REQUEST: {prompt}

OUTPUT:
Return ONLY the `.ss` script content. No explanations, no markdown formatting."""

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
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
