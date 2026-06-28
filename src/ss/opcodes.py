from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class OpcodeType(str, Enum):
    ASSIGN = "ASSIGN"
    CALL = "CALL"
    INFER = "INFER"
    LOOP = "LOOP"
    END = "END"
    IF = "IF"
    ELSE = "ELSE"
    JUMP = "JUMP"
    JUMPIF = "JUMPIF"
    DEF = "DEF"
    RETURN = "RETURN"
    IMPORT = "IMPORT"
    LOAD_SKILL = "LOAD_SKILL"
    HALT = "HALT"

class Opcode(BaseModel):
    type: OpcodeType
    params: Dict[str, Any] = {}
    source_line: Optional[int] = None

class Program(BaseModel):
    lines: List[Opcode]
