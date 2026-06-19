import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional


class LoadedSkill:
    def __init__(self, path: str, alias: str):
        self.path = Path(path).resolve()
        self.alias = alias
        self.name = ""
        self.description = ""
        self.instructions = ""
        self.metadata: Dict[str, str] = {}
        self.scripts: Dict[str, str] = {}
        self.references: Dict[str, str] = {}

    def load(self):
        skill_md = self.path / "SKILL.md"
        if not skill_md.exists():
            raise FileNotFoundError(f"SKILL.md not found in {self.path}")

        content = skill_md.read_text()
        self._parse_skill_md(content)

        scripts_dir = self.path / "scripts"
        if scripts_dir.exists():
            for f in sorted(scripts_dir.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    self.scripts[f.stem] = str(f)

        refs_dir = self.path / "references"
        if refs_dir.exists():
            for f in sorted(refs_dir.iterdir()):
                if f.is_file() and not f.name.startswith("."):
                    self.references[f.stem] = str(f)

    def _parse_skill_md(self, content: str):
        frontmatter = {}
        body = content

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                raw_fm = parts[1].strip()
                body = parts[2].strip()
                frontmatter = self._parse_frontmatter(raw_fm)

        self.name = frontmatter.get("name", self.alias)
        self.description = frontmatter.get("description", "")
        if "metadata" in frontmatter and isinstance(frontmatter["metadata"], dict):
            self.metadata = {str(k): str(v) for k, v in frontmatter["metadata"].items()}
        self.instructions = body

    def _parse_frontmatter(self, raw: str) -> Dict[str, Any]:
        result = {}
        current_key = None
        current_value_lines = []
        is_multiline = False

        for line in raw.split("\n"):
            stripped = line.rstrip()

            key_match = re.match(r"^(\w[\w-]*)\s*:\s*(.*)", stripped)
            if key_match and not stripped.startswith(" "):
                if current_key:
                    val = "\n".join(current_value_lines).strip()
                    if val:
                        result[current_key] = val
                current_key = key_match.group(1)
                rest = key_match.group(2).strip()
                if rest.startswith("|"):
                    current_value_lines = []
                    is_multiline = True
                elif rest:
                    current_value_lines = [rest]
                    is_multiline = False
                else:
                    current_value_lines = []
                    is_multiline = True
            elif current_key and is_multiline:
                current_value_lines.append(stripped)

        if current_key:
            val = "\n".join(current_value_lines).strip()
            if val:
                result[current_key] = val

        return result
