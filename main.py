#!/usr/bin/env python3
"""SmartReco launcher — the single entrypoint. Run from the project root:

    python main.py

Host, port and reload come from `app.core.config`, which is the only module
permitted to read the environment (CONTEXT §8). The one `os.environ` write
below is not configuration: it hands the import path to uvicorn's reloader
subprocess, which does not inherit this process's `sys.path`.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "code" / "backend"

# Make `app.*` importable regardless of where this is launched from,
# and propagate it to uvicorn's reloader subprocess.
sys.path.insert(0, str(BACKEND))
os.environ["PYTHONPATH"] = str(BACKEND) + os.pathsep + os.environ.get("PYTHONPATH", "")

if __name__ == "__main__":
    import uvicorn

    from app.core.config import settings

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        app_dir=str(BACKEND),
    )
