# Trading Agent Architecture
## Overview
This package contains an XAUUSD trading system organized into strategy, execution, and bridge components.
The supplied engine uses an H4 context, M15 structure, and M1 execution approach.
## Main Components
### Engine
Location: `engine/`
- `live_multi_state_machine_v28_5_2_primary_only_breakeven.py` — main strategy engine and orchestration.
- `m1_setup_detector.py` — M1 setup detection.
- `risk_engine.py` — risk controls.
- `strategy_config.py` — strategy parameters.
### Execution
Location: `execution/`
- `trade_executor_primary_only.py` — communicates execution requests to the bridge.
### Bridge
Location: `bridge/`
- `mt5_bridge.py` — local API used to communicate with MetaTrader 5.
### Launchers
- `run_bridge.py` starts the bridge.
- `run_agent.py` starts the strategy engine.
## Communication
The engine and execution components communicate with the bridge through `MT5_BRIDGE_URL`.
Default bridge URL:
`http://127.0.0.1:8000`
The bridge uses an API key supplied through the environment.
## Trading Flow
1. H4 trend context.
2. M15 market structure.
3. M1 setup detection.
4. Execution request.
5. Bridge-side validation and MT5 interaction.
Actual trading outcomes depend on market conditions, broker behavior, terminal connectivity, and execution conditions.
## Important Configuration
Review `engine/strategy_config.py` and `engine/risk_engine.py` before operating the system.
Do not assume changing a configuration value is safe without testing its effects.
