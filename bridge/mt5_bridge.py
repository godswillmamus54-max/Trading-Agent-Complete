import os
import hmac
import MetaTrader5 as mt5

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Header
)

from pydantic import BaseModel

from datetime import datetime, timezone


# ============================================================
# CONFIGURATION
# ============================================================

MT5_PATH = os.getenv("MT5_TERMINAL_PATH") or None
MAGIC = 260927

API_KEY = os.environ["MT5_BRIDGE_API_KEY"]


app = FastAPI(
    title="MT5 Trading Agent Bridge",
    version="2.3.0"
)


# ============================================================
# API AUTHENTICATION
# ============================================================

def verify_api_key(x_api_key: str | None):

    if not isinstance(x_api_key, str) or not hmac.compare_digest(x_api_key, API_KEY):

        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key"
        )


# ============================================================
# TIMEFRAME MAP
# ============================================================

TIMEFRAMES = {

    "M1": mt5.TIMEFRAME_M1,

    "M5": mt5.TIMEFRAME_M5,

    "M15": mt5.TIMEFRAME_M15,

    "M30": mt5.TIMEFRAME_M30,

    "H1": mt5.TIMEFRAME_H1,

    "H4": mt5.TIMEFRAME_H4,

    "D1": mt5.TIMEFRAME_D1,
}


# ============================================================
# MT5 CONNECTION
# ============================================================

def connect_mt5():

    terminal = mt5.terminal_info()

    if terminal is not None and terminal.connected:

        return True

    return mt5.initialize(
        path=MT5_PATH,
        timeout=10000
    )


def ensure_connection():

    if not connect_mt5():

        raise HTTPException(

            status_code=503,

            detail={

                "error":
                    "MT5 connection failed",

                "mt5_error":
                    str(mt5.last_error())
            }
        )


def ensure_demo_account():

    """Fail closed unless MT5 is connected to a permitted demo account."""

    account = mt5.account_info()

    if account is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Unable to verify MT5 account",
                "mt5_error": str(mt5.last_error()),
            },
        )

    demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
    account_mode = getattr(account, "trade_mode", None)

    if demo_mode is None or account_mode is None:
        raise HTTPException(
            status_code=503,
            detail="Unable to verify demo-account mode; trading is blocked",
        )

    if int(account_mode) != int(demo_mode):
        raise HTTPException(
            status_code=403,
            detail="EXECUTION BLOCKED: this bridge is restricted to MT5 demo accounts",
        )

    if not bool(getattr(account, "trade_allowed", False)):
        raise HTTPException(
            status_code=403,
            detail="MT5 account does not permit trading",
        )

    if not bool(getattr(account, "trade_expert", False)):
        raise HTTPException(
            status_code=403,
            detail="MT5 expert trading is not permitted",
        )

    return account


# ============================================================
# ORDER REQUEST
# ============================================================

class OrderRequest(BaseModel):

    symbol: str

    side: str

    volume: float

    sl: float

    tp: float

    deviation: int = 20

    magic: int = MAGIC

    comment: str = "XAUUSD_TRADING_AGENT"


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup_event():

    print("=" * 70)
    print("MT5 TRADING AGENT BRIDGE")
    print("=" * 70)

    print("Connecting to MetaTrader 5...")

    if not connect_mt5():

        print(
            "ERROR: MT5 initialization failed:"
        )

        print(
            mt5.last_error()
        )

    else:

        account = mt5.account_info()

        if account:

            print(
                f"MT5 connected | "
                f"Account: {account.login} | "
                f"Server: {account.server} | "
                f"Balance: {account.balance}"
            )

        else:

            print(
                "MT5 connected but account information unavailable."
            )

    print("=" * 70)


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health(

    x_api_key: str | None = Header(
        default=None
    )

):

    verify_api_key(x_api_key)

    ensure_connection()

    terminal = mt5.terminal_info()

    account = mt5.account_info()

    if terminal is None:

        raise HTTPException(

            status_code=503,

            detail="MT5 terminal information unavailable"
        )

    response = {

        "status":
            "ok",

        "mt5_connected":
            True,

        "terminal_connected":
            terminal.connected,

        "account":
            None
    }

    if account:

        response["account"] = {

            "login":
                account.login,

            "server":
                account.server,

            "currency":
                account.currency,

            "balance":
                float(account.balance),

            "equity":
                float(account.equity),

            "trade_allowed":
                bool(account.trade_allowed),

            "trade_expert":
                bool(account.trade_expert)
        }

    return response


