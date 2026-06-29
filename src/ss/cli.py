import sys
import logging
import argparse
from .decoder import Decoder, preprocess_lines
from .vm import VM

def run_script(file_path: str, config_path: str = "config.toml"):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    with open(file_path, "r") as f:
        lines = f.readlines()

    decoder = Decoder(config_path=config_path)

    program = []
    imports = []
    load_skills = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import "):
            imports.append(stripped)
        elif stripped.startswith("load skill "):
            load_skills.append(stripped)

    imports_context = "\n".join(imports)
    skills_context = "\n".join(load_skills)

    full_context = imports_context
    if skills_context:
        full_context += "\n" + skills_context

    pp_lines = preprocess_lines(lines)
    for line in pp_lines:
        if not line.strip() or line.strip().startswith("#"):
            continue
        opcodes = decoder.decode_line(line, imports_context=full_context)
        program.extend(opcodes)

    vm = VM(config_path=config_path)
    vm.load_program(program)
    vm.run()

    print("\nFinal State:")
    for reg, val in vm.registers.items():
        display_val = str(val)
        if len(display_val) > 100:
            display_val = display_val[:97] + "..."
        print(f"{reg}: {display_val}")


def main():
    if len(sys.argv) == 1:
        print("Usage:")
        print("  ss <file.ss>              Run a script")
        print("  ss create <prompt>        Generate an agent script")
        print("  ss run <file.ss> <prompt>  Run an agent script with input")
        print("  ss server                 Start the API server")
        print("")
        print("Standalone commands:")
        print("  agent-create <prompt>     Generate an agent script")
        print("  run-agent <file.ss> <p>   Run an agent script with input")
        sys.exit(1)

    if sys.argv[1] == "create":
        from .agent_create import main as create_main
        sys.argv = sys.argv[1:]
        create_main()
    elif sys.argv[1] == "run":
        from .agent_runner import main as run_main
        sys.argv = sys.argv[1:]
        run_main()
    elif sys.argv[1] == "server":
        from .server import main as server_main
        sys.argv = sys.argv[1:]
        server_main()
    else:
        parser = argparse.ArgumentParser(description="Structured Skills VM")
        parser.add_argument("file", help="The .ss file to run")
        parser.add_argument("--config", default="config.toml", help="Path to config file (default: %(default)s)")

        args, _ = parser.parse_known_args()
        run_script(args.file, args.config)


if __name__ == "__main__":
    main()
