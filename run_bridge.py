import os
import runpy
from pathlib import Path
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
if not os.getenv("MT5_BRIDGE_API_KEY"):
    raise SystemExit(
        "ERROR: MT5_BRIDGE_API_KEY is missing. "
        "Copy .env.example to .env and configure your secret."
    )
os.chdir(ROOT)
runpy.run_path(
    str(ROOT / "bridge" / "mt5_bridge.py"),
    run_name="__main__"
)
