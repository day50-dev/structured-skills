import tomllib
import os
from pathlib import Path
import sys

SETUP_GUIDANCE = """
How to set up config.toml:
  1. Copy the example: cp config.toml.example config.toml
  2. Edit config.toml and fill in:
     [llm]
     model = "gpt-4o"              # or any OpenAI-compatible model
     base_url = "https://api.openai.com/v1"  # or your proxy endpoint
     api_key = "sk-..."            # your actual API key
  3. Run the command again.
"""

def load_config(config_path: str = "config.toml"):
    path = Path(config_path)
    if not path.exists():
        print(f"Error: Configuration file not found at {path.absolute()}")
        print(SETUP_GUIDANCE)
        sys.exit(1)

    try:
        with open(path, "rb") as f:
            config = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        print(f"Error: Invalid TOML in {path.absolute()}")
        print(f"  {e}")
        print(SETUP_GUIDANCE)
        sys.exit(1)

    # Use [llm] as the base for everything
    base = config.get("llm", {})
    if not base:
        print(f"Error: Missing [llm] section in {path.absolute()}")
        print(SETUP_GUIDANCE)
        sys.exit(1)

    # Resulting sections (merging overrides if they exist)
    decoder = base.copy()
    decoder.update(config.get("decoder", {}))

    inference = base.copy()
    inference.update(config.get("inference", {}))

    # Validation: Ensure critical fields exist
    for section_name, section in [("decoder", decoder), ("inference", inference)]:
        missing = [field for field in ["model", "base_url", "api_key"] if field not in section]
        if missing:
            print(f"Error: Missing required fields {missing} in [{section_name}] or [llm] section of {path.absolute()}")
            print(SETUP_GUIDANCE)
            sys.exit(1)

    return {
        "decoder": decoder,
        "inference": inference
    }
