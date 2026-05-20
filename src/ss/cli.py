import sys
import argparse
from .decoder import Decoder
from .vm import VM

def run_script(file_path: str, config_path: str = "config.toml"):
    with open(file_path, "r") as f:
        lines = f.readlines()

    decoder = Decoder(config_path=config_path)

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
    else:
        parser = argparse.ArgumentParser(description="Structured Skills VM")
        parser.add_argument("file", help="The .ss file to run")
        parser.add_argument("--config", default="config.toml", help="Path to config file (default: %(default)s)")

        args, _ = parser.parse_known_args()
        run_script(args.file, args.config)


if __name__ == "__main__":
    main()