# ============================================================
# ACCOUNT
# ============================================================

@app.get("/account")
def account_endpoint(

    x_api_key: str | None = Header(
        default=None
    )

):

    verify_api_key(x_api_key)

    ensure_connection()

    account = mt5.account_info()

    if account is None:

        raise HTTPException(

            status_code=503,

            detail={

                "error":
                    "Unable to retrieve account",

                "mt5_error":
                    str(mt5.last_error())
            }
        )

    return {

        "login":
            account.login,

        "server":
            account.server,

        "trade_mode":
            int(account.trade_mode),

        "is_demo":
            account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO,

        "currency":
            account.currency,

        "balance":
            float(account.balance),

        "equity":
            float(account.equity),

        "margin":
            float(account.margin),

        "free_margin":
            float(account.margin_free),

        "margin_level":
            (
                float(account.margin_level)
                if account.margin_level is not None
                else None
            ),

        "trade_allowed":
            bool(account.trade_allowed),

        "trade_expert":
            bool(account.trade_expert)
    }


# ============================================================
# SYMBOLS
# ============================================================

@app.get("/symbols")
def symbols(

    x_api_key: str | None = Header(
        default=None
    )

):

    verify_api_key(x_api_key)

    ensure_connection()

    symbol_list = mt5.symbols_get()

    if symbol_list is None:

        raise HTTPException(

            status_code=503,

            detail={

                "error":
                    "Unable to retrieve symbols",

                "mt5_error":
                    str(mt5.last_error())
            }
        )

    result = []

    for symbol in symbol_list:

        result.append({

            "name":
                symbol.name,

            "description":
                symbol.description,

            "path":
                symbol.path,

            "visible":
                symbol.visible,

            "trade_mode":
                symbol.trade_mode
        })

    return {

        "count":
            len(result),

        "symbols":
            result
    }


# ============================================================
# MARKET DATA
# ============================================================

@app.get("/market")
def market(

    symbol: str = Query(
        "XAUUSD",
        min_length=1
    ),

    timeframe: str = Query(
        "M15",
        min_length=1
    ),

    bars: int = Query(
        200,
        ge=10,
        le=1000
    ),

    x_api_key: str | None = Header(
        default=None
    )

):

    verify_api_key(x_api_key)

    symbol = symbol.upper()

    timeframe = timeframe.upper()

    if timeframe not in TIMEFRAMES:

        raise HTTPException(

            status_code=400,

            detail={

                "error":
                    "Unsupported timeframe",

                "supported":
                    list(TIMEFRAMES.keys())
            }
        )

    ensure_connection()

    # --------------------------------------------------------
    # SELECT SYMBOL
    # --------------------------------------------------------

    if not mt5.symbol_select(
        symbol,
        True
    ):

        raise HTTPException(

            status_code=404,

            detail={

                "error":
                    f"Unable to select symbol {symbol}",

                "mt5_error":
                    str(mt5.last_error())
            }
        )

    # --------------------------------------------------------
    # SYMBOL INFO
    # --------------------------------------------------------

    info = mt5.symbol_info(
        symbol
    )

    if info is None:

        raise HTTPException(

            status_code=404,

            detail={

                "error":
                    f"Symbol {symbol} not found",

                "mt5_error":
                    str(mt5.last_error())
            }
        )

    # --------------------------------------------------------
    # CLOSED CANDLES
    # --------------------------------------------------------

    rates = mt5.copy_rates_from_pos(

        symbol,

        TIMEFRAMES[timeframe],

        1,

        bars
    )

    if rates is None:

        raise HTTPException(

            status_code=503,

            detail={

                "error":
                    "Unable to retrieve market data",

                "mt5_error":
                    str(mt5.last_error())
            }
        )

    candles = []

    for candle in rates:

        candle_time = datetime.fromtimestamp(

            int(candle["time"]),

            tz=timezone.utc
        )

        candles.append({

            "time":
                candle_time.isoformat(),

            "open":
                float(candle["open"]),

            "high":
                float(candle["high"]),

            "low":
                float(candle["low"]),

            "close":
                float(candle["close"]),

            "tick_volume":
                int(candle["tick_volume"]),

            "spread":
                int(candle["spread"]),

            "real_volume":
                int(candle["real_volume"])
        })

    # --------------------------------------------------------
    # CURRENT TICK
    # --------------------------------------------------------

    tick = mt5.symbol_info_tick(
        symbol
    )

    current_price = None

    if tick:

        if tick.bid > 0 or tick.ask > 0:

            current_price = {

                "bid":
                    float(tick.bid),

                "ask":
                    float(tick.ask),

                "last":
                    float(tick.last),

                "time": (

                    datetime.fromtimestamp(

                        int(tick.time),

                        tz=timezone.utc

                    ).isoformat()

                    if tick.time > 0

                    else None
                )
            }

    return {

        "symbol":
            symbol,

        "description":
            info.description,

        "timeframe":
            timeframe,

        "bars_requested":
            bars,

        "bars_returned":
            len(candles),

        "closed_candles_only":
            True,

        "symbol_info": {

            "digits":
                info.digits,

            "point":
                info.point,

            "contract_size":
                info.trade_contract_size,

            "volume_min":
                info.volume_min,

            "volume_max":
                info.volume_max,

            "volume_step":
                info.volume_step
        },

        "current_tick":
            current_price,

        "candles":
            candles
    }


