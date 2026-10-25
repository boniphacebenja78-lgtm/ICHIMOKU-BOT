"""Market data via the MetaTrader5 terminal.

Windows only. The official `MetaTrader5` pip package talks to a MT5
terminal running on the same machine over a local IPC channel - there is
no cloud/REST equivalent from MetaQuotes. Install the terminal, log into
your Exness account in it at least once, then this module can drive it.
"""

import os
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv

load_dotenv()   # reads .env in the current folder into os.environ

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1,
}

COLS = ["time", "open", "high", "low", "close", "tick_volume"]


def connect():
    """Attach to (or launch) the local MT5 terminal and log into Exness.

    Credentials come from environment variables (.env), never hardcoded:
    MT5_LOGIN (your account number), MT5_PASSWORD, MT5_SERVER (the exact
    server name shown on your MT5 login screen, e.g. "Exness-MT5Real8").

    MT5_PATH (optional): full path to terminal64.exe. initialize() can't
    always auto-locate the terminal - if it fails with "MetaTrader 5 x64
    not found", set this in .env to the exact path (right-click your MT5
    desktop icon -> Open file location -> copy the path to terminal64.exe).
    """
    path = os.environ.get("MT5_PATH")
    ok = mt5.initialize(path) if path else mt5.initialize()
    if not ok:
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
    login = int(os.environ["MT5_LOGIN"])
    password = os.environ["MT5_PASSWORD"]
    server = os.environ["MT5_SERVER"]
    if not mt5.login(login, password=password, server=server):
        err = mt5.last_error()
        mt5.shutdown()
        raise RuntimeError(f"MT5 login() failed: {err}")
    return mt5


def _to_frame(rates):
    df = pd.DataFrame(rates)[COLS].rename(columns={"tick_volume": "volume"})
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.set_index("time").astype(float)


def ensure_symbol(symbol):
    """Make sure a symbol is selected/visible in Market Watch before use.

    Accept a unique broker suffix when the requested base name is not exact.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        available = mt5.symbols_get() or ()
        matches = [item for item in available if item.name.casefold().startswith(symbol.casefold())]
        if len(matches) == 1:
            info = matches[0]
        elif matches:
            names = ", ".join(item.name for item in matches)
            raise RuntimeError(f"symbol '{symbol}' is ambiguous; matching MT5 symbols: {names}")
        else:
            raise RuntimeError(f"symbol '{symbol}' not found in the connected MT5 account")
    if not info.visible and not mt5.symbol_select(info.name, True):
        raise RuntimeError(f"Could not select MT5 symbol '{info.name}': {mt5.last_error()}")
    return info


def lots_for(symbol, units):
    """Convert raw currency units (from strategy.position_size) into a
    valid lot size for this specific symbol. Contract size, step, and
    minimum volume all differ between forex, gold, and crypto instruments
    on Exness - this reads the real numbers from MT5 rather than assuming
    a single lot convention across every symbol.
    """
    info = ensure_symbol(symbol)
    lots = units / info.trade_contract_size
    lots = max(info.volume_min, round(lots / info.volume_step) * info.volume_step)
    return round(lots, 2)


def fetch_recent(symbol, timeframe, limit=300):
    """Latest candles. The final one is still forming - drop it before use."""
    symbol = ensure_symbol(symbol).name
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[timeframe], 0, limit)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"copy_rates_from_pos failed: {mt5.last_error()}")
    return _to_frame(rates)


def fetch_history(symbol, timeframe, since_days=365, cache=True):
    """Historical candles for backtesting, cached to disk after first pull."""
    path = f"cache_{symbol}_{timeframe}.csv"
    if cache and os.path.exists(path):
        return pd.read_csv(path, index_col="time", parse_dates=["time"])

    symbol = ensure_symbol(symbol).name
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=since_days)
    rates = mt5.copy_rates_range(symbol, TIMEFRAMES[timeframe], date_from, date_to)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"copy_rates_range failed: {mt5.last_error()}")

    df = _to_frame(rates)
    if cache:
        df.to_csv(path)
    return df
