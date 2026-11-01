import os
import runpy
import sys
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
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "execution"))
ENGINE = ROOT / "engine" / (
    "live_multi_state_machine_v28_5_2_primary_only_breakeven.py"
)
runpy.run_path(str(ENGINE), run_name="__main__")
