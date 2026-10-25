"""Event-driven backtester. Fees and slippage are applied on every fill."""

import numpy as np
import pandas as pd

import config
import data
import strategy


def run(df, sig=None, verbose=True):
    sig = sig if sig is not None else strategy.signals(df)
    equity = config.EQUITY
    units = 0.0
    entry = stop = 0.0
    curve, trades = [], []

    for ts, bar in df.iterrows():
        price = bar["open"]          # we act at the open of the bar

        # 1. stop loss check first, using the bar's low
        if units > 0 and bar["low"] <= stop:
            fill = stop * (1 - config.SLIPPAGE_PCT)
            equity += units * fill * (1 - config.FEE_PCT)
            trades.append((ts, "stop", fill, (fill - entry) / entry))
            units = 0.0

        want = sig.loc[ts]

        # 2. entry
        if want == 1 and units == 0:
            stop = price * (1 - config.STOP_LOSS_PCT)
            size = strategy.position_size(equity, price, stop)
            if size > 0:
                fill = price * (1 + config.SLIPPAGE_PCT)
                cost = size * fill * (1 + config.FEE_PCT)
                if cost <= equity:
                    equity -= cost
                    units, entry = size, fill
                    trades.append((ts, "buy", fill, 0.0))

        # 3. exit on signal
        elif want == 0 and units > 0:
            fill = price * (1 - config.SLIPPAGE_PCT)
            equity += units * fill * (1 - config.FEE_PCT)
            trades.append((ts, "sell", fill, (fill - entry) / entry))
            units = 0.0

        curve.append(equity + units * bar["close"])

    eq = pd.Series(curve, index=df.index)
    if verbose:
        report(eq, trades, df)
    return eq, trades


def report(eq, trades, df):
    closed = [t for t in trades if t[1] in ("sell", "stop")]
    rets = [t[3] for t in closed]
    total = eq.iloc[-1] / config.EQUITY - 1
    buy_hold = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    dd = (eq / eq.cummax() - 1).min()
    wins = [r for r in rets if r > 0]

    print(f"Bars           : {len(df)}  ({df.index[0].date()} to {df.index[-1].date()})")
    print(f"Final equity   : {eq.iloc[-1]:.2f}  (start {config.EQUITY:.2f})")
    print(f"Strategy return: {total:+.2%}")
    print(f"Buy & hold     : {buy_hold:+.2%}   <-- must beat this to be worth it")
    print(f"Max drawdown   : {dd:.2%}")
    print(f"Closed trades  : {len(closed)}")
    if rets:
        print(f"Win rate       : {len(wins)/len(rets):.1%}")
        print(f"Avg trade      : {np.mean(rets):+.2%}")


if __name__ == "__main__":
    data.connect()
    tfs = ["H1", "H4", "D1", "W1"]     # H1 execution + the higher-tf structure
    for symbol in config.MT5_SYMBOLS:
        print(f"\n=== {symbol} ===")
        try:
            dfs = {tf: data.fetch_history(symbol, tf, since_days=730) for tf in tfs}
        except RuntimeError as e:
            print(f"skipped: {e}")
            continue
        sig = strategy.signals_mtf(dfs)
        run(dfs["H1"], sig=sig)
