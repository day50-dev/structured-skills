"""Tests for importing skills as first-class objects."""
import json
import tempfile
from pathlib import Path
from ss.decoder import Decoder, preprocess_lines
from ss.opcodes import OpcodeType
from ss.vm import VM


class StubDecoder(Decoder):
    """Decoder that bypasses LLM — uses regex only."""
    def __init__(self):
        self.config = None
        self.client = None

    def decode_line(self, line, imports_context="", line_number=0):
        ops = self._decode_regex(line)
        for op in ops:
            if op.source_line is None:
                op.source_line = line_number
        return ops


def test_decode_import_simple():
    d = StubDecoder()
    ops = d.decode_line("import somefile.md")
    assert len(ops) == 1
    assert ops[0].type == OpcodeType.IMPORT
    assert ops[0].params["name"] == "somefile"
    assert ops[0].params["source"] == "somefile.md"
    assert ops[0].params["import_type"] == "skill_file"


def test_decode_import_with_alias():
    d = StubDecoder()
    ops = d.decode_line("import myfile.md as myskill")
    assert len(ops) == 1
    assert ops[0].type == OpcodeType.IMPORT
    assert ops[0].params["name"] == "myskill"
    assert ops[0].params["source"] == "myfile.md"
    assert ops[0].params["import_type"] == "skill_file"


def test_decode_import_mcp():
    d = StubDecoder()
    ops = d.decode_line("import fetch from uvx://mcp-server-fetch")
    assert len(ops) == 1
    assert ops[0].type == OpcodeType.IMPORT
    assert ops[0].params["name"] == "fetch"
    assert ops[0].params["source"] == "uvx://mcp-server-fetch"
    assert ops[0].params["import_type"] == "mcp"


def test_decode_import_skill_remote():
    d = StubDecoder()
    ops = d.decode_line("import skill myskill from anthropic://skills/test-skill")
    assert len(ops) == 1
    assert ops[0].type == OpcodeType.IMPORT
    assert ops[0].params["name"] == "myskill"
    assert ops[0].params["source"] == "anthropic://skills/test-skill"
    assert ops[0].params["import_type"] == "skill_remote"


def test_decode_import_skill_remote_no_match_without_from():
    """import skill X from Y must have 'from' to parse correctly."""
    d = StubDecoder()
    # Without 'from', this falls through to simple file import
    ops = d.decode_line("import skill myskill")
    assert len(ops) == 1
    assert ops[0].params["import_type"] == "skill_file"
    assert ops[0].params["name"] == "skill"


def test_vm_import_skill_file():
    vm = VM.__new__(VM)
    vm.registers = {}
    vm.loaded_skills = {}
    vm.config = {}  # minimal

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Test Skill\n\nAlways respond with: skill-ok")
        skill_path = f.name

    try:
        alias = "testskill"
        vm._import_skill_file(alias, skill_path)

        assert alias in vm.loaded_skills
        ls = vm.loaded_skills[alias]
        assert ls.instructions == "# Test Skill\n\nAlways respond with: skill-ok"
        assert f"${alias}_instructions" in vm.registers
        assert vm.registers[f"${alias}_instructions"] == ls.instructions

        # Verify register metadata
        meta = json.loads(vm.registers[f"${alias}_meta"])
        assert meta["name"] == alias
        assert meta["scripts"] == []
    finally:
        Path(skill_path).unlink(missing_ok=True)


def test_imported_skill_callable():
    """Imported skill should be callable via %alias(arg) and run inference."""
    vm = VM.__new__(VM)
    vm.registers = {}
    vm.loaded_skills = {}
    vm.config = {"model": "mock", "base_url": "http://mock", "api_key": "none"}

    # Override client to return a deterministic response
    class MockResponse:
        choices = [type("", (), {"message": type("", (), {"content": "mock skill result"})})()]
    class MockClient:
        def chat(self, *a, **kw):
            return self
        def completions(self, *a, **kw):
            return self
        def create(self, *a, **kw):
            return MockResponse()
    vm.client = MockClient()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("# Test Skill\nRefine this: ")
        skill_path = f.name

    try:
        vm._import_skill_file("testskill", skill_path)
        assert "testskill" in vm.loaded_skills

        ls = vm.loaded_skills["testskill"]
        assert not ls.scripts
        assert ls.instructions
    finally:
        Path(skill_path).unlink(missing_ok=True)


def test_preprocess_lines_preserves_import():
    """preprocess_lines should pass import lines through unchanged."""
    lines = [
        "import somefile.md",
        "import other.md as myskill",
        "import fetch from uvx://pkg",
        "$x = 42",
    ]
    result = preprocess_lines(lines)
    assert result == lines


def test_load_skill_unchanged():
    """Existing load skill syntax must still work."""
    d = StubDecoder()
    ops = d.decode_line("load skill ./my-skill as alias")
    assert len(ops) == 1
    assert ops[0].type == OpcodeType.LOAD_SKILL
    assert ops[0].params["path"] == "./my-skill"
    assert ops[0].params["alias"] == "alias"
