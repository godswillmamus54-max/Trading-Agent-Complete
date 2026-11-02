# XAUUSD Trading Agent
A Python-based automated trading system for MetaTrader 5, built around a multi-timeframe market-structure strategy.
## Architecture
- H4 directional context
- M15 setup and opportunity generation
- M1 execution confirmation
- M15 opportunity detection followed by M1 confirmation
- MT5 bridge for market data and trade operations
- Risk engine and trade audit logging
- Primary execution path
## Project Structure
```text
Trading-Agent-Complete/
|-- bridge/
|   `-- mt5_bridge.py
|-- engine/
|   |-- live_multi_state_machine_v28_5_2_primary_only_breakeven.py
|   |-- m1_setup_detector.py
|   |-- strategy_config.py
|   `-- risk_engine.py
|-- execution/
|   `-- trade_executor_primary_only.py
|-- tests/
|-- docs/
|-- requirements.txt
|-- requirements-lock-py311-windows.txt
|-- .env.example
|-- .gitignore
|-- run_bridge.py
`-- run_agent.py
```

## Requirements
- Windows
- Python 3.11 recommended
- MetaTrader 5 desktop terminal
- A compatible MT5 trading account
- Internet connection
- Python dependencies listed in requirements.txt

The MetaTrader5 Python package requires a compatible Windows environment and MT5 terminal installation.

## Installation
1. Download or clone the repository.
2. Open PowerShell in the project directory.
3. Create a virtual environment:
python -m venv .venv
4. Activate it:
.\.venv\Scripts\Activate.ps1
5. Install dependencies:
python -m pip install --upgrade pip
pip install -r requirements.txt
6. Create your environment file:
Copy-Item .env.example .env
7. Edit .env and configure a strong, private API key.
Example:
MT5_BRIDGE_API_KEY=YOUR_PRIVATE_RANDOM_SECRET
MT5_TERMINAL_PATH=
MT5_BRIDGE_URL=http://127.0.0.1:8000

If MT5 is not detected automatically, set MT5_TERMINAL_PATH to the full path of your terminal executable.

## Running the System
1. Open MetaTrader 5 and log in to the intended account.
2. Open a PowerShell window in the project directory.
3. Activate the virtual environment.
4. Start the bridge:
python run_bridge.py
5. Open a second PowerShell window in the same project directory.
6. Activate the same virtual environment.
7. Start the trading engine:
python run_agent.py

## Important Trading Risk
The supplied configuration contains aggressive risk settings:
- Risk per new trading day: 10% of starting balance.
- Maximum daily loss setting: 20%.
These are the supplied software settings, not recommendations or assurances of safety. Significant losses, including loss of the entire trading balance, are possible.
Review and independently validate the risk configuration before any trading use.

## Safety and Testing
The bridge correction bundle includes safeguards intended to:
- Restrict trade operations to demo accounts.
- Check trading permissions.
- Validate trade ownership using the configured magic number.
- Validate stop-loss and take-profit values.
- Support idempotent order handling.
- Reconcile trade operations.
These safeguards require runtime verification. Passing source-level tests does not prove broker execution safety.
Start with a demo account. Do not connect this package to a live account without a separate, thorough review and validation.

## Runtime Files
The engine creates runtime state and audit files, including:
- multi_setup_state_v28_5_2_primary_only.json
- xauusd_trade_audit_v28_5_2_primary_only.jsonl
- risk_state.json
These files are excluded from Git tracking by default.
Back them up carefully if you need to preserve a running system's state.

## Shadow Confirmation
Shadow confirmation is disabled in the supplied engine.
The shadow bridge configuration is retained, but this package does not include a separately configured shadow bridge deployment. Do not enable shadow confirmation without completing that setup and testing it.

## Limitations
- No profitability is guaranteed.
- No backtest or forward-test performance claim is made by this README.
- Offline source tests do not establish live broker compatibility.
- Broker symbol names, execution conditions, spreads, and account restrictions may affect operation.

## Project Status
This is a packaged development build. It requires offline testing, installation testing, and controlled MT5 demo validation before distribution as a verified operational release.

## Security
- Keep API keys private.
- Never commit .env.
- Keep the bridge bound to localhost unless a separately secured deployment is designed.
- Do not distribute account credentials.
- Give repository access only to approved users.

## License
No redistribution or commercial-use license has been assigned yet. Obtain the author's permission before redistributing or modifying this project for commercial purposes.