# ============================================================
# POSITIONS
# ============================================================

@app.get("/positions")
def positions(

    symbol: str | None = Query(
        default=None
    ),

    x_api_key: str | None = Header(
        default=None
    )

):

    verify_api_key(x_api_key)

    ensure_connection()

    if symbol:

        symbol = symbol.upper()

        position_list = mt5.positions_get(
            symbol=symbol
        )

    else:

        position_list = mt5.positions_get()

    if position_list is None:

        raise HTTPException(

            status_code=503,

            detail={

                "error":
                    "Unable to retrieve positions",

                "mt5_error":
                    str(mt5.last_error())
            }
        )

    result = []

    for position in position_list:

        result.append({

            "ticket":
                int(position.ticket),

            "symbol":
                position.symbol,

            "type":
                int(position.type),

            "volume":
                float(position.volume),

            "price_open":
                float(position.price_open),

            "sl":
                float(position.sl),

            "tp":
                float(position.tp),

            "profit":
                float(position.profit),

            "magic":
                int(position.magic),

            "comment":
                position.comment,

            "time": (

                datetime.fromtimestamp(

                    int(position.time),

                    tz=timezone.utc

                ).isoformat()

                if position.time > 0

                else None
            )
        })

    return {

        "count":
            len(result),

        "positions":
            result
    }


# ============================================================
# ORDER EXECUTION HELPERS
# ============================================================

def safe_int(value, default=0):
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


# ============================================================
# ORDER EXECUTION
# ============================================================

