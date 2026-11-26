import os
import platform
from pathlib import Path


def get_data_dir() -> Path:
    override = os.environ.get("MYCELIUM_DATA_DIR", "").strip()
    if override:
        p = Path(override).expanduser()
    elif platform.system().lower() == "windows":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        p = Path(base) / "Mycelium"
    else:
        # Works on Linux, macOS, and Android/Termux
        p = Path.home() / ".mycelium"

    p.mkdir(parents=True, exist_ok=True)
    return p


def get_db_path(filename: str = "ledger.db") -> str:
    return str(get_data_dir() / filename)
