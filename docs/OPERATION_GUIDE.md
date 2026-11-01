# Trading Agent Operation Guide

## 1. Before Starting

Confirm the following:

- MetaTrader 5 is installed and running.
- You are logged into an MT5 demo account.
- The terminal is connected to the broker.
- The project's virtual environment is activated.
- The `.env` file exists and contains a valid API key.
- The configured risk settings have been reviewed.
- The bridge port is available.

## 2. Start the Bridge

Open a PowerShell terminal in the project directory.

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Start the bridge:

```powershell
python run_bridge.py
```

Keep this terminal open while the system is running.

The bridge uses the default local address:

`http://127.0.0.1:8000`

## 3. Start the Trading Agent

Open a second PowerShell terminal in the project directory.

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Start the agent:

```powershell
python run_agent.py
```

Keep both terminals running during operation.

## 4. Stop the System

To stop the system safely:

1. Press `Ctrl + C` in the agent terminal.
2. Wait for the agent process to stop.
3. Press `Ctrl + C` in the bridge terminal.
4. Confirm both processes have stopped.

## 5. Troubleshooting

### Missing API Key

Check that `.env` exists and contains a valid `MT5_BRIDGE_API_KEY`.

### Bridge Connection Failure

Confirm that the bridge is running and that `MT5_BRIDGE_URL` points to the correct local address.

### MT5 Initialization Failure

Check:

- MT5 terminal installation.
- Terminal path configuration.
- Account login and connection.
- MetaTrader5 Python package installation.

### Dependency Errors

Activate the virtual environment and run:

```powershell
pip install -r requirements.txt
```

### Port Already in Use

Check whether another application or bridge process is using port 8000 before attempting to restart the bridge.

## 6. Operational Caution

The seven source-level safety tests do not replace a complete MT5 demo-account integration test.

Do not assume successful installation means that order execution, broker connectivity, or strategy performance has been validated.

Do not switch to a live account as part of routine installation or packaging.