@app.post("/order")
def place_order(

    request: OrderRequest,

    x_api_key: str | None = Header(
        default=None
    )

):

    verify_api_key(x_api_key)

    ensure_connection()
    ensure_demo_account()

    symbol = request.symbol.upper()

    side = request.side.upper()

    # --------------------------------------------------------
    # VALIDATE SIDE
    # --------------------------------------------------------

    if side not in ["BUY", "SELL"]:

        raise HTTPException(

            status_code=400,

            detail="side must be BUY or SELL"
        )

    # --------------------------------------------------------
    # SELECT SYMBOL
    # --------------------------------------------------------

    if not mt5.symbol_select(
        symbol,
        True
    ):

        raise HTTPException(

            status_code=404,

            detail={

                "error":
                    f"Unable to select symbol {symbol}",

                "mt5_error":
                    str(mt5.last_error())
            }
        )

    # --------------------------------------------------------
    # SYMBOL INFO
    # --------------------------------------------------------

    info = mt5.symbol_info(
        symbol
    )

    if info is None:

        raise HTTPException(

            status_code=404,

            detail={
                "error":
                    f"Symbol {symbol} not found",

                "mt5_error":
                    str(mt5.last_error())
            }
        )

    # --------------------------------------------------------
    # TRADING ENABLED?
    # --------------------------------------------------------

    if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:

        raise HTTPException(

            status_code=400,

            detail=
                f"Trading is disabled for {symbol}"
        )

    # --------------------------------------------------------
    # CURRENT TICK
    # --------------------------------------------------------

    tick = mt5.symbol_info_tick(
        symbol
    )

    if tick is None:

        raise HTTPException(

            status_code=503,

            detail={
                "error":
                    f"No tick available for {symbol}",

                "mt5_error":
                    str(mt5.last_error())
            }
        )

    # --------------------------------------------------------
    # IDEMPOTENCY GUARD
    # --------------------------------------------------------
    # New engine versions assign a unique comment to each setup. If an
    # identical setup reaches the bridge again after an HTTP/transport error,
    # return the existing position instead of opening another one.
    existing_positions = mt5.positions_get(symbol=symbol)

    if existing_positions:

        expected_position_type = (
            mt5.POSITION_TYPE_BUY
            if side == "BUY"
            else mt5.POSITION_TYPE_SELL
        )

        for existing in existing_positions:

            if (
                int(existing.magic) == int(request.magic)
                and int(existing.type) == int(expected_position_type)
                and str(existing.comment) == str(request.comment)
            ):

                return {
                    "success": True,
                    "status": "IDEMPOTENT_EXISTING_POSITION",
                    "retcode": int(mt5.TRADE_RETCODE_DONE),
                    "retcode_description": "Existing matching position returned; no duplicate order sent.",
                    "order": 0,
                    "deal": 0,
                    "symbol": symbol,
                    "side": side,
                    "volume": float(existing.volume),
                    "price": float(existing.price_open),
                    "sl": float(existing.sl),
                    "tp": float(existing.tp),
                    "magic": int(request.magic),
                    "comment": str(existing.comment),
                    "position_ticket": int(existing.ticket),
                }

    # --------------------------------------------------------
    # VOLUME VALIDATION
    # --------------------------------------------------------

    requested_volume = float(
        request.volume
    )

    if requested_volume <= 0:

        raise HTTPException(

            status_code=400,

            detail="Volume must be greater than zero"
        )

    volume_min = float(
        info.volume_min
    )

    volume_max = float(
        info.volume_max
    )

    volume_step = float(
        info.volume_step
    )

    if requested_volume < volume_min:

        raise HTTPException(

            status_code=400,

            detail={

                "error":
                    "Volume below broker minimum",

                "requested":
                    requested_volume,

                "minimum":
                    volume_min
            }
        )

    if requested_volume > volume_max:

        raise HTTPException(

            status_code=400,

            detail={

                "error":
                    "Volume above broker maximum",

                "requested":
                    requested_volume,

                "maximum":
                    volume_max
            }
        )

    # --------------------------------------------------------
    # NORMALIZE VOLUME
    # --------------------------------------------------------

    volume = round(

        round(
            requested_volume /
            volume_step
        ) * volume_step,

        8
    )

    # --------------------------------------------------------
    # ORDER TYPE
    # --------------------------------------------------------

    if side == "BUY":

        order_type = (
            mt5.ORDER_TYPE_BUY
        )

        price = float(
            tick.ask
        )

    else:

        order_type = (
            mt5.ORDER_TYPE_SELL
        )

        price = float(
            tick.bid
        )

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    if price <= 0:

        raise HTTPException(

            status_code=503,

            detail="Invalid market price"
        )

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    digits = int(
        info.digits
    )

    sl = round(
        float(request.sl),
        digits
    )

    tp = round(
        float(request.tp),
        digits
    )

    # --------------------------------------------------------
    # BUY VALIDATION
    # --------------------------------------------------------

    if side == "BUY":

        if sl >= price:

            raise HTTPException(

                status_code=400,

                detail=
                    "BUY SL must be below entry price"
            )

        if tp <= price:

            raise HTTPException(

                status_code=400,

                detail=
                    "BUY TP must be above entry price"
            )

    # --------------------------------------------------------
    # SELL VALIDATION
    # --------------------------------------------------------

    if side == "SELL":

        if sl <= price:

            raise HTTPException(

                status_code=400,

                detail=
                    "SELL SL must be above entry price"
            )

        if tp >= price:

            raise HTTPException(

                status_code=400,

                detail=
                    "SELL TP must be below entry price"
            )

    # --------------------------------------------------------
    # FILLING MODE
    # --------------------------------------------------------
    # IMPORTANT: the installed MetaTrader5 Python package exposes the
    # ORDER_FILLING_* constants used in trade requests, but this installed
    # build does not expose SYMBOL_FILLING_* constants.
    #
    # MQL5 symbol filling flags are: FOK=1, IOC=2, BOC=4. We only use
    # FOK/IOC here because this is a market DEAL request; RETURN is not a
    # safe fallback for every market-execution symbol.

    filling_mode = int(getattr(info, "filling_mode", 0) or 0)

    SYMBOL_FILLING_FOK_FLAG = 1
    SYMBOL_FILLING_IOC_FLAG = 2

    if filling_mode & SYMBOL_FILLING_IOC_FLAG:
        filling_constant = mt5.ORDER_FILLING_IOC
        filling_name = "IOC"
    elif filling_mode & SYMBOL_FILLING_FOK_FLAG:
        filling_constant = mt5.ORDER_FILLING_FOK
        filling_name = "FOK"
    else:
        # XAUUSD previously accepted IOC on this MetaQuotes-Demo account.
        # Keep IOC as the final fallback instead of referencing unavailable
        # SYMBOL_FILLING_* attributes or blindly using RETURN.
        filling_constant = mt5.ORDER_FILLING_IOC
        filling_name = "IOC_FALLBACK"

    # --------------------------------------------------------
    # ORDER REQUEST
    # --------------------------------------------------------

    trade_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": int(request.deviation),
        "magic": int(request.magic),
        "comment": request.comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_constant,
    }

    print(
        f"[ORDER REQUEST] {symbol} {side} "
        f"volume={volume} price={price:.2f} "
        f"sl={sl:.2f} tp={tp:.2f} filling={filling_name}"
    )

    # --------------------------------------------------------
    # PRE-FLIGHT ORDER CHECK + MARGIN-AWARE VOLUME CAP
    # --------------------------------------------------------
    # The strategy calculates volume from requested dollar risk. On a small
    # account, that requested volume can exceed available margin. MT5 reports
    # this as retcode 10019 (No money). Reduce only for that specific case,
    # one broker volume step at a time, until order_check passes.

    requested_volume = float(trade_request["volume"])
    volume_step = float(info.volume_step)
    volume_min = float(info.volume_min)
    adjusted_volume = requested_volume
    check = None

    while adjusted_volume + 1e-12 >= volume_min:

        trade_request["volume"] = round(adjusted_volume, 8)
        check = mt5.order_check(trade_request)

        if check is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "MT5 order_check returned None",
                    "mt5_error": str(mt5.last_error()),
                    "request": trade_request,
                    "requested_volume": requested_volume,
                    "symbol_diagnostics": {
                        "trade_mode": int(info.trade_mode),
                        "trade_exemode": int(info.trade_exemode),
                        "filling_mode": filling_mode,
                        "trade_stops_level": int(getattr(info, "trade_stops_level", 0) or 0),
                        "trade_freeze_level": int(getattr(info, "trade_freeze_level", 0) or 0),
                        "volume_min": volume_min,
                        "volume_max": float(info.volume_max),
                        "volume_step": volume_step,
                    },
                },
            )

        check_retcode = int(getattr(check, "retcode", -1))

        if check_retcode == 0:
            break

        if check_retcode == 10019:
            next_volume = round(adjusted_volume - volume_step, 8)

            if next_volume < volume_min:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "Insufficient margin even at broker minimum volume",
                        "retcode": check_retcode,
                        "comment": str(getattr(check, "comment", "")),
                        "requested_volume": requested_volume,
                        "minimum_volume": volume_min,
                        "mt5_error": str(mt5.last_error()),
                        "request": trade_request,
                        "order_check": str(check),
                        "symbol_diagnostics": {
                            "trade_mode": int(info.trade_mode),
                            "trade_exemode": int(info.trade_exemode),
                            "filling_mode": filling_mode,
                            "trade_stops_level": int(getattr(info, "trade_stops_level", 0) or 0),
                            "trade_freeze_level": int(getattr(info, "trade_freeze_level", 0) or 0),
                            "volume_min": volume_min,
                            "volume_max": float(info.volume_max),
                            "volume_step": volume_step,
                        },
                    },
                )

            adjusted_volume = next_volume
            continue

        raise HTTPException(
            status_code=400,
            detail={
                "error": "MT5 order_check rejected request",
                "retcode": check_retcode,
                "comment": str(getattr(check, "comment", "")),
                "mt5_error": str(mt5.last_error()),
                "request": trade_request,
                "order_check": str(check),
                "symbol_diagnostics": {
                    "trade_mode": int(info.trade_mode),
                    "trade_exemode": int(info.trade_exemode),
                    "filling_mode": filling_mode,
                    "trade_stops_level": int(getattr(info, "trade_stops_level", 0) or 0),
                    "trade_freeze_level": int(getattr(info, "trade_freeze_level", 0) or 0),
                    "volume_min": volume_min,
                    "volume_max": float(info.volume_max),
                    "volume_step": volume_step,
                },
            },
        )

    if adjusted_volume < requested_volume:
        print(
            f"[MARGIN CAP] requested_volume={requested_volume:.2f} "
            f"-> approved_volume={adjusted_volume:.2f} "
            f"reason=MT5_NO_MONEY"
        )

    # --------------------------------------------------------
    # SEND
    # --------------------------------------------------------

    ensure_demo_account()
    result = mt5.order_send(
        trade_request
    )

    if result is None:

        raise HTTPException(

            status_code=503,

            detail={

                "error":
                    "MT5 order_send returned None",

                "mt5_error":
                    str(mt5.last_error())
            }
        )

    # Market execution can legitimately report a completed partial fill or
    # an accepted placement. Treat those as accepted submissions so the
    # engine does not blindly resend the same setup.
    accepted_ret_codes = {
        int(mt5.TRADE_RETCODE_DONE),
        int(mt5.TRADE_RETCODE_DONE_PARTIAL),
        int(mt5.TRADE_RETCODE_PLACED),
    }

    success = int(result.retcode) in accepted_ret_codes

    response = {

        "success":
            success,

        "retcode":
            int(result.retcode),

        "retcode_description":
            result.comment,

        "accepted":
            success,

        "order":
            safe_int(getattr(result, "order", 0)),

        "deal":
            safe_int(getattr(result, "deal", 0)),

        "symbol":
            symbol,

        "side":
            side,

        "volume":
            adjusted_volume,

        "requested_volume":
            requested_volume,

        "volume_adjusted":
            adjusted_volume < requested_volume,

        "price":
            price,

        "sl":
            sl,

        "tp":
            tp,

        "magic":
            int(request.magic),

        "comment":
            request.comment
    }

    if not success:

        raise HTTPException(

            status_code=400,

            detail={
                "error": "MT5 order_send rejected request",
                "retcode": int(result.retcode),
                "comment": str(result.comment),
                "order": safe_int(getattr(result, "order", 0)),
                "deal": safe_int(getattr(result, "deal", 0)),
                "mt5_error": str(mt5.last_error()),
                "response": response,
                "request": trade_request,
            }
        )

    return response


