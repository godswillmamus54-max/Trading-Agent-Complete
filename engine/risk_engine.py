import json
import os
from datetime import datetime, timezone


# ============================================================
# CONFIGURATION
# ============================================================

RISK_STATE_FILE = "risk_state.json"

# 10% of the new trading day's starting balance.
RISK_PERCENT = 0.10

# Hard daily loss protection.
MAX_DAILY_LOSS_PERCENT = 0.20


# ============================================================
# STATE
# ============================================================

def empty_risk_state():

    return {
        "trading_day": None,
        "day_start_balance": None,
        "day_start_equity": None,
        "current_risk_amount": 0.0,
        "daily_realized_pnl": 0.0,
        "last_updated": None,
    }


def load_risk_state():

    if not os.path.exists(
        RISK_STATE_FILE
    ):
        return empty_risk_state()

    try:

        with open(
            RISK_STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            state = json.load(f)

        base = empty_risk_state()
        base.update(state)

        return base

    except Exception as error:

        print(
            f"[RISK STATE LOAD ERROR] {error}"
        )

        return empty_risk_state()


def save_risk_state(state):

    with open(
        RISK_STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            indent=2
        )


# ============================================================
# BROKER TRADING DAY
# ============================================================

def trading_day_from_market_time(
    market_time
):

    if not market_time:
        raise ValueError(
            "Market time is required."
        )

    if isinstance(
        market_time,
        datetime
    ):

        return market_time.strftime(
            "%Y-%m-%d"
        )

    value = str(
        market_time
    )

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    parsed = datetime.fromisoformat(
        value
    )

    return parsed.strftime(
        "%Y-%m-%d"
    )


# ============================================================
# DAILY INITIALIZATION / ROLLOVER
# ============================================================

def initialize_trading_day(
    account_balance,
    account_equity,
    market_time
):

    state = load_risk_state()

    trading_day = (
        trading_day_from_market_time(
            market_time
        )
    )

    # New MT5 market day.
    if (
        state["trading_day"]
        != trading_day
    ):

        state = empty_risk_state()

        state[
            "trading_day"
        ] = trading_day

        state[
            "day_start_balance"
        ] = float(
            account_balance
        )

        state[
            "day_start_equity"
        ] = float(
            account_equity
        )

        state[
            "current_risk_amount"
        ] = (
            float(account_balance)
            * RISK_PERCENT
        )

        state[
            "last_updated"
        ] = datetime.now(
            timezone.utc
        ).isoformat()

        save_risk_state(
            state
        )

        print()
        print("=" * 70)
        print("NEW TRADING DAY")
        print("=" * 70)

        print(
            f"Trading day:    "
            f"{trading_day}"
        )

        print(
            f"Start balance:  "
            f"{account_balance}"
        )

        print(
            f"Risk percent:   "
            f"{RISK_PERCENT * 100:.2f}%"
        )

        print(
            f"Risk amount:    "
            f"{state['current_risk_amount']:.2f}"
        )

        print(
            f"Daily loss cap: "
            f"{float(account_balance) * MAX_DAILY_LOSS_PERCENT:.2f}"
        )

        print("=" * 70)

    return state


# ============================================================
# CURRENT RISK
# ============================================================

def get_risk_amount(
    account_balance,
    account_equity,
    market_time
):

    state = initialize_trading_day(
        account_balance,
        account_equity,
        market_time
    )

    return float(
        state[
            "current_risk_amount"
        ]
    )


# ============================================================
# DAILY LOSS CAP
# ============================================================

def get_daily_loss_limit(
    account_balance,
    account_equity,
    market_time
):

    state = initialize_trading_day(
        account_balance,
        account_equity,
        market_time
    )

    return (
        float(
            state[
                "day_start_balance"
            ]
        )
        * MAX_DAILY_LOSS_PERCENT
    )


def update_daily_pnl(
    current_balance
):

    state = load_risk_state()

    if (
        state[
            "day_start_balance"
        ]
        is None
    ):

        return state

    state[
        "daily_realized_pnl"
    ] = (
        float(current_balance)
        - float(
            state[
                "day_start_balance"
            ]
        )
    )

    state[
        "last_updated"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    save_risk_state(
        state
    )

    return state


def daily_loss_limit_reached():

    state = load_risk_state()

    if (
        state[
            "day_start_balance"
        ]
        is None
    ):

        return False

    daily_limit = (
        float(
            state[
                "day_start_balance"
            ]
        )
        * MAX_DAILY_LOSS_PERCENT
    )

    realized_pnl = float(
        state[
            "daily_realized_pnl"
        ]
    )

    return (
        realized_pnl
        <= -daily_limit
    )


# ============================================================
# LOT SIZE
# ============================================================

def calculate_volume(
    risk_amount,
    stop_distance,
    contract_size,
    volume_min,
    volume_max,
    volume_step
):

    risk_amount = float(
        risk_amount
    )

    stop_distance = abs(
        float(stop_distance)
    )

    contract_size = float(
        contract_size
    )

    volume_min = float(
        volume_min
    )

    volume_max = float(
        volume_max
    )

    volume_step = float(
        volume_step
    )

    if risk_amount <= 0:
        raise ValueError(
            "Risk amount must be greater than zero."
        )

    if stop_distance <= 0:
        raise ValueError(
            "Stop distance must be greater than zero."
        )

    if contract_size <= 0:
        raise ValueError(
            "Contract size must be greater than zero."
        )

    if volume_step <= 0:
        raise ValueError(
            "Volume step must be greater than zero."
        )

    raw_volume = (
        risk_amount
        / (
            stop_distance
            * contract_size
        )
    )

    # Round DOWN to broker step.
    steps = int(
        raw_volume
        / volume_step
    )

    volume = (
        steps
        * volume_step
    )

    if volume < volume_min:
        volume = volume_min

    if volume > volume_max:
        volume = volume_max

    step_text = (
        f"{volume_step:.8f}"
    )

    decimals = 0

    if "." in step_text:

        decimals = len(
            step_text.rstrip(
                "0"
            ).split(".")[1]
        )

    return round(
        volume,
        decimals
    )


# ============================================================
# SUMMARY
# ============================================================

def get_risk_summary(
    account_balance,
    account_equity,
    market_time
):

    state = initialize_trading_day(
        account_balance,
        account_equity,
        market_time
    )

    daily_loss_limit = (
        float(
            state[
                "day_start_balance"
            ]
        )
        * MAX_DAILY_LOSS_PERCENT
    )

    return {
        "trading_day":
            state["trading_day"],

        "day_start_balance":
            state["day_start_balance"],

        "day_start_equity":
            state["day_start_equity"],

        "risk_percent":
            RISK_PERCENT,

        "risk_amount":
            state["current_risk_amount"],

        "daily_realized_pnl":
            state["daily_realized_pnl"],

        "max_daily_loss_percent":
            MAX_DAILY_LOSS_PERCENT,

        "max_daily_loss_amount":
            daily_loss_limit,

        "daily_loss_limit_reached":
            daily_loss_limit_reached(),
    }