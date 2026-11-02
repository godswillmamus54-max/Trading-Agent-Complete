# Trading Agent Operation Guide

## 1. Before Starting

Confirm the following:

- MetaTrader 5 is installed and running.
- You are logged into your own MT5 demo account.
- The terminal is connected to the broker.
- Automated trading permissions are enabled.
- The project's `.venv` environment exists.
- The `.env` file exists and contains a valid private API key.
- The configured risk settings have been reviewed.
- Port 8000 is available.

## 2. Start the System — One-Click Startup

1. Open MetaTrader 5.
2. Log in to your demo account.
3. Confirm the terminal is connected.
4. Confirm automated trading permissions.
5. Navigate to the `Trading-Agent-Complete` project folder.
6. Double-click `START_TRADING_AGENT.bat`.
7. Wait for the startup controller to perform its checks.

The launcher performs the following checks before starting the trading engine:

- Python environment verification.
- API key configuration.
- Local bridge URL validation.
- MT5 bridge health and connection.
- MT5 demo-account verification.
- Trading permission verification.

The trading engine starts only after these checks pass.

Keep the launcher window open while the system is running.

## 3. Stop the System

To request shutdown:

1. Focus the launcher terminal window.
2. Press `Ctrl+C`.
3. Allow the launcher to stop the trading engine and bridge.
4. Confirm the startup session has ended.

Do not close the terminal abruptly while the system is operating.

## 4. Manual Startup — Alternative

The components can also be started separately.

First terminal:

```powershell
.\.venv\Scripts\Activate.ps1
python run_bridge.py
```

Second terminal:

```powershell
.\.venv\Scripts\Activate.ps1
python run_agent.py
```

Keep both terminals open while the system is running.

To stop the manual setup, stop the trading engine first, then the bridge.

## 5. Troubleshooting

### Missing API Key

Check that `.env` exists and contains a valid `MT5_BRIDGE_API_KEY`.

Never share your private API key.

### Bridge Connection Failure

Confirm that:

- MT5 is running.
- The terminal is connected.
- The bridge URL is correct.
- Port 8000 is available.

### Demo Account Verification Failure

Confirm that MT5 is logged into a demo account.

The launcher blocks startup if the account cannot be verified as a demo account.

### MT5 Initialization Failure

Check:

- MT5 terminal installation.
- Terminal path configuration.
- Account login and connection.
- MetaTrader5 Python package installation.

### Dependency Errors

Activate the virtual environment and run:

```powershell
python -m pip install -r requirements.txt
```

### Port Already in Use

Check whether another application or bridge process is using port 8000 before attempting to restart the bridge.

## 6. Operational Caution

The 15 automated tests include source-level bridge safety checks and isolated launcher tests using mocked responses.

They do not replace a complete MT5 demo-account integration test.

Do not assume successful installation means that order execution, broker connectivity, or strategy performance has been validated.

Do not switch to a live account as part of routine installation or packaging.