import os
import time
import requests

BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "http://127.0.0.1:8000")
API_KEY = os.environ["MT5_BRIDGE_API_KEY"]

SYMBOL = "XAUUSD"
MAGIC = 260927

HEADERS = {
    "x-api-key": API_KEY
}


def get_account():
    response = requests.get(
        f"{BRIDGE_URL}/account",
        headers=HEADERS,
        timeout=10
    )
    response.raise_for_status()
    result = response.json()
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(f"POSITION_CLOSE_REJECTED: {result}")
    return result


def get_positions():
    response = requests.get(
        f"{BRIDGE_URL}/positions",
        headers=HEADERS,
        timeout=10
    )
    response.raise_for_status()
    return response.json()


def _position_matches_order(
    position,
    direction,
    volume,
    stop_loss,
    take_profit,
    comment,
):
    """Match an existing MT5 position to the order we intended to submit."""

    if position.get("symbol") != SYMBOL:
        return False

    expected_type = 0 if direction == "BUY" else 1

    try:
        if int(position.get("type", -1)) != expected_type:
            return False
        if int(position.get("magic", 0)) != MAGIC:
            return False
    except (TypeError, ValueError):
        return False

    position_comment = str(position.get("comment", ""))

    # Preferred match for all new orders.
    if comment and position_comment == comment:
        return True

    # Legacy fallback for positions opened by the previous engine, which used
    # one constant comment for every setup. Protection levels make this much
    # narrower than matching by direction alone.
    if position_comment not in {
        "XAUUSD_MULTI_SETUP",
        "XAUUSD_STRATEGY",
        "",
    }:
        return False

    try:
        pos_volume = float(position.get("volume", 0.0))
        pos_sl = float(position.get("sl", 0.0))
        pos_tp = float(position.get("tp", 0.0))
        requested_volume = float(volume)
        requested_sl = float(stop_loss)
        requested_tp = float(take_profit)
    except (TypeError, ValueError):
        return False

    return (
        pos_volume > 0
        and pos_volume <= requested_volume + 1e-9
        and abs(pos_sl - requested_sl) <= 0.02
        and abs(pos_tp - requested_tp) <= 0.02
    )


def _reconcile_existing_position(
    direction,
    volume,
    stop_loss,
    take_profit,
    comment,
    attempts=4,
):
    """Check MT5 briefly for a position already created by this submission."""

    for attempt in range(attempts):
        try:
            positions = get_positions()

            for position in positions.get("positions", []):
                if _position_matches_order(
                    position=position,
                    direction=direction,
                    volume=volume,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    comment=comment,
                ):
                    return {
                        "status": "RECONCILED_EXECUTION",
                        "success": True,
                        "source": "mt5_position_reconciliation",
                        "position": position,
                        "comment": comment,
                    }

        except Exception:
            # The original bridge error is more useful than a secondary
            # reconciliation failure, so keep retrying quietly.
            pass

        if attempt < attempts - 1:
            time.sleep(0.25)

    return None


def execute_market_order(
    direction,
    volume,
    stop_loss,
    take_profit,
    comment="XAUUSD_STRATEGY"
):

    if direction not in ("BUY", "SELL"):
        raise ValueError(
            "Direction must be BUY or SELL."
        )

    account = get_account()

    # Hard safety lock.
    if "demo" not in account["server"].lower():
        raise RuntimeError(
            f"EXECUTION BLOCKED: "
            f"account server is {account['server']}"
        )

    if not account["trade_allowed"]:
        raise RuntimeError(
            "MT5 trading is not allowed."
        )

    if not account["trade_expert"]:
        raise RuntimeError(
            "MT5 expert trading is not allowed."
        )

    if volume < 0.01:
        raise ValueError(
            "Volume below broker minimum."
        )

    if stop_loss is None:
        raise ValueError(
            "Stop loss is required."
        )

    if take_profit is None:
        raise ValueError(
            "Take profit is required."
        )

    payload = {
        "symbol": SYMBOL,
        "side": direction,
        "volume": round(volume, 2),
        "sl": round(stop_loss, 2),
        "tp": round(take_profit, 2),
        "magic": MAGIC,
        "comment": comment
    }

    # Safety net for a restart or repeated poll after MT5 has already created
    # the position.
    existing = _reconcile_existing_position(
        direction,
        volume,
        stop_loss,
        take_profit,
        comment,
        attempts=1,
    )

    if existing is not None:
        print(
            f"[ORDER RECONCILED] existing MT5 position matched "
            f"comment={comment}"
        )
        return existing

    try:
        response = requests.post(
            f"{BRIDGE_URL}/order",
            headers=HEADERS,
            json=payload,
            timeout=15
        )
    except requests.RequestException as exc:
        reconciled = _reconcile_existing_position(
            direction,
            volume,
            stop_loss,
            take_profit,
            comment,
        )

        if reconciled is not None:
            print(
                f"[ORDER RECONCILED] transport error after MT5 submission: "
                f"{type(exc).__name__}"
            )
            return reconciled

        raise RuntimeError(
            f"BRIDGE_ORDER_TRANSPORT_ERROR: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text.strip()

        # Critical protection: the broker may already have created the
        # position even though the HTTP layer reported an error. Never allow
        # the state machine to blindly retry until this reconciliation check
        # has completed.
        reconciled = _reconcile_existing_position(
            direction,
            volume,
            stop_loss,
            take_profit,
            comment,
        )

        if reconciled is not None:
            print(
                f"[ORDER RECONCILED] HTTP {response.status_code} but "
                f"position exists for comment={comment}"
            )
            return reconciled

        raise RuntimeError(
            f"BRIDGE_ORDER_REJECTED: HTTP {response.status_code} | "
            f"detail={detail}"
        ) from exc

    result = response.json()

    if isinstance(result, dict) and result.get("success") is False:
        reconciled = _reconcile_existing_position(
            direction,
            volume,
            stop_loss,
            take_profit,
            comment,
        )

        if reconciled is not None:
            return reconciled

        raise RuntimeError(
            f"BRIDGE_ORDER_REJECTED: detail={result}"
        )

    return result



def modify_position(ticket, symbol="XAUUSD", sl=None, tp=None, magic=MAGIC):
    payload = {
        "symbol": symbol,
        "ticket": int(ticket),
        "magic": int(magic),
        "sl": None if sl is None else round(float(sl), 2),
        "tp": None if tp is None else round(float(tp), 2),
    }
    response = requests.post(
        f"{BRIDGE_URL}/position/modify",
        headers=HEADERS,
        json=payload,
        timeout=10,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text.strip()
        raise RuntimeError(
            f"POSITION_MODIFY_REJECTED: HTTP {response.status_code} | detail={detail}"
        ) from exc
    result = response.json()
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(f"POSITION_MODIFY_REJECTED: {result}")
    return result


def close_position(ticket, symbol="XAUUSD", magic=MAGIC, comment="XAUUSD_POSITION_CLOSE"):
    payload = {
        "symbol": symbol,
        "ticket": int(ticket),
        "magic": int(magic),
        "comment": comment,
    }
    response = requests.post(
        f"{BRIDGE_URL}/position/close",
        headers=HEADERS,
        json=payload,
        timeout=10,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text.strip()
        raise RuntimeError(
            f"POSITION_CLOSE_REJECTED: HTTP {response.status_code} | detail={detail}"
        ) from exc
    return response.json()