# ============================================================
# POSITION MANAGEMENT
# ============================================================

class PositionModifyRequest(BaseModel):
    symbol: str
    ticket: int
    sl: float | None = None
    tp: float | None = None
    deviation: int = 20
    magic: int = MAGIC


class PositionCloseRequest(BaseModel):
    symbol: str
    ticket: int
    deviation: int = 20
    magic: int = MAGIC
    comment: str = "XAUUSD_POSITION_CLOSE"


def _select_market_filling(info):
    filling_mode = int(getattr(info, "filling_mode", 0) or 0)
    if filling_mode & 2:
        return mt5.ORDER_FILLING_IOC, "IOC"
    if filling_mode & 1:
        return mt5.ORDER_FILLING_FOK, "FOK"
    return mt5.ORDER_FILLING_IOC, "IOC_FALLBACK"


def _find_position(ticket, symbol):
    positions = mt5.positions_get(symbol=symbol.upper())
    if positions is None:
        return None
    for position in positions:
        if int(position.ticket) == int(ticket):
            return position
    return None


@app.post("/position/modify")
def modify_position(
    request: PositionModifyRequest,
    x_api_key: str | None = Header(default=None),
):
    verify_api_key(x_api_key)
    ensure_connection()
    ensure_demo_account()

    symbol = request.symbol.upper()
    position = _find_position(request.ticket, symbol)
    if position is None:
        raise HTTPException(status_code=404, detail=f"Position {request.ticket} not found")
    if int(position.magic) != int(request.magic):
        raise HTTPException(
            status_code=403,
            detail="Position ownership check failed: magic number does not match",
        )

    info = mt5.symbol_info(symbol)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

    digits = int(info.digits)
    current_sl = float(position.sl or 0.0)
    current_tp = float(position.tp or 0.0)
    sl = current_sl if request.sl is None else round(float(request.sl), digits)
    tp = current_tp if request.tp is None else round(float(request.tp), digits)

    if int(position.type) == int(mt5.POSITION_TYPE_BUY):
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise HTTPException(status_code=503, detail="No current tick")
        if sl and sl >= float(tick.bid):
            raise HTTPException(status_code=400, detail="BUY SL must remain below current bid")
        if tp and tp <= float(tick.ask):
            raise HTTPException(status_code=400, detail="BUY TP must remain above current ask")
    else:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise HTTPException(status_code=503, detail="No current tick")
        if sl and sl <= float(tick.ask):
            raise HTTPException(status_code=400, detail="SELL SL must remain above current ask")
        if tp and tp >= float(tick.bid):
            raise HTTPException(status_code=400, detail="SELL TP must remain below current bid")

    request_payload = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": int(position.ticket),
        "sl": sl,
        "tp": tp,
    }

    ensure_demo_account()
    result = mt5.order_send(request_payload)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "MT5 order_send returned None", "mt5_error": str(mt5.last_error())},
        )

    success = int(result.retcode) == int(mt5.TRADE_RETCODE_DONE)
    response = {
        "success": success,
        "retcode": int(result.retcode),
        "retcode_description": str(result.comment),
        "symbol": symbol,
        "ticket": int(position.ticket),
        "sl": sl,
        "tp": tp,
    }

    if not success:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "MT5 position modification rejected",
                "response": response,
                "mt5_error": str(mt5.last_error()),
            },
        )

    return response


