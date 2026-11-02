
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
BRIDGE_STARTUP_TIMEOUT = 45
POLL_INTERVAL = 0.5


def stop_process(process, name):
    if process is None or process.poll() is not None:
        return

    print(f"\nStopping {name}...")

    try:
        process.send_signal(signal.CTRL_BREAK_EVENT)
        process.wait(timeout=10)

    except subprocess.TimeoutExpired:
        print(f"{name} did not stop normally. Forcing shutdown.")
        process.kill()
        process.wait()

    except (OSError, ValueError):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def validate_configuration():
    load_dotenv(ROOT / ".env")

    api_key = os.getenv("MT5_BRIDGE_API_KEY", "").strip()

    if not api_key or api_key.startswith("REPLACE_WITH_"):
        raise RuntimeError(
            "MT5_BRIDGE_API_KEY is missing or still contains "
            "the example placeholder. Configure your .env file."
        )

    bridge_url = os.getenv(
        "MT5_BRIDGE_URL",
        "http://127.0.0.1:8000"
    ).rstrip("/")

    parsed = urlparse(bridge_url)

    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.port not in (None, 8000)
        or parsed.path not in ("", "/")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "For safety, this launcher only supports the local "
            "bridge at http://127.0.0.1:8000 or localhost:8000."
        )

    os.environ["MT5_BRIDGE_URL"] = bridge_url

    return api_key, bridge_url


def verify_bridge(process, api_key, bridge_url):
    headers = {"x-api-key": api_key}
    deadline = time.monotonic() + BRIDGE_STARTUP_TIMEOUT

    print("\nWaiting for MT5 bridge...")

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "Bridge process exited before becoming ready. "
                "Check the bridge error messages above."
            )

        try:
            response = requests.get(
                f"{bridge_url}/health",
                headers=headers,
                timeout=3
            )

            response.raise_for_status()
            health = response.json()

            if (
                health.get("status") == "ok"
                and health.get("mt5_connected") is True
                and health.get("terminal_connected") is True
            ):
                print("Bridge health check passed.")
                break

        except (requests.RequestException, ValueError):
            pass

        time.sleep(1)

    else:
        raise RuntimeError(
            "Bridge did not establish a verified MT5 connection "
            "within the startup timeout."
        )

    if process.poll() is not None:
        raise RuntimeError("Bridge stopped during verification.")

    print("\nChecking MT5 account mode...")

    response = requests.get(
        f"{bridge_url}/account",
        headers=headers,
        timeout=5
    )
    response.raise_for_status()
    account = response.json()

    if account.get("is_demo") is not True:
        raise RuntimeError(
            "EXECUTION BLOCKED: MT5 account is not verified as DEMO."
        )

    if account.get("trade_allowed") is not True:
        raise RuntimeError(
            "MT5 account does not currently permit trading."
        )

    if account.get("trade_expert") is not True:
        raise RuntimeError(
            "MT5 expert trading permission is disabled."
        )

    if process.poll() is not None:
        raise RuntimeError("Bridge stopped during account verification.")

    print("DEMO ACCOUNT VERIFIED.")
    print(f"Account login: {account.get('login')}")
    print(f"Server: {account.get('server')}")
    print(f"Balance: {account.get('balance')}")
    print("Trading permissions verified.")

    return account


def main():
    bridge_process = None
    agent_process = None

    try:
        if sys.version_info < (3, 11):
            raise RuntimeError("Python 3.11 or newer is required.")

        expected_python = (
            ROOT / ".venv" / "Scripts" / "python.exe"
        ).resolve()

        actual_python = Path(sys.executable).resolve()

        if actual_python != expected_python:
            raise RuntimeError(
                "Run this launcher using the repository's "
                ".venv Python interpreter."
            )

        print("=" * 65)
        print("V28.5.2 MT5 TRADING AGENT STARTUP")
        print("=" * 65)

        api_key, bridge_url = validate_configuration()

        print("\nConfiguration verified.")
        print("Starting MT5 bridge...")

        bridge_process = subprocess.Popen(
            [sys.executable, str(ROOT / "run_bridge.py")],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )

        verify_bridge(
            bridge_process,
            api_key,
            bridge_url
        )

        print("\nAll pre-flight checks passed.")
        print("Starting V28.5.2 trading engine...")
        print("Press Ctrl+C to stop the engine and bridge.")

        agent_process = subprocess.Popen(
            [sys.executable, str(ROOT / "run_agent.py")],
            cwd=str(ROOT),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )

        while agent_process.poll() is None:
            if bridge_process.poll() is not None:
                raise RuntimeError(
                    "MT5 bridge stopped unexpectedly. "
                    "Stopping the trading engine."
                )

            time.sleep(POLL_INTERVAL)

        print(
            f"\nTrading engine exited with code "
            f"{agent_process.returncode}."
        )

    except KeyboardInterrupt:
        print("\nShutdown requested.")
        return 0

    except Exception as exc:
        print(f"\nSTARTUP ERROR: {exc}")
        return 1

    finally:
        stop_process(agent_process, "Trading engine")
        stop_process(bridge_process, "MT5 bridge")

        print("\nStartup session ended.")


if __name__ == "__main__":
    raise SystemExit(main())
