import os
import requests
from datetime import datetime, timezone

from strategy_config import (
    SYMBOL,
    TIMEFRAME,
    M1_BARS,
    SWING_LOOKBACK,
    LIQUIDITY_LOOKBACK,
    MIN_SWEEP_DISTANCE,
    BOS_LOOKAHEAD,
    RETEST_LOOKAHEAD,
    MIN_BOS_BODY,
)

# ============================================================
# CONFIGURATION
# ============================================================

BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "http://127.0.0.1:8000")
API_KEY = os.environ["MT5_BRIDGE_API_KEY"]

# ============================================================
# HTTP
# ============================================================

HEADERS = {
    "x-api-key": API_KEY
}


def get_market_data():
    url = f"{BRIDGE_URL}/market"

    params = {
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "bars": M1_BARS
    }

    response = requests.get(
        url,
        headers=HEADERS,
        params=params,
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if data.get("bars_returned", 0) == 0:
        raise RuntimeError(
            f"No market data returned: {data}"
        )

    return data


# ============================================================
# CANDLE HELPERS
# ============================================================

def candle_body(candle):
    return abs(candle["close"] - candle["open"])


def candle_range(candle):
    return candle["high"] - candle["low"]


def is_bullish(candle):
    return candle["close"] > candle["open"]


def is_bearish(candle):
    return candle["close"] < candle["open"]


# ============================================================
# SWINGS
# ============================================================

def is_swing_low(candles, index, lookback=2):

    if index < lookback:
        return False

    if index >= len(candles) - lookback:
        return False

    current = candles[index]["low"]

    for i in range(1, lookback + 1):

        if current >= candles[index - i]["low"]:
            return False

        if current >= candles[index + i]["low"]:
            return False

    return True


def is_swing_high(candles, index, lookback=2):

    if index < lookback:
        return False

    if index >= len(candles) - lookback:
        return False

    current = candles[index]["high"]

    for i in range(1, lookback + 1):

        if current <= candles[index - i]["high"]:
            return False

        if current <= candles[index + i]["high"]:
            return False

    return True


def find_swing_points(candles):

    swing_highs = []
    swing_lows = []

    for i in range(len(candles)):

        if is_swing_high(
            candles,
            i,
            SWING_LOOKBACK
        ):
            swing_highs.append({
                "index": i,
                "price": candles[i]["high"]
            })

        if is_swing_low(
            candles,
            i,
            SWING_LOOKBACK
        ):
            swing_lows.append({
                "index": i,
                "price": candles[i]["low"]
            })

    return swing_highs, swing_lows


# ============================================================
# LIQUIDITY LEVELS
# ============================================================

def previous_swing_low(
    swing_lows,
    index
):

    candidates = [
        x for x in swing_lows
        if x["index"] < index
    ]

    if not candidates:
        return None

    return candidates[-1]


def previous_swing_high(
    swing_highs,
    index
):

    candidates = [
        x for x in swing_highs
        if x["index"] < index
    ]

    if not candidates:
        return None

    return candidates[-1]


# ============================================================
# LIQUIDITY SWEEP
# ============================================================

def find_bullish_sweep(
    candles,
    index,
    swing_lows
):

    if index <= 0:
        return None

    liquidity = previous_swing_low(
        swing_lows,
        index
    )

    if liquidity is None:
        return None

    candle = candles[index]

    # Price must trade below the previous swing low.
    if candle["low"] >= liquidity["price"]:
        return None

    # Minimum sweep distance.
    if (
        liquidity["price"] - candle["low"]
        < MIN_SWEEP_DISTANCE
    ):
        return None

    # Reclaim condition:
    # candle closes back above the liquidity level.
    if candle["close"] <= liquidity["price"]:
        return None

    return {
        "index": index,
        "type": "BULLISH_SWEEP",
        "liquidity": liquidity["price"],
        "sweep_price": candle["low"],
        "close": candle["close"]
    }


def find_bearish_sweep(
    candles,
    index,
    swing_highs
):

    if index <= 0:
        return None

    liquidity = previous_swing_high(
        swing_highs,
        index
    )

    if liquidity is None:
        return None

    candle = candles[index]

    # Price must trade above previous swing high.
    if candle["high"] <= liquidity["price"]:
        return None

    # Minimum sweep distance.
    if (
        candle["high"] - liquidity["price"]
        < MIN_SWEEP_DISTANCE
    ):
        return None

    # Rejection:
    # candle closes back below liquidity.
    if candle["close"] >= liquidity["price"]:
        return None

    return {
        "index": index,
        "type": "BEARISH_SWEEP",
        "liquidity": liquidity["price"],
        "sweep_price": candle["high"],
        "close": candle["close"]
    }


# ============================================================
# STRUCTURE LEVEL BEFORE SWEEP
# ============================================================

def structure_high_before_sweep(
    swing_highs,
    sweep_index
):

    candidates = [
        x for x in swing_highs
        if x["index"] < sweep_index
    ]

    if not candidates:
        return None

    return candidates[-1]


def structure_low_before_sweep(
    swing_lows,
    sweep_index
):

    candidates = [
        x for x in swing_lows
        if x["index"] < sweep_index
    ]

    if not candidates:
        return None

    return candidates[-1]


# ============================================================
# BOS
# ============================================================

def find_bullish_bos(
    candles,
    sweep,
    swing_highs
):

    sweep_index = sweep["index"]

    structure = structure_high_before_sweep(
        swing_highs,
        sweep_index
    )

    if structure is None:
        return None

    level = structure["price"]

    end = min(
        len(candles),
        sweep_index + BOS_LOOKAHEAD + 1
    )

    for i in range(
        sweep_index + 1,
        end
    ):

        candle = candles[i]

        # Bullish BOS requires a close above structure.
        if candle["close"] <= level:
            continue

        body = candle_body(candle)

        if body < MIN_BOS_BODY:
            continue

        return {
            "index": i,
            "type": "BULLISH_BOS",
            "level": level,
            "close": candle["close"],
            "body": body
        }

    return None


def find_bearish_bos(
    candles,
    sweep,
    swing_lows
):

    sweep_index = sweep["index"]

    structure = structure_low_before_sweep(
        swing_lows,
        sweep_index
    )

    if structure is None:
        return None

    level = structure["price"]

    end = min(
        len(candles),
        sweep_index + BOS_LOOKAHEAD + 1
    )

    for i in range(
        sweep_index + 1,
        end
    ):

        candle = candles[i]

        # Bearish BOS requires close below structure.
        if candle["close"] >= level:
            continue

        body = candle_body(candle)

        if body < MIN_BOS_BODY:
            continue

        return {
            "index": i,
            "type": "BEARISH_BOS",
            "level": level,
            "close": candle["close"],
            "body": body
        }

    return None


# ============================================================
# BREAKER BLOCK
# ============================================================

def find_bullish_breaker(
    candles,
    sweep,
    bos
):

    # Search backward from the BOS candle.
    #
    # First bearish candle becomes the candidate
    # bullish breaker block.

    start = bos["index"] - 1

    end = max(
        sweep["index"],
        bos["index"] - 10
    )

    for i in range(
        start,
        end - 1,
        -1
    ):

        candle = candles[i]

        if not is_bearish(candle):
            continue

        return {
            "type": "BULLISH_BREAKER",
            "index": i,
            "high": candle["high"],
            "low": candle["low"],
            "open": candle["open"],
            "close": candle["close"]
        }

    return None


def find_bearish_breaker(
    candles,
    sweep,
    bos
):

    start = bos["index"] - 1

    end = max(
        sweep["index"],
        bos["index"] - 10
    )

    for i in range(
        start,
        end - 1,
        -1
    ):

        candle = candles[i]

        if not is_bullish(candle):
            continue

        return {
            "type": "BEARISH_BREAKER",
            "index": i,
            "high": candle["high"],
            "low": candle["low"],
            "open": candle["open"],
            "close": candle["close"]
        }

    return None


# ============================================================
# RETEST / MITIGATION
# ============================================================

def price_touches_zone(
    candle,
    zone
):

    return (
        candle["low"] <= zone["high"]
        and
        candle["high"] >= zone["low"]
    )


def find_bullish_retest(
    candles,
    bos,
    breaker
):

    start = bos["index"] + 1

    end = min(
        len(candles),
        start + RETEST_LOOKAHEAD
    )

    for i in range(start, end):

        candle = candles[i]

        if not price_touches_zone(
            candle,
            breaker
        ):
            continue

        # Bullish rejection:
        # candle touches breaker and closes
        # back above its midpoint.
        midpoint = (
            breaker["high"]
            + breaker["low"]
        ) / 2

        if candle["close"] <= midpoint:
            continue

        return {
            "index": i,
            "type": "BULLISH_RETEST",
            "close": candle["close"]
        }

    return None


def find_bearish_retest(
    candles,
    bos,
    breaker
):

    start = bos["index"] + 1

    end = min(
        len(candles),
        start + RETEST_LOOKAHEAD
    )

    for i in range(start, end):

        candle = candles[i]

        if not price_touches_zone(
            candle,
            breaker
        ):
            continue

        midpoint = (
            breaker["high"]
            + breaker["low"]
        ) / 2

        if candle["close"] >= midpoint:
            continue

        return {
            "index": i,
            "type": "BEARISH_RETEST",
            "close": candle["close"]
        }

    return None


# ============================================================
# COMPLETE SETUP SCANNER
# ============================================================

def scan_setups(
    candles,
    swing_highs,
    swing_lows
):

    setups = []

    used_until = -1

    for i in range(
        SWING_LOOKBACK,
        len(candles) - SWING_LOOKBACK
    ):

        if i <= used_until:
            continue

        # ----------------------------------------------------
        # BULLISH SEQUENCE
        # ----------------------------------------------------

        sweep = find_bullish_sweep(
            candles,
            i,
            swing_lows
        )

        if sweep:

            bos = find_bullish_bos(
                candles,
                sweep,
                swing_highs
            )

            if bos:

                breaker = find_bullish_breaker(
                    candles,
                    sweep,
                    bos
                )

                if breaker:

                    retest = find_bullish_retest(
                        candles,
                        bos,
                        breaker
                    )

                    if retest:

                        setups.append({
                            "direction": "BUY",
                            "sweep": sweep,
                            "bos": bos,
                            "breaker": breaker,
                            "retest": retest
                        })

                        used_until = retest["index"]

                        continue

        # ----------------------------------------------------
        # BEARISH SEQUENCE
        # ----------------------------------------------------

        sweep = find_bearish_sweep(
            candles,
            i,
            swing_highs
        )

        if sweep:

            bos = find_bearish_bos(
                candles,
                sweep,
                swing_lows
            )

            if bos:

                breaker = find_bearish_breaker(
                    candles,
                    sweep,
                    bos
                )

                if breaker:

                    retest = find_bearish_retest(
                        candles,
                        bos,
                        breaker
                    )

                    if retest:

                        setups.append({
                            "direction": "SELL",
                            "sweep": sweep,
                            "bos": bos,
                            "breaker": breaker,
                            "retest": retest
                        })

                        used_until = retest["index"]

    return setups


# ============================================================
# DISPLAY
# ============================================================

def format_time(candle):

    value = candle["time"]

    if isinstance(value, str):
        return value

    return str(value)


def display_setup(
    candles,
    setup,
    number
):

    sweep = setup["sweep"]
    bos = setup["bos"]
    breaker = setup["breaker"]
    retest = setup["retest"]

    print()
    print("-" * 70)
    print(
        f"SETUP #{number} → {setup['direction']}"
    )
    print("-" * 70)

    print(
        f"Sweep:   "
        f"{format_time(candles[sweep['index']])} | "
        f"liquidity={sweep['liquidity']:.2f} | "
        f"sweep={sweep['sweep_price']:.2f}"
    )

    print(
        f"BOS:     "
        f"{format_time(candles[bos['index']])} | "
        f"level={bos['level']:.2f} | "
        f"close={bos['close']:.2f}"
    )

    print(
        f"Breaker: "
        f"{format_time(candles[breaker['index']])} | "
        f"zone={breaker['low']:.2f} - "
        f"{breaker['high']:.2f}"
    )

    print(
        f"Retest:  "
        f"{format_time(candles[retest['index']])} | "
        f"close={retest['close']:.2f}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("XAUUSD SWEEP → BOS → BREAKER → RETEST DETECTOR")
    print("=" * 70)

    print(f"Symbol:        {SYMBOL}")
    print(f"Timeframe:     {TIMEFRAME}")
    print(f"Bars:          {M1_BARS}")

    data = get_market_data()

    candles = data["candles"]

    print(
        f"Latest candle: "
        f"{candles[-1]['time']}"
    )

    print(
        f"Latest close:  "
        f"{candles[-1]['close']}"
    )

    swing_highs, swing_lows = find_swing_points(
        candles
    )

    print()
    print(
        f"M1 swing highs: {len(swing_highs)}"
    )

    print(
        f"M1 swing lows:  {len(swing_lows)}"
    )

    setups = scan_setups(
        candles,
        swing_highs,
        swing_lows
    )

    print()
    print("=" * 70)
    print("COMPLETE HISTORICAL SETUPS")
    print("=" * 70)

    print(
        f"Valid BUY setups:  "
        f"{sum(1 for x in setups if x['direction'] == 'BUY')}"
    )

    print(
        f"Valid SELL setups: "
        f"{sum(1 for x in setups if x['direction'] == 'SELL')}"
    )

    print(
        f"Total setups:      "
        f"{len(setups)}"
    )

    for number, setup in enumerate(
        setups[-20:],
        1
    ):
        display_setup(
            candles,
            setup,
            number
        )

    print()
    print("=" * 70)
    print("SCAN COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()