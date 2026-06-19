import re
import json
from typing import List
from openai import OpenAI
from .opcodes import Opcode, OpcodeType
from .config import load_config
from .prompts import DECODER_PROMPT

class Decoder:
    def __init__(self, config_path: str = "config.toml"):
        self.config = load_config(config_path)["decoder"]
        self.client = OpenAI(
            base_url=self.config["base_url"],
            api_key=self.config["api_key"] or "none"
        )

    def decode_line(self, line: str, imports_context: str = "") -> List[Opcode]:
        line = line.strip()
        if not line or line.startswith("#"):
            return []

        # Structural blocks are better handled by regex for reliability
        if any(line.startswith(x) for x in ["def ", "if ", "for ", "return ", "import ", "load "]) or line in ["end", "else:"]:
             return self._decode_regex(line)

        # For "vibe" lines, try the LLM
        try:
            response = self.client.chat.completions.create(
                model=self.config["model"],
                messages=[
                    {"role": "system", "content": DECODER_PROMPT.format(imports=imports_context, line=line)}
                ],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            opcodes_data = data.get("opcodes", [])
            return [Opcode(**op) for op in opcodes_data]
        except Exception as e:
            # If API fails or key is missing, fallback to regex
            return self._decode_regex(line)

    def _decode_regex(self, line: str) -> List[Opcode]:
        # DEF
        def_match = re.match(r"def\s+([\w\.-]+)\s*(.*):", line)
        if def_match:
            name = def_match.group(1)
            params_str = def_match.group(2)
            params = [p.strip() for p in params_str.split(",") if p.strip()]
            return [Opcode(type=OpcodeType.DEF, params={"name": name, "params": params})]

        # RETURN
        if line.startswith("return "):
            val = line[7:].strip()
            return [Opcode(type=OpcodeType.RETURN, params={"value": val})]

        # LOOP
        loop_match = re.match(r"for\s+each\s+(\$\w+)\s+in\s+(.*):", line)
        if loop_match:
            item = loop_match.group(1)
            source = loop_match.group(2).strip()
            if source.startswith("%"):
                call_match = re.match(r"%([\w\.-]+)\s*(.*)", source)
                if call_match:
                    name = call_match.group(1)
                    args_str = call_match.group(2)
                    args = [a.strip() for a in args_str.split() if a.strip()]
                    temp_reg = f"$temp_list_{abs(hash(line))}"
                    return [
                        Opcode(type=OpcodeType.CALL, params={"name": name, "args": args, "register": temp_reg}),
                        Opcode(type=OpcodeType.LOOP, params={"item": item, "register": temp_reg})
                    ]
            return [Opcode(type=OpcodeType.LOOP, params={"item": item, "register": source})]

        # ASSIGN
        assign_match = re.match(r"(\$\w+)\s*=\s*(.*)", line)
        if assign_match:
            register = assign_match.group(1)
            rest = assign_match.group(2).strip()
            if rest.startswith("infer "):
                prompt = rest[6:].strip().strip('"').strip("'")
                return [Opcode(type=OpcodeType.INFER, params={"prompt": prompt, "register": register})]
            if rest.startswith("%"):
                call_match = re.match(r"%([\w\.-]+)\s*(.*)", rest)
                if call_match:
                    name = call_match.group(1)
                    args_str = call_match.group(2)
                    args = [a.strip() for a in args_str.split() if a.strip()]
                    return [Opcode(type=OpcodeType.CALL, params={"name": name, "args": args, "register": register})]
            return [Opcode(type=OpcodeType.ASSIGN, params={"register": register, "value": rest})]

        # VIBE APPEND (Special case regex)
        vibe_append = re.match(r"append\s+(\$\w+)\s+to\s+([\w\./-]+)\s+using\s+%([\w\.-]+)", line)
        if vibe_append:
            var = vibe_append.group(1)
            file_path = vibe_append.group(2)
            return [Opcode(type=OpcodeType.CALL, params={"name": "append_to_file", "args": [file_path, var]})]

        # CALL
        if line.startswith("%"):
            call_match = re.match(r"%([\w\.-]+)\s*(.*)", line)
            if call_match:
                name = call_match.group(1)
                args_str = call_match.group(2)
                target_match = re.search(r"->\s*(\$\w+)", args_str)
                register = None
                if target_match:
                    register = target_match.group(1)
                    args_str = args_str[:target_match.start()].strip()
                args = [a.strip() for a in args_str.split() if a.strip()]
                return [Opcode(type=OpcodeType.CALL, params={"name": name, "args": args, "register": register})]

        # INFER
        if line.startswith("infer "):
            prompt = line[6:].strip().strip('"').strip("'")
            return [Opcode(type=OpcodeType.INFER, params={"prompt": prompt})]

        # IMPORT
        if line.startswith("import "):
            import_match = re.match(r"import\s+([\w\.-]+)\s+from\s+(.*)", line)
            if import_match:
                name = import_match.group(1)
                source = import_match.group(2)
                return [Opcode(type=OpcodeType.IMPORT, params={"name": name, "source": source})]

        # LOAD SKILL
        if line.startswith("load "):
            load_match = re.match(r"load\s+skill\s+(.+?)\s+as\s+(\w+)", line)
            if load_match:
                skill_path = load_match.group(1).strip()
                alias = load_match.group(2)
                return [Opcode(type=OpcodeType.LOAD_SKILL, params={"path": skill_path, "alias": alias})]

        # IF / ELSE / END
        if line == "else:": return [Opcode(type=OpcodeType.ELSE)]
        if line == "end": return [Opcode(type=OpcodeType.END)]
        if line.startswith("if "):
            condition = line[3:].strip().rstrip(":")
            return [Opcode(type=OpcodeType.IF, params={"condition": condition})]

        return []