@app.post("/position/close")
def close_position(
    request: PositionCloseRequest,
    x_api_key: str | None = Header(default=None),
):
    verify_api_key(x_api_key)
    ensure_connection()
    ensure_demo_account()

    symbol = request.symbol.upper()
    position = _find_position(request.ticket, symbol)
    if position is None:
        return {
            "success": True,
            "status": "ALREADY_CLOSED",
            "ticket": int(request.ticket),
            "symbol": symbol,
        }

    if int(position.magic) != int(request.magic):
        raise HTTPException(
            status_code=403,
            detail="Position ownership check failed: magic number does not match",
        )

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        raise HTTPException(status_code=503, detail="Unable to read symbol/tick for close")

    close_type = (
        mt5.ORDER_TYPE_SELL
        if int(position.type) == int(mt5.POSITION_TYPE_BUY)
        else mt5.ORDER_TYPE_BUY
    )
    price = float(tick.bid) if close_type == mt5.ORDER_TYPE_SELL else float(tick.ask)
    filling_constant, filling_name = _select_market_filling(info)

    trade_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(position.volume),
        "type": close_type,
        "position": int(position.ticket),
        "price": price,
        "deviation": int(request.deviation),
        "magic": int(request.magic),
        "comment": request.comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_constant,
    }

    print(
        f"[POSITION CLOSE] ticket={int(position.ticket)} "
        f"symbol={symbol} volume={float(position.volume):.2f} filling={filling_name}"
    )

    ensure_demo_account()
    result = mt5.order_send(trade_request)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "MT5 close order_send returned None", "mt5_error": str(mt5.last_error())},
        )

    success = int(result.retcode) in {
        int(mt5.TRADE_RETCODE_DONE),
        int(mt5.TRADE_RETCODE_DONE_PARTIAL),
        int(mt5.TRADE_RETCODE_PLACED),
    }

    response = {
        "success": success,
        "retcode": int(result.retcode),
        "retcode_description": str(result.comment),
        "ticket": int(position.ticket),
        "symbol": symbol,
        "volume": float(position.volume),
        "price": price,
        "comment": request.comment,
    }

    if not success:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "MT5 position close rejected",
                "response": response,
                "mt5_error": str(mt5.last_error()),
                "request": trade_request,
            },
        )

    return response


# ============================================================
# SHUTDOWN
# ============================================================

@app.on_event("shutdown")
def shutdown_event():

    print(
        "Shutting down MT5 connection..."
    )

    mt5.shutdown()

    print(
        "MT5 connection closed."
    )


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(

        app,

        host="127.0.0.1",

        port=8000
    )