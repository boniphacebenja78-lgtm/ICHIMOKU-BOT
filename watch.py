"""Daily alert-only watcher, multi-timeframe, across multiple symbols.

Runs only during your trading session (config.SESSION_START_HOUR to
SESSION_END_HOUR, in GMT/UTC). Structure (support/resistance zones) comes
from the higher timeframes in config.HTF_LIST (W1/D1/H4) - a level only
counts if the bigger picture shows it. Entries are confirmed by an
engulfing or tweezer candlestick pattern on the timeframes in
config.CONFIRM_LIST (H4/H1), checked against config.MT5_SYMBOLS on
every poll. It never sends an order - it beeps and prints the entry,
stop, and suggested lot size, and you place the trade yourself in MT5.
"""

import time
from datetime import datetime, timezone

import config
import data
import strategy

try:
    import winsound
    def beep():
        winsound.Beep(1000, 400)
except ImportError:                    # not on Windows / no sound device
    def beep():
        print("\a", end="")


def in_session(now=None):
    now = now or datetime.now(timezone.utc)
    return config.SESSION_START_HOUR <= now.hour < config.SESSION_END_HOUR


def check_symbol(symbol, last_alerted):
    """Pull every timeframe this symbol's signal needs, check the latest
    closed H1 bar, alert once per bar on a fresh setup."""
    needed = ["H1"] + config.HTF_LIST + config.CONFIRM_LIST
    dfs = {}
    for tf in dict.fromkeys(needed):       # de-dupe, keep order
        try:
            df = data.fetch_recent(symbol, tf, limit=300)
        except RuntimeError as e:
            print(f"  {symbol}: skipped ({e})")
            return last_alerted
        dfs[tf] = df.iloc[:-1]             # drop the still-forming candle

    h1 = dfs["H1"]
    last_ts = h1.index[-1]
    want = int(strategy.signals_mtf(dfs).iloc[-1])

    if want == 1 and last_ts != last_alerted:
        price = float(h1["close"].iloc[-1])
        stop = price * (1 - config.STOP_LOSS_PCT)
        units = strategy.position_size(config.EQUITY, price, stop)
        lots = data.lots_for(symbol, units)
        beep()
        print("=" * 52)
        print(f"SETUP  {symbol}  bar closed {last_ts}")
        print(f"  entry ~ {price:.5f}")
        print(f"  stop  ~ {stop:.5f}  ({config.STOP_LOSS_PCT:.1%} below entry)")
        print(f"  size  ~ {lots} lots  (risking {config.RISK_PER_TRADE:.1%} of "
              f"{config.EQUITY:.2f} account currency)")
        print("  Confirmed by structure on", config.HTF_LIST,
              "+ candlestick pattern on", config.CONFIRM_LIST)
        print("  This is a suggestion, not an order - check it against the")
        print("  chart yourself before placing anything in MT5.")
        print("=" * 52)
        return last_ts

    print(f"  {symbol}: last H1 bar {last_ts} | signal={want} | no new setup")
    return last_alerted


def main():
    data.connect()
    print(f"watching {config.MT5_SYMBOLS} | structure {config.HTF_LIST} | "
          f"confirm {config.CONFIRM_LIST} | "
          f"session {config.SESSION_START_HOUR}:00-{config.SESSION_END_HOUR}:00 UTC | "
          f"alert-only, no auto-trading")
    last_alerted = {symbol: None for symbol in config.MT5_SYMBOLS}
    try:
        while True:
            now_str = f"{datetime.now(timezone.utc):%H:%M} UTC"
            if in_session():
                print(f"{now_str} | checking {len(config.MT5_SYMBOLS)} symbols")
                for symbol in config.MT5_SYMBOLS:
                    last_alerted[symbol] = check_symbol(symbol, last_alerted[symbol])
            else:
                print(f"{now_str} | outside session, sleeping")
            time.sleep(config.POLL_SECONDS)
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
