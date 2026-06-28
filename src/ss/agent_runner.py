import sys
import os
import logging
import tempfile
import argparse
import threading
from .decoder import Decoder, parse_input_specs
from .vm import VM
from .dap_server import DAPServer

def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\"", "\\\"")


def _resolve_input_value(spec, raw: str) -> str:
    """Convert a raw input value according to the spec type."""
    if spec.type == "file":
        path = raw.strip()
        if path:
            with open(path) as f:
                return f.read()
        return raw
    return raw


def _prompt_for_input(spec, index: int, cli_args: list[str]) -> str | None:
    """Return a value for this input from CLI args or interactive prompt."""
    if index < len(cli_args):
        return _resolve_input_value(spec, cli_args[index])

    label = f"  {spec.name} ({spec.type})"
    if spec.type == "file":
        path = input(f"{label}: ").strip()
        if path:
            with open(path) as f:
                return f.read()
        return ""
    else:
        return input(f"{label}: ").strip()


def _build_input_lines(original_lines: list[str], cli_inputs: list[str]) -> tuple[list[str], list[str]]:
    """Build $REG = value lines for each declared input spec.
    Returns (prepend_lines, remaining_cli_args)."""
    specs = parse_input_specs(original_lines)
    if not specs:
        return [], cli_inputs

    lines = []
    remaining = list(cli_inputs)
    for spec in specs:
        value = _prompt_for_input(spec, 0, remaining)
        if value is not None and remaining:
            remaining.pop(0)
        lines.append(f'${spec.name} = "{_escape(value or "")}"\n')

    return lines, remaining


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(
        description="Run an ss agent script with inputs. If the script declares input specs, "
                    "they are prompted interactively or filled from positional args."
    )
    parser.add_argument("file", help="The .ss agent script to run")
    parser.add_argument("prompt", nargs="*", default=[],
                        help="Input values for declared inputs (positional), then $prompt")
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

    # Build input-value assignments from declared input specs + CLI args
    input_assignments, remaining = _build_input_lines(original_lines, list(args.prompt))

    if remaining:
        prompt_val = " ".join(remaining)
        input_assignments.append(f'$prompt = "{_escape(prompt_val)}"\n')
    elif not input_assignments and args.prompt:
        # No input specs — original behaviour: first arg goes to $prompt
        prompt_val = " ".join(args.prompt) if isinstance(args.prompt, list) else args.prompt
        input_assignments.append(f'$prompt = "{_escape(prompt_val)}"\n')

    # Prepend input assignments, then the original script
    lines = input_assignments + original_lines

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
