import sys
import re
import json
import argparse
import logging
from openai import OpenAI
from .config import load_config

logger = logging.getLogger(__name__)

TEMPLATE = """def answer $query:
    $result = infer "INSTRUCTION_1"
    return $result
end

$prompt = %answer $prompt"""

AGENT_CREATE_PROMPT = """You are filling in a .ss script template. Replace INSTRUCTION_1 with a short, direct instruction for an LLM.

USER REQUEST: {prompt}

TEMPLATE:
{TEMPLATE}

CRITICAL: INSTRUCTION_1 will be sent to an LLM. It must be:
- A direct question or instruction (1-2 sentences max)
- Asking the LLM to use its own knowledge
- NO meta-commentary, no roleplay instructions, no "act as"
- NEVER use: search, fetch, browse, look up, access, retrieve, scrape, crawl
- Reference $query to include the user's original question

Good examples:
  "Answer this question in detail: $query"
  "Explain the following topic thoroughly: $query"
  "List and describe the key aspects of: $query"

Bad examples:
  "Based on your knowledge, act as a researcher..."  (roleplay/meta)
  "From your knowledge, please provide..."  (wordy)
  "You will receive raw research data..."  (assumes context it doesn't have)

OUTPUT: the filled template. No explanations, no markdown."""

BUILTIN_TOOLS = {"infer", "read", "write", "append", "join", "list_files", "add", "sum",
                 "True", "False", "None"}

def _fix_script(script: str) -> str:
    """Post-process generated script: fix missing % on skill calls."""
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


def _generate_script(prompt: str, config: dict) -> tuple[str, dict | None]:
    client = OpenAI(base_url=config["base_url"], api_key=config["api_key"] or "none")
    system_msg = AGENT_CREATE_PROMPT.format(
        prompt=prompt,
        TEMPLATE=TEMPLATE,
    )
    response = client.chat.completions.create(
        model=config["model"],
        messages=[{"role": "system", "content": system_msg}],
    )
    usage = getattr(response, "usage", None)
    tokens = {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens, "total": usage.total_tokens} if usage else None
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    lines = raw.split("\n")
    if lines and lines[0].lower().startswith("template"):
        lines = lines[1:]
    script = "\n".join(lines).strip()
    script = _fix_script(script)
    return script, tokens


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

    print(f"Generating agent: {prompt}")

    try:
        script, tokens = _generate_script(prompt, config)
        if tokens:
            logger.info("Tokens: %s prompt → %s generated → %s total", tokens["prompt"], tokens["completion"], tokens["total"])
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

    with open(output_path, "w") as f:
        f.write(script + "\n")

    print(f"Agent written to {output_path}")

if __name__ == "__main__":
    main()
