import sys
import threading
from typing import List
from .vm import VM
from .opcodes import Opcode


class DebugREPL:
    def __init__(self, vm: VM, source_lines: List[str], program: List[Opcode]):
        self.vm = vm
        self.source_lines = source_lines
        self.program = program
        self.vm.debug_mode = True
        self.vm.stopped_callback = self._on_stopped
        self.stopped_event = threading.Event()
        self.running = True
        self.vm.step_mode = "over"

    def _on_stopped(self, reason: str, line: int, ip: int):
        location = f"line {line}" if line else f"ip {ip}"
        print(f"\n  \u23f8 Stopped at {location} (reason: {reason})", file=sys.stderr)
        self._print_context()
        self.stopped_event.set()

    def _print_context(self):
        line = self.vm.current_line()
        if line and 1 <= line <= len(self.source_lines):
            start = max(0, line - 4)
            end = min(len(self.source_lines), line + 2)
            for i in range(start, end):
                marker = "\u2192" if i + 1 == line else " "
                print(f"  {marker} {i+1}: {self.source_lines[i].rstrip()}", file=sys.stderr)
        else:
            ip = self.vm.ip
            if 0 <= ip < len(self.program):
                op = self.program[ip]
                print(f"  {op.type} {op.params}", file=sys.stderr)

    def run(self):
        self._print_welcome()
        vm_thread = threading.Thread(target=self._run_vm, daemon=True)
        vm_thread.start()
        self._repl_loop()

    def _run_vm(self):
        try:
            self.vm.run()
        finally:
            self.stopped_event.set()

    def _print_welcome(self):
        print("  Structured Skills Debugger", file=sys.stderr)
        print("  Commands: step(s), step-in(si), step-out(so), continue(c),", file=sys.stderr)
        print("            registers(r), break(b), clear, list(l),", file=sys.stderr)
        print("            stack, ip, eval, quit(q), help(h)", file=sys.stderr)

    def _repl_loop(self):
        self.stopped_event.wait()
        self.stopped_event.clear()

        while self.running and not self.vm.halted:
            try:
                cmd = input("(ss-dbg) ")
            except (EOFError, KeyboardInterrupt):
                print(file=sys.stderr)
                break
            if self._handle_command(cmd):
                self.stopped_event.wait()
                self.stopped_event.clear()

        print("  Program halted.", file=sys.stderr)

    def _handle_command(self, cmd: str) -> bool:
        """Handle a command. Returns True if the VM was resumed (caller should wait for next stop)."""
        if not cmd:
            return False
        parts = cmd.split(maxsplit=1)
        verb = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if verb in ("step", "s"):
            self.vm.step_over()
            return True
        elif verb in ("step-in", "si"):
            self.vm.step_in()
            return True
        elif verb in ("step-out", "so"):
            self.vm.step_out()
            return True
        elif verb in ("continue", "c"):
            self.vm.continue_run()
            return True

        elif verb in ("registers", "r"):
            if arg:
                reg_name = arg if arg.startswith("$") else f"${arg}"
                if reg_name in self.vm.registers:
                    val = self.vm.registers[reg_name]
                    display = str(val)
                    if len(display) > 500:
                        display = display[:500] + "..."
                    print(f"  {reg_name} = {display}", file=sys.stderr)
                else:
                    print(f"  Register {reg_name} not found", file=sys.stderr)
            else:
                if not self.vm.registers:
                    print("  (empty)", file=sys.stderr)
                for reg, val in self.vm.registers.items():
                    display = str(val)
                    if len(display) > 200:
                        display = display[:200] + "..."
                    print(f"  {reg} = {display}", file=sys.stderr)
            return False

        elif verb in ("break", "b"):
            if arg:
                try:
                    line_num = int(arg)
                    self.vm.breakpoints.add(line_num)
                    print(f"  Breakpoint set at line {line_num}", file=sys.stderr)
                except ValueError:
                    print(f"  Usage: break <line_number>", file=sys.stderr)
            else:
                if self.vm.breakpoints:
                    for bp in sorted(self.vm.breakpoints):
                        print(f"  Line {bp}", file=sys.stderr)
                else:
                    print("  No breakpoints set", file=sys.stderr)
            return False

        elif verb == "clear":
            if arg:
                try:
                    line_num = int(arg)
                    self.vm.breakpoints.discard(line_num)
                    print(f"  Breakpoint cleared at line {line_num}", file=sys.stderr)
                except ValueError:
                    print(f"  Usage: clear <line_number>", file=sys.stderr)
            else:
                print(f"  Usage: clear <line_number>", file=sys.stderr)
            return False

        elif verb in ("list", "l"):
            self._print_context()
            return False

        elif verb in ("stack", "bt"):
            if self.vm.call_stack:
                for i, frame in enumerate(reversed(self.vm.call_stack)):
                    return_line = "(unknown)"
                    rip = frame["return_ip"]
                    if 0 <= rip < len(self.program):
                        src = self.program[rip].source_line
                        if src:
                            return_line = f"line {src} (ip={rip})"
                        else:
                            return_line = f"ip={rip}"
                    target = frame.get("target_register", "")
                    print(f"  #{i}: return to {return_line} target={target}", file=sys.stderr)
            else:
                print("  Call stack is empty", file=sys.stderr)
            return False

        elif verb == "ip":
            line = self.vm.current_line()
            print(f"  ip={self.vm.ip}, source_line={line}", file=sys.stderr)
            return False

        elif verb == "eval":
            if arg:
                result = self.vm.evaluate(arg)
                print(f"  {arg} = {repr(result)}", file=sys.stderr)
            else:
                print(f"  Usage: eval <expression>", file=sys.stderr)
            return False

        elif verb in ("quit", "q"):
            self.vm.halted = True
            self.vm.continue_run()
            self.running = False
            return False

        elif verb in ("help", "h"):
            self._print_help()
            return False
        else:
            print(f"  Unknown command: {verb}", file=sys.stderr)
            return False

    def _print_help(self):
        print("  Commands:", file=sys.stderr)
        print("    step (s)        - Execute next line (step over)", file=sys.stderr)
        print("    step-in (si)    - Step into function call", file=sys.stderr)
        print("    step-out (so)   - Step out of current function", file=sys.stderr)
        print("    continue (c)    - Continue execution until next breakpoint", file=sys.stderr)
        print("    registers (r)   - Show all registers", file=sys.stderr)
        print("    registers <reg> - Show specific register", file=sys.stderr)
        print("    break (b) <n>   - Set breakpoint at source line n", file=sys.stderr)
        print("    break (b)       - List breakpoints", file=sys.stderr)
        print("    clear <n>       - Clear breakpoint at line n", file=sys.stderr)
        print("    list (l)        - Show source context around current line", file=sys.stderr)
        print("    stack           - Show call stack", file=sys.stderr)
        print("    ip              - Show instruction pointer", file=sys.stderr)
        print("    eval <expr>     - Evaluate an expression in current context", file=sys.stderr)
        print("    quit (q)        - Exit debugger", file=sys.stderr)
        print("    help (h)        - Show this help", file=sys.stderr)
