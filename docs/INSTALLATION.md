# Installation Guide

## Requirements

- Windows operating system.
- Python version compatible with the MetaTrader5 package.
- MetaTrader 5 desktop terminal.
- A broker-provided MT5 demo account for initial testing.
- Internet connectivity.
- Dependencies listed in `requirements.txt`.

## 1. Prepare the Environment

Open PowerShell in the project directory:

```powershell
# Open PowerShell inside the cloned Trading-Agent-Complete folder.
Get-Location
```

Create a virtual environment using Python 3.11, if installed and compatible:

```powershell
py -3.11 -m venv .venv
```

Activate the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 2. Configure Environment Variables

Create your local environment file:

```powershell
Copy-Item .env.example .env
```

Open `.env` and replace the placeholder API key with a long, random secret.

Set `MT5_TERMINAL_PATH` if your MetaTrader 5 terminal is not discovered automatically.

**Never commit your real `.env` file to GitHub or share it with other users.**

## 3. Prepare MetaTrader 5

1. Install and open MetaTrader 5.
2. Sign in to a demo account.
3. Confirm that the terminal is connected.
4. Check automated trading permissions.
5. Verify the terminal path if you use a custom installation.

## 4. Before Starting

Review these files:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/SAFETY_AND_RISK.md`
- `engine/strategy_config.py`
- `engine/risk_engine.py`

Installation does not establish that the strategy is profitable or that the complete system works with every broker.

## Important

Do not use a live trading account during initial installation and testing. Complete the separate demo-account validation first.