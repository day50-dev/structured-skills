import sys
import tempfile
import argparse
from .decoder import Decoder
from .vm import VM

def main():
    parser = argparse.ArgumentParser(description="Run an ss agent script with a user prompt")
    parser.add_argument("file", help="The .ss agent script to run")
    parser.add_argument("prompt", nargs="?", default="", help="The input prompt (sets $prompt register)")
    parser.add_argument("--config", default="config.toml", help="Path to config file (default: %(default)s)")

    args = parser.parse_args()

    if not args.file:
        parser.print_help()
        sys.exit(1)

    with open(args.file, "r") as f:
        original_lines = f.readlines()

    escaped_prompt = args.prompt.replace("\\", "\\\\").replace("\"", "\\\"")
    prompt_line = f'$prompt = "{escaped_prompt}"\n'

    # Prepend the prompt assignment, then the original script
    lines = [prompt_line] + original_lines

    decoder = Decoder(config_path=args.config)

    program = []
    imports = []
    for line in lines:
        if line.strip().startswith("import "):
            imports.append(line.strip())

    imports_context = "\n".join(imports)

    for line in lines:
        if not line.strip() or line.strip().startswith("#"):
            continue
        opcodes = decoder.decode_line(line, imports_context=imports_context)
        program.extend(opcodes)

    vm = VM(config_path=args.config)
    vm.load_program(program)
    vm.run()

    print("\nFinal State:")
    for reg, val in vm.registers.items():
        display_val = str(val)
        if len(display_val) > 200:
            display_val = display_val[:197] + "..."
        print(f"{reg}: {display_val}")

if __name__ == "__main__":
    main()
