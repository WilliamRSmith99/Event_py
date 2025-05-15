import json
from pathlib import Path
import shutil
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

def read_json(file_name: str) -> Any:
    file_path = DATA_DIR / file_name
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json(file_name: str, data: dict) -> None:
    file_path = DATA_DIR / file_name
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def write_json_atomic(file_name: str, data: dict) -> None:
    """Write JSON data atomically by writing to a temp file then renaming it."""
    final_path = DATA_DIR / file_name
    temp_path = final_path.with_suffix(".tmp")

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    shutil.move(str(temp_path), str(final_path))