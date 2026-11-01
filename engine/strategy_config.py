# ============================================================
# XAUUSD STRATEGY CONFIGURATION
# ============================================================
#
# These values mirror the rules currently implemented in
# m1_setup_detector.py.
#
# Execution values are kept separate because the supplied
# setup source defines the setup through RETEST, but does not
# define entry / SL / TP mathematically.
# ============================================================

SYMBOL = "XAUUSD"
TIMEFRAME = "M1"

M1_BARS = 500

SWING_LOOKBACK = 2
LIQUIDITY_LOOKBACK = 20

MIN_SWEEP_DISTANCE = 0.05

BOS_LOOKAHEAD = 10

RETEST_LOOKAHEAD = 15

MIN_BOS_BODY = 0.10


# ============================================================
# EXECUTION PARAMETERS
# ============================================================

# These are execution defaults, not source-defined strategy
# rules.

EXECUTION_ENABLED = True

VOLUME = 0.01

RR_RATIO = 2.0

SL_BUFFER = 0.05

MAGIC = 260927