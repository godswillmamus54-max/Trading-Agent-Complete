# Trading Agent Installation Guide

## 1. Requirements

- Windows operating system.
- Python 3.11.
- MetaTrader 5 desktop terminal.
- A broker-provided MT5 demo account.
- Internet connection.
- Git installed (for cloning the repository).

## 2. Clone the Repository

Accept the GitHub collaborator invitation before proceeding.

Open PowerShell and run:

```powershell
git clone https://github.com/godswillmamus54-max/Trading-Agent-Complete.git
cd Trading-Agent-Complete
```

## 3. Prepare the Python Environment

Create a Python 3.11 virtual environment:

```powershell
py -3.11 -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

For a compatible Windows and Python 3.11 environment, the supplied dependency lock file is also available:

```powershell
python -m pip install -r requirements-lock-py311-windows.txt
```

Use either the standard requirements file or the lock file, not both consecutively.

## 4. Configure Your Private Environment

Create your own environment file:

```powershell
Copy-Item .env.example .env
```

Generate a unique API key:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Open the `.env` file:

```powershell
notepad .env
```

Replace the placeholder with your generated key:

```text
MT5_BRIDGE_API_KEY=YOUR_UNIQUE_PRIVATE_SECRET
MT5_TERMINAL_PATH=
MT5_BRIDGE_URL=http://127.0.0.1:8000
```

Save and close the file.

If MT5 is not detected automatically, configure `MT5_TERMINAL_PATH` with the full path to your own `terminal64.exe`.

**Security requirements:**

- Generate your own API key.
- Never use another person's `.env` file.
- Never share your MT5 login credentials.
- Never commit `.env` to GitHub.

## 5. Prepare MetaTrader 5

1. Install and open MetaTrader 5.
2. Log in using your own broker-provided demo account.
3. Confirm that the terminal is connected.
4. Confirm that automated trading permissions are enabled.
5. Keep MT5 running.

The supplied launcher checks the bridge connection, account mode and trading permissions before starting the engine.

## 6. Start the Trading Agent

Navigate to the project folder.

Double-click:

`START_TRADING_AGENT.bat`

The launcher performs pre-flight checks:

- Python virtual environment verification.
- API key validation.
- Local bridge URL validation.
- MT5 bridge health verification.
- MT5 demo-account verification.
- Trading permission verification.

The trading engine starts only after these checks pass.

Keep the launcher window open during operation.

## 7. Stop the Trading Agent

Focus the launcher window and press:

`Ctrl+C`

Allow the launcher to stop the trading engine and bridge.

## 8. Troubleshooting

### Python not found

Confirm Python 3.11 is installed:

```powershell
py -3.11 --version
```

### Virtual environment missing

Recreate it:

```powershell
py -3.11 -m venv .venv
```

### Dependency errors

Activate the virtual environment and reinstall:

```powershell
python -m pip install -r requirements.txt
```

### Missing API key

Confirm `.env` exists and contains your own valid `MT5_BRIDGE_API_KEY`.

### MT5 connection failure

Check the MT5 terminal, account connection and terminal path configuration.

### Demo verification failure

Confirm that MT5 is logged into a demo account. The launcher must not proceed when demo status cannot be verified.

### Port 8000 already in use

Check whether another bridge process or application is using the port before restarting.

## 9. Risk and Operational Notice

The supplied configuration contains aggressive risk settings:

- Risk per new trading day: 10% of starting balance.
- Maximum daily loss setting: 20%.

These are software settings, not recommendations or guarantees. Significant losses are possible.

Read `docs/SAFETY_AND_RISK.md` and `docs/OPERATION_GUIDE.md` before operation.

The automated tests do not replace a complete MT5 demo-account integration test. No profitability or broker compatibility guarantee is made.

**Do not use a live trading account during installation or initial validation.**