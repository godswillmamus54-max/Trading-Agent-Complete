import json
import os
import time
import hashlib
import requests
from datetime import datetime, timedelta, timezone

from m1_setup_detector import (
    get_market_data,
    find_swing_points,
    find_bullish_sweep,
    find_bearish_sweep,
    structure_high_before_sweep,
    structure_low_before_sweep,
    find_bullish_breaker,
    find_bearish_breaker,
    price_touches_zone,
    scan_setups,
)

from trade_executor_primary_only import (
    get_account,
    get_positions,
    execute_market_order,
    modify_position,
    close_position,
)

from strategy_config import (
    SYMBOL,
    BOS_LOOKAHEAD,
    RETEST_LOOKAHEAD,
    MIN_BOS_BODY,
)

from risk_engine import (
    get_risk_summary,
    get_risk_amount,
    calculate_volume,
)

# ============================================================
# CONFIGURATION
# ============================================================

POLL_SECONDS = 5
BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "http://127.0.0.1:8000")
STATE_FILE = "multi_setup_state_v28_5_2_primary_only.json"

# ------------------------------------------------------------
# V21 REAL-BROKER SHADOW CONFIRMATION / MARKET INTEGRITY
# ------------------------------------------------------------
# The MetaQuotes-Demo feed remains the execution-test feed. The unfunded
# Exness MT5 terminal is read-only and supplies an independent live-market
# confirmation layer. It can NEVER place orders through this engine.
SHADOW_CONFIRMATION_ENABLED = False
SHADOW_BRIDGE_URL = "http://127.0.0.1:8001"
SHADOW_SYMBOL = "XAUUSDc"
SHADOW_REQUEST_TIMEOUT_SECONDS = 8
SHADOW_MAX_TICK_AGE_SECONDS = 90
SHADOW_MAX_M1_CANDLE_AGE_SECONDS = 150
DEMO_MAX_TICK_AGE_SECONDS = 90
DEMO_MAX_M1_CANDLE_AGE_SECONDS = 150
SHADOW_H4_OPPOSITE_BLOCK = True
SHADOW_DIRECTIONAL_MOVE_LOOKBACK = 5
SHADOW_DIRECTIONAL_MOVE_MIN_PCT = 0.015
SHADOW_STATE_UPDATE_EVERY_POLLS = 1
STATE_VERSION = 40

# ------------------------------------------------------------
# V23 M15 OPPORTUNITY / REVERSAL EXECUTION LANE
# ------------------------------------------------------------
# M15 decides WHERE the opportunity exists. M15 displacement/reversal
# decides WHETHER the area is reacting. M1 supplies execution confirmation.
# The original strict SWEEP -> BOS -> BREAKER -> RETEST route remains active.
M15_OPPORTUNITY_ENABLED = True

# V28: M15 is the ONLY setup generator. M1 is execution confirmation only.
STRICT_M1_SETUP_LANE_ENABLED = False
M15_OPPORTUNITY_LOOKBACK = 32
M15_OPPORTUNITY_MOVE_BARS = 4
M15_OPPORTUNITY_MIN_MOVE = 8.0
M15_OPPORTUNITY_ZONE_MAX_DISTANCE = 2.50
M15_OPPORTUNITY_REVERSAL_BODY_MIN = 0.80
M15_OPPORTUNITY_RECLAIM_FRACTION = 0.55
M15_OPPORTUNITY_MAX_AGE_MINUTES = 180.0
M15_OPPORTUNITY_M1_CONFIRM_BARS = 30
M15_OPPORTUNITY_M1_CONFIRM_MAX_AGE_MINUTES = 5.0
M15_OPPORTUNITY_M1_MIN_BODY = 0.25
M15_OPPORTUNITY_M1_BREAK_LOOKBACK = 3
M15_OPPORTUNITY_MAX_ENTRY_DISTANCE = 2.00
# V27: after M1 confirmation, a missed entry is held until price returns
# to the same freshness envelope. Never widen this threshold to chase price.
M15_OPPORTUNITY_REENTRY_DISTANCE = M15_OPPORTUNITY_MAX_ENTRY_DISTANCE
M15_OPPORTUNITY_MAX_ORDERS_PER_POLL = 1

# V28 strategy-cycle controls: prevent multiple signals from the same local
# market condition from becoming a stream of independent trades.
V28_ENTRY_COOLDOWN_MINUTES = 5.0
V28_OPPOSITE_DIRECTION_COOLDOWN_MINUTES = 10.0
V28_ONE_ENTRY_PER_M15_BAR = True
V28_REQUIRE_M15_NEW_BAR_AFTER_ENTRY = True
V28_REQUIRE_M15_ZONE_TOUCH = True
V28_MIN_ZONE_TOUCHES = 1
V28_SINGLE_LATEST_M15_OPPORTUNITY = True
V28_H4_HARD_DIRECTION_GATE = False

# ------------------------------------------------------------
# V22 DAILY MARKET VIEW / INTRADAY HORIZON MAP
# ------------------------------------------------------------
# The original execution hierarchy remains H4 -> M15 -> M1. V22 adds a
# slower planning layer so the engine knows whether it is in continuation,
# pullback, compression/range, or transition before it accepts an M1 setup.
DAILY_VIEW_ENABLED = True
DAILY_VIEW_ENTRY_GATE_ENABLED = False  # Use daily view as context; do not hard-block otherwise-qualified M15 setups.
DAILY_VIEW_D1_BARS = 60
DAILY_VIEW_H1_BARS = 120
DAILY_VIEW_BLOCK_COUNTERTREND = True
AUDIT_FILE = "xauusd_trade_audit_v28_5_2_primary_only.jsonl"

EXECUTION_ENABLED = True
RR_RATIO = 2.0
# V27: risk-quality test. Broker minimum is 0.01 lots, so the initial
# XAUUSD stop is reduced to keep the actual dollar risk materially below V27.
INITIAL_SL_DISTANCE = 10.0
FIXED_VOLUME = 0.01
MAX_RISK_PER_TRADE_PERCENT = 0.08   # Demo-only ceiling; keep the configured stop intact and reject if it exceeds 8% of balance.
MAX_OPEN_XAU_POSITIONS = 1  # Controlled demo test: one XAUUSD position at a time.

MAX_TRADE_HISTORY = 1000

# ------------------------------------------------------------
# PROVIDER-BASED POSITION MANAGEMENT
# ------------------------------------------------------------
H4_TIMEFRAME = "H4"
H4_BARS = 120
H4_SWING_LOOKBACK = 2
H4_DIRECTION_REQUIRED = True
H4_NEUTRAL_ALLOWS_BOTH = True  # In NEUTRAL, qualifying BUY and SELL setups remain eligible.
H4_SOFT_BIAS_ENABLED = True    # H4 guides confidence; it does not hard-block the opposite direction.
COUNTER_H4_M15_MAX_DISTANCE = 30.0  # Counter-H4 entries need tighter M15 zone alignment than normal entries.
COUNTER_H4_MIN_ZONE_STRENGTH = 0.0   # 0 = use existing M15 strength without inventing a new score threshold.
STRONG_TURN_ENABLED = False  # Legacy provider turn exception; no separate hard block is used in v15.
# V29: Previous breakeven and candle-trailing settings retired.
# All SL protection is handled by the V29 profit-protection manager.

# V29 profit protection
PROFIT_LOCK_TARGET_USD = 3.0
PROFIT_PROTECTION_STEP = 5.0
PROFIT_PROTECTION_API_TIMEOUT = 5.0

POSITION_MANAGER_ENABLED = True
MANAGE_MAGIC = 260927
H4_TREND_EXIT_GRACE_MINUTES = 2.0
H4_TREND_EXIT_CONFIRM_POLLS = 2
H4_ENTRY_RECHECK_ENABLED = True

# ------------------------------------------------------------
# V16 REACTION / REVERSAL ENGINE
# ------------------------------------------------------------
# The engine does not blindly flip direction at an SL/TP. Instead, an
# active trade reaching a stress/profit boundary arms an opposite-direction
# reaction watch. A fresh SWEEP -> BOS -> BREAKER -> RETEST setup can then
# be prioritized for execution.
REACTION_ENGINE_ENABLED = False
REACTION_SL_PROXIMITY = 2.0
REACTION_TP_PROXIMITY = 2.0
REACTION_POST_EXIT_TTL_MINUTES = 15.0
REACTION_MAX_M15_DISTANCE = 30.0
REACTION_MIN_ZONE_STRENGTH = 0.0
REACTION_MAX_ACTIVE_WATCHES = 12

# ------------------------------------------------------------
# V17 OPPORTUNITY RECOGNITION / FAST EXECUTION
# ------------------------------------------------------------
# Protection logic remains unchanged. V17 adds a market-wide fast path for
# fully completed SWEEP -> BOS -> BREAKER -> RETEST setups. This prevents a
# qualifying opportunity from waiting for the 30-minute recovery cycle or
# for a state-seed timing mismatch before it can be executed.
FAST_COMPLETE_SCAN_ENABLED = False
FAST_COMPLETE_SCAN_BARS = 120
FAST_COMPLETE_MAX_RETEST_AGE_MINUTES = 2.0
FAST_COMPLETE_MAX_ORDERS_PER_POLL = 3

# ------------------------------------------------------------
# MULTI-TIMEFRAME CONTEXT
# ------------------------------------------------------------
# M15 is the context/timeframe used to locate support/resistance.
# M1 remains the execution timeframe for SWEEP -> BOS -> BREAKER -> RETEST.
M15_TIMEFRAME = "M15"
M15_BARS = 200
M15_SWING_LOOKBACK = 2
M15_ZONE_TOLERANCE = 2.0
M15_CONTEXT_MAX_DISTANCE = 20.0
M15_CONTEXT_REQUIRED = True

# Every poll performs a recent-history setup scan. This is deliberately
# wider than the previous 12-bar recovery window so a qualifying sweep
# is not dependent on the exact poll/candle boundary at which it appears.
POLL_DISCOVERY_BARS = 120

# ------------------------------------------------------------
# LIVE SETUP FOLLOWING WINDOWS
# ------------------------------------------------------------
# The original 10/15-bar limits were first-pass detector hypotheses.
# For the live multi-setup scalper, candidates remain actionable much
# longer so the state machine does not throw away a setup simply because
# the first short window passed. Each setup is still individually tracked.
LIVE_BOS_LOOKAHEAD_BARS = 30
LIVE_RETEST_LOOKAHEAD_BARS = 30

# 30-minute watchdog. It rescans a wider window and attempts recovery of
# only very recent completed setups.
NO_TRADE_WATCHDOG_MINUTES = 30
CRITICAL_RESCAN_BARS = 240
CRITICAL_MAX_RETEST_AGE_MINUTES = 10

# A retest found retrospectively during an ordinary poll may still be
# executed when it is recent. This protects against short bridge/API gaps.
NORMAL_RECOVERY_RETEST_AGE_MINUTES = 5

# ------------------------------------------------------------
# V18/V19 OPPORTUNITY-STATE HYGIENE
# ------------------------------------------------------------
SETUP_DEDUP_EVENT_GAP_MINUTES = 3.0
SETUP_DEDUP_PRICE_DECIMALS = 2
SETUP_MAX_ORIGIN_AGE_MINUTES = 30.0

# ------------------------------------------------------------
# V20 RETEST ACCEPTANCE
# ------------------------------------------------------------
# A breaker retest must now do more than merely touch the zone.
# It must penetrate meaningfully into the breaker and reclaim the
# directional side of the zone with a stronger close.
RETEST_MIN_PENETRATION_FRACTION = 0.35
RETEST_MIN_CLOSE_RECLAIM_FRACTION = 0.10
RETEST_MAX_ENTRY_DISTANCE_BEYOND_ZONE = 0.75

# Every poll is recorded as two independent directional watch tickets.
# These are monitoring records, not fake trade signals. A trade still
# requires SWEEP -> BOS -> BREAKER -> RETEST.
POLL_WATCH_HISTORY = 2000

# ============================================================
# H4 MASTER TREND ENGINE
# ============================================================


def get_h4_market_data():
    headers = {"x-api-key": os.environ["MT5_BRIDGE_API_KEY"]}
    response = requests.get(
        f"{BRIDGE_URL}/market",
        headers=headers,
        params={"symbol": SYMBOL, "timeframe": H4_TIMEFRAME, "bars": H4_BARS},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("bars_returned", 0) < 20:
        raise RuntimeError(f"Not enough H4 data returned: {data}")
    return data


def h4_find_swings(candles):
    highs = []
    lows = []
    lb = H4_SWING_LOOKBACK
    for i in range(lb, len(candles) - lb):
        c = candles[i]
        if all(c["high"] > candles[j]["high"] for j in range(i-lb, i+lb+1) if j != i):
            highs.append(float(c["high"]))
        if all(c["low"] < candles[j]["low"] for j in range(i-lb, i+lb+1) if j != i):
            lows.append(float(c["low"]))
    return highs, lows


def determine_h4_trend(candles):
    highs, lows = h4_find_swings(candles)
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL", {"reason": "insufficient_swings"}
    hh = highs[-1] > highs[-2]
    hl = lows[-1] > lows[-2]
    lh = highs[-1] < highs[-2]
    ll = lows[-1] < lows[-2]
    if hh and hl:
        return "BULLISH", {"last_high": highs[-1], "prev_high": highs[-2], "last_low": lows[-1], "prev_low": lows[-2]}
    if lh and ll:
        return "BEARISH", {"last_high": highs[-1], "prev_high": highs[-2], "last_low": lows[-1], "prev_low": lows[-2]}
    return "NEUTRAL", {"last_high": highs[-1], "prev_high": highs[-2], "last_low": lows[-1], "prev_low": lows[-2]}


# ============================================================
# V22 DAILY MARKET VIEW / INTRADAY HORIZON MAP
# ============================================================

def get_h1_market_data():
    headers = {"x-api-key": os.environ["MT5_BRIDGE_API_KEY"]}
    response = requests.get(
        f"{BRIDGE_URL}/market",
        headers=headers,
        params={"symbol": SYMBOL, "timeframe": "H1", "bars": DAILY_VIEW_H1_BARS},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("bars_returned", 0) < 30:
        raise RuntimeError(f"Not enough H1 data returned: {data}")
    return data


def get_d1_market_data():
    headers = {"x-api-key": os.environ["MT5_BRIDGE_API_KEY"]}
    response = requests.get(
        f"{BRIDGE_URL}/market",
        headers=headers,
        params={"symbol": SYMBOL, "timeframe": "D1", "bars": DAILY_VIEW_D1_BARS},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("bars_returned", 0) < 20:
        raise RuntimeError(f"Not enough D1 data returned: {data}")
    return data


def determine_structure_trend(candles, swing_lookback=2):
    if not candles or len(candles) < (swing_lookback * 2 + 5):
        return "NEUTRAL", {"reason": "insufficient_candles"}

    highs = []
    lows = []
    lb = swing_lookback
    for i in range(lb, len(candles) - lb):
        c = candles[i]
        if all(c["high"] > candles[j]["high"] for j in range(i-lb, i+lb+1) if j != i):
            highs.append(float(c["high"]))
        if all(c["low"] < candles[j]["low"] for j in range(i-lb, i+lb+1) if j != i):
            lows.append(float(c["low"]))

    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL", {"reason": "insufficient_swings", "highs": len(highs), "lows": len(lows)}

    last_high, prev_high = highs[-1], highs[-2]
    last_low, prev_low = lows[-1], lows[-2]
    hh = last_high > prev_high
    hl = last_low > prev_low
    lh = last_high < prev_high
    ll = last_low < prev_low

    if hh and hl:
        trend = "BULLISH"
    elif lh and ll:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    return trend, {
        "last_high": last_high,
        "prev_high": prev_high,
        "last_low": last_low,
        "prev_low": prev_low,
    }


def true_range(candle, previous_close):
    high = float(candle["high"])
    low = float(candle["low"])
    if previous_close is None:
        return high - low
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def atr_from_candles(candles, period=14):
    if not candles or len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        prev_close = float(candles[i - 1]["close"])
        trs.append(true_range(candles[i], prev_close))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def _day_key_from_time(value):
    dt = parse_time(value)
    return dt.date().isoformat() if dt else None


def _hour_key_from_time(value):
    dt = parse_time(value)
    return dt.strftime("%Y-%m-%dT%H") if dt else None


def _current_day_h1_stats(h1_candles, market_time):
    target_day = _day_key_from_time(market_time)
    same_day = [c for c in h1_candles if _day_key_from_time(c.get("time")) == target_day]
    if not same_day:
        return {
            "day": target_day,
            "open": None,
            "high": None,
            "low": None,
            "mid": None,
            "bars": 0,
        }
    day_open = float(same_day[0]["open"])
    day_high = max(float(c["high"]) for c in same_day)
    day_low = min(float(c["low"]) for c in same_day)
    return {
        "day": target_day,
        "open": day_open,
        "high": day_high,
        "low": day_low,
        "mid": (day_high + day_low) / 2.0,
        "bars": len(same_day),
    }


def build_daily_market_view(d1_data, h1_data, h4_data, h4_trend, m15_context, market_time):
    d1 = d1_data["candles"]
    h1 = h1_data["candles"]
    current_day = _current_day_h1_stats(h1, market_time)

    d1_trend, d1_details = determine_structure_trend(d1, swing_lookback=2)
    h1_trend, h1_details = determine_structure_trend(h1, swing_lookback=2)

    # V22 receives the H4 data and trend from the main loop. Reconstruct the
    # H4 structural details here so the daily-view builder has the same
    # last/previous swing values used by the live H4 trend calculation.
    _, h4_details = determine_h4_trend(h4_data["candles"])

    h4_last_high = float(h4_details.get("last_high", 0.0))
    h4_prev_high = float(h4_details.get("prev_high", h4_last_high))
    h4_last_low = float(h4_details.get("last_low", 0.0))
    h4_prev_low = float(h4_details.get("prev_low", h4_last_low))
    h4_compression = (
        h4_trend == "NEUTRAL"
        and h4_last_high < h4_prev_high
        and h4_last_low > h4_prev_low
    )

    if d1_trend == "BULLISH" and h4_trend == "BULLISH" and h1_trend != "BEARISH":
        regime = "BULLISH_CONTINUATION"
        long_direction = "BUY"
        short_directions = ["BUY"]
    elif d1_trend == "BEARISH" and h4_trend == "BEARISH" and h1_trend != "BULLISH":
        regime = "BEARISH_CONTINUATION"
        long_direction = "SELL"
        short_directions = ["SELL"]
    elif h4_trend == "BULLISH" and h1_trend == "BEARISH":
        regime = "BULLISH_PULLBACK"
        long_direction = "BUY"
        short_directions = ["BUY"]
    elif h4_trend == "BEARISH" and h1_trend == "BULLISH":
        regime = "BEARISH_PULLBACK"
        long_direction = "SELL"
        short_directions = ["SELL"]
    elif h4_compression or (h4_trend == "NEUTRAL" and h1_trend == "NEUTRAL"):
        regime = "RANGE_COMPRESSION"
        long_direction = "NONE"
        short_directions = ["BUY", "SELL"]
    else:
        regime = "TRANSITION"
        long_direction = "NONE"
        short_directions = ["BUY", "SELL"]

    previous_day = d1[-1] if d1 else None
    previous_day_high = float(previous_day["high"]) if previous_day else None
    previous_day_low = float(previous_day["low"]) if previous_day else None
    previous_day_close = float(previous_day["close"]) if previous_day else None

    d1_atr14 = atr_from_candles(d1, 14)
    day_position = None
    if current_day["high"] is not None and current_day["low"] is not None and current_day["high"] > current_day["low"]:
        try:
            last_price = float(m15_context["price"])
            day_position = (last_price - current_day["low"]) / (current_day["high"] - current_day["low"])
        except Exception:
            day_position = None

    support = None
    resistance = None
    try:
        supports = m15_context.get("support_zones", [])
        resistances = m15_context.get("resistance_zones", [])
        price = float(m15_context["price"])
        below = [z for z in supports if float(z["center"]) <= price]
        above = [z for z in resistances if float(z["center"]) >= price]
        if below:
            support = max(below, key=lambda z: float(z["center"]))
        if above:
            resistance = min(above, key=lambda z: float(z["center"]))
    except Exception:
        pass

    if regime == "RANGE_COMPRESSION":
        view_text = "Higher-timeframe compression/range; long intraday direction is unconfirmed; short-term setups should be treated as edge-to-edge opportunities."
    elif regime == "BULLISH_CONTINUATION":
        view_text = "Higher-timeframe bullish continuation context; prioritize BUY setups for intraday continuation."
    elif regime == "BEARISH_CONTINUATION":
        view_text = "Higher-timeframe bearish continuation context; prioritize SELL setups for intraday continuation."
    elif regime == "BULLISH_PULLBACK":
        view_text = "H4 remains bullish while H1 is pulling back; wait for BUY-side structural recovery rather than treating the pullback as a new long-horizon reversal."
    elif regime == "BEARISH_PULLBACK":
        view_text = "H4 remains bearish while H1 is pulling back; wait for SELL-side structural recovery rather than treating the pullback as a new long-horizon reversal."
    else:
        view_text = "Higher-timeframe transition; no long intraday direction is confirmed, so only fully formed short-term structures should be considered."

    return {
        "market_time": market_time,
        "day": _day_key_from_time(market_time),
        "refresh_key": _hour_key_from_time(market_time),
        "d1_trend": d1_trend,
        "d1_details": d1_details,
        "d1_atr14": d1_atr14,
        "h4_trend": h4_trend,
        "h4_details": h4_details,
        "h4_compression": h4_compression,
        "h1_trend": h1_trend,
        "h1_details": h1_details,
        "regime": regime,
        "long_intraday_direction": long_direction,
        "short_intraday_directions": short_directions,
        "previous_day_high": previous_day_high,
        "previous_day_low": previous_day_low,
        "previous_day_close": previous_day_close,
        "current_day": current_day,
        "day_position": day_position,
        "m15_support": support.get("center") if support else None,
        "m15_resistance": resistance.get("center") if resistance else None,
        "m15_price": float(m15_context["price"]),
        "view_text": view_text,
        "shadow_higher_tf_agreement": True,
    }


def refresh_daily_market_view(state, h4_data, h4_trend, m15_context, market_time, force=False):
    if not DAILY_VIEW_ENABLED:
        return state.get("daily_market_view")

    refresh_key = _hour_key_from_time(market_time)
    day_key = _day_key_from_time(market_time)
    existing = state.get("daily_market_view")

    should_refresh = (
        force
        or existing is None
        or existing.get("day") != day_key
        or state.get("daily_view_refresh_key") != refresh_key
    )
    if not should_refresh:
        return existing

    h1_data = get_h1_market_data()
    d1_data = get_d1_market_data()
    view = build_daily_market_view(
        d1_data=d1_data,
        h1_data=h1_data,
        h4_data=h4_data,
        h4_trend=h4_trend,
        m15_context=m15_context,
        market_time=market_time,
    )

    # The Exness shadow feed independently confirms the higher-timeframe view
    # once per refresh cycle. Existing v21 H4/M1 freshness checks remain in force.
    if SHADOW_CONFIRMATION_ENABLED:
        try:
            shadow_h1 = _shadow_get_market("H1", DAILY_VIEW_H1_BARS)
            shadow_d1 = _shadow_get_market("D1", DAILY_VIEW_D1_BARS)
            shadow_h1_trend, _ = determine_structure_trend(shadow_h1["candles"], swing_lookback=2)
            shadow_d1_trend, _ = determine_structure_trend(shadow_d1["candles"], swing_lookback=2)
            view["shadow_h1_trend"] = shadow_h1_trend
            view["shadow_d1_trend"] = shadow_d1_trend
            view["shadow_higher_tf_agreement"] = (
                shadow_h1_trend in {"NEUTRAL", view["h1_trend"]}
                and shadow_d1_trend in {"NEUTRAL", view["d1_trend"]}
            )
        except Exception as error:
            view["shadow_higher_tf_agreement"] = False
            view["shadow_view_error"] = f"{type(error).__name__}: {error}"

    state["daily_market_view"] = view
    state["daily_view_refresh_key"] = refresh_key

    print("=" * 70)
    print("V22 DAILY MARKET VIEW REFRESH")
    print("=" * 70)
    print(f"Date:             {view['day']}")
    print(f"D1 trend:         {view['d1_trend']}")
    print(f"H4 trend:         {view['h4_trend']}")
    print(f"H1 trend:         {view['h1_trend']}")
    print(f"Regime:           {view['regime']}")
    print(f"Long intraday:    {view['long_intraday_direction']}")
    print(f"Short intraday:   {','.join(view['short_intraday_directions'])}")
    print(f"Prev day H/L:     {view['previous_day_high']} / {view['previous_day_low']}")
    print(f"Today O/H/L:      {view['current_day'].get('open')} / {view['current_day'].get('high')} / {view['current_day'].get('low')}")
    print(f"M15 S/R:          {view['m15_support']} / {view['m15_resistance']}")
    print("Secondary shadow D1/H1 confirmation: DISABLED")
    print(f"View:             {view['view_text']}")
    print("=" * 70)

    audit_event("DAILY_MARKET_VIEW", {"view": view})
    return view


def daily_view_direction_allowed(direction, daily_view):
    if not DAILY_VIEW_ENTRY_GATE_ENABLED or not DAILY_VIEW_ENABLED or not daily_view:
        return True, "daily view gate disabled/unavailable"

    short_allowed = direction in set(daily_view.get("short_intraday_directions", []))
    long_direction = daily_view.get("long_intraday_direction")
    shadow_agreement = daily_view.get("shadow_higher_tf_agreement", True)

    if not shadow_agreement:
        return False, "shadow higher-timeframe market view disagrees or is unavailable"

    if DAILY_VIEW_BLOCK_COUNTERTREND and not short_allowed:
        return False, f"direction {direction} is outside the current daily/intraday view"

    if short_allowed and long_direction == direction:
        return True, "direction agrees with long-intraday and short-term view"
    if short_allowed:
        return True, "direction is allowed for short-term intraday conditions"

    return False, "direction not allowed by current daily view"


def daily_view_horizon(direction, daily_view):
    if not daily_view:
        return "UNCLASSIFIED"
    if direction == daily_view.get("long_intraday_direction"):
        return "LONG_INTRADAY_CANDIDATE"
    if direction in set(daily_view.get("short_intraday_directions", [])):
        return "SHORT_TERM_ONLY"
    return "BLOCKED_BY_DAILY_VIEW"


def is_counter_h4_direction(direction, h4_trend):
    return (
        (direction == "SELL" and h4_trend == "BULLISH")
        or (direction == "BUY" and h4_trend == "BEARISH")
    )


def counter_h4_entry_allowed(setup, h4_trend):
    """Apply the v15 soft H4 bias at execution time.

    Counter-H4 trades are not forbidden. They must have tighter M15 location
    alignment than a same-direction H4 trade. The M1 SWEEP -> BOS -> BREAKER
    -> RETEST sequence is already required before this function is reached.
    """
    if not H4_SOFT_BIAS_ENABLED or h4_trend not in {"BULLISH", "BEARISH"}:
        return True, "H4_NEUTRAL_OR_SOFT_BIAS_ONLY"

    direction = setup.get("direction")
    if not is_counter_h4_direction(direction, h4_trend):
        return True, "H4_ALIGNED"

    context = setup.get("m15_context") or {}
    try:
        distance = float(context.get("zone_distance"))
    except (TypeError, ValueError):
        return False, "COUNTER_H4_MISSING_M15_ZONE_DISTANCE"

    try:
        strength = float(context.get("zone_strength", 0.0))
    except (TypeError, ValueError):
        strength = 0.0

    limit = (
        REACTION_MAX_M15_DISTANCE
        if setup.get("reaction_triggered")
        else COUNTER_H4_M15_MAX_DISTANCE
    )
    if distance > limit:
        return False, f"COUNTER_H4_M15_DISTANCE_{distance:.2f}_GT_{limit:.2f}"
    if strength < COUNTER_H4_MIN_ZONE_STRENGTH:
        return False, f"COUNTER_H4_M15_STRENGTH_{strength:.2f}_LT_{COUNTER_H4_MIN_ZONE_STRENGTH:.2f}"

    return True, f"COUNTER_H4_STRONG_M15_ALIGNMENT_DISTANCE_{distance:.2f}"


def h4_allows_direction(direction, h4_trend):
    # v15: H4 is a directional bias, not a hard gate. Both directions remain
    # eligible; counter-H4 setups receive a tighter M15 execution check later.
    if h4_trend in {"BULLISH", "BEARISH", "NEUTRAL"}:
        return True
    return False if H4_DIRECTION_REQUIRED else True


def filter_setups_by_h4(setups, h4_trend, verbose=True):
    accepted = []
    for setup in setups:
        direction = setup.get("direction")
        accepted.append(setup)
        if not verbose:
            continue
        if h4_trend == "NEUTRAL":
            print(f"[H4 BIAS] {setup.get('id')} allowed: H4=NEUTRAL; {direction} remains eligible.")
        elif is_counter_h4_direction(direction, h4_trend):
            print(
                f"[H4 BIAS] {setup.get('id')} allowed to develop: {direction} is counter to H4={h4_trend}; "
                f"tighter M15 confirmation will be required at execution."
            )
        else:
            print(f"[H4 BIAS] {setup.get('id')} aligned with H4={h4_trend}; normal execution rules apply.")
    return accepted


# ============================================================
# ACCOUNT / DAY STATUS — INFORMATIONAL ONLY IN STRATEGY-TEST MODE
# ============================================================

DAILY_LOSS_LIMIT_ENABLED = False
DAILY_LOSS_LIMIT_PERCENT = 0.08  # Stop new entries at 8% equity drawdown from day-start balance.


def get_account_status(account, market_time):
    """Return live account/risk information used by the entry gate."""
    summary = get_risk_summary(
        account_balance=float(account["balance"]),
        account_equity=float(account["equity"]),
        market_time=market_time,
    )

    day_start = float(summary["day_start_balance"])
    balance = float(account["balance"])
    equity = float(account["equity"])
    realized_pnl = balance - day_start
    floating_pnl = equity - balance
    drawdown = max(0.0, day_start - equity)

    live_summary = dict(summary)
    live_summary["risk_percent"] = float(summary.get("risk_percent", 0.10))
    live_summary["daily_loss_limit_enabled"] = DAILY_LOSS_LIMIT_ENABLED
    live_summary["daily_loss_limit_percent"] = DAILY_LOSS_LIMIT_PERCENT
    live_summary["daily_realized_pnl"] = realized_pnl
    live_summary["daily_loss_cap_amount"] = day_start * DAILY_LOSS_LIMIT_PERCENT
    live_summary["live_balance"] = balance
    live_summary["live_equity"] = equity
    live_summary["floating_pnl"] = floating_pnl
    live_summary["daily_drawdown"] = drawdown
    return live_summary, drawdown, False


def print_account_status(summary):
    print(
        f"[ACCOUNT P/L] day={summary['trading_day']} "
        f"start=${summary['day_start_balance']:.2f} "
        f"balance=${summary['live_balance']:.2f} "
        f"equity=${summary['live_equity']:.2f} "
        f"realized=${summary['daily_realized_pnl']:.2f} "
        f"floating=${summary['floating_pnl']:.2f} "
        f"drawdown=${summary['daily_drawdown']:.2f} "
        f"daily_limit={'ENABLED' if DAILY_LOSS_LIMIT_ENABLED else 'DISABLED'}"
    )


def update_daily_ledger(state, summary, account):
    current_day = summary["trading_day"]
    previous = state.get("daily_ledger")
    if previous and previous.get("trading_day") != current_day:
        print("=" * 70)
        print("TRADING DAY CLOSED")
        print("=" * 70)
        print(f"Trading day:      {previous.get('trading_day')}")
        print(f"Start balance:    {previous.get('start_balance', 0.0):.2f}")
        print(f"End balance:      {previous.get('last_balance', 0.0):.2f}")
        print(f"Realized P/L:     {previous.get('last_realized', 0.0):.2f}")
        print(f"End equity:       {previous.get('last_equity', 0.0):.2f}")
        print("=" * 70)

    ledger = state.setdefault("daily_ledger", {})
    if ledger.get("trading_day") != current_day:
        ledger.clear()
        ledger.update({
            "trading_day": current_day,
            "start_balance": float(summary["day_start_balance"]),
        })

    ledger["last_balance"] = float(account["balance"])
    ledger["last_equity"] = float(account["equity"])
    ledger["last_realized"] = float(summary["daily_realized_pnl"])



# ============================================================
# REACTION / REVERSAL ENGINE
# ============================================================

def opposite_direction(direction):
    return "SELL" if direction == "BUY" else "BUY"


def _ensure_reaction_state(state):
    return state.setdefault("reaction_watches", {})


def arm_reaction_watch(
    state,
    direction,
    reason,
    source_ticket=None,
    anchor_price=None,
    market_time=None,
):
    if not REACTION_ENGINE_ENABLED:
        return

    watches = _ensure_reaction_state(state)
    key = f"{direction}:{source_ticket or 'MARKET'}:{reason}"
    expires_at = None
    if market_time:
        dt = parse_time(market_time)
        if dt is not None:
            expires_at = (dt + timedelta(minutes=REACTION_POST_EXIT_TTL_MINUTES)).isoformat()

    watches[key] = {
        "direction": direction,
        "reason": reason,
        "source_ticket": int(source_ticket) if source_ticket is not None else None,
        "anchor_price": float(anchor_price) if anchor_price is not None else None,
        "armed_at": market_time,
        "expires_at": expires_at,
        "triggered_setups": 0,
    }

    # Prevent unbounded growth.
    for old_key in list(watches.keys())[:-REACTION_MAX_ACTIVE_WATCHES]:
        watches.pop(old_key, None)

    audit_event("REACTION_WATCH_ARMED", {
        "direction": direction,
        "reason": reason,
        "source_ticket": source_ticket,
        "anchor_price": anchor_price,
        "armed_at": market_time,
        "expires_at": expires_at,
    })
    print(
        f"[REACTION WATCH] armed {direction} | reason={reason} | "
        f"ticket={source_ticket} | anchor={anchor_price}"
    )


def cleanup_reaction_watches(state, market_time):
    watches = _ensure_reaction_state(state)
    now_dt = parse_time(market_time)
    if now_dt is None:
        return

    for key, watch in list(watches.items()):
        expiry = parse_time(watch.get("expires_at"))
        if expiry is not None and now_dt > expiry:
            audit_event("REACTION_WATCH_EXPIRED", {
                "key": key,
                "direction": watch.get("direction"),
                "reason": watch.get("reason"),
                "expired_at": market_time,
            })
            watches.pop(key, None)


def reaction_watch_active_for_direction(state, direction, market_time):
    cleanup_reaction_watches(state, market_time)
    return [
        watch
        for watch in _ensure_reaction_state(state).values()
        if watch.get("direction") == direction
    ]


def mark_reaction_setup(setup, state, market_time):
    """Annotate a fresh setup when an active reaction watch targets its direction."""
    watches = reaction_watch_active_for_direction(
        state, setup.get("direction"), market_time
    )
    if not watches:
        return setup

    # Pick the most recent watch.
    watch = sorted(
        watches,
        key=lambda x: x.get("armed_at") or "",
        reverse=True,
    )[0]

    setup["reaction_triggered"] = True
    setup["reaction_reason"] = watch.get("reason")
    setup["reaction_source_ticket"] = watch.get("source_ticket")
    return setup


def update_reaction_watches(data, state, market_time):
    """Arm reversal watches near SL/TP of currently open positions."""
    if not REACTION_ENGINE_ENABLED:
        return

    cleanup_reaction_watches(state, market_time)
    positions = get_positions().get("positions", [])
    xau = [
        p for p in positions
        if p.get("symbol") == SYMBOL and int(p.get("magic", 0)) == MANAGE_MAGIC
    ]
    tick = data["current_tick"]

    for position in xau:
        ticket = int(position["ticket"])
        direction = "BUY" if int(position.get("type", 0)) == 0 else "SELL"
        current_price = float(tick["bid"] if direction == "BUY" else tick["ask"])
        sl = float(position.get("sl") or 0.0)
        tp = float(position.get("tp") or 0.0)

        if sl > 0:
            sl_distance = (current_price - sl) if direction == "BUY" else (sl - current_price)
            if 0 <= sl_distance <= REACTION_SL_PROXIMITY:
                arm_reaction_watch(
                    state,
                    opposite_direction(direction),
                    "ACTIVE_SL_STRESS",
                    source_ticket=ticket,
                    anchor_price=sl,
                    market_time=market_time,
                )

        if tp > 0:
            tp_distance = (tp - current_price) if direction == "BUY" else (current_price - tp)
            if 0 <= tp_distance <= REACTION_TP_PROXIMITY:
                arm_reaction_watch(
                    state,
                    opposite_direction(direction),
                    "ACTIVE_TP_APPROACH",
                    source_ticket=ticket,
                    anchor_price=tp,
                    market_time=market_time,
                )


def arm_reaction_from_closed_position(state, rec, market_time):
    """Infer a post-exit reaction watch from the last observed position state."""
    if not REACTION_ENGINE_ENABLED:
        return

    direction = rec.get("direction")
    last_profit = float(rec.get("last_profit", 0.0) or 0.0)
    last_price = float(rec.get("last_price", 0.0) or 0.0)
    last_sl = float(rec.get("last_sl", 0.0) or 0.0)
    last_tp = float(rec.get("last_tp", 0.0) or 0.0)
    source_ticket = rec.get("ticket")

    # A profitable disappearing position is treated as a potential exhaustion
    # point. A losing disappearance is treated as a potential SL failure point
    # only when the last observed price was close to its stop.
    if last_profit > 0:
        reason = "POST_PROFIT_EXIT"
        anchor = last_tp if last_tp > 0 else last_price
        arm_reaction_watch(
            state,
            opposite_direction(direction),
            reason,
            source_ticket=source_ticket,
            anchor_price=anchor,
            market_time=market_time,
        )
        return

    if last_sl > 0 and last_price > 0:
        sl_distance = (last_price - last_sl) if direction == "BUY" else (last_sl - last_price)
        if abs(sl_distance) <= REACTION_SL_PROXIMITY + 1.0:
            arm_reaction_watch(
                state,
                opposite_direction(direction),
                "POST_SL_EXIT",
                source_ticket=source_ticket,
                anchor_price=last_sl,
                market_time=market_time,
            )


# ============================================================
# POSITION MANAGER
# ============================================================


def _is_more_protective(direction, current_sl, candidate_sl):
    current_sl = float(current_sl or 0.0)
    candidate_sl = float(candidate_sl)
    if direction == "BUY":
        return current_sl <= 0 or candidate_sl > current_sl + 0.001
    return current_sl <= 0 or candidate_sl < current_sl - 0.001


def _favorable_change_percent(direction, entry, current_price):
    """Return the individual trade's favorable Change % from entry.

    BUY:  (Bid - Entry) / Entry * 100
    SELL: (Entry - Ask) / Entry * 100
    Negative movement is clamped to zero because only favorable movement
    should trigger breakeven protection.
    """
    entry = float(entry)
    current_price = float(current_price)
    if entry <= 0:
        return 0.0
    move = (current_price - entry) if direction == "BUY" else (entry - current_price)
    return max(0.0, (move / entry) * 100.0)


def manage_open_positions(data, h4_trend, market_time, state=None, silent=False):
    if not POSITION_MANAGER_ENABLED:
        return {"managed": 0, "protected": 0, "closed": 0, "active_tickets": []}
    if state is None:
        state = {"position_management": {}}
    pm_state = state.setdefault("position_management", {})

    positions = get_positions().get("positions", [])
    xau = [p for p in positions if p.get("symbol") == SYMBOL and int(p.get("magic", 0)) == MANAGE_MAGIC]
    active_tickets = {str(int(p["ticket"])) for p in xau}

    # Detect disappearance between polls. Exact broker exit details remain in MT5 history.
    for key, rec in list(pm_state.items()):
        if key not in active_tickets and not rec.get("closed_observed"):
            rec["closed_observed"] = True
            rec["closure_observed_at"] = market_time
            audit_event("POSITION_CLOSE_OBSERVED", {
                "ticket": int(key), "direction": rec.get("direction"),
                "entry": rec.get("entry"), "last_price": rec.get("last_price"),
                "last_profit": rec.get("last_profit"), "last_sl": rec.get("last_sl"),
                "last_tp": rec.get("last_tp"), "last_action": rec.get("last_action"),
                "note": "Position disappeared between polls; verify exact broker close in MT5 history."
            })
            print(f"[POSITION CLOSE OBSERVED] ticket={key} | last_profit=${float(rec.get('last_profit',0.0)):.2f} | last_action={rec.get('last_action','UNKNOWN')}")
            arm_reaction_from_closed_position(state, rec, market_time)

    candles=data["candles"]; tick=data["current_tick"]
    protected=0; closed=0

    for position in xau:
        ticket=int(position["ticket"]); key=str(ticket)
        direction="BUY" if int(position.get("type",0))==0 else "SELL"
        entry=float(position["price_open"]); current_sl=float(position.get("sl") or 0.0); current_tp=float(position.get("tp") or 0.0)
        current_price=float(tick["bid"] if direction=="BUY" else tick["ask"]); profit=float(position.get("profit",0.0))
        favorable_move=current_price-entry if direction=="BUY" else entry-current_price
        favorable_change_pct=_favorable_change_percent(direction,entry,current_price)

        rec=pm_state.setdefault(key,{
            "ticket":ticket,"direction":direction,"entry":entry,"first_seen_time":market_time,
            "entry_h4_trend":h4_trend,"h4_opposite_polls":0,"be_triggered":False,
            "trail_updates":0,"trend_exit_requested":False,"closed_observed":False,
            "max_favorable_move":0.0,"max_adverse_move":0.0,"last_action":"MONITOR",
            "initial_sl_distance": INITIAL_SL_DISTANCE, "max_r_multiple": 0.0
        })
        rec["last_price"]=current_price; rec["last_profit"]=profit; rec["last_sl"]=current_sl; rec["last_tp"]=current_tp
        rec["max_favorable_move"]=max(float(rec.get("max_favorable_move",0.0)),max(favorable_move,0.0))
        rec["max_adverse_move"]=max(float(rec.get("max_adverse_move",0.0)),max(-favorable_move,0.0))

        age_minutes=minutes_between(rec.get("first_seen_time"),market_time) or 0.0
        print(f"[POSITION MANAGER] ticket={ticket} {direction} entry={entry:.2f} price={current_price:.2f} change={favorable_change_pct:.2f}% profit=${profit:.2f} sl={current_sl:.2f} tp={current_tp:.2f} H4={h4_trend} entry_H4={rec.get('entry_h4_trend')} age={age_minutes:.2f}m")

        against_h4=((direction=="BUY" and h4_trend=="BEARISH") or (direction=="SELL" and h4_trend=="BULLISH"))
        if against_h4 and h4_trend != rec.get("entry_h4_trend"):
            rec["h4_opposite_polls"]=int(rec.get("h4_opposite_polls",0))+1
        else:
            rec["h4_opposite_polls"]=0

        trend_exit_confirmed=(against_h4 and h4_trend != rec.get("entry_h4_trend") and age_minutes >= H4_TREND_EXIT_GRACE_MINUTES and rec.get("h4_opposite_polls",0) >= H4_TREND_EXIT_CONFIRM_POLLS)
        if trend_exit_confirmed and not rec.get("trend_exit_requested"):
            try:
                result=close_position(ticket,SYMBOL,MANAGE_MAGIC,f"XMS_TREND_EXIT_{ticket}")
                rec["trend_exit_requested"]=True; rec["last_action"]="TREND_EXIT"
                audit_event("TREND_EXIT_REQUESTED",{
                    "ticket":ticket,"direction":direction,"entry":entry,"current_price":current_price,"profit":profit,
                    "entry_h4_trend":rec.get("entry_h4_trend"),"current_h4_trend":h4_trend,
                    "opposite_polls":rec.get("h4_opposite_polls"),"age_minutes":round(age_minutes,3),"result":result})
                print(f"[TREND EXIT] ticket={ticket} result={result}"); closed+=1
            except Exception as error:
                print(f"[TREND EXIT ERROR] ticket={ticket} {type(error).__name__}: {error}")
            continue

        initial_risk_distance = float(
            rec.get("initial_sl_distance", INITIAL_SL_DISTANCE) or INITIAL_SL_DISTANCE
        )
        if initial_risk_distance <= 0:
            initial_risk_distance = INITIAL_SL_DISTANCE
        rec["initial_sl_distance"] = initial_risk_distance

        r_multiple = favorable_move / initial_risk_distance if favorable_move > 0 else 0.0
        rec["max_r_multiple"] = max(float(rec.get("max_r_multiple", 0.0)), r_multiple)


        # V29: broker-aware profit lock and fixed 5-price-unit ratchet.
        # First stage targets estimated $3 net profit.
        # Subsequent stages lock 5, 10, 15... price units from entry.

        if favorable_move >= PROFIT_PROTECTION_STEP:
            try:
                candidate_sl = None
                protection_stage = int(
                    favorable_move // PROFIT_PROTECTION_STEP
                )

                if protection_stage == 1:
                    headers = {
                        "x-api-key": os.environ["MT5_BRIDGE_API_KEY"]
                    }

                    # BUY: entry is the lower-profit boundary.
                    # SELL: current price is the higher-profit boundary.
                    if direction == "BUY":
                        low = entry
                        high = current_price
                    else:
                        low = current_price
                        high = entry

                    best_candidate = None
                    best_estimate = None

                    # Find the closest-to-market stop that meets
                    # the estimated profit target.
                    for _ in range(18):
                        mid = (low + high) / 2.0

                        response = requests.get(
                            f"{BRIDGE_URL}/position/profit-at-price",
                            headers=headers,
                            params={
                                "ticket": ticket,
                                "close_price": mid,
                            },
                            timeout=PROFIT_PROTECTION_API_TIMEOUT,
                        )
                        response.raise_for_status()
                        estimate = response.json()

                        meets_target = (
                            float(
                                estimate.get(
                                    "estimated_net_profit",
                                    float("-inf"),
                                )
                            ) >= PROFIT_LOCK_TARGET_USD
                        )

                        if direction == "BUY":
                            if meets_target:
                                high = mid
                                best_candidate = mid
                                best_estimate = estimate
                            else:
                                low = mid
                        else:
                            if meets_target:
                                low = mid
                                best_candidate = mid
                                best_estimate = estimate
                            else:
                                high = mid

                    if best_candidate is not None:
                        candidate_sl = best_candidate

                        # Recheck the actual final candidate.
                        verify_response = requests.get(
                            f"{BRIDGE_URL}/position/profit-at-price",
                            headers=headers,
                            params={
                                "ticket": ticket,
                                "close_price": candidate_sl,
                            },
                            timeout=PROFIT_PROTECTION_API_TIMEOUT,
                        )
                        verify_response.raise_for_status()
                        final_estimate = verify_response.json()

                        if float(
                            final_estimate.get(
                                "estimated_net_profit",
                                float("-inf"),
                            )
                        ) < PROFIT_LOCK_TARGET_USD:
                            candidate_sl = None
                        else:
                            # Use the exact broker-tick-normalized price
                            # that was used by the bridge profit calculation.
                            candidate_sl = float(final_estimate["close_price"])
                            rec["first_lock_estimate"] = final_estimate

                else:
                    locked_distance = (
                        protection_stage - 1
                    ) * PROFIT_PROTECTION_STEP

                    candidate_sl = (
                        entry + locked_distance
                        if direction == "BUY"
                        else entry - locked_distance
                    )

                if candidate_sl is not None:
                    candidate_sl = float(candidate_sl)

                    valid = (
                        candidate_sl < current_price
                        if direction == "BUY"
                        else candidate_sl > current_price
                    )

                    if valid and _is_more_protective(
                        direction,
                        current_sl,
                        candidate_sl,
                    ):
                        result = modify_position(
                            ticket,
                            SYMBOL,
                            candidate_sl,
                            current_tp,
                        )

                        # Only record success if the bridge confirms it.
                        if (
                            isinstance(result, dict)
                            and result.get("success") is True
                            and result.get("observed_sl") is not None
                        ):
                            actual_sl = float(result["observed_sl"])
                            rec["trail_updates"] = (
                                int(rec.get("trail_updates", 0)) + 1
                            )
                            rec["last_action"] = "PROFIT_LOCK_STEP"
                            rec["last_protection_stage"] = protection_stage
                            rec["last_sl"] = actual_sl

                            audit_event(
                                "V29_PROFIT_LOCK_UPDATED",
                                {
                                    "ticket": ticket,
                                    "direction": direction,
                                    "entry": entry,
                                    "current_price": current_price,
                                    "favorable_move": favorable_move,
                                    "stage": protection_stage,
                                    "requested_sl": candidate_sl,
                                    "new_sl": actual_sl,
                                    "profit_at_update": profit,
                                    "estimate": rec.get("first_lock_estimate"),
                                    "result": result,
                                },
                            )

                            print(
                                f"[V29 PROFIT LOCK] ticket={ticket} "
                                f"stage={protection_stage} "
                                f"SL={actual_sl:.2f} "
                                f"move={favorable_move:.2f}"
                            )

                            current_sl = actual_sl
                            protected += 1
                        else:
                            print(
                                f"[V29 PROFIT LOCK NOT CONFIRMED] "
                                f"ticket={ticket} result={result}"
                            )

            except Exception as error:
                print(
                    f"[V29 PROFIT LOCK ERROR] ticket={ticket} "
                    f"{type(error).__name__}: {error}"
                )

    return {"managed":len(xau),"protected":protected,"closed":closed,"active_tickets":sorted(int(x) for x in active_tickets)}

# ============================================================
# M15 CONTEXT ENGINE
# ============================================================

M15_HEADERS = {
    "x-api-key": os.environ["MT5_BRIDGE_API_KEY"]
}


def get_m15_market_data():
    """Fetch the higher-timeframe M15 context window."""
    response = requests.get(
        f"{BRIDGE_URL}/market",
        headers=M15_HEADERS,
        params={
            "symbol": SYMBOL,
            "timeframe": M15_TIMEFRAME,
            "bars": M15_BARS,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("bars_returned", 0) == 0:
        raise RuntimeError(f"No M15 data returned: {data}")
    return data


def m15_find_swing_points(candles):
    highs = []
    lows = []
    lb = M15_SWING_LOOKBACK

    for i in range(lb, len(candles) - lb):
        current = candles[i]
        high_ok = True
        low_ok = True

        for j in range(i - lb, i + lb + 1):
            if j == i:
                continue
            if candles[j]["high"] >= current["high"]:
                high_ok = False
            if candles[j]["low"] <= current["low"]:
                low_ok = False

        if high_ok:
            highs.append({
                "index": i,
                "time": current["time"],
                "price": float(current["high"]),
            })

        if low_ok:
            lows.append({
                "index": i,
                "time": current["time"],
                "price": float(current["low"]),
            })

    return highs, lows


def m15_cluster_zones(points):
    if not points:
        return []

    ordered = sorted(points, key=lambda x: x["price"])
    zones = []
    current = [ordered[0]]

    for point in ordered[1:]:
        avg = sum(x["price"] for x in current) / len(current)
        if abs(point["price"] - avg) <= M15_ZONE_TOLERANCE:
            current.append(point)
        else:
            zones.append(m15_build_zone(current))
            current = [point]

    zones.append(m15_build_zone(current))
    return zones


def m15_build_zone(points):
    prices = [float(x["price"]) for x in points]
    latest = max(points, key=lambda x: x["index"])
    return {
        "center": round(sum(prices) / len(prices), 2),
        "lower": round(min(prices), 2),
        "upper": round(max(prices), 2),
        "touches": len(points),
        "latest_time": latest["time"],
        "latest_index": latest["index"],
    }


def m15_score_zones(zones, total_candles):
    scored = []
    denominator = max(total_candles - 1, 1)
    for zone in zones:
        touch_score = zone["touches"] * 10
        recency_score = (zone["latest_index"] / denominator) * 10
        copy = dict(zone)
        copy["strength"] = round(touch_score + recency_score, 2)
        scored.append(copy)
    return sorted(scored, key=lambda z: z["strength"], reverse=True)


def zone_distance(price, zone):
    price = float(price)
    lower = float(zone["lower"])
    upper = float(zone["upper"])
    if lower <= price <= upper:
        return 0.0
    if price < lower:
        return lower - price
    return price - upper


def build_m15_context(data):
    candles = data["candles"]
    if len(candles) < 20:
        raise RuntimeError("Not enough M15 candles for context")

    highs, lows = m15_find_swing_points(candles)
    support = m15_score_zones(
        m15_cluster_zones(lows),
        len(candles),
    )
    resistance = m15_score_zones(
        m15_cluster_zones(highs),
        len(candles),
    )

    tick = data.get("current_tick", {})
    bid = float(tick.get("bid", candles[-1]["close"]))
    ask = float(tick.get("ask", candles[-1]["close"]))
    price = (bid + ask) / 2.0

    return {
        "time": candles[-1]["time"],
        "price": price,
        "support_zones": support,
        "resistance_zones": resistance,
        "latest_candle": candles[-1],
    }


def m15_context_for_setup(direction, liquidity_price, m15_context):
    """Map an M1 sweep to the relevant M15 location context.

    BUY  -> M15 support
    SELL -> M15 resistance

    The M15 module supplied with the project defines support/resistance
    zones but does not itself place an order. M1 still owns execution.
    """
    if not m15_context:
        return None

    zones = (
        m15_context["support_zones"]
        if direction == "BUY"
        else m15_context["resistance_zones"]
    )

    candidates = []
    context_price = float(m15_context["price"])
    for zone in zones:
        center = float(zone["center"])

        # Directional sanity filter:
        # BUY support must not sit above the market.
        # SELL resistance must not sit below the market.
        if direction == "BUY" and center > context_price:
            continue
        if direction == "SELL" and center < context_price:
            continue

        distance = zone_distance(liquidity_price, zone)
        if distance <= M15_CONTEXT_MAX_DISTANCE:
            copy = dict(zone)
            copy["distance"] = round(distance, 2)
            candidates.append(copy)

    if not candidates:
        return None

    candidates.sort(key=lambda z: (z["distance"], -z["strength"]))
    selected = candidates[0]

    return {
        "time": m15_context["time"],
        "zone_type": "SUPPORT" if direction == "BUY" else "RESISTANCE",
        "zone_center": selected["center"],
        "zone_lower": selected["lower"],
        "zone_upper": selected["upper"],
        "zone_strength": selected["strength"],
        "zone_distance": selected["distance"],
    }


# ============================================================
# TIME HELPERS
# ============================================================

def parse_time(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    text = str(value).replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed


def minutes_between(start_value, end_value):
    start = parse_time(start_value)
    end = parse_time(end_value)

    if start is None or end is None:
        return None

    return (end - start).total_seconds() / 60.0


def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# TRADE JOURNAL / PERFORMANCE AUDIT
# ============================================================

def audit_event(event_type, payload):
    event = {"ts": now_utc_iso(), "event": event_type, **payload}
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, separators=(",", ":")) + "\n")
    except Exception as error:
        print(f"[AUDIT WRITE ERROR] {type(error).__name__}: {error}")


def audit_trade_lifecycle_summary(state):
    history = state.get("trade_history", [])
    summary = {
        "trade_attempts": 0,
        "order_results": 0,
        "h4_entry_blocks": 0,
        "be_activations": 0,
        "trail_updates": 0,
        "trend_exit_requests": 0,
        "observed_closes": 0,
        "reaction_watches": 0,
        "reaction_setup_attempts": 0,
        "v23_m15_opportunity_trades": 0,
    }
    for item in history[-MAX_TRADE_HISTORY:]:
        status = item.get("status")
        if status in {"TRADE_ATTEMPTED", "ORDER_ACCEPTED"}:
            summary["trade_attempts"] += 1
            result = item.get("result") or {}
            if result.get("success") or result.get("accepted"):
                summary["order_results"] += 1
        if status == "V23_M15_OPPORTUNITY_TRADE":
            summary["v23_m15_opportunity_trades"] += 1
        if status == "H4_STALE_BLOCK":
            summary["h4_entry_blocks"] += 1
        if "H4_SOFT_BIAS_BLOCK:" in str(item.get("error", "")):
            summary["h4_entry_blocks"] += 1
    for rec in state.get("position_management", {}).values():
        if rec.get("be_triggered"):
            summary["be_activations"] += 1
        summary["trail_updates"] += int(rec.get("trail_updates", 0) or 0)
        if rec.get("trend_exit_requested"):
            summary["trend_exit_requests"] += 1
        if rec.get("closed_observed"):
            summary["observed_closes"] += 1
    summary["reaction_watches"] = len(state.get("reaction_watches", {}))
    summary["reaction_setup_attempts"] = sum(
        1 for item in state.get("trade_history", [])
        if item.get("reaction_triggered")
    )
    return summary


def print_audit_summary(state):
    x = audit_trade_lifecycle_summary(state)
    print(
        "[PERFORMANCE AUDIT] "
        f"attempts={x['trade_attempts']} | "
        f"BE={x['be_activations']} | "
        f"trail={x['trail_updates']} | "
        f"H4_entry_blocks={x['h4_entry_blocks']} | "
        f"trend_exits={x['trend_exit_requests']} | "
        f"observed_closes={x['observed_closes']} | "
        f"reaction_watches={x['reaction_watches']} | "
        f"reaction_setups={x['reaction_setup_attempts']} | "
        f"v23_m15={x['v23_m15_opportunity_trades']}"
    )


# ============================================================
# STATE
# ============================================================

def empty_state():
    return {
        "version": STATE_VERSION,
        "poll_number": 0,
        "last_processed_candle": None,
        "active_setups": [],
        "trade_history": [],
        "poll_watches": [],
        "direction_watchers": {},
        "last_order_time": None,
        "last_critical_review": None,
        "session_start_time": None,
        "position_management": {},
        "reaction_watches": {},
        "shadow_last_m1_time": None,
        "shadow_last_tick_time": None,
        "shadow_last_status": None,
        "last_audit_summary_time": None,
        "daily_market_view": None,
        "daily_view_refresh_key": None,
        "m15_opportunity_watches": {},
        "m15_opportunity_history": [],
        "v28_last_entry_time": None,
        "v28_last_entry_direction": None,
        "v28_last_entry_m15_bar": None,
        "v28_cycle_id": None,
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        return empty_state()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        # The setup ledger structure has intentionally changed. Do not
        # resurrect state from an older implementation.
        if state.get("version") != STATE_VERSION:
            print(
                f"[STATE VERSION RESET] Found {state.get('version')}; "
                f"expected {STATE_VERSION}. Starting clean."
            )
            return empty_state()

        base = empty_state()
        base.update(state)

        cleaned = []
        for setup in base.get("active_setups", []):
            normalized = normalize_setup(setup)
            if normalized.get("id") and normalized.get("sweep_time"):
                cleaned.append(normalized)

        base["active_setups"] = deduplicate_active_setups(cleaned)
        base["trade_history"] = base.get("trade_history", [])[-MAX_TRADE_HISTORY:]
        base["poll_watches"] = base.get("poll_watches", [])[-POLL_WATCH_HISTORY:]
        base["direction_watchers"] = base.get("direction_watchers", {})
        base["position_management"] = base.get("position_management", {})
        base["reaction_watches"] = base.get("reaction_watches", {})
        base["last_audit_summary_time"] = base.get("last_audit_summary_time")
        base["m15_opportunity_watches"] = base.get("m15_opportunity_watches", {})
        base["m15_opportunity_history"] = base.get("m15_opportunity_history", [])[-200:]
        base["v28_last_entry_time"] = base.get("v28_last_entry_time")
        base["v28_last_entry_direction"] = base.get("v28_last_entry_direction")
        base["v28_last_entry_m15_bar"] = base.get("v28_last_entry_m15_bar")
        base["v28_cycle_id"] = base.get("v28_cycle_id")
        return base

    except Exception as error:
        print(f"[STATE LOAD ERROR] {error}")
        return empty_state()


def save_state(state):
    temp_file = f"{STATE_FILE}.tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    os.replace(temp_file, STATE_FILE)


# ============================================================
# CANDLE / SETUP HELPERS
# ============================================================

def candle_index_by_time(candles, target_time):
    if target_time is None:
        return None

    for i, candle in enumerate(candles):
        if candle.get("time") == target_time:
            return i

    return None


def make_setup_id(direction, sweep_time):
    return f"{direction}_{sweep_time}"


def normalize_setup(setup):
    result = dict(setup)

    # Never trust rolling-window indexes from prior versions.
    for key in ("sweep_index", "bos_index", "breaker_index"):
        result.pop(key, None)

    result.setdefault("stage", "WAIT_BOS")
    result.setdefault("bos_time", None)
    result.setdefault("bos_close", None)
    result.setdefault("breaker_time", None)
    result.setdefault("breaker_low", None)
    result.setdefault("breaker_high", None)
    result.setdefault("order_attempted", False)
    result.setdefault("created_time", result.get("sweep_time"))
    result.setdefault("last_evaluated_candle", None)
    result.setdefault("m15_context", None)
    result.setdefault("brain_trade", False)
    result.setdefault("brain_mode", None)
    result.setdefault("brain_reason", None)
    result.setdefault("brain_confidence", None)
    result.setdefault("brain_stop_loss", None)
    result.setdefault("last_announced_retest_time", None)

    if not result.get("id") and result.get("direction") and result.get("sweep_time"):
        result["id"] = make_setup_id(
            result["direction"],
            result["sweep_time"],
        )

    return result


def create_setup(direction, sweep, structure, candle, m15_context=None):
    return {
        "id": make_setup_id(direction, candle["time"]),
        "direction": direction,
        "stage": "WAIT_BOS",
        "sweep_time": candle["time"],
        "liquidity": float(sweep["liquidity"]),
        "sweep_price": float(sweep["sweep_price"]),
        "structure_level": float(structure["price"]),
        "bos_time": None,
        "bos_close": None,
        "breaker_time": None,
        "breaker_low": None,
        "breaker_high": None,
        "order_attempted": False,
        "created_time": candle["time"],
        "last_evaluated_candle": None,
        "m15_context": m15_context,
        "reaction_triggered": False,
        "reaction_reason": None,
        "reaction_source_ticket": None,
    }


def known_terminal_ids(state):
    blocked = set()

    for record in state.get("trade_history", []):
        status = record.get("status", "")
        # Completed orders and actual order errors must never be retried
        # automatically as a duplicate trade.
        if status in {
            "TRADE_ATTEMPTED",
            "CRITICAL_RECOVERY_TRADE",
            "ORDER_ERROR",
            "CRITICAL_RECOVERY_ORDER_ERROR",
            "BOS_EXPIRED",
            "RETEST_EXPIRED",
            "BOS_DATA_GAP",
            "HISTORICAL_EXPIRED",
            "HISTORICAL_EXPIRED_LIVE_WINDOW",
            "MARGIN_BLOCKED",
            "STALE_RETEST",
            "SETUP_ORIGIN_EXPIRED",
        }:
            if record.get("id"):
                blocked.add(record["id"])

    return blocked


def known_active_ids(state):
    return {
        setup.get("id")
        for setup in state.get("active_setups", [])
        if setup.get("id")
    }


# ============================================================
# DEDUPLICATION
# ============================================================
# V18 keeps genuinely independent sweeps, but collapses near-identical
# setup objects that represent the same underlying structural event.
# This prevents one liquidity/BOS/breaker event from becoming several
# executable states while preserving later independent re-sweeps.

def _rounded_price(value):
    try:
        return round(float(value), SETUP_DEDUP_PRICE_DECIMALS)
    except (TypeError, ValueError):
        return None


def structural_setup_key(setup):
    return (
        setup.get("direction"),
        _rounded_price(setup.get("liquidity")),
        _rounded_price(setup.get("structure_level")),
    )


def _setup_stage_rank(setup):
    return {"WAIT_BOS": 1, "WAIT_RETEST": 2, "COMPLETE": 3}.get(
        setup.get("stage"), 0
    )


def _setup_timestamp_gap_minutes(a, b):
    ta = parse_time(a.get("sweep_time"))
    tb = parse_time(b.get("sweep_time"))
    if ta is None or tb is None:
        return None
    return abs((ta - tb).total_seconds()) / 60.0


def setups_are_structural_duplicates(a, b):
    """Identify setup records representing the same structural event."""
    if a.get("direction") != b.get("direction"):
        return False

    # Convergent BOS/breaker events are one event even when the originating
    # liquidity/sweep records differ slightly. This is the exact pattern
    # observed when several sweeps resolve into one BOS and one breaker.
    if (
        a.get("bos_time") is not None
        and a.get("bos_time") == b.get("bos_time")
        and a.get("breaker_time") is not None
        and a.get("breaker_time") == b.get("breaker_time")
    ):
        return True

    if structural_setup_key(a) != structural_setup_key(b):
        return False

    gap = _setup_timestamp_gap_minutes(a, b)
    if gap is not None and gap <= SETUP_DEDUP_EVENT_GAP_MINUTES:
        return True

    return False


def _merge_duplicate_setup(primary, duplicate):
    p = normalize_setup(primary)
    d = normalize_setup(duplicate)

    for key, value in d.items():
        if p.get(key) in (None, "") and value not in (None, ""):
            p[key] = value

    if d.get("reaction_triggered") and not p.get("reaction_triggered"):
        p["reaction_triggered"] = True
        p["reaction_reason"] = d.get("reaction_reason")
        p["reaction_source_ticket"] = d.get("reaction_source_ticket")

    return p


def _choose_duplicate_winner(a, b):
    ra = _setup_stage_rank(a)
    rb = _setup_stage_rank(b)
    if rb > ra:
        return _merge_duplicate_setup(b, a)
    if ra > rb:
        return _merge_duplicate_setup(a, b)

    ta = parse_time(a.get("sweep_time"))
    tb = parse_time(b.get("sweep_time"))
    if ta is not None and tb is not None and tb < ta:
        return _merge_duplicate_setup(b, a)
    return _merge_duplicate_setup(a, b)


def deduplicate_active_setups(active_setups):
    result = []
    for raw in active_setups:
        setup = normalize_setup(raw)
        duplicate_index = None
        for index, existing in enumerate(result):
            if setups_are_structural_duplicates(existing, setup):
                duplicate_index = index
                break

        if duplicate_index is None:
            result.append(setup)
        else:
            result[duplicate_index] = _choose_duplicate_winner(
                result[duplicate_index], setup
            )

    return result


def has_structural_duplicate(setup, setups):
    return any(
        setups_are_structural_duplicates(setup, existing)
        for existing in setups
    )


# ============================================================
# RETEST LOGIC
# ============================================================

def bullish_retest(candle, breaker):
    if not price_touches_zone(candle, breaker):
        return False

    low = float(breaker["low"])
    high = float(breaker["high"])
    width = max(high - low, 0.000001)
    midpoint = (high + low) / 2.0
    penetration_floor = high - (width * RETEST_MIN_PENETRATION_FRACTION)
    reclaim_close = midpoint + (width * RETEST_MIN_CLOSE_RECLAIM_FRACTION)

    candle_low = float(candle["low"])
    candle_close = float(candle["close"])

    # BUY retest: price must travel meaningfully back into the breaker
    # before closing back on the bullish side with a stronger reclaim.
    return (
        candle_low <= penetration_floor
        and candle_close > reclaim_close
    )


def bearish_retest(candle, breaker):
    if not price_touches_zone(candle, breaker):
        return False

    low = float(breaker["low"])
    high = float(breaker["high"])
    width = max(high - low, 0.000001)
    midpoint = (high + low) / 2.0
    penetration_ceiling = low + (width * RETEST_MIN_PENETRATION_FRACTION)
    reclaim_close = midpoint - (width * RETEST_MIN_CLOSE_RECLAIM_FRACTION)

    candle_high = float(candle["high"])
    candle_close = float(candle["close"])

    # SELL retest: price must travel meaningfully back into the breaker
    # before closing back on the bearish side with a stronger reclaim.
    return (
        candle_high >= penetration_ceiling
        and candle_close < reclaim_close
    )


# ============================================================
# SWEEP DISCOVERY
# ============================================================

def detect_setup_seeds_for_index(candles, index, m15_context=None):
    """Return every M1 BUY/SELL sweep candidate aligned with current M15 context."""
    if index <= 0 or index >= len(candles):
        return []

    history = candles[: index + 1]
    swing_highs, swing_lows = find_swing_points(history)
    candle = history[-1]
    result = []

    bullish = find_bullish_sweep(
        history,
        len(history) - 1,
        swing_lows,
    )

    if bullish:
        structure = structure_high_before_sweep(
            swing_highs,
            len(history) - 1,
        )
        if structure:
            context = m15_context_for_setup(
                "BUY",
                float(bullish["liquidity"]),
                m15_context,
            )
            if context is not None or not M15_CONTEXT_REQUIRED:
                result.append(
                    create_setup(
                        "BUY",
                        bullish,
                        structure,
                        candle,
                        context,
                    )
                )

    bearish = find_bearish_sweep(
        history,
        len(history) - 1,
        swing_highs,
    )

    if bearish:
        structure = structure_low_before_sweep(
            swing_lows,
            len(history) - 1,
        )
        if structure:
            context = m15_context_for_setup(
                "SELL",
                float(bearish["liquidity"]),
                m15_context,
            )
            if context is not None or not M15_CONTEXT_REQUIRED:
                result.append(
                    create_setup(
                        "SELL",
                        bearish,
                        structure,
                        candle,
                        context,
                    )
                )

    return result


def discover_recent_setups(candles, state, m15_context=None, bars=POLL_DISCOVERY_BARS):
    """Scan recent closed candles on EVERY poll, not only on new-candle events."""
    if not candles:
        return []

    start = max(1, len(candles) - bars)
    latest_index = len(candles) - 1
    active_ids = known_active_ids(state)
    terminal_ids = known_terminal_ids(state)
    discovered = []

    for index in range(start, len(candles)):
        candidates = detect_setup_seeds_for_index(candles, index, m15_context)

        for setup in candidates:
            setup_id = setup["id"]
            age_bars = latest_index - index

            # Discovery must obey the same hard origin-age boundary used by
            # advance_setup(). Without this, a setup can expire at 30 minutes
            # and then be rediscovered from the rolling scan until the broader
            # 60-bar BOS+RETEST window is exhausted.
            origin_age_minutes = minutes_between(
                setup.get("sweep_time"),
                candles[latest_index]["time"],
            )
            if (
                origin_age_minutes is not None
                and origin_age_minutes > SETUP_MAX_ORIGIN_AGE_MINUTES
            ):
                continue

            # A new sweep must still be close enough to have a live BOS
            # window. Older complete setups are handled by critical recovery.
            if age_bars > LIVE_BOS_LOOKAHEAD_BARS + LIVE_RETEST_LOOKAHEAD_BARS:
                continue

            if setup_id in active_ids or setup_id in terminal_ids:
                continue

            if has_structural_duplicate(setup, state.get("active_setups", [])):
                continue
            if has_structural_duplicate(setup, discovered):
                continue

            active_ids.add(setup_id)
            discovered.append(setup)

    return discovered


# ============================================================
# BOS + BREAKER SEARCH
# ============================================================

def find_valid_bos_and_breaker(candles, setup, current_index):
    sweep_index = candle_index_by_time(
        candles,
        setup.get("sweep_time"),
    )

    if sweep_index is None:
        return None, None

    if current_index <= sweep_index:
        return None, None

    end_index = min(
        current_index,
        sweep_index + LIVE_BOS_LOOKAHEAD_BARS,
    )

    structure_level = float(setup["structure_level"])

    for i in range(sweep_index + 1, end_index + 1):
        candle = candles[i]

        body = abs(
            float(candle["close"]) - float(candle["open"])
        )

        if body < MIN_BOS_BODY:
            continue

        if setup["direction"] == "BUY":
            if float(candle["close"]) <= structure_level:
                continue
        else:
            if float(candle["close"]) >= structure_level:
                continue

        bos = {
            "index": i,
            "close": float(candle["close"]),
        }

        sweep = {"index": sweep_index}

        if setup["direction"] == "BUY":
            breaker = find_bullish_breaker(
                candles,
                sweep,
                bos,
            )
        else:
            breaker = find_bearish_breaker(
                candles,
                sweep,
                bos,
            )

        # A BOS without a breaker does NOT kill the setup. Continue searching
        # for another valid BOS inside the permitted BOS window.
        if breaker is None:
            continue

        return bos, breaker

    return None, None


# ============================================================
# ORDER CALCULATION / EXECUTION
# ============================================================

def _execution_float(mapping, key, label, fallback=None):
    value = mapping.get(key) if isinstance(mapping, dict) else None

    if value is None and fallback is not None:
        print(
            f"[EXEC DATA FALLBACK] {label}=None -> using {fallback}"
        )
        value = fallback

    if value is None:
        raise RuntimeError(
            f"MISSING_EXECUTION_DATA: {label}=None | "
            f"payload={mapping}"
        )

    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"INVALID_EXECUTION_DATA: {label}={value!r}"
        ) from exc


def calculate_order(setup, current_tick, symbol_info, account, market_time):
    risk_amount = get_risk_amount(
        account_balance=float(account["balance"]),
        account_equity=float(account["equity"]),
        market_time=market_time,
    )

    if SYMBOL == "XAUUSD":
        # Current MetaQuotes-Demo XAUUSD contract specifications already
        # verified for this project. They are used only when the bridge
        # returns None for a metadata field; live bid/ask are NEVER guessed.
        fallback = {
            "contract_size": 100.0,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
        }
    else:
        fallback = {}

    # V27.4 strategy-test mode: use the configured strategy SL directly.
    # No account-risk cap is allowed to alter or reject a qualified setup.
    if setup["direction"] == "BUY":
        entry = _execution_float(current_tick, "ask", "current_tick.ask")
        stop_loss = entry - INITIAL_SL_DISTANCE
        risk_distance = INITIAL_SL_DISTANCE
    else:
        entry = _execution_float(current_tick, "bid", "current_tick.bid")
        stop_loss = entry + INITIAL_SL_DISTANCE
        risk_distance = INITIAL_SL_DISTANCE

    if risk_distance <= 0:
        raise RuntimeError(
            f"Invalid risk distance: {risk_distance}"
        )

    contract_size = _execution_float(
        symbol_info, "contract_size", "symbol_info.contract_size",
        fallback.get("contract_size"),
    )
    volume_min = _execution_float(
        symbol_info, "volume_min", "symbol_info.volume_min",
        fallback.get("volume_min"),
    )
    volume_max = _execution_float(
        symbol_info, "volume_max", "symbol_info.volume_max",
        fallback.get("volume_max"),
    )
    volume_step = _execution_float(
        symbol_info, "volume_step", "symbol_info.volume_step",
        fallback.get("volume_step"),
    )

    # V28.5 controlled demo: preserve the strategy stop exactly. Never shrink
    # the stop to manufacture a smaller risk number; reject if the nominal
    # contract-size estimate exceeds the demo per-trade ceiling.
    volume = max(float(FIXED_VOLUME), float(volume_min))
    volume = round(round(volume / volume_step) * volume_step, 8)

    if volume > volume_max:
        raise RuntimeError(
            f"FIXED_VOLUME_ABOVE_BROKER_MAX: {volume} > {volume_max}"
        )

    actual_risk = risk_distance * contract_size * volume
    max_risk_dollars = float(account["balance"]) * MAX_RISK_PER_TRADE_PERCENT
    if actual_risk > max_risk_dollars + 1e-9:
        raise RuntimeError(
            "V28.5_RISK_CAP: preserving the configured stop would risk "
            f"an estimated ${actual_risk:.2f}, above the demo cap "
            f"${max_risk_dollars:.2f} ({MAX_RISK_PER_TRADE_PERCENT:.1%} of balance); "
            "trade skipped without narrowing the stop."
        )

    # V20 breaker chase guard remains active for the original strict route.
    if not setup.get("m15_opportunity"):
        breaker_low = setup.get("breaker_low")
        breaker_high = setup.get("breaker_high")
        if breaker_low is not None and breaker_high is not None:
            if setup["direction"] == "BUY":
                distance_beyond_zone = entry - float(breaker_high)
            else:
                distance_beyond_zone = float(breaker_low) - entry

            if distance_beyond_zone > RETEST_MAX_ENTRY_DISTANCE_BEYOND_ZONE:
                raise RuntimeError(
                    "RETEST_ACCEPTANCE_INVALID: entry moved "
                    f"{distance_beyond_zone:.2f} beyond breaker zone; "
                    "setup is no longer a fresh retest entry."
                )

    # V23 opportunity freshness guard.
    if setup.get("m15_opportunity"):
        reference = float(setup.get("opportunity_entry_reference", entry))
        expansion = (
            entry - reference
            if setup["direction"] == "BUY"
            else reference - entry
        )
        if expansion > M15_OPPORTUNITY_MAX_ENTRY_DISTANCE:
            raise RuntimeError(
                "V27_OPPORTUNITY_CHASE_INVALID: execution moved "
                f"{expansion:.2f} beyond the M1 confirmation reference."
            )

    if setup["direction"] == "BUY":
        take_profit = entry + risk_distance * RR_RATIO
    else:
        take_profit = entry - risk_distance * RR_RATIO

    return {
        "entry": round(entry, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "risk_distance": round(risk_distance, 2),
        "target_risk": round(float(risk_amount), 2),
        "actual_risk": round(actual_risk, 2),
        "volume": volume,
    }


def is_insufficient_margin_error(error):
    """Return True when MT5 explicitly says the order cannot be funded."""
    text = str(error).lower()
    return (
        "retcode': 10019" in text
        or "retcode=10019" in text
        or "insufficient margin" in text
        or "no money" in text
        or "margin even at broker minimum" in text
    )


def is_invalid_risk_distance_error(error):
    text = str(error).lower()
    return "invalid risk distance:" in text


def is_retest_acceptance_error(error):
    text = str(error).lower()
    return "retest_acceptance_invalid:" in text


def execute_setup(setup, current_tick, symbol_info, market_time, h4_trend=None):
    if setup.get("order_attempted"):
        return {"status": "ALREADY_ATTEMPTED"}

    last_error_time = setup.get("last_order_error_time")
    if last_error_time is not None:
        retry_age = minutes_between(last_error_time, market_time)
        if retry_age is not None and retry_age < (10.0 / 60.0):
            return {
                "status": "RETRY_COOLDOWN",
                "retry_in_seconds": round(10.0 - (retry_age * 60.0), 1),
            }

    account = get_account()

    print()
    print("=" * 70)
    print("TRADE EXECUTION")
    print("=" * 70)
    print(f"Setup:          {setup['id']}")
    print(f"Direction:      {setup['direction']}")
    print(f"Server:         {account['server']}")
    print(f"Balance:        {account['balance']}")
    print(f"Equity:         {account['equity']}")

    if "MetaQuotes-Demo" not in account["server"]:
        raise RuntimeError(
            "ORDER BLOCKED: non-demo server detected."
        )

    if not account["trade_allowed"]:
        raise RuntimeError(
            "ORDER BLOCKED: trading is not allowed."
        )

    if not account["trade_expert"]:
        raise RuntimeError(
            "ORDER BLOCKED: expert trading is not allowed."
        )

    if H4_ENTRY_RECHECK_ENABLED and h4_trend in {"BULLISH", "BEARISH"}:
        direction = setup.get("direction")
        allowed, reason = counter_h4_entry_allowed(setup, h4_trend)
        if not allowed:
            audit_event("H4_SOFT_BIAS_ENTRY_BLOCK", {
                "setup_id": setup.get("id"),
                "direction": direction,
                "h4_trend": h4_trend,
                "reason": reason,
                "m15_context": setup.get("m15_context"),
            })
            setup["last_order_error"] = f"H4_SOFT_BIAS_BLOCK: {direction} counter to H4={h4_trend}; {reason}"
            raise RuntimeError(setup["last_order_error"])
        if is_counter_h4_direction(direction, h4_trend):
            reaction_note = " | REACTION-PRIORITY" if setup.get("reaction_triggered") else ""
            print(f"[H4 SOFT BIAS] counter-H4 {direction} permitted: {reason}{reaction_note}")

    risk_summary, live_drawdown, _ = get_account_status(account, market_time)

    daily_cap = float(risk_summary["day_start_balance"]) * DAILY_LOSS_LIMIT_PERCENT
    if DAILY_LOSS_LIMIT_ENABLED and live_drawdown >= daily_cap:
        raise RuntimeError(
            f"V28.5_DAILY_EQUITY_DRAWDOWN_CAP: drawdown=${live_drawdown:.2f} "
            f"has reached the ${daily_cap:.2f} daily limit; new entries blocked."
        )

    positions = get_positions()
    xau_positions = [
        p for p in positions.get("positions", [])
        if p.get("symbol") == SYMBOL
    ]
    if len(xau_positions) >= MAX_OPEN_XAU_POSITIONS:
        raise RuntimeError(
            f"V28.5_MAX_OPEN_POSITIONS: {len(xau_positions)} XAUUSD position(s) "
            f"already open; limit={MAX_OPEN_XAU_POSITIONS}."
        )

    print(f"Trading day:    {risk_summary['trading_day']}")
    print(
        f"Risk/trade reference: "
        f"{risk_summary['risk_amount']:.2f}"
    )
    print(f"Daily equity drawdown limit: {'ENABLED' if DAILY_LOSS_LIMIT_ENABLED else 'DISABLED'} at {DAILY_LOSS_LIMIT_PERCENT:.1%}")
    print(f"Live day drawdown: ${live_drawdown:.2f} / ${daily_cap:.2f}")
    print(f"Current XAUUSD positions: {len(xau_positions)} / {MAX_OPEN_XAU_POSITIONS}")

    print(
        "[EXECUTION STATE] "
        f"stage={setup.get('stage')} | "
        f"bos={setup.get('bos_time')} | "
        f"breaker={setup.get('breaker_time')} | "
        f"breaker_low={setup.get('breaker_low')} | "
        f"breaker_high={setup.get('breaker_high')}"
    )

    order = calculate_order(
        setup=setup,
        current_tick=current_tick,
        symbol_info=symbol_info,
        account=account,
        market_time=market_time,
    )

    print()
    print(f"Entry:          {order['entry']:.2f}")
    print(f"Stop Loss:      {order['stop_loss']:.2f}")
    print(f"Take Profit:    {order['take_profit']:.2f}")
    print(f"Volume:         {order['volume']}")
    print(f"Target risk:    ${order['target_risk']:.2f}")
    print(f"Actual risk:    ${order['actual_risk']:.2f}")
    print(f"R:R:            {RR_RATIO}:1")

    print(
        "[V28.5 CONTROLLED DEMO] per-trade estimate cap="
        f"{MAX_RISK_PER_TRADE_PERCENT:.1%} | daily equity drawdown cap="
        f"{DAILY_LOSS_LIMIT_PERCENT:.1%} | max XAUUSD positions={MAX_OPEN_XAU_POSITIONS}"
    )
    print("=" * 70)

    if not EXECUTION_ENABLED:
        print("[EXECUTION DISABLED]")
        return {"status": "DISABLED"}

    # Do NOT mark the setup attempted before the broker call.
    # If order calculation/submission fails, the setup stays alive for retry.
    # Each setup gets a deterministic short broker comment. This lets the
    # executor reconcile an order that reached MT5 even when the HTTP layer
    # reports an error afterward, without confusing independent setups.
    setup_fingerprint = hashlib.sha1(
        setup["id"].encode("utf-8")
    ).hexdigest()[:16]
    order_comment = f"XMS_{setup_fingerprint}"
    setup["order_comment"] = order_comment

    if setup.get("reaction_triggered"):
        audit_event("REACTION_ORDER_ATTEMPT", {
            "setup_id": setup.get("id"),
            "direction": setup.get("direction"),
            "reason": setup.get("reaction_reason"),
            "source_ticket": setup.get("reaction_source_ticket"),
            "entry": order.get("entry"),
        })

    result = execute_market_order(
        direction=setup["direction"],
        volume=order["volume"],
        stop_loss=order["stop_loss"],
        take_profit=order["take_profit"],
        comment=order_comment,
    )

    setup["order_attempted"] = True
    setup["execution_status"] = "SUBMITTED"
    setup["last_order_error"] = None
    setup["last_order_error_time"] = None

    print()
    print("=" * 70)
    print("MT5 ORDER RESPONSE")
    print("=" * 70)
    print(result)
    print("=" * 70)

    audit_event("ORDER_RESULT", {
        "setup_id": setup.get("id"), "direction": setup.get("direction"),
        "entry": order.get("entry"), "stop_loss": order.get("stop_loss"),
        "take_profit": order.get("take_profit"), "volume": order.get("volume"),
        "result": result
    })

    return result


# ============================================================
# SETUP ADVANCEMENT
# ============================================================

def find_retest_in_window(candles, bos_index, current_index, direction, breaker):
    end_index = min(
        current_index,
        bos_index + LIVE_RETEST_LOOKAHEAD_BARS,
    )

    for i in range(bos_index + 1, end_index + 1):
        candle = candles[i]

        if direction == "BUY":
            valid = bullish_retest(candle, breaker)
        else:
            valid = bearish_retest(candle, breaker)

        if valid:
            return i

    return None


def advance_setup(
    candles,
    current_index,
    setup,
    current_tick,
    symbol_info,
    state,
    allow_trade=True,
    silent=False,
    recovery_max_age_minutes=NORMAL_RECOVERY_RETEST_AGE_MINUTES,
):
    """Fully re-evaluate one setup against all currently available closed M1 candles."""

    # IMPORTANT: do not re-normalize/copy the setup here.
    # The caller has already normalized this dictionary. Re-normalizing
    # creates a second dict and loses BOS/breaker mutations made below.
    latest_time = candles[current_index]["time"]

    origin_age = minutes_between(setup.get("sweep_time"), latest_time)
    if origin_age is not None and origin_age > SETUP_MAX_ORIGIN_AGE_MINUTES:
        if not silent:
            print(
                f"[EXPIRED] {setup['id']} setup origin age="
                f"{origin_age:.2f} min exceeds "
                f"{SETUP_MAX_ORIGIN_AGE_MINUTES:.2f} min."
            )
        return "EXPIRE", {
            "status": "SETUP_ORIGIN_EXPIRED",
            "origin_age_minutes": round(origin_age, 2),
        }

    sweep_index = candle_index_by_time(
        candles,
        setup.get("sweep_time"),
    )

    if sweep_index is None:
        return "DROP", None

    # --------------------------------------------------------
    # WAIT_BOS -> find BOS + breaker across the whole live window.
    # --------------------------------------------------------
    if setup["stage"] == "WAIT_BOS":
        bars_after_sweep = current_index - sweep_index

        if bars_after_sweep <= 0:
            setup["last_evaluated_candle"] = latest_time
            return "KEEP", None

        if bars_after_sweep > LIVE_BOS_LOOKAHEAD_BARS:
            if not silent:
                print(
                    f"[EXPIRED] {setup['id']} BOS follow window expired after "
                    f"{LIVE_BOS_LOOKAHEAD_BARS} M1 bars."
                )
            return "EXPIRE", {"status": "BOS_EXPIRED"}

        bos, breaker = find_valid_bos_and_breaker(
            candles,
            setup,
            current_index,
        )

        if bos is None or breaker is None:
            setup["last_evaluated_candle"] = latest_time
            return "KEEP", None

        setup["stage"] = "WAIT_RETEST"
        setup["bos_time"] = candles[bos["index"]]["time"]
        setup["bos_close"] = bos["close"]
        setup["breaker_time"] = candles[breaker["index"]]["time"]
        setup["breaker_low"] = float(breaker["low"])
        setup["breaker_high"] = float(breaker["high"])

        if not silent:
            print()
            print("=" * 70)
            print("BOS + BREAKER DETECTED")
            print("=" * 70)
            print(f"Setup:          {setup['id']}")
            print(f"Direction:      {setup['direction']}")
            print(f"BOS time:       {setup['bos_time']}")
            print(f"BOS level:      {setup['structure_level']:.2f}")
            print(
                f"Breaker:        "
                f"{setup['breaker_low']:.2f} - "
                f"{setup['breaker_high']:.2f}"
            )
            print("State:          WAIT_RETEST")
            print("=" * 70)

    # --------------------------------------------------------
    # WAIT_RETEST -> search the full permissible retest window.
    # --------------------------------------------------------
    if setup["stage"] == "WAIT_RETEST":
        bos_index = candle_index_by_time(
            candles,
            setup.get("bos_time"),
        )

        if bos_index is None:
            return "DROP", {"status": "BOS_DATA_GAP"}

        bars_after_bos = current_index - bos_index
        if bars_after_bos <= 0:
            setup["last_evaluated_candle"] = latest_time
            return "KEEP", None

        if bars_after_bos > LIVE_RETEST_LOOKAHEAD_BARS:
            if not silent:
                print(
                    f"[EXPIRED] {setup['id']} retest follow window expired after "
                    f"{LIVE_RETEST_LOOKAHEAD_BARS} M1 bars."
                )
            return "EXPIRE", {"status": "RETEST_EXPIRED"}

        breaker = {
            "low": setup["breaker_low"],
            "high": setup["breaker_high"],
        }

        retest_index = find_retest_in_window(
            candles,
            bos_index,
            current_index,
            setup["direction"],
            breaker,
        )

        if retest_index is None:
            setup["last_evaluated_candle"] = latest_time
            return "KEEP", None

        retest_time = candles[retest_index]["time"]
        retest_age = minutes_between(retest_time, latest_time)

        # Never keep stale completed retests alive. Once the recovery window
        # has passed, the setup is terminal for execution purposes.
        if retest_age is None or retest_age > recovery_max_age_minutes:
            if not silent:
                print(
                    f"[STALE RETEST] {setup['id']} retest age="
                    f"{retest_age:.2f} min; recovery window="
                    f"{recovery_max_age_minutes:.2f} min. Setup retired."
                    if retest_age is not None
                    else f"[STALE RETEST] {setup['id']} retest age unknown; setup retired."
                )
            setup["last_evaluated_candle"] = latest_time
            return "EXPIRE", {"status": "STALE_RETEST"}

        # Announce each retest event once per setup, even though the state
        # machine continues checking it every poll.
        if setup.get("last_announced_retest_time") != retest_time:
            if not silent:
                print()
                print("=" * 70)
                print("VALID SETUP DETECTED")
                print("=" * 70)
                print(f"Setup:          {setup['id']}")
                print(f"Direction:      {setup['direction']}")
                print(f"Sweep:          {setup['sweep_time']}")
                print(f"BOS:            {setup['bos_time']}")
                print(f"Breaker:        {setup['breaker_time']}")
                print(f"Retest:         {retest_time}")
                print(
                    f"Retest close:   "
                    f"{candles[retest_index]['close']:.2f}"
                )
                print(
                    f"Retest age:     "
                    f"{retest_age:.2f} min"
                )
                print("=" * 70)
            setup["last_announced_retest_time"] = retest_time

        return "COMPLETE", {
            "retest_time": retest_time,
            "retest_index": retest_index,
            # Carry the fully enriched execution state forward so the
            # executor cannot accidentally receive the original WAIT_BOS
            # seed instead of the setup that actually reached retest.
            "execution_state": {
                "stage": setup["stage"],
                "bos_time": setup["bos_time"],
                "bos_close": setup["bos_close"],
                "breaker_time": setup["breaker_time"],
                "breaker_low": setup["breaker_low"],
                "breaker_high": setup["breaker_high"],
            },
        }

    setup["last_evaluated_candle"] = latest_time
    return "KEEP", None


# ============================================================
# SETUP REGISTRATION
# ============================================================

def register_setups(state, setups, verbose=True):
    if not setups:
        return 0

    active_ids = known_active_ids(state)
    terminal_ids = known_terminal_ids(state)
    added = 0

    for setup in setups:
        setup = mark_reaction_setup(setup, state, now_utc_iso())
        setup_id = setup["id"]

        if setup_id in active_ids or setup_id in terminal_ids:
            continue

        if has_structural_duplicate(setup, state.get("active_setups", [])):
            print(
                f"[SETUP DEDUP] {setup_id} | "
                "same underlying structural event already tracked; not registering another setup."
            )
            continue

        state["active_setups"].append(setup)
        active_ids.add(setup_id)
        added += 1

        if verbose:
            print()
            print("=" * 70)
            print("NEW SETUP TRACKING")
            print("=" * 70)
            print(f"ID:             {setup['id']}")
            print(f"Direction:      {setup['direction']}")
            print(f"Sweep:          {setup['sweep_time']}")
            print(f"Liquidity:      {setup['liquidity']:.2f}")
            print(f"BOS level:      {setup['structure_level']:.2f}")
            context = setup.get("m15_context") or {}
            if context:
                print(
                    f"M15 context:    {context.get('zone_type')} "
                    f"{context.get('zone_lower'):.2f}-{context.get('zone_upper'):.2f} | "
                    f"distance={context.get('zone_distance'):.2f} | "
                    f"strength={context.get('zone_strength'):.2f}"
                )
            else:
                print("M15 context:    none")
            if setup.get("reaction_triggered"):
                print(
                    f"Reaction priority: {setup.get('reaction_reason')} "
                    f"| source_ticket={setup.get('reaction_source_ticket')}"
                )
            print("State recorded: FOLLOW UNTIL ORDER / EXPIRY")
            print("=" * 70)

    state["active_setups"] = deduplicate_active_setups(
        state["active_setups"]
    )
    return added


# ============================================================
# EXECUTION STATE HYDRATION
# ============================================================

def hydrate_execution_setup(setup, info, candles, current_index):
    """
    Build the exact setup state that is allowed to reach the order executor.

    The important invariant is:
        EXECUTION -> never receives the original WAIT_BOS seed
        when the same setup has already reached BOS/BREAKER/RETEST.

    The primary source is the execution_state captured by advance_setup().
    If that payload is incomplete, re-derive BOS + breaker from the SAME
    sweep/structure setup before allowing execution. This does not invent a
    new pattern; it only reconstructs state for the already-qualified setup.
    """
    hydrated = normalize_setup(setup)

    execution_state = (info or {}).get("execution_state") or {}

    for key in (
        "bos_time",
        "bos_close",
        "breaker_time",
        "breaker_low",
        "breaker_high",
    ):
        value = execution_state.get(key)
        if value is not None:
            hydrated[key] = value

    hydrated["stage"] = execution_state.get(
        "stage",
        hydrated.get("stage"),
    )

    required = (
        hydrated.get("bos_time"),
        hydrated.get("bos_close"),
        hydrated.get("breaker_time"),
        hydrated.get("breaker_low"),
        hydrated.get("breaker_high"),
    )

    if any(value is None for value in required):
        bos, breaker = find_valid_bos_and_breaker(
            candles,
            hydrated,
            current_index,
        )

        if bos is not None and breaker is not None:
            hydrated["stage"] = "WAIT_RETEST"
            hydrated["bos_time"] = candles[bos["index"]]["time"]
            hydrated["bos_close"] = bos["close"]
            hydrated["breaker_time"] = candles[breaker["index"]]["time"]
            hydrated["breaker_low"] = float(breaker["low"])
            hydrated["breaker_high"] = float(breaker["high"])

    missing = [
        key
        for key in (
            "bos_time",
            "bos_close",
            "breaker_time",
            "breaker_low",
            "breaker_high",
        )
        if hydrated.get(key) is None
    ]

    if missing:
        raise RuntimeError(
            "EXECUTION_STATE_INCOMPLETE: "
            f"missing={missing} | setup={hydrated}"
        )

    if hydrated.get("stage") not in {"WAIT_RETEST", "COMPLETE"}:
        raise RuntimeError(
            "EXECUTION_STATE_INVALID_STAGE: "
            f"stage={hydrated.get('stage')} | setup={hydrated}"
        )

    return hydrated


# ============================================================
# PROCESS ALL ACTIVE SETUPS EVERY POLL
# ============================================================

def process_all_active_setups(data, state, h4_trend=None, silent=False, allow_new_entries=True, daily_view=None):
    candles = data["candles"]
    current_tick = data["current_tick"]
    symbol_info = data["symbol_info"]
    current_index = len(candles) - 1
    current_time = candles[current_index]["time"]

    # V18 safety barrier: deduplicate before any completion can reach the executor.
    state["active_setups"] = deduplicate_active_setups(
        state.get("active_setups", [])
    )

    remaining = []
    completions = []

    for raw_setup in list(state["active_setups"]):
        setup = normalize_setup(raw_setup)

        status, info = advance_setup(
            candles=candles,
            current_index=current_index,
            setup=setup,
            current_tick=current_tick,
            symbol_info=symbol_info,
            state=state,
            allow_trade=True,
            silent=silent,
            recovery_max_age_minutes=NORMAL_RECOVERY_RETEST_AGE_MINUTES,
        )

        if status == "KEEP":
            remaining.append(setup)
            continue

        if status == "EXPIRE":
            state["trade_history"].append({
                "id": setup["id"],
                "status": info.get("status", "EXPIRED") if info else "EXPIRED",
                "direction": setup["direction"],
                "time": current_time,
            })
            continue

        if status == "DROP":
            state["trade_history"].append({
                "id": setup["id"],
                "status": info.get("status", "DATA_GAP") if info else "DATA_GAP",
                "direction": setup["direction"],
                "time": current_time,
            })
            continue

        if status == "COMPLETE":
            # The setup object returned by advance_setup() is normally already
            # enriched. Hydrate it explicitly before it enters the execution
            # queue so a stale WAIT_BOS seed can never be submitted.
            execution_setup = hydrate_execution_setup(
                setup=setup,
                info=info,
                candles=candles,
                current_index=current_index,
            )
            remaining.append(execution_setup)
            completions.append((execution_setup, info))
            continue

        remaining.append(setup)

    state["active_setups"] = deduplicate_active_setups(remaining)

    # Execute qualifying setups after primary-feed validation and daily-view checks.
    # Account-level entry gates remain enforced inside execute_setup().

    for setup, info in completions:
        if not allow_new_entries:
            retest_time = (info or {}).get("retest_time")
            if setup.get("last_shadow_gate_blocked_retest") != retest_time:
                print(
                    f"[NEW ENTRY BLOCKED] {setup['id']} | "
                    "entry gate is not clear; setup retained for fresh retry window."
                )
                setup["last_shadow_gate_blocked_retest"] = retest_time
            continue

        view_allowed, view_reason = daily_view_direction_allowed(setup.get("direction"), daily_view)
        if not view_allowed:
            retest_time = (info or {}).get("retest_time")
            if setup.get("last_daily_view_blocked_retest") != retest_time:
                print(f"[DAILY VIEW BLOCK] {setup['id']} | {view_reason}")
                audit_event("DAILY_VIEW_ENTRY_BLOCK", {
                    "setup_id": setup.get("id"),
                    "direction": setup.get("direction"),
                    "reason": view_reason,
                    "regime": (daily_view or {}).get("regime"),
                    "market_time": current_time,
                })
                setup["last_daily_view_blocked_retest"] = retest_time
            remaining.append(setup)
            continue

        try:
            print(
                f"[EXECUTION STATE] id={setup.get('id')} | "
                f"stage={setup.get('stage')} | "
                f"bos_time={setup.get('bos_time')} | "
                f"breaker_time={setup.get('breaker_time')} | "
                f"breaker_low={setup.get('breaker_low')} | "
                f"breaker_high={setup.get('breaker_high')}"
            )

            result = execute_setup(
                setup=setup,
                current_tick=current_tick,
                symbol_info=symbol_info,
                market_time=current_time,
                h4_trend=h4_trend,
            )

            trade_status = (
                "TRADE_ATTEMPTED"
                if result.get("status") not in {"RETRY_COOLDOWN", "ALREADY_ATTEMPTED"}
                else result.get("status")
            )

            state["trade_history"].append({
                "id": setup["id"],
                "status": trade_status,
                "direction": setup["direction"],
                "time": current_time,
                "retest_time": info.get("retest_time") if info else None,
                "result": result,
                "reaction_triggered": bool(setup.get("reaction_triggered")),
                "reaction_reason": setup.get("reaction_reason"),
            })
            if result.get("status") not in {"RETRY_COOLDOWN", "ALREADY_ATTEMPTED"}:
                state["last_order_time"] = current_time

                # Remove only after an actual submission result.
                state["active_setups"] = [
                    item
                    for item in state["active_setups"]
                    if item.get("id") != setup["id"]
                ]

                if not silent:
                    print(
                        f"[SETUP CLOSED] {setup['id']} -> TRADE_ATTEMPTED"
                    )
            else:
                if not silent:
                    print(
                        f"[SETUP RETAINED] {setup['id']} -> {result.get('status')}"
                    )

        except Exception as error:
            if str(error).startswith("H4_STALE_BLOCK:"):
                state["trade_history"].append({"id":setup["id"],"status":"H4_STALE_BLOCK","direction":setup["direction"],"time":current_time,"error":str(error)})
                print(f"[SETUP BLOCKED] {setup['id']} | {error}")
                continue

            # V20 acceptance failure: the setup reached a complete pattern,
            # but execution price moved too far beyond the breaker before the
            # order could be submitted. Retire it rather than chasing it.
            if is_retest_acceptance_error(error):
                setup["order_attempted"] = True
                setup["execution_status"] = "RETEST_ACCEPTANCE_REJECTED"
                setup["last_order_error"] = str(error)
                setup["last_order_error_time"] = current_time
                state["trade_history"].append({
                    "id": setup["id"],
                    "status": "RETEST_ACCEPTANCE_REJECTED",
                    "direction": setup["direction"],
                    "time": current_time,
                    "error": str(error),
                })
                state["active_setups"] = [
                    item for item in state["active_setups"]
                    if item.get("id") != setup["id"]
                ]
                print(
                    f"[SETUP REJECTED] {setup['id']} | "
                    "retest acceptance failed; no chase and no retry."
                )
                continue

            # Once price crosses the intended breaker-derived stop, the
            # setup is no longer executable at the original retest. Do not
            # retry it every poll; retire it immediately and wait for a new
            # independent setup.
            if is_invalid_risk_distance_error(error):
                setup["order_attempted"] = True
                setup["execution_status"] = "INVALIDATED_PRICE"
                setup["last_order_error"] = str(error)
                setup["last_order_error_time"] = current_time

                state["trade_history"].append({
                    "id": setup["id"],
                    "status": "INVALIDATED_PRICE",
                    "direction": setup["direction"],
                    "time": current_time,
                    "error": str(error),
                })

                print(
                    f"[SETUP INVALIDATED] {setup['id']} | "
                    "price moved through the breaker-derived stop; no retry."
                )
                continue

            # A margin failure is a broker/account capacity condition, not a
            # transient transport error. The setup must not be spam-retried and
            # must not execute later after the original retest has gone stale.
            if is_insufficient_margin_error(error):
                setup["order_attempted"] = True
                setup["execution_status"] = "MARGIN_BLOCKED"
                setup["last_order_error"] = str(error)
                setup["last_order_error_time"] = current_time

                state["trade_history"].append({
                    "id": setup["id"],
                    "status": "MARGIN_BLOCKED",
                    "direction": setup["direction"],
                    "time": current_time,
                    "error": str(error),
                })

                state["active_setups"] = [
                    item
                    for item in state["active_setups"]
                    if item.get("id") != setup["id"]
                ]
                print(
                    f"[SETUP BLOCKED] {setup['id']} | "
                    "Insufficient MT5 margin; no retry for this retest."
                )
                continue

            # Preserve the completed setup for genuine transient execution/data
            # errors such as temporary bridge connectivity.
            setup["order_attempted"] = False
            setup["execution_status"] = "EXECUTION_RETRY"
            setup["last_order_error"] = str(error)
            setup["last_order_error_time"] = current_time

            state["trade_history"].append({
                "id": setup["id"],
                "status": "EXECUTION_RETRY",
                "direction": setup["direction"],
                "time": current_time,
                "error": str(error),
            })

            if not any(
                item.get("id") == setup["id"]
                for item in state["active_setups"]
            ):
                state["active_setups"].append(setup)

            print(
                f"[ORDER RETRY QUEUED] {setup['id']} | "
                f"{type(error).__name__}: {error}"
            )


# ============================================================
# POLL WATCHERS
# ============================================================

def record_poll_watch(state, data):
    candles = data["candles"]
    latest = candles[-1]
    state["poll_number"] = int(state.get("poll_number", 0)) + 1

    watch = {
        "poll_number": state["poll_number"],
        "poll_time": now_utc_iso(),
        "candle_time": latest["time"],
        "BUY": {
            "stage": "WATCH_SWEEP_BOS_BREAKER_RETEST",
            "direction": "BUY",
            "price": float(data["current_tick"]["ask"]),
        },
        "SELL": {
            "stage": "WATCH_SWEEP_BOS_BREAKER_RETEST",
            "direction": "SELL",
            "price": float(data["current_tick"]["bid"]),
        },
    }

    state["poll_watches"].append(watch)
    state["poll_watches"] = state["poll_watches"][-POLL_WATCH_HISTORY:]

    print(
        f"[POLL WATCH] #{state['poll_number']} | "
        f"BUY + SELL monitored | "
        f"M1={latest['time']} | "
        f"active={len(state['active_setups'])}"
    )


# ============================================================
# PERSISTENT BUY / SELL SETUP WATCHERS
# ============================================================
# These are deliberate monitoring states, not fake trade signals.
# They guarantee that BUY and SELL are continuously represented in
# the state machine even when there is no live sweep yet.

def ensure_direction_watchers(state):
    watchers = state.setdefault("direction_watchers", {})

    for direction in ("BUY", "SELL"):
        watchers.setdefault(
            direction,
            {
                "direction": direction,
                "stage": "WATCH_SWEEP",
                "polls_seen": 0,
                "last_poll_time": None,
                "last_candle_time": None,
                "liquidity_level": None,
                "note": "CONTINUOUSLY MONITORING",
            },
        )

    return watchers

def update_direction_watchers(state, data, m15_context=None, verbose=True):
    """Update permanent BUY/SELL watchers on every poll, including M15 context."""
    watchers = ensure_direction_watchers(state)
    candles = data["candles"]
    latest = candles[-1]
    poll_time = now_utc_iso()

    swing_highs, swing_lows = find_swing_points(candles)
    recent_low = swing_lows[-1] if swing_lows else None
    recent_high = swing_highs[-1] if swing_highs else None

    buy = watchers["BUY"]
    buy["polls_seen"] = int(buy.get("polls_seen", 0)) + 1
    buy["last_poll_time"] = poll_time
    buy["last_candle_time"] = latest["time"]
    buy["stage"] = "WATCH_M15_SUPPORT_TO_M1_SWEEP"
    buy["liquidity_level"] = float(recent_low["price"]) if recent_low else None

    sell = watchers["SELL"]
    sell["polls_seen"] = int(sell.get("polls_seen", 0)) + 1
    sell["last_poll_time"] = poll_time
    sell["last_candle_time"] = latest["time"]
    sell["stage"] = "WATCH_M15_RESISTANCE_TO_M1_SWEEP"
    sell["liquidity_level"] = float(recent_high["price"]) if recent_high else None

    if m15_context:
        buy_zone = m15_context.get("support_zones", [])
        sell_zone = m15_context.get("resistance_zones", [])
        buy["m15_zone"] = buy_zone[0] if buy_zone else None
        sell["m15_zone"] = sell_zone[0] if sell_zone else None
    else:
        buy["m15_zone"] = None
        sell["m15_zone"] = None

    if verbose:
        buy_level = f"{buy['liquidity_level']:.2f}" if buy["liquidity_level"] is not None else "none"
        sell_level = f"{sell['liquidity_level']:.2f}" if sell["liquidity_level"] is not None else "none"
        buy_center = (
            f"{buy['m15_zone']['center']:.2f}"
            if buy.get("m15_zone") else "none"
        )
        sell_center = (
            f"{sell['m15_zone']['center']:.2f}"
            if sell.get("m15_zone") else "none"
        )
        print(
            f"[SETUP MONITOR] BUY=M15_SUPPORT({buy_center}) -> M1_SWEEP({buy_level}) | "
            f"SELL=M15_RESISTANCE({sell_center}) -> M1_SWEEP({sell_level}) | "
            f"active_setups={len(state['active_setups'])}"
        )


def count_recent_sweep_candidates(candles, m15_context=None, bars=20):
    """Diagnostic census: raw M1 sweeps versus M15-aligned sweeps."""
    if not candles:
        return {
            "raw_buy": 0,
            "raw_sell": 0,
            "aligned_buy": 0,
            "aligned_sell": 0,
        }

    start = max(1, len(candles) - bars)
    counts = {
        "raw_buy": 0,
        "raw_sell": 0,
        "aligned_buy": 0,
        "aligned_sell": 0,
    }

    for index in range(start, len(candles)):
        # Raw detector census, independent of M15.
        history = candles[: index + 1]
        swing_highs, swing_lows = find_swing_points(history)
        latest_index = len(history) - 1

        bullish = find_bullish_sweep(
            history, latest_index, swing_lows
        )
        bearish = find_bearish_sweep(
            history, latest_index, swing_highs
        )

        if bullish:
            counts["raw_buy"] += 1
            if m15_context_for_setup(
                "BUY", float(bullish["liquidity"]), m15_context
            ) is not None:
                counts["aligned_buy"] += 1

        if bearish:
            counts["raw_sell"] += 1
            if m15_context_for_setup(
                "SELL", float(bearish["liquidity"]), m15_context
            ) is not None:
                counts["aligned_sell"] += 1

    return counts


# ============================================================
# WARMUP
# ============================================================

def warmup_state(candles, m15_context=None):
    print()
    print("[WARMUP] Reconstructing unfinished setups...")

    state = empty_state()

    if len(candles) < 20:
        print("[WARMUP] Not enough candles.")
        return state

    # Scan a broad recent window for unfinished seeds.
    start = max(20, len(candles) - POLL_DISCOVERY_BARS)

    for index in range(start, len(candles)):
        seeds = detect_setup_seeds_for_index(candles, index, m15_context)
        register_setups(state, seeds, verbose=False)

    # Re-evaluate each active setup on the latest market state WITHOUT
    # sending historical trades.
    current_index = len(candles) - 1
    current_time = candles[current_index]["time"]

    remaining = []

    for raw_setup in state["active_setups"]:
        setup = normalize_setup(raw_setup)
        status, info = advance_setup(
            candles=candles,
            current_index=current_index,
            setup=setup,
            current_tick={"bid": 0.0, "ask": 0.0},
            symbol_info={
                "contract_size": 100.0,
                "volume_min": 0.01,
                "volume_max": 100.0,
                "volume_step": 0.01,
            },
            state=state,
            allow_trade=False,
            silent=True,
            recovery_max_age_minutes=0,
        )

        if status in ("KEEP", "COMPLETE"):
            remaining.append(setup)
        else:
            # Historical expiries are not tradeable but are recorded to
            # prevent noisy re-creation during the same warmup.
            state["trade_history"].append({
                "id": setup["id"],
                "status": info.get("status", "HISTORICAL_EXPIRED") if info else "HISTORICAL_EXPIRED",
                "direction": setup["direction"],
                "time": current_time,
            })

    state["active_setups"] = deduplicate_active_setups(remaining)
    state["last_processed_candle"] = current_time
    state["session_start_time"] = current_time
    state["trade_history"] = state["trade_history"][-MAX_TRADE_HISTORY:]

    print(
        f"[WARMUP COMPLETE] Unfinished setups recovered: "
        f"{len(state['active_setups'])}"
    )
    return state


# ============================================================
# V17 FAST COMPLETE-SETUP OPPORTUNITY SCAN
# ============================================================

def execute_fast_complete_setups(data, state, h4_trend=None, m15_context=None, allow_new_entries=True, daily_view=None):
    """Detect and execute very recent fully-formed setups every poll.

    This is an opportunity-recognition layer only. It does not alter the
    existing stop, BE+, trailing, or position-management rules. It reuses the
    same source detector and the same SWEEP -> BOS -> BREAKER -> RETEST pattern
    and is limited to very recent retests to avoid chasing stale moves.
    """
    if not FAST_COMPLETE_SCAN_ENABLED:
        return 0

    if not allow_new_entries:
        print("[ENTRY GATE] FAST opportunity execution blocked.")
        return 0

    candles = data["candles"]
    current_tick = data["current_tick"]
    now_time = candles[-1]["time"]
    now_dt = parse_time(now_time)
    if now_dt is None or len(candles) < 20:
        return 0

    try:
        scan_candles = candles[-FAST_COMPLETE_SCAN_BARS:]
        swing_highs, swing_lows = find_swing_points(scan_candles)
        complete_setups = scan_setups(scan_candles, swing_highs, swing_lows)
    except Exception as error:
        audit_event("FAST_COMPLETE_SCAN_ERROR", {
            "error": str(error),
            "market_time": now_time,
        })
        print(f"[FAST OPPORTUNITY SCAN ERROR] {type(error).__name__}: {error}")
        return 0

    active_ids = {item.get("id") for item in state.get("active_setups", [])}
    terminal_ids = known_terminal_ids(state)
    recent = []

    for complete in complete_setups:
        direction = complete.get("direction")
        retest_index = int(complete["retest"]["index"])
        if retest_index < 0 or retest_index >= len(scan_candles):
            continue

        retest_time = scan_candles[retest_index]["time"]
        retest_dt = parse_time(retest_time)
        if retest_dt is None:
            continue
        age_seconds = (now_dt - retest_dt).total_seconds()
        if age_seconds < 0 or age_seconds > FAST_COMPLETE_MAX_RETEST_AGE_MINUTES * 60:
            continue

        sweep_time = scan_candles[int(complete["sweep"]["index"])]["time"]
        sweep_dt = parse_time(sweep_time)
        if sweep_dt is None:
            continue
        origin_age_seconds = (now_dt - sweep_dt).total_seconds()
        if origin_age_seconds < 0 or origin_age_seconds > SETUP_MAX_ORIGIN_AGE_MINUTES * 60:
            continue

        setup_id = make_setup_id(direction, sweep_time)
        if setup_id in active_ids or setup_id in terminal_ids:
            continue

        liquidity = float(complete["sweep"]["liquidity"])
        m15_match = m15_context_for_setup(direction, liquidity, m15_context)
        if M15_CONTEXT_REQUIRED and m15_match is None:
            continue

        if direction == "BUY":
            structure = structure_high_before_sweep(swing_highs, int(complete["sweep"]["index"]))
        else:
            structure = structure_low_before_sweep(swing_lows, int(complete["sweep"]["index"]))

        setup = create_setup(
            direction=direction,
            sweep={
                "liquidity": liquidity,
                "sweep_price": float(complete["sweep"]["sweep_price"]),
            },
            structure=structure,
            candle=scan_candles[int(complete["sweep"]["index"])],
            m15_context=m15_match,
        )
        setup["id"] = setup_id
        setup["stage"] = "WAIT_RETEST"
        setup["bos_time"] = scan_candles[int(complete["bos"]["index"])]["time"]
        setup["bos_close"] = float(complete["bos"]["close"])
        setup["breaker_time"] = scan_candles[int(complete["breaker"]["index"])]["time"]
        setup["breaker_low"] = float(complete["breaker"]["low"])
        setup["breaker_high"] = float(complete["breaker"]["high"])
        setup["retest_time"] = retest_time

        # A reaction watch can raise priority, but a fresh market setup does
        # not need an active position or a stress trigger to be eligible.
        setup = mark_reaction_setup(setup, state, now_time)

        if has_structural_duplicate(setup, state.get("active_setups", [])):
            print(
                f"[FAST SETUP DEDUP] {setup_id} | "
                "same structural event already active; skipping duplicate fast candidate."
            )
            continue

        if has_structural_duplicate(setup, [item[0] for item in recent]):
            print(
                f"[FAST SETUP DEDUP] {setup_id} | "
                "duplicate complete setup in the same scan; keeping one candidate."
            )
            continue

        recent.append((setup, age_seconds))

    recent.sort(key=lambda item: item[1])
    executed = 0

    for setup, age_seconds in recent[:FAST_COMPLETE_MAX_ORDERS_PER_POLL]:
        print()
        print("=" * 70)
        print("FAST OPPORTUNITY EXECUTION")
        print("=" * 70)
        print(f"Setup:          {setup['id']}")
        print(f"Direction:      {setup['direction']}")
        print(f"Retest age:     {age_seconds / 60.0:.2f} min")
        print(f"M15 context:    {setup.get('m15_context')}")
        print("Recognition:    FRESH COMPLETE SWEEP -> BOS -> BREAKER -> RETEST")
        print("Protection:     UNCHANGED")

        audit_event("FAST_COMPLETE_SETUP_DETECTED", {
            "setup_id": setup.get("id"),
            "direction": setup.get("direction"),
            "retest_time": setup.get("retest_time"),
            "retest_age_seconds": round(age_seconds, 1),
            "m15_context": setup.get("m15_context"),
            "reaction_triggered": bool(setup.get("reaction_triggered")),
        })

        view_allowed, view_reason = daily_view_direction_allowed(setup.get("direction"), daily_view)
        if not view_allowed:
            print(f"[DAILY VIEW BLOCK] {setup['id']} | {view_reason}")
            audit_event("FAST_DAILY_VIEW_ENTRY_BLOCK", {
                "setup_id": setup.get("id"),
                "direction": setup.get("direction"),
                "reason": view_reason,
                "regime": (daily_view or {}).get("regime"),
                "market_time": now_time,
            })
            continue

        try:
            print(f"[DAILY VIEW] {setup['id']} | horizon={daily_view_horizon(setup.get('direction'), daily_view)} | regime={(daily_view or {}).get('regime')}")
            result = execute_setup(
                setup=setup,
                current_tick=current_tick,
                symbol_info=data["symbol_info"],
                market_time=now_time,
                h4_trend=h4_trend,
            )
            state["trade_history"].append({
                "id": setup["id"],
                "status": "FAST_TRADE_ATTEMPTED",
                "direction": setup["direction"],
                "time": now_time,
                "retest_time": setup.get("retest_time"),
                "result": result,
                "reaction_triggered": bool(setup.get("reaction_triggered")),
                "reaction_reason": setup.get("reaction_reason"),
            })
            if result.get("status") not in {"RETRY_COOLDOWN", "ALREADY_ATTEMPTED"}:
                state["last_order_time"] = now_time
                executed += 1
                audit_event("FAST_COMPLETE_SETUP_EXECUTED", {
                    "setup_id": setup.get("id"),
                    "direction": setup.get("direction"),
                    "result": result,
                })
                print(f"[FAST OPPORTUNITY] {setup['id']} -> {result.get('status')}")
            else:
                print(f"[FAST OPPORTUNITY RETAINED] {setup['id']} -> {result.get('status')}")
        except Exception as error:
            if is_retest_acceptance_error(error):
                state["trade_history"].append({
                    "id": setup["id"],
                    "status": "RETEST_ACCEPTANCE_REJECTED",
                    "direction": setup["direction"],
                    "time": now_time,
                    "error": str(error),
                })
                audit_event("FAST_RETEST_ACCEPTANCE_REJECTED", {
                    "setup_id": setup.get("id"),
                    "direction": setup.get("direction"),
                    "error": str(error),
                })
                print(
                    f"[FAST OPPORTUNITY REJECTED] {setup['id']} | "
                    "retest acceptance failed; no chase and no retry."
                )
                continue

            if is_insufficient_margin_error(error):
                state["trade_history"].append({
                    "id": setup["id"],
                    "status": "MARGIN_BLOCKED",
                    "direction": setup["direction"],
                    "time": now_time,
                    "error": str(error),
                })
                print(
                    f"[FAST OPPORTUNITY BLOCKED] {setup['id']} | "
                    "Insufficient MT5 margin; no retry for this retest."
                )
                continue

            audit_event("FAST_COMPLETE_SETUP_ERROR", {
                "setup_id": setup.get("id"),
                "direction": setup.get("direction"),
                "error": str(error),
            })
            print(f"[FAST OPPORTUNITY BLOCKED] {setup['id']} | {error}")

    return executed


# ============================================================
# 30-MINUTE CRITICAL RECOVERY
# ============================================================

def critical_review(data, state, m15_context=None, allow_new_entries=True, daily_view=None):
    candles = data["candles"]
    current_tick = data["current_tick"]
    symbol_info = data["symbol_info"]
    now_time = candles[-1]["time"]

    state["last_critical_review"] = now_time

    print()
    print("=" * 70)
    print("CRITICAL 30-MINUTE REVIEW")
    print("=" * 70)
    print(
        f"Active setups before review: {len(state['active_setups'])}"
    )
    if m15_context:
        print(
            f"M15 context price: {m15_context['price']:.2f} | "
            f"support_zones={len(m15_context['support_zones'])} | "
            f"resistance_zones={len(m15_context['resistance_zones'])}"
        )

    recovered = discover_recent_setups(
        candles,
        state,
        m15_context,
        CRITICAL_RESCAN_BARS,
    )

    register_setups(state, recovered, verbose=True)

    # First, force a complete re-evaluation of every currently active setup.
    process_all_active_setups(
        data=data,
        state=state,
        silent=False,
        allow_new_entries=allow_new_entries,
        daily_view=daily_view,
    )

    # Second, inspect the source detector for very recent COMPLETE setups.
    # This is recovery only; it does not invent a new trade pattern.
    try:
        swing_highs, swing_lows = find_swing_points(candles)
        complete_setups = scan_setups(
            candles,
            swing_highs,
            swing_lows,
        )
    except Exception as error:
        print(
            f"[CRITICAL SOURCE SCAN ERROR] "
            f"{type(error).__name__}: {error}"
        )
        complete_setups = []

    blocked = known_terminal_ids(state)
    cutoff = parse_time(now_time) - timedelta(
        minutes=CRITICAL_MAX_RETEST_AGE_MINUTES
    )

    for complete in complete_setups:
        retest_time = candles[
            complete["retest"]["index"]
        ]["time"]
        retest_dt = parse_time(retest_time)

        if retest_dt is None or retest_dt < cutoff:
            continue

        setup_id = make_setup_id(
            complete["direction"],
            candles[complete["sweep"]["index"]]["time"],
        )

        if setup_id in blocked:
            continue

        m15_match = m15_context_for_setup(
            complete["direction"],
            float(complete["sweep"]["liquidity"]),
            m15_context,
        )

        if M15_CONTEXT_REQUIRED and m15_match is None:
            print(
                f"[CRITICAL SKIP] {setup_id} has no valid M15 context."
            )
            continue

        setup = create_setup(
            direction=complete["direction"],
            sweep={
                "liquidity": complete["sweep"]["liquidity"],
                "sweep_price": complete["sweep"]["sweep_price"],
            },
            structure=(
                structure_high_before_sweep(
                    swing_highs,
                    complete["sweep"]["index"],
                )
                if complete["direction"] == "BUY"
                else structure_low_before_sweep(
                    swing_lows,
                    complete["sweep"]["index"],
                )
            ),
            candle=candles[complete["sweep"]["index"]],
            m15_context=m15_match,
        )

        setup["id"] = setup_id
        setup["stage"] = "WAIT_RETEST"
        setup["bos_time"] = candles[complete["bos"]["index"]]["time"]
        setup["bos_close"] = complete["bos"]["close"]
        setup["breaker_time"] = candles[complete["breaker"]["index"]]["time"]
        setup["breaker_low"] = float(complete["breaker"]["low"])
        setup["breaker_high"] = float(complete["breaker"]["high"])

        print(
            f"[CRITICAL RECOVERY] Recent complete setup {setup_id} "
            f"found; attempting order."
        )

        if not allow_new_entries:
            print(
                f"[CRITICAL ENTRY GATE] {setup_id} | "
                "entry gate not clear; no new order."
            )
            continue

        view_allowed, view_reason = daily_view_direction_allowed(setup.get("direction"), daily_view)
        if not view_allowed:
            print(f"[CRITICAL DAILY VIEW BLOCK] {setup_id} | {view_reason}")
            continue

        print(f"[V23 M15 ORDER READY] {opportunity['id']} | sending to common executor")
        try:
            result = execute_setup(
                setup=setup,
                current_tick=current_tick,
                symbol_info=symbol_info,
                market_time=now_time,
            )

            state["trade_history"].append({
                "id": setup_id,
                "status": "CRITICAL_RECOVERY_TRADE",
                "direction": setup["direction"],
                "time": now_time,
                "retest_time": retest_time,
                "result": result,
            })
            state["last_order_time"] = now_time
            blocked.add(setup_id)

        except Exception as error:
            if is_retest_acceptance_error(error):
                state["trade_history"].append({
                    "id": setup_id,
                    "status": "RETEST_ACCEPTANCE_REJECTED",
                    "direction": setup["direction"],
                    "time": now_time,
                    "error": str(error),
                })
                blocked.add(setup_id)
                print(
                    f"[CRITICAL RECOVERY REJECTED] {setup_id} | "
                    "retest acceptance failed; no chase and no retry."
                )
            elif is_insufficient_margin_error(error):
                state["trade_history"].append({
                    "id": setup_id,
                    "status": "MARGIN_BLOCKED",
                    "direction": setup["direction"],
                    "time": now_time,
                    "error": str(error),
                })
                blocked.add(setup_id)
                print(
                    f"[CRITICAL RECOVERY BLOCKED] {setup_id} | "
                    "Insufficient MT5 margin; no retry for this retest."
                )
            else:
                state["trade_history"].append({
                    "id": setup_id,
                    "status": "CRITICAL_RECOVERY_ORDER_ERROR",
                    "direction": setup["direction"],
                    "time": now_time,
                    "error": str(error),
                })
                print(
                    f"[CRITICAL RECOVERY ERROR] "
                    f"{type(error).__name__}: {error}"
                )

    state["active_setups"] = [
        setup
        for setup in deduplicate_active_setups(state["active_setups"])
        if setup.get("id") not in blocked
    ]

    print(
        f"[CRITICAL REVIEW COMPLETE] "
        f"active={len(state['active_setups'])}"
    )
    print("=" * 70)


# ============================================================
# DISPLAY
# ============================================================

def print_active_setups(active_setups):
    if not active_setups:
        print("[TRADE SETUPS] none")
        return

    print(f"[TRADE SETUPS] {len(active_setups)}")

    for setup in active_setups:
        print(
            f"  {setup['id']} | "
            f"{setup['direction']} | "
            f"{setup['stage']} | "
            f"sweep={setup['sweep_time']}"
        )


def print_header():
    print("=" * 70)
    print("XAUUSD M15 STRUCTURE -> M1 EXECUTION ENGINE v28.5 BALANCED DEMO")
    print("=" * 70)
    print(f"Symbol:          {SYMBOL}")
    print(f"Polling:         {POLL_SECONDS}s")
    print("Mode:            BALANCED M15 OPPORTUNITY SCAN (DEMO ONLY)")
    print("Architecture:    H4 CONTEXT -> M15 SETUP -> M1 EXECUTION")
    print("Setup generator: M15 ONLY")
    print("M1 role:         EXECUTION CONFIRMATION ONLY")
    print("Strict M1 lane:  DISABLED")
    print("Fast scan lane:  DISABLED")
    print("Reaction lane:   DISABLED")
    print(f"M15 move min:    {M15_OPPORTUNITY_MIN_MOVE:.2f}")
    print(f"M15 zone max:    {M15_OPPORTUNITY_ZONE_MAX_DISTANCE:.2f}")
    print(f"M15 reversal min:{M15_OPPORTUNITY_REVERSAL_BODY_MIN:.2f}")
    print(f"M15 reclaim min: {M15_OPPORTUNITY_RECLAIM_FRACTION:.0%}")
    print(f"M15 zone touches:{V28_MIN_ZONE_TOUCHES}+ required")
    print(f"M1 body min:     {M15_OPPORTUNITY_M1_MIN_BODY:.2f}")
    print(f"M1 break lookback:{M15_OPPORTUNITY_M1_BREAK_LOOKBACK} bars")
    print(f"Entry cooldown:  {V28_ENTRY_COOLDOWN_MINUTES:.1f} min")
    print(f"Opposite cooldown:{V28_OPPOSITE_DIRECTION_COOLDOWN_MINUTES:.1f} min")
    print("One entry/M15 bar: ENABLED")
    print("H4 direction gate: BIAS FIRST; counter-H4 setups still face M15 checks")
    print(f"Daily view hard gate: {'ENABLED' if DAILY_VIEW_ENTRY_GATE_ENABLED else 'DISABLED (context only)'}")
    print("Secondary shadow feed: DISABLED (primary MT5 bridge only)")
    print("Risk mode:       CONTROLLED DEMO | TRADE + DAILY DRAWDOWN CAPS")
    print(f"Risk cap/trade:  {MAX_RISK_PER_TRADE_PERCENT:.1%} nominal estimate; stop never narrowed")
    print(f"Daily loss cap:  DISABLED (configured {DAILY_LOSS_LIMIT_PERCENT:.1%}; no daily stop enforced)")
    print(f"Initial SL:      {INITIAL_SL_DISTANCE:.2f} price units")
    print(f"R:R:             {RR_RATIO}:1")
    print(f"Broker volume:   minimum/fixed {FIXED_VOLUME:.2f} lots")
    print("Risk enforcement: nominal per-trade cap + one-position limit; DAILY LOSS STOP DISABLED")
    print("Goal:            reduce repeated/local churn before further testing")
    print("=" * 70)


# ============================================================
# V21 REAL-BROKER SHADOW CONFIRMATION
# ============================================================

def _shadow_headers():
    key = os.environ.get("MT5_SHADOW_BRIDGE_API_KEY") or os.environ.get("MT5_BRIDGE_API_KEY")
    if not key:
        raise RuntimeError("MT5_SHADOW_BRIDGE_API_KEY / MT5_BRIDGE_API_KEY is not set")
    return {"x-api-key": key}


def _shadow_get_market(timeframe, bars):
    response = requests.get(
        f"{SHADOW_BRIDGE_URL}/market",
        headers=_shadow_headers(),
        params={
            "symbol": SHADOW_SYMBOL,
            "timeframe": timeframe,
            "bars": bars,
        },
        timeout=SHADOW_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _market_tick_age_seconds(market_data, now_dt):
    tick = (market_data or {}).get("current_tick") or {}
    tick_time = parse_time(tick.get("time"))
    if tick_time is None or now_dt is None:
        return None
    return max(0.0, (now_dt - tick_time).total_seconds())


def _latest_candle_age_seconds(market_data, now_dt):
    candles = (market_data or {}).get("candles") or []
    if not candles or now_dt is None:
        return None
    latest = parse_time(candles[-1].get("time"))
    if latest is None:
        return None
    return max(0.0, (now_dt - latest).total_seconds())


def _net_move_pct(candles, lookback=5):
    if not candles or len(candles) < lookback:
        return None
    window = candles[-lookback:]
    first_open = float(window[0]["open"])
    last_close = float(window[-1]["close"])
    if first_open <= 0:
        return None
    return (last_close - first_open) / first_open * 100.0


def _movement_relation(demo_m1, shadow_m1):
    demo_move = _net_move_pct((demo_m1 or {}).get("candles", []), SHADOW_DIRECTIONAL_MOVE_LOOKBACK)
    shadow_move = _net_move_pct((shadow_m1 or {}).get("candles", []), SHADOW_DIRECTIONAL_MOVE_LOOKBACK)
    if demo_move is None or shadow_move is None:
        return "UNKNOWN", demo_move, shadow_move

    threshold = SHADOW_DIRECTIONAL_MOVE_MIN_PCT
    demo_significant = abs(demo_move) >= threshold
    shadow_significant = abs(shadow_move) >= threshold

    if not demo_significant or not shadow_significant:
        return "NEUTRAL", demo_move, shadow_move

    same_direction = (demo_move > 0 and shadow_move > 0) or (demo_move < 0 and shadow_move < 0)
    return ("AGREE" if same_direction else "MISMATCH"), demo_move, shadow_move


def get_shadow_confirmation(demo_m1, demo_m15, demo_h4_data, demo_h4_trend, state, market_time):
    """Read the unfunded real-broker feed and decide whether new entries are allowed."""
    result = {
        "enabled": bool(SHADOW_CONFIRMATION_ENABLED),
        "status": "DISABLED" if not SHADOW_CONFIRMATION_ENABLED else "UNKNOWN",
        "can_new_entries": not SHADOW_CONFIRMATION_ENABLED,
        "reason": "shadow confirmation disabled" if not SHADOW_CONFIRMATION_ENABLED else None,
        "shadow_m1": None,
        "shadow_m15": None,
        "shadow_h4": None,
        "shadow_h4_trend": "UNKNOWN",
        "demo_h4_trend": demo_h4_trend,
        "movement_relation": "UNKNOWN",
        "demo_move_pct": None,
        "shadow_move_pct": None,
    }

    if not SHADOW_CONFIRMATION_ENABLED:
        return result

    # Shadow timestamps come from the independent broker terminal; compare them
    # against the local UTC wall clock, not the demo candle timestamp.
    now_dt = datetime.now(timezone.utc)

    try:
        shadow_m1 = _shadow_get_market("M1", 120)
        shadow_m15 = _shadow_get_market("M15", 200)
        shadow_h4 = _shadow_get_market("H4", 120)

        shadow_h4_trend, shadow_h4_details = determine_h4_trend(shadow_h4["candles"])
        movement, demo_move, shadow_move = _movement_relation(demo_m1, shadow_m1)

        shadow_tick_age = _market_tick_age_seconds(shadow_m1, now_dt)
        shadow_m1_age = _latest_candle_age_seconds(shadow_m1, now_dt)
        demo_tick_age = _market_tick_age_seconds(demo_m1, now_dt)
        demo_m1_age = _latest_candle_age_seconds(demo_m1, now_dt)

        shadow_h4_opposite = (
            SHADOW_H4_OPPOSITE_BLOCK
            and demo_h4_trend in {"BULLISH", "BEARISH"}
            and shadow_h4_trend in {"BULLISH", "BEARISH"}
            and demo_h4_trend != shadow_h4_trend
        )

        freshness_ok = (
            shadow_tick_age is not None
            and shadow_tick_age <= SHADOW_MAX_TICK_AGE_SECONDS
            and shadow_m1_age is not None
            and shadow_m1_age <= SHADOW_MAX_M1_CANDLE_AGE_SECONDS
            and demo_tick_age is not None
            and demo_tick_age <= DEMO_MAX_TICK_AGE_SECONDS
            and demo_m1_age is not None
            and demo_m1_age <= DEMO_MAX_M1_CANDLE_AGE_SECONDS
        )

        movement_ok = movement != "MISMATCH"
        h4_ok = not shadow_h4_opposite
        can_new_entries = freshness_ok and movement_ok and h4_ok

        if can_new_entries:
            status = "PASS"
            reason = "real shadow feed fresh and context compatible"
        elif not freshness_ok:
            status = "BLOCKED_STALE"
            reason = "demo or real shadow feed is stale"
        elif shadow_h4_opposite:
            status = "BLOCKED_H4_DISAGREEMENT"
            reason = f"demo H4={demo_h4_trend} vs shadow H4={shadow_h4_trend}"
        else:
            status = "BLOCKED_MOVEMENT_MISMATCH"
            reason = f"5-bar movement mismatch demo={demo_move:.4f}% shadow={shadow_move:.4f}%"

        result.update({
            "status": status,
            "can_new_entries": can_new_entries,
            "reason": reason,
            "shadow_m1": shadow_m1,
            "shadow_m15": shadow_m15,
            "shadow_h4": shadow_h4,
            "shadow_h4_trend": shadow_h4_trend,
            "shadow_h4_details": shadow_h4_details,
            "movement_relation": movement,
            "demo_move_pct": demo_move,
            "shadow_move_pct": shadow_move,
            "shadow_tick_age_seconds": shadow_tick_age,
            "shadow_m1_age_seconds": shadow_m1_age,
            "demo_tick_age_seconds": demo_tick_age,
            "demo_m1_age_seconds": demo_m1_age,
        })
        state["shadow_last_m1_time"] = ((shadow_m1.get("candles") or [{}])[-1].get("time"))
        state["shadow_last_tick_time"] = ((shadow_m1.get("current_tick") or {}).get("time"))
        state["shadow_last_status"] = status
        return result

    except Exception as error:
        result.update({
            "status": "BLOCKED_SHADOW_UNAVAILABLE",
            "can_new_entries": False,
            "reason": f"shadow confirmation unavailable: {type(error).__name__}: {error}",
        })
        state["shadow_last_status"] = "BLOCKED_SHADOW_UNAVAILABLE"
        print(f"[SHADOW ERROR] {type(error).__name__}: {error}")
        return result


def print_shadow_confirmation(result):
    shadow_m1 = result.get("shadow_m1") or {}
    tick = shadow_m1.get("current_tick") or {}
    shadow_price = tick.get("bid")
    shadow_ask = tick.get("ask")
    m15 = result.get("shadow_m15") or {}
    shadow_m15_price = None
    try:
        shadow_m15_price = float((m15.get("candles") or [])[-1]["close"])
    except Exception:
        pass

    print(
        f"[REAL SHADOW] status={result.get('status')} | "
        f"XAUUSDc bid={shadow_price} ask={shadow_ask} | "
        f"M15_close={shadow_m15_price} | "
        f"H4={result.get('shadow_h4_trend')} | "
        f"movement={result.get('movement_relation')} | "
        f"new_entries={'ENABLED' if result.get('can_new_entries') else 'BLOCKED'}"
    )
    print(
        f"[MARKET INTEGRITY] demo_tick_age={result.get('demo_tick_age_seconds')}s | "
        f"shadow_tick_age={result.get('shadow_tick_age_seconds')}s | "
        f"demo_M1_age={result.get('demo_m1_age_seconds')}s | "
        f"shadow_M1_age={result.get('shadow_m1_age_seconds')}s | "
        f"reason={result.get('reason')}"
    )



# ============================================================
# V23 M15 OPPORTUNITY / REVERSAL ENGINE
# ============================================================
def _m15_zone_near_price(direction, m15_context, reference_price, max_distance=None):
    """Find the nearest M15 S/R zone to a historical candle extreme.

    V23 fix: the zone is evaluated against the M15 impulse/reversal location,
    NOT against the current live price. A valid reversal can therefore be
    detected after price has already bounced away from the zone.
    """
    if not m15_context:
        return None

    zones = m15_context.get(
        "support_zones" if direction == "BUY" else "resistance_zones", []
    )
    limit = M15_OPPORTUNITY_ZONE_MAX_DISTANCE if max_distance is None else float(max_distance)
    candidates = []

    for zone in zones:
        try:
            center = float(zone["center"])
        except (TypeError, ValueError, KeyError):
            continue
        distance = abs(float(reference_price) - center)
        if distance <= limit:
            item = dict(zone)
            item["distance"] = round(distance, 2)
            candidates.append(item)

    if not candidates:
        return None

    candidates.sort(key=lambda z: (z["distance"], -float(z.get("strength", 0.0))))
    return candidates[0]


def _m15_reversal_quality(candle, direction):
    high = float(candle["high"])
    low = float(candle["low"])
    op = float(candle["open"])
    close = float(candle["close"])
    rng = max(high - low, 0.000001)
    body = abs(close - op)

    if body < M15_OPPORTUNITY_REVERSAL_BODY_MIN:
        return 0.0

    if direction == "BUY":
        if close <= op:
            return 0.0
        close_location = (close - low) / rng
    else:
        if close >= op:
            return 0.0
        close_location = (high - close) / rng

    return max(0.0, min(1.0, close_location))


def _m15_impulse(candles, direction, reversal_index):
    """Measure the directional impulse immediately before a reversal candle."""
    start_index = max(0, reversal_index - M15_OPPORTUNITY_MOVE_BARS)
    window = candles[start_index:reversal_index]

    if len(window) < M15_OPPORTUNITY_MOVE_BARS:
        return None

    first_open = float(window[0]["open"])

    if direction == "BUY":
        extreme = min(float(c["low"]) for c in window)
        move = first_open - extreme
    else:
        extreme = max(float(c["high"]) for c in window)
        move = extreme - first_open

    return {
        "move": max(0.0, move),
        "extreme": extreme,
        "first_open": first_open,
        "start_index": start_index,
        "end_index": reversal_index - 1,
    }


def detect_m15_opportunities(m15_data, m15_context):
    """Detect recent M15 displacement INTO S/R, followed by M15 reversal.

    V28.2 keeps the exact V28 strategy thresholds, but adds diagnostics so
    every recent M15 candidate can be accounted for. Only fully qualified
    candidates are returned to the execution layer.
    """
    if not M15_OPPORTUNITY_ENABLED:
        return []

    candles = (m15_data or {}).get("candles") or []
    minimum = M15_OPPORTUNITY_MOVE_BARS + 2
    if len(candles) < minimum:
        print(f"[V28.2 M15 SCAN] insufficient candles={len(candles)} required={minimum}")
        return []

    latest_index = len(candles) - 1
    latest_time = candles[latest_index]["time"]
    first_candidate = max(M15_OPPORTUNITY_MOVE_BARS, latest_index - M15_OPPORTUNITY_LOOKBACK + 1)
    opportunities = []
    stats = {
        "scanned": 0,
        "directional_impulse": 0,
        "zone": 0,
        "touches": 0,
        "reversal": 0,
        "reclaim": 0,
        "age": 0,
        "qualified": 0,
        "buy": 0,
        "sell": 0,
    }

    for reversal_index in range(first_candidate, latest_index + 1):
        reversal = candles[reversal_index]
        reversal_time = reversal.get("time")
        age = minutes_between(reversal_time, latest_time)

        for direction in ("BUY", "SELL"):
            stats["scanned"] += 1

            impulse = _m15_impulse(candles, direction, reversal_index)
            if impulse is None or impulse["move"] < M15_OPPORTUNITY_MIN_MOVE:
                continue
            stats["directional_impulse"] += 1

            zone = _m15_zone_near_price(
                direction,
                m15_context,
                impulse["extreme"],
            )
            if zone is None:
                continue
            stats["zone"] += 1

            if V28_REQUIRE_M15_ZONE_TOUCH and int(zone.get("touches", 0)) < V28_MIN_ZONE_TOUCHES:
                continue
            stats["touches"] += 1

            quality = _m15_reversal_quality(reversal, direction)
            if quality <= 0.0:
                continue
            stats["reversal"] += 1

            high = float(reversal["high"])
            low = float(reversal["low"])
            close = float(reversal["close"])
            rng = max(high - low, 0.000001)

            if direction == "BUY":
                reclaim = (close - low) / rng
            else:
                reclaim = (high - close) / rng

            if reclaim < M15_OPPORTUNITY_RECLAIM_FRACTION:
                continue
            stats["reclaim"] += 1

            # Keep the same 120-minute freshness rule, but reject stale
            # candidates here so the execution layer only receives actionable
            # M15 opportunities.
            if age is None or age < 0 or age > M15_OPPORTUNITY_MAX_AGE_MINUTES:
                continue
            stats["age"] += 1

            opportunity = {
                "id": f"M15REV_{direction}_{reversal['time']}",
                "direction": direction,
                "m15_time": reversal["time"],
                "m15_price": float(m15_context.get("price", close)),
                "m15_zone": zone,
                "displacement": round(impulse["move"], 2),
                "reversal_quality": round(quality, 3),
                "reclaim_fraction": round(reclaim, 3),
                "m15_high": high,
                "m15_low": low,
                "m15_open": float(reversal["open"]),
                "m15_close": close,
                "impulse_extreme": round(impulse["extreme"], 2),
                "impulse_start": candles[impulse["start_index"]]["time"],
                "impulse_end": candles[impulse["end_index"]]["time"],
            }
            opportunities.append(opportunity)
            stats["qualified"] += 1
            stats[direction.lower()] += 1

    opportunities.sort(
        key=lambda x: (x["m15_time"], x["displacement"], x["reversal_quality"]),
        reverse=True,
    )

    print(
        "[V28.2 M15 SCAN] "
        f"bars={latest_index - first_candidate + 1} "
        f"pairs={stats['scanned']} "
        f"impulse={stats['directional_impulse']} "
        f"zone={stats['zone']} "
        f"touches={stats['touches']} "
        f"reversal={stats['reversal']} "
        f"reclaim={stats['reclaim']} "
        f"fresh={stats['age']} "
        f"qualified={stats['qualified']} "
        f"BUY={stats['buy']} SELL={stats['sell']}"
    )

    if opportunities:
        newest = opportunities[0]
        print(
            f"[V28.2 M15 CANDIDATE] {newest['id']} | "
            f"dir={newest['direction']} | age={minutes_between(newest['m15_time'], latest_time):.1f}m | "
            f"move={newest['displacement']:.2f} | "
            f"zone={newest['m15_zone']['center']:.2f} dist={newest['m15_zone']['distance']:.2f} | "
            f"q={newest['reversal_quality']:.3f} | reclaim={newest['reclaim_fraction']:.3f}"
        )
    else:
        print("[V28.2 M15 CANDIDATE] none | no fresh fully-qualified M15 reversal")

    return opportunities

def _m1_opportunity_confirmation(candles, opportunity, now_time=None):
    """Return the newest fresh M1 execution confirmation after an M15 reversal.

    Older qualifying candles are ignored rather than selected and later used
    to terminally expire the opportunity. If no fresh confirmation exists,
    return None so the caller can keep the opportunity waiting.
    """
    if not candles or len(candles) < M15_OPPORTUNITY_M1_BREAK_LOOKBACK + 3:
        return None

    opportunity_time = parse_time(opportunity.get("m15_time"))
    if opportunity_time is None:
        return None

    if now_time is None:
        now_time = candles[-1].get("time")
    now_parsed = parse_time(now_time)
    if now_parsed is None:
        return None

    candidate_indices = []
    for i, candle in enumerate(candles):
        candle_time = parse_time(candle.get("time"))
        if candle_time is None or candle_time <= opportunity_time:
            continue
        age = minutes_between(candle_time, now_parsed)
        if age is None or age < 0 or age > M15_OPPORTUNITY_M1_CONFIRM_MAX_AGE_MINUTES:
            continue
        candidate_indices.append(i)

    if not candidate_indices:
        return None

    # Keep the configured search bound, then inspect newest-to-oldest.
    candidate_indices = candidate_indices[-M15_OPPORTUNITY_M1_CONFIRM_BARS:]
    for i in reversed(candidate_indices):
        if i < M15_OPPORTUNITY_M1_BREAK_LOOKBACK:
            continue
        candle = candles[i]
        body = abs(float(candle["close"]) - float(candle["open"]))
        if body < M15_OPPORTUNITY_M1_MIN_BODY:
            continue

        prior = candles[max(0, i - M15_OPPORTUNITY_M1_BREAK_LOOKBACK):i]
        if not prior:
            continue

        if opportunity["direction"] == "BUY":
            micro_level = max(float(c["high"]) for c in prior)
            valid = (
                float(candle["close"]) > micro_level
                and float(candle["close"]) > float(candle["open"])
            )
        else:
            micro_level = min(float(c["low"]) for c in prior)
            valid = (
                float(candle["close"]) < micro_level
                and float(candle["close"]) < float(candle["open"])
            )

        if valid:
            return {
                "index": i,
                "time": candle["time"],
                "entry_reference": float(candle["close"]),
                "micro_level": micro_level,
                "body": body,
            }
    return None


def _m15_opportunity_to_setup(opportunity, confirmation, current_tick):
    """Build common execution data without inventing a fake breaker."""
    return {
        "id": opportunity["id"],
        "direction": opportunity["direction"],
        "stage": "M15_OPPORTUNITY_CONFIRMED",
        "sweep_time": opportunity["m15_time"],
        "liquidity": float(opportunity["m15_zone"]["center"]),
        "sweep_price": float(opportunity["m15_zone"]["center"]),
        "structure_level": float(confirmation["micro_level"]),
        "bos_time": confirmation["time"],
        "bos_close": confirmation["entry_reference"],
        "breaker_time": None,
        "breaker_low": None,
        "breaker_high": None,
        "order_attempted": False,
        "created_time": opportunity["m15_time"],
        "last_evaluated_candle": confirmation["time"],
        "m15_context": {
            "time": opportunity["m15_time"],
            "zone_type": "SUPPORT" if opportunity["direction"] == "BUY" else "RESISTANCE",
            "zone_center": opportunity["m15_zone"]["center"],
            "zone_lower": opportunity["m15_zone"]["lower"],
            "zone_upper": opportunity["m15_zone"]["upper"],
            "zone_strength": opportunity["m15_zone"].get("strength", 0.0),
            "zone_distance": opportunity["m15_zone"].get("distance", 0.0),
        },
        "reaction_triggered": False,
        "reaction_reason": None,
        "reaction_source_ticket": None,
        "m15_opportunity": True,
        "m15_displacement": opportunity["displacement"],
        "m15_reversal_quality": opportunity["reversal_quality"],
        "m1_confirmation_time": confirmation["time"],
        "m1_confirmation_level": confirmation["micro_level"],
        "m1_confirmation_body": confirmation["body"],
        "opportunity_entry_reference": confirmation["entry_reference"],
        "opportunity_current_tick": dict(current_tick or {}),
    }


def _v28_m15_bar_time(m15_data):
    candles = (m15_data or {}).get("candles") or []
    return candles[-1].get("time") if candles else None


def v28_entry_gate(state, direction, now_time, m15_data, setup=None):
    """Global strategy gate applied to every new V28 entry.

    This is intentionally strategy-level, not account-risk protection. It
    prevents repeated local signals from becoming multiple entries while
    leaving broker margin and the configured strategy stop untouched.
    """
    last_time = state.get("v28_last_entry_time")
    last_direction = state.get("v28_last_entry_direction")
    last_m15_bar = state.get("v28_last_entry_m15_bar")
    current_m15_bar = _v28_m15_bar_time(m15_data)

    if last_time:
        elapsed = minutes_between(last_time, now_time)
        if elapsed is not None and elapsed < V28_ENTRY_COOLDOWN_MINUTES:
            return False, (
                f"V28_ENTRY_COOLDOWN_{elapsed:.1f}m_LT_{V28_ENTRY_COOLDOWN_MINUTES:.1f}m"
            )

    if V28_REQUIRE_M15_NEW_BAR_AFTER_ENTRY and last_m15_bar and current_m15_bar == last_m15_bar:
        return False, "V28_ONE_ENTRY_PER_M15_BAR"

    if last_time and last_direction and last_direction != direction:
        elapsed = minutes_between(last_time, now_time)
        if elapsed is not None and elapsed < V28_OPPOSITE_DIRECTION_COOLDOWN_MINUTES:
            return False, (
                f"V28_OPPOSITE_DIRECTION_COOLDOWN_{elapsed:.1f}m_LT_{V28_OPPOSITE_DIRECTION_COOLDOWN_MINUTES:.1f}m"
            )

    if V28_H4_HARD_DIRECTION_GATE and setup is not None:
        h4_trend = setup.get("_h4_trend")
        if h4_trend == "BULLISH" and direction != "BUY":
            return False, "V28_H4_DIRECTION_GATE_BULLISH"
        if h4_trend == "BEARISH" and direction != "SELL":
            return False, "V28_H4_DIRECTION_GATE_BEARISH"

    return True, "V28_ENTRY_ALLOWED"


def v28_mark_entry(state, direction, now_time, m15_data, setup_id):
    bar = _v28_m15_bar_time(m15_data)
    state["v28_last_entry_time"] = now_time
    state["v28_last_entry_direction"] = direction
    state["v28_last_entry_m15_bar"] = bar
    state["v28_cycle_id"] = setup_id

    audit_event("V28_STRATEGY_ENTRY_CYCLE", {
        "setup_id": setup_id,
        "direction": direction,
        "entry_time": now_time,
        "m15_bar": bar,
        "cooldown_minutes": V28_ENTRY_COOLDOWN_MINUTES,
        "opposite_direction_cooldown_minutes": V28_OPPOSITE_DIRECTION_COOLDOWN_MINUTES,
    })


def execute_m15_opportunity_setups(
    data, state, h4_trend=None, m15_data=None, m15_context=None,
    allow_new_entries=True, daily_view=None
):
    """V27: M15 opportunity -> M1 confirmation -> freshness-gated execution.

    A confirmed opportunity is persistent. If price has already moved too far
    from the M1 confirmation reference, the machine does NOT chase it and does
    NOT repeatedly call execute_setup(). It enters WAITING_REENTRY and only
    attempts the order again when the live execution price returns inside the
    original freshness envelope.
    """
    if not M15_OPPORTUNITY_ENABLED or not m15_data or not m15_context:
        return 0

    opportunities = detect_m15_opportunities(m15_data, m15_context)

    # V28.2: select the newest H4-aligned M15 candidate. If H4 is neutral,
    # retain the newest qualified candidate. This prevents a countertrend
    # candidate from consuming the single-cycle slot.
    if opportunities and h4_trend in {"BULLISH", "BEARISH"}:
        aligned_direction = "BUY" if h4_trend == "BULLISH" else "SELL"
        aligned = [x for x in opportunities if x.get("direction") == aligned_direction]
        if aligned:
            opportunities = aligned
        else:
            # H4 is a preference, not a detector kill-switch. Keep qualified
            # counter-H4 candidates; execution still applies the M15 alignment
            # check in counter_h4_entry_allowed() before submitting an order.
            print("[V28.5 H4 BIAS] no aligned M15 candidate; retaining qualified counter-H4 candidate(s) for normal execution checks.")

    candles = data["candles"]
    current_tick = data["current_tick"]
    now_time = candles[-1]["time"]
    executed = 0
    used = 0

    watches = state.setdefault("m15_opportunity_watches", {})
    history = state.setdefault("m15_opportunity_history", [])
    # Terminal outcomes are remembered so an unaffordable broker-minimum order or
    # expired confirmation cannot be retried on every five-second poll.
    terminal_statuses = {"EXECUTED", "BLOCKED_NO_MARGIN", "EXPIRED_CONFIRMATION"}
    historical_ids = {x.get("id") for x in history if x.get("status") in terminal_statuses}

    # Rehydrate persistent opportunities first. A confirmed/re-entry watch is
    # authoritative; detector output must not erase its stored confirmation.
    queued = {}
    persistent_statuses = {
        "WAITING_M1_CONFIRMATION",
        "M1_CONFIRMED",
        "WAITING_REENTRY",
    }
    for item in watches.values():
        if item.get("id") and item.get("status") in persistent_statuses:
            queued[item["id"]] = dict(item)

    for opportunity in opportunities:
        oid = opportunity.get("id")
        existing = watches.get(oid)
        if existing and existing.get("status") in {"M1_CONFIRMED", "WAITING_REENTRY"}:
            # Keep the original M1 confirmation/reference. The opportunity
            # detector may rediscover the same M15 candle every poll.
            merged = dict(opportunity)
            for key in (
                "status", "confirmation", "last_checked",
                "last_execution_error", "reentry_last_logged",
            ):
                if key in existing:
                    merged[key] = existing[key]
            queued[oid] = merged
        else:
            queued[oid] = opportunity

    if not queued:
        print("[V28 M15 OPPORTUNITY] none | no active/new M15 displacement->S/R->reversal opportunity")
        return 0

    def live_entry_price(direction):
        field = "ask" if direction == "BUY" else "bid"
        return _execution_float(current_tick, field, f"current_tick.{field}")

    def reentry_gap(direction, current_price, reference):
        return (
            current_price - reference
            if direction == "BUY"
            else reference - current_price
        )

    for opportunity in queued.values():
        if used >= M15_OPPORTUNITY_MAX_ORDERS_PER_POLL:
            break

        oid = opportunity.get("id")
        if not oid or oid in historical_ids:
            continue

        age = minutes_between(opportunity.get("m15_time"), now_time)
        if age is None or age < 0:
            continue
        if age > M15_OPPORTUNITY_MAX_AGE_MINUTES:
            if oid in watches:
                watches[oid]["status"] = "EXPIRED"
            print(
                f"[V28 M15 OPPORTUNITY EXPIRED] {oid} | "
                f"age={age:.2f}m > {M15_OPPORTUNITY_MAX_AGE_MINUTES:.2f}m"
            )
            continue

        status = opportunity.get("status")
        confirmation = opportunity.get("confirmation")

        # A previously confirmed opportunity is never reconfirmed from a
        # later M1 candle. Its original confirmation is the execution anchor.
        if status not in {"M1_CONFIRMED", "WAITING_REENTRY"}:
            print()
            print("=" * 70)
            print("V28.2 M15 OPPORTUNITY DETECTED")
            print("=" * 70)
            print(f"Setup:             {opportunity['id']}")
            print(f"Direction:         {opportunity['direction']}")
            print(f"M15 displacement:  {opportunity['displacement']:.2f}")
            print(f"M15 zone:          {opportunity['m15_zone']['center']:.2f}")
            print(f"Zone distance:     {opportunity['m15_zone']['distance']:.2f}")
            print(f"M15 reversal q:    {opportunity['reversal_quality']:.3f}")
            print(f"M15 age:           {age:.2f} min")
            print(f"Impulse extreme:   {opportunity.get('impulse_extreme', 0.0):.2f}")
            print(f"Impulse window:    {opportunity.get('impulse_start')} -> {opportunity.get('impulse_end')}")

            confirmation = _m1_opportunity_confirmation(candles, opportunity, now_time)
            if confirmation is None:
                print("M1 confirmation:   WAITING")
                print("Execution model:   M15 opportunity -> M1 confirmation")
                print("=" * 70)
                watches[oid] = {
                    **opportunity,
                    "status": "WAITING_M1_CONFIRMATION",
                    "last_checked": now_time,
                }
                continue

            opportunity = {
                **opportunity,
                "status": "M1_CONFIRMED",
                "confirmation": confirmation,
                "last_checked": now_time,
            }
            watches[oid] = dict(opportunity)

            print(f"M1 confirmation:   {confirmation['time']}")
            print(f"M1 break level:    {confirmation['micro_level']:.2f}")
            print(f"M1 entry reference:{confirmation['entry_reference']:.2f}")
            print("Execution model:   M15 opportunity -> M1 confirmation")
            print("=" * 70)

        else:
            # Keep the stored confirmation/reference authoritative.
            if not confirmation:
                print(
                    f"[V28 M15 STATE RECOVERY] {oid} has {status} "
                    "but no confirmation; returning to M1 confirmation."
                )
                watches[oid]["status"] = "WAITING_M1_CONFIRMATION"
                continue

        # An M1 confirmation is an execution trigger, not a reusable signal.
        # Refuse to execute if the confirmation is older than the configured
        # freshness window, even when the parent M15 opportunity remains fresh.
        confirmation_time = confirmation.get("time") if isinstance(confirmation, dict) else None
        confirmation_age = minutes_between(confirmation_time, now_time) if confirmation_time else None
        if confirmation_age is None or confirmation_age < 0 or confirmation_age > M15_OPPORTUNITY_M1_CONFIRM_MAX_AGE_MINUTES:
            reason = (
                f"M1 confirmation stale/invalid: age={confirmation_age!r} min; "
                f"maximum allowed={M15_OPPORTUNITY_M1_CONFIRM_MAX_AGE_MINUTES:.1f} min"
            )
            watches[oid] = {
                **watches.get(oid, {}), **opportunity,
                "status": "EXPIRED_CONFIRMATION",
                "confirmation": confirmation,
                "last_checked": now_time,
                "last_execution_error": reason,
            }
            history.append({"id": oid, "status": "EXPIRED_CONFIRMATION", "time": now_time,
                            "direction": opportunity.get("direction"),
                            "confirmation_time": confirmation_time, "reason": reason})
            historical_ids.add(oid)
            audit_event("V28_5_EXPIRED_STALE_M1_CONFIRMATION", {
                "setup_id": oid, "direction": opportunity.get("direction"),
                "market_time": now_time, "confirmation_time": confirmation_time,
                "confirmation_age_minutes": confirmation_age, "reason": reason,
            })
            print(f"[V28.5 STALE CONFIRMATION BLOCKED] {oid} | {reason}")
            continue

        setup = _m15_opportunity_to_setup(
            opportunity,
            confirmation,
            current_tick,
        )

        if not allow_new_entries:
            print(
                f"[V28 M15 OPPORTUNITY BLOCKED] {oid} | "
                "primary entry gate blocked new entries."
            )
            continue

        allowed, reason = daily_view_direction_allowed(
            setup["direction"], daily_view
        )
        if not allowed:
            print(f"[V28 DAILY VIEW BLOCK] {oid} | {reason}")
            audit_event("V27_DAILY_VIEW_ENTRY_BLOCK", {
                "setup_id": oid,
                "direction": setup["direction"],
                "reason": reason,
                "regime": (daily_view or {}).get("regime"),
                "market_time": now_time,
            })
            continue

        setup["_h4_trend"] = h4_trend
        v28_allowed, v28_reason = v28_entry_gate(
            state, setup["direction"], now_time, m15_data, setup=setup
        )
        if not v28_allowed:
            if watches.get(oid, {}).get("last_v28_block_reason") != v28_reason:
                print(f"[V28 STRATEGY GATE BLOCK] {oid} | {v28_reason}")
                audit_event("V28_STRATEGY_ENTRY_BLOCK", {
                    "setup_id": oid,
                    "direction": setup["direction"],
                    "reason": v28_reason,
                    "time": now_time,
                })
                watches[oid]["last_v28_block_reason"] = v28_reason
            continue

        reference = float(confirmation["entry_reference"])
        current_price = live_entry_price(setup["direction"])
        gap = reentry_gap(setup["direction"], current_price, reference)

        # V27 core behavior: a stale confirmed signal waits. Do not call
        # execute_setup(), so the console is quiet and no order-attempt spam
        # occurs while price is away from the M1 confirmation reference.
        if gap > M15_OPPORTUNITY_REENTRY_DISTANCE:
            previous_status = watches.get(oid, {}).get("status")
            watches[oid] = {
                **watches.get(oid, {}),
                **opportunity,
                "status": "WAITING_REENTRY",
                "confirmation": confirmation,
                "last_checked": now_time,
                "last_reentry_gap": round(gap, 4),
            }
            # Announce the transition, then only re-log when the gap changes
            # materially or after a new M1 candle, keeping overnight output
            # manageable.
            previous_gap = watches[oid].get("reentry_last_logged")
            should_log = (
                previous_status != "WAITING_REENTRY"
                or previous_gap is None
                or abs(float(previous_gap) - gap) >= 0.50
            )
            if should_log:
                watches[oid]["reentry_last_logged"] = round(gap, 4)
                print(
                    f"[V28 M15 WAITING RE-ENTRY] {oid} | "
                    f"side={setup['direction']} | "
                    f"confirmation_ref={reference:.2f} | "
                    f"current={current_price:.2f} | "
                    f"gap={gap:.2f} | "
                    f"required<={M15_OPPORTUNITY_REENTRY_DISTANCE:.2f}"
                )
                audit_event("V27_M15_OPPORTUNITY_WAITING_REENTRY", {
                    "setup_id": oid,
                    "direction": setup["direction"],
                    "confirmation_time": confirmation["time"],
                    "reference": reference,
                    "current_price": current_price,
                    "gap": gap,
                    "max_reentry_distance": M15_OPPORTUNITY_REENTRY_DISTANCE,
                    "market_time": now_time,
                })
            continue

        # Price has returned to the original execution envelope.
        if watches.get(oid, {}).get("status") == "WAITING_REENTRY":
            print(
                f"[V28 M15 RE-ENTRY READY] {oid} | "
                f"side={setup['direction']} | "
                f"confirmation_ref={reference:.2f} | "
                f"current={current_price:.2f} | "
                f"gap={gap:.2f}"
            )
            audit_event("V27_M15_OPPORTUNITY_REENTRY_READY", {
                "setup_id": oid,
                "direction": setup["direction"],
                "confirmation_time": confirmation["time"],
                "reference": reference,
                "current_price": current_price,
                "gap": gap,
                "market_time": now_time,
            })

        try:
            result = execute_setup(
                setup=setup,
                current_tick=current_tick,
                symbol_info=data["symbol_info"],
                market_time=now_time,
                h4_trend=h4_trend,
            )

            state["trade_history"].append({
                "id": setup["id"],
                "status": "V27_M15_OPPORTUNITY_TRADE",
                "direction": setup["direction"],
                "time": now_time,
                "m15_time": opportunity["m15_time"],
                "m1_confirmation_time": confirmation["time"],
                "result": result,
            })

            status_text = str(result.get("status", "")).upper()
            broker_accepted = (
                result.get("success") is True
                or result.get("accepted") is True
                or status_text in {"EXECUTED", "FILLED", "PLACED", "DONE", "DONE_PARTIAL"}
            )
            retryable_status = status_text in {"RETRY_COOLDOWN", "ALREADY_ATTEMPTED", "DISABLED"}
            if broker_accepted:
                state["last_order_time"] = now_time
                v28_mark_entry(state, setup["direction"], now_time, m15_data, oid)
                history.append({
                    "id": oid,
                    "status": "EXECUTED",
                    "time": now_time,
                    "direction": setup["direction"],
                    "m1_confirmation_time": confirmation["time"],
                    "broker_result": result,
                })
                watches.pop(oid, None)
                executed += 1
                used += 1
                print(f"[V28.5 BROKER ACCEPTED] {oid} -> {status_text or result.get('retcode_description', 'accepted')}")
            else:
                # Do not consume the setup or start the entry cooldown merely
                # because an HTTP call returned a dictionary. Keep the watch
                # and expose the returned response for diagnosis.
                watches[oid] = {
                    **watches.get(oid, {}),
                    **opportunity,
                    "status": "M1_CONFIRMED",
                    "confirmation": confirmation,
                    "last_checked": now_time,
                    "last_execution_error": f"BROKER_NOT_CONFIRMED_ACCEPTED: {result}",
                }
                print(f"[V28.5 BROKER NOT CONFIRMED] {oid} | retryable={retryable_status} | result={result}")
        except Exception as error:
            error_text = f"{type(error).__name__}: {error}"
            error_lower = error_text.lower()
            no_margin = (
                "10019" in error_text
                or "no money" in error_lower
                or "insufficient margin" in error_lower
            )
            if no_margin:
                # A broker-confirmed margin rejection is terminal for this
                # setup. Do not hammer the broker every poll or mark it filled.
                reason = "BROKER_NO_MARGIN: minimum volume rejected; setup blocked without retry"
                watches[oid] = {
                    **watches.get(oid, {}), **opportunity,
                    "status": "BLOCKED_NO_MARGIN",
                    "confirmation": confirmation,
                    "last_checked": now_time,
                    "last_execution_error": error_text,
                }
                history.append({"id": oid, "status": "BLOCKED_NO_MARGIN", "time": now_time,
                                "direction": setup.get("direction"),
                                "confirmation_time": confirmation.get("time"),
                                "reason": reason, "error": error_text})
                historical_ids.add(oid)
                audit_event("V28_5_BROKER_NO_MARGIN_TERMINAL_BLOCK", {
                    "setup_id": oid, "direction": setup.get("direction"),
                    "market_time": now_time, "confirmation_time": confirmation.get("time"),
                    "error": error_text, "reason": reason,
                })
                print(f"[V28.5 NO-MARGIN TERMINAL BLOCK] {oid} | {reason}")
                continue

            # A chase rejection should be handled as a waiting state. Other
            # execution errors remain persistent too, but they do not trigger
            # an immediate retry storm.
            watches[oid] = {
                **watches.get(oid, {}),
                **opportunity,
                "status": "WAITING_REENTRY"
                if "V27_OPPORTUNITY_CHASE_INVALID" in str(error)
                else "M1_CONFIRMED",
                "confirmation": confirmation,
                "last_checked": now_time,
                "last_execution_error": error_text,
            }

            audit_event("V27_M15_OPPORTUNITY_EXECUTION_ERROR", {
                "setup_id": oid,
                "direction": setup["direction"],
                "time": now_time,
                "error": str(error),
                "status": watches[oid]["status"],
            })

            print(
                f"[V28 M15 OPPORTUNITY RETAINED] {oid} | "
                f"{error_text}"
            )

    state["m15_opportunity_history"] = history[-200:]
    return executed



# ============================================================
# MAIN LOOP
# ============================================================

def main():
    print_header()

    state = load_state()
    ensure_direction_watchers(state)

    # If state is completely fresh, warm it from the current market window.
    if (
        not state["last_processed_candle"]
        and not state["active_setups"]
    ):
        try:
            warmup_data = get_market_data()
            warmup_m15 = get_m15_market_data()
            m15_context = build_m15_context(warmup_m15)
            state = empty_state()
            if STRICT_M1_SETUP_LANE_ENABLED:
                state = warmup_state(
                    warmup_data["candles"],
                    m15_context,
                )
            # Warmed setups are never executed against an H4 filter without review.
            h4_data = get_h4_market_data()
            h4_trend, _ = determine_h4_trend(h4_data["candles"])
            state["active_setups"] = filter_setups_by_h4(
                state["active_setups"], h4_trend, verbose=True
            )
            ensure_direction_watchers(state)
            save_state(state)
            print(
                f"[M15 CONTEXT] price={m15_context['price']:.2f} | "
                f"support_zones={len(m15_context['support_zones'])} | "
                f"resistance_zones={len(m15_context['resistance_zones'])}"
            )
        except Exception as error:
            print(
                f"[WARMUP ERROR] "
                f"{type(error).__name__}: {error}"
            )

    print(
        f"[START] Active setups: "
        f"{len(state['active_setups'])}"
    )

    while True:
        try:
            data = get_market_data()
            candles = data["candles"]
            latest_time = candles[-1]["time"]

            m15_data = get_m15_market_data()
            m15_context = build_m15_context(m15_data)
            h4_data = get_h4_market_data()
            h4_trend, h4_details = determine_h4_trend(h4_data["candles"])
            account = get_account()
            risk_summary, daily_drawdown, _ = get_account_status(account, latest_time)
            print(
                f"[M15 CONTEXT] price={m15_context['price']:.2f} | "
                f"support={len(m15_context['support_zones'])} | "
                f"resistance={len(m15_context['resistance_zones'])}"
            )
            print(f"[H4 TREND] {h4_trend} | {h4_details}")
            print_account_status(risk_summary)
            update_daily_ledger(state, risk_summary, account)

            # Existing positions are always managed before any new entry scan.
            manage_open_positions(data, h4_trend, latest_time, state=state)
            update_reaction_watches(data, state, latest_time)

            # ----------------------------------------------------
            # V21 real-broker confirmation. Existing positions were already
            # managed above and remain protected even if the gate blocks
            # new entries.
            # ----------------------------------------------------
            shadow_confirmation = get_shadow_confirmation(
                demo_m1=data,
                demo_m15=m15_data,
                demo_h4_data=h4_data,
                demo_h4_trend=h4_trend,
                state=state,
                market_time=latest_time,
            )
            print_shadow_confirmation(shadow_confirmation)

            daily_view = refresh_daily_market_view(
                state=state,
                h4_data=h4_data,
                h4_trend=h4_trend,
                m15_context=m15_context,
                market_time=latest_time,
            )
            allow_new_entries = bool(shadow_confirmation.get("can_new_entries"))

            # The shadow gate validates feed integrity/context; the daily view
            # then decides whether the current direction belongs to the active
            # intraday opportunity regime. Individual setup execution applies
            # the direction-specific daily-view gate below.

            # ----------------------------------------------------
            # 1. Every poll updates permanent BUY and SELL watches.
            #    These remain active even when there is no sweep yet.
            # ----------------------------------------------------
            update_direction_watchers(state, data, m15_context, verbose=True)
            record_poll_watch(state, data)

            # ----------------------------------------------------
            # 2. V28: STRICT M1 SETUP DISCOVERY DISABLED.
            #    M15 is the only setup generator; M1 is execution confirmation.
            # ----------------------------------------------------
            if STRICT_M1_SETUP_LANE_ENABLED:
                discovered = discover_recent_setups(
                    candles, state, m15_context, POLL_DISCOVERY_BARS
                )
                discovered = filter_setups_by_h4(discovered, h4_trend, verbose=True)
                register_setups(state, discovered, verbose=True)
            else:
                discovered = []
                state["active_setups"] = []

            # ----------------------------------------------------
            # 3. V23 M15 OPPORTUNITY LANE
            #    M15 identifies displacement/reversal; M1 confirms execution.
            #    This is independent of the old strict M1 chain.
            # ----------------------------------------------------
            execute_m15_opportunity_setups(
                data=data,
                state=state,
                h4_trend=h4_trend,
                m15_data=m15_data,
                m15_context=m15_context,
                allow_new_entries=allow_new_entries,
                daily_view=daily_view,
            )

            # ----------------------------------------------------
            # 4. V17 FAST OPPORTUNITY LANE
            #    Original strict SWEEP -> BOS -> BREAKER -> RETEST route.
            # ----------------------------------------------------
            if FAST_COMPLETE_SCAN_ENABLED:
                execute_fast_complete_setups(
                    data=data,
                    state=state,
                    h4_trend=h4_trend,
                    m15_context=m15_context,
                    allow_new_entries=allow_new_entries,
                    daily_view=daily_view,
                )

            # ----------------------------------------------------
            # 5. V28 has no independent M1 setup lane. Existing positions
            #    are managed above; new trades originate only from M15.
            # ----------------------------------------------------

            # ----------------------------------------------------
            # 6. Show the current opportunity census.
            # ----------------------------------------------------
            sweep_counts = count_recent_sweep_candidates(candles, m15_context, bars=20)
            v23_waiting = sum(
                1 for item in state.get("m15_opportunity_watches", {}).values()
                if item.get("status") == "WAITING_M1_CONFIRMATION"
            )
            v23_confirmed = sum(
                1 for item in state.get("m15_opportunity_watches", {}).values()
                if item.get("status") == "M1_CONFIRMED"
            )
            print(
                f"[OPPORTUNITY CENSUS] last 20 M1: "
                f"raw BUY={sweep_counts['raw_buy']} | "
                f"raw SELL={sweep_counts['raw_sell']} | "
                f"M15-aligned BUY={sweep_counts['aligned_buy']} | "
                f"M15-aligned SELL={sweep_counts['aligned_sell']} | "
                f"V23 M15 waiting={v23_waiting} | "
                f"V23 M1 confirmed={v23_confirmed} | "
                f"trade_setups={len(state['active_setups'])}"
            )

            # Explicit deterministic decision-engine status.
            if state["active_setups"]:
                stage_counts = {}
                for active in state["active_setups"]:
                    stage = active.get("stage", "UNKNOWN")
                    stage_counts[stage] = stage_counts.get(stage, 0) + 1
                print(f"[DECISION ENGINE] active stages={stage_counts}")
            else:
                print(
                    "[DECISION ENGINE] no live trade candidate yet; "
                    f"watching BUY={sweep_counts['aligned_buy']} / "
                    f"SELL={sweep_counts['aligned_sell']} M15-aligned sweep candidates"
                )

            # ----------------------------------------------------
            # 7. Keep the candle checkpoint for diagnostics only.
            # ----------------------------------------------------
            state["last_processed_candle"] = latest_time
            if state.get("session_start_time") is None:
                state["session_start_time"] = latest_time

            # ----------------------------------------------------
            # 8. 30-minute critical review.
            # ----------------------------------------------------
            anchor = (
                state.get("last_order_time")
                or state.get("session_start_time")
            )
            elapsed = minutes_between(anchor, latest_time)

            should_review = (
                STRICT_M1_SETUP_LANE_ENABLED
                and elapsed is not None
                and elapsed >= NO_TRADE_WATCHDOG_MINUTES
            )

            if should_review:
                last_review = state.get("last_critical_review")
                since_review = minutes_between(
                    last_review,
                    latest_time,
                ) if last_review else None

                if (
                    last_review is None
                    or since_review is None
                    or since_review >= NO_TRADE_WATCHDOG_MINUTES
                    or (
                        state.get("last_order_time")
                        and parse_time(state["last_order_time"])
                        > parse_time(last_review)
                    )
                ):
                    critical_review(
                        data,
                        state,
                        m15_context,
                        allow_new_entries=allow_new_entries,
                        daily_view=daily_view,
                    )

            # ----------------------------------------------------
            # 9. Periodic execution/performance audit.
            # ----------------------------------------------------
            if state["poll_number"] % 30 == 0:
                print_audit_summary(state)
                audit_event("PERFORMANCE_AUDIT", {
                    "market_time": latest_time,
                    "summary": audit_trade_lifecycle_summary(state),
                    "account_balance": float(account["balance"]),
                    "account_equity": float(account["equity"]),
                    "secondary_feed": "DISABLED",
                    "new_entries_allowed": allow_new_entries,
                    "v23_m15_opportunity_watches": len(state.get("m15_opportunity_watches", {})),
                    "v23_m15_history": len(state.get("m15_opportunity_history", [])),
                })
                state["last_audit_summary_time"] = latest_time

            # ----------------------------------------------------
            # 10. Persist everything after EVERY poll.
            # ----------------------------------------------------
            state["active_setups"] = deduplicate_active_setups(
                state["active_setups"]
            )
            state["trade_history"] = state["trade_history"][-MAX_TRADE_HISTORY:]
            state["poll_watches"] = state["poll_watches"][-POLL_WATCH_HISTORY:]
            save_state(state)

            # Periodic compact heartbeat.
            if state["poll_number"] % 6 == 0:
                print(
                    f"[HEARTBEAT] {latest_time} | "
                    f"poll={state['poll_number']} | "
                    f"trade_setups={len(state['active_setups'])} | "
                    f"BUY+SELL watchers=2"
                )

        except KeyboardInterrupt:
            print()
            print("MULTI-SETUP TRADING ENGINE STOPPED.")
            save_state(state)
            break

        except Exception as error:
            print()
            print(
                f"[ERROR] {type(error).__name__}: {error}"
            )
            try:
                save_state(state)
            except Exception:
                pass

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
