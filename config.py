"""All tunable settings in one place. Never put credentials here - use .env"""

# --- broker: Exness via MetaTrader 5 ---
# MT5_SYMBOL: exact name as it appears in your MT5 Market Watch - Exness
# sometimes suffixes symbols (e.g. "EURUSDm" on some account types), so
# check the terminal rather than assuming "EURUSD" is correct.
MT5_SYMBOL = "EURUSD"       # used by bot.py (single-symbol live trading)
MT5_SYMBOLS = ["EURUSD", "XAUUSD", "GBPUSD", "BTCUSD"]  # used by backtest.py/watch.py
MT5_TIMEFRAME = "H4"        # M1, M5, M15, M30, H1, H4, D1
# Lot size, step, and minimum volume are no longer hardcoded here - gold,
# crypto, and forex pairs have different contract sizes on Exness, so
# data.lots_for() reads the correct one from MT5 for each symbol.

# --- daily alert window (watch.py only checks for setups in this window) ---
SESSION_START_HOUR = 13     # 1pm GMT / UTC - New York session open
SESSION_END_HOUR = 17       # 5pm GMT / UTC
POLL_SECONDS = 120          # how often watch.py checks for a fresh setup

# --- multi-timeframe confirmation ---
# Structure (support/resistance zones) comes from the HIGH timeframes -
# a level only counts if it shows up on the bigger picture. Entries are
# timed off the LOW timeframes, waiting for a candlestick confirmation
# right at that structural level.
HTF_LIST = ["W1", "D1", "H4"]       # timeframes used to build S/R zones
CONFIRM_LIST = ["H4", "H1"]         # timeframes checked for engulfing/tweezer
TWEEZER_TOL_PCT = 0.001             # how close two wicks must be to count as a tweezer match

# --- strategy: support/resistance + trendline confluence ---
SWING_ORDER = 5             # bars each side needed to confirm a swing point
ZONE_TOL_PCT = 0.0025       # price tolerance for clustering zones / confluence match
MIN_TOUCHES = 2             # a zone needs this many touches to count as real S/R
TRENDLINE_MIN_POINTS = 3    # minimum swing points required to fit a trendline
REJECTION_WICK_FRAC = 0.4   # min fraction of candle range that must be the rejecting wick

# --- risk ---
EQUITY = 100.0               # starting capital in account currency
RISK_PER_TRADE = 0.01        # fraction of equity risked per trade (1%)
STOP_LOSS_PCT = 0.01         # stop distance below entry (forex moves far less than crypto)
MAX_DAILY_LOSS = 0.05        # kill switch: stop trading after -5% in a day

# --- costs ---
# Forex/CFD cost is dominated by the spread, not a flat fee - these are a
# rough stand-in until you pull your actual Exness spread for MT5_SYMBOL.
FEE_PCT = 0.0
SLIPPAGE_PCT = 0.0005

# --- execution ---
DRY_RUN = True               # True = log orders only, never send them
