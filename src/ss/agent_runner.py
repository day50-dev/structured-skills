import sys
import logging
import tempfile
import argparse
import threading
from .decoder import Decoder
from .vm import VM
from .dap_server import DAPServer

def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Run an ss agent script with a user prompt")
    parser.add_argument("file", help="The .ss agent script to run")
    parser.add_argument("prompt", nargs="?", default="", help="The input prompt (sets $prompt register)")
    parser.add_argument("--config", default="config.toml", help="Path to config file (default: %(default)s)")
    parser.add_argument("--debug", action="store_true", help="Start DAP debug server")
    parser.add_argument("--debug-host", default="127.0.0.1", help="DAP server host (default: 127.0.0.1)")
    parser.add_argument("--debug-port", type=int, default=4711, help="DAP server port (default: 4711)")

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

    for line_num, line in enumerate(lines, start=1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        opcodes = decoder.decode_line(line, imports_context=full_context, line_number=line_num)
        program.extend(opcodes)

    if args.debug:
        dap = DAPServer(host=args.debug_host, port=args.debug_port)
        dap.vm = VM(config_path=args.config)
        dap.vm.debug_mode = True
        dap.vm.stopped_callback = dap._on_stopped
        dap.vm.load_program(program)
        t = threading.Thread(target=dap.serve, daemon=True)
        t.start()
        print(f"DAP server on {args.debug_host}:{args.debug_port}", file=sys.stderr, flush=True)
        t.join()
        return

    vm = VM(config_path=args.config)
    vm.load_program(program)
    vm.run()

    print("\n=== RESULTS ===")
    for reg, val in vm.registers.items():
        display = str(val)
        print(f"\n{reg} ({len(display)} chars):")
        print(display)

    if vm.token_usage:
        total_tokens = sum(t["total"] for t in vm.token_usage)
        print(f"\n=== TOKENS ===")
        for i, t in enumerate(vm.token_usage):
            print(f"  Infer {i+1}: {t['prompt']} in → {t['completion']} out ({t['total']} total)")
        print(f"  Total: {total_tokens}")

if __name__ == "__main__":
    main()
