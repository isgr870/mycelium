import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEP = ";" if platform.system().lower() == "windows" else ":"

cmd = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--onefile",
    "--name",
    "mycelium-node",
    "--add-data",
    f"{ROOT / 'web'}{SEP}web",
    "--add-data",
    f"{ROOT / 'core'}{SEP}core",
    str(ROOT / "node.py"),
]

print("Running:", " ".join(cmd))
subprocess.run(cmd, cwd=str(ROOT), check=True)
print("Build complete. Output in:", ROOT / "dist")
