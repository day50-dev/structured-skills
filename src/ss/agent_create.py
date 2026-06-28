import sys
import re
import argparse
import logging
from openai import OpenAI
from .config import load_config

logger = logging.getLogger(__name__)

TEMPLATE = """import fetch from uvx://mcp-server-fetch?--ignore-robots-txt

def research $query:
    $encoded = %urlencode $query
    $url = "https://lite.duckduckgo.com/lite/?q=$encoded"
    $results = %fetch.fetch url=$url max_length=8000
    $entries = infer "INSTRUCTION_1_EXTRACT"
    return $entries
end

def synthesize $info:
    $answer = infer "INSTRUCTION_2_ANSWER"
    return $answer
end

$initial = %research $prompt
$prompt = %synthesize $initial"""

AGENT_CREATE_PROMPT = """Replace INSTRUCTION_1_EXTRACT and INSTRUCTION_2_ANSWER in the template below with actual infer prompt strings (2-3 sentences each, imperative mood, referencing $results or $info).

Example of good INSTRUCTION_1_EXTRACT:
"From these DuckDuckGo search results ($results), extract the key facts relevant to the query. List them as bullet points. Ignore ads and navigation."

Example of good INSTRUCTION_2_ANSWER:
"Based on these extracted facts ($info), write a single clear answer to the original question. Reference $info. Output only the answer."

USER REQUEST: {prompt}

TEMPLATE:
{TEMPLATE}

OUTPUT ONLY the filled template. No explanations, no markdown formatting."""

MODIFY_PROMPT = """Modify the ss script below according to the user's instruction.

Rules:
- Keep the `import fetch from uvx://mcp-server-fetch?--ignore-robots-txt` line
- Use `$registers` for data, `%prefix` for calls, `infer "..."` for LLM inference
- infer prompts should be imperative, 1-3 sentences, referencing $variables
- Output ONLY the complete modified script, no explanations, no markdown formatting

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
    lines = raw.split("\n")
    if lines and lines[0].lower().startswith("template"):
        lines = lines[1:]
    script = "\n".join(lines).strip()
    script = _fix_script(script)
    return script, tokens


def _generate_script(prompt: str, config: dict) -> tuple[str, dict | None]:
    system_msg = AGENT_CREATE_PROMPT.format(prompt=prompt, TEMPLATE=TEMPLATE)
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
