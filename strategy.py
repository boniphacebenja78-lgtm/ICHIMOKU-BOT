"""Support/Resistance + trendline confluence strategy.

Rules being codified:
1. Find swing highs/lows and cluster them into S/R zones - more touches at
   roughly the same price means a stronger zone.
2. When price returns to a zone, require a rejection candle as confirmation
   (a wick into the zone, but a strong close back out of it).
3. Only take the trade if a trendline - fit through recent swing lows for an
   uptrend, swing highs for a downtrend - also projects to roughly the same
   price at that moment. That's the confluence: two independent reasons the
   level should hold, not one.

Lookahead safety: a swing point at bar i can only be *known* once `order`
bars have passed after it (that's what makes it a swing - you need the
future price action to confirm price actually turned there). So a swing at
position i is only added to a zone once bar i+order has been reached. At any
bar t we only ever use swings and trendlines built from information that
existed by bar t. The final signal is shifted by one more bar so a trade
acts on the open *after* the bar that confirmed it, not the same bar.

Honest caveat: "resistance", "confirmation", and "trendline" are fuzzy,
discretionary ideas on a chart. This is one reasonable, testable way to make
them mechanical - not the only way, and not guaranteed to match what your
eye sees. Treat SWING_ORDER, ZONE_TOL_PCT, MIN_TOUCHES, and
REJECTION_WICK_FRAC in config.py as things to tune and backtest, not fixed
truths. Backtest before trusting any of this with money.
"""

import numpy as np
import pandas as pd

import config


# ---------------------------------------------------------------- swings --
def find_swings(df, order=config.SWING_ORDER):
    """Confirmed swing highs/lows as (bar_position, price) tuples.

    A bar is a swing high if its high is strictly the max within `order`
    bars on either side (and similarly for swing lows). Computed once over
    the whole series - safe because each swing point is only *used* starting
    at i + order (see generate loop below), never before it could be known.
    """
    highs, lows = df["high"].values, df["low"].values
    n = len(df)
    swing_highs, swing_lows = [], []
    for i in range(order, n - order):
        wh = highs[i - order:i + order + 1]
        wl = lows[i - order:i + order + 1]
        if highs[i] == wh.max() and (wh == highs[i]).sum() == 1:
            swing_highs.append((i, highs[i]))
        if lows[i] == wl.min() and (wl == lows[i]).sum() == 1:
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows


# ----------------------------------------------------------------- zones --
def _merge_zone(zones, price, tol):
    """Add a swing price into the nearest existing zone, or start a new one."""
    for z in zones:
        if abs(price - z["price"]) / z["price"] <= tol:
            z["price"] = (z["price"] * z["touches"] + price) / (z["touches"] + 1)
            z["touches"] += 1
            return
    zones.append({"price": price, "touches": 1})


def _nearest_zone(zones, price, tol):
    candidates = [z for z in zones if abs(price - z["price"]) / z["price"] <= tol]
    if not candidates:
        return None
    return min(candidates, key=lambda z: abs(price - z["price"]))


def _trendline_value(points, at_x):
    """Fit a line through recent swing points, project its value at at_x."""
    if len(points) < 2:
        return None
    xs = np.array([p[0] for p in points], dtype=float)
    ys = np.array([p[1] for p in points], dtype=float)
    slope, intercept = np.polyfit(xs, ys, 1)
    return slope * at_x + intercept


# --------------------------------------------------------------- signals --
def signals(df):
    """Return a Series: 1 = want to be long, 0 = want to be flat.

    Long-only, matching the rest of the scaffold. Entry: price taps a
    strong support zone that has trendline confluence, with a bullish
    rejection candle. Exit: price closes back below that support (setup
    invalidated) or taps a resistance zone with a bearish rejection
    (take profit at the next level).
    """
    order = config.SWING_ORDER
    tol = config.ZONE_TOL_PCT
    swing_highs, swing_lows = find_swings(df, order)
    n = len(df)
    want = np.zeros(n, dtype=int)

    lows, highs = df["low"].values, df["high"].values
    opens, closes = df["open"].values, df["close"].values

    support_zones, resistance_zones = [], []
    sl_ptr = sh_ptr = 0
    in_position = False
    entry_support = None

    for t in range(n):
        # reveal only the swings that are confirmed by bar t
        while sl_ptr < len(swing_lows) and swing_lows[sl_ptr][0] + order <= t:
            _merge_zone(support_zones, swing_lows[sl_ptr][1], tol)
            sl_ptr += 1
        while sh_ptr < len(swing_highs) and swing_highs[sh_ptr][0] + order <= t:
            _merge_zone(resistance_zones, swing_highs[sh_ptr][1], tol)
            sh_ptr += 1

        rng = highs[t] - lows[t]

        if in_position:
            r_zone = _nearest_zone(resistance_zones, highs[t], tol)
            hit_resistance = (
                r_zone is not None and rng > 0
                and (highs[t] - closes[t]) / rng >= config.REJECTION_WICK_FRAC
            )
            broke_support = closes[t] < entry_support * (1 - tol)
            if hit_resistance or broke_support:
                in_position = False
                entry_support = None
                want[t] = 0
            else:
                want[t] = 1
            continue

        avail_lows = [(i, p) for i, p in swing_lows if i + order <= t]
        trend_val = None
        if len(avail_lows) >= config.TRENDLINE_MIN_POINTS:
            trend_val = _trendline_value(avail_lows[-6:], t)

        zone = _nearest_zone(support_zones, lows[t], tol)
        if zone and zone["touches"] >= config.MIN_TOUCHES:
            confluence = (
                trend_val is not None
                and abs(trend_val - zone["price"]) / zone["price"] <= tol
            )
            rejection = (
                rng > 0
                and (closes[t] - lows[t]) / rng >= config.REJECTION_WICK_FRAC
                and closes[t] > opens[t]
            )
            if confluence and rejection:
                want[t] = 1
                in_position = True
                entry_support = zone["price"]
                continue

        want[t] = 0

    # act on the bar AFTER the one that confirmed the signal
    return pd.Series(want, index=df.index).shift(1).fillna(0).astype(int)


# ---------------------------------------------------------------- sizing --
def position_size(equity, price, stop_price, risk_frac=config.RISK_PER_TRADE):
    """Fixed-fractional sizing: never risk more than risk_frac of equity.

    Ideally the stop sits just under the support zone that triggered the
    trade rather than a flat percentage - config.STOP_LOSS_PCT is a
    simplification used by backtest.py/bot.py, which don't currently see
    zone metadata. Worth upgrading once the entry logic itself checks out.
    """
    risk_per_unit = price - stop_price
    if risk_per_unit <= 0:
        return 0.0
    units = (equity * risk_frac) / risk_per_unit
    max_units = equity / price          # never use leverage by accident
    return min(units, max_units)


# =============================================================
# Multi-timeframe version: structure from higher timeframes,
# entries confirmed by candlestick patterns on lower timeframes.
# =============================================================

def find_swings_ts(df, order=config.SWING_ORDER):
    """Like find_swings, but keyed by real timestamp instead of bar
    position - needed so swings from different timeframes (W1, D1, H4)
    can be compared and revealed on a single shared timeline.

    Returns two lists of (swing_time, price, confirmed_at) tuples, where
    confirmed_at is the timestamp of the bar `order` places later - the
    earliest real moment this swing point could be known to exist.
    """
    highs, lows = df["high"].values, df["low"].values
    idx = df.index
    n = len(df)
    swing_highs, swing_lows = [], []
    for i in range(order, n - order):
        wh = highs[i - order:i + order + 1]
        wl = lows[i - order:i + order + 1]
        if highs[i] == wh.max() and (wh == highs[i]).sum() == 1:
            swing_highs.append((idx[i], highs[i], idx[i + order]))
        if lows[i] == wl.min() and (wl == lows[i]).sum() == 1:
            swing_lows.append((idx[i], lows[i], idx[i + order]))
    return swing_highs, swing_lows


def _trendline_value_ts(points, at_ts):
    """Like _trendline_value, but points are (timestamp, price) and the
    line is projected using real elapsed hours instead of a bar index -
    necessary once swing points come from more than one timeframe."""
    if len(points) < 2:
        return None
    ref = points[0][0]
    xs = np.array([(p[0] - ref).total_seconds() / 3600 for p in points])
    ys = np.array([p[1] for p in points])
    slope, intercept = np.polyfit(xs, ys, 1)
    at_x = (at_ts - ref).total_seconds() / 3600
    return slope * at_x + intercept


def _bullish_engulfing(o0, c0, o1, c1):
    """Candle 0 = previous bar, candle 1 = current bar."""
    prev_bearish = c0 < o0
    cur_bullish = c1 > o1
    engulfs = o1 <= c0 and c1 >= o0
    return prev_bearish and cur_bullish and engulfs


def _bearish_engulfing(o0, c0, o1, c1):
    prev_bullish = c0 > o0
    cur_bearish = c1 < o1
    engulfs = o1 >= c0 and c1 <= o0
    return prev_bullish and cur_bearish and engulfs


def _bullish_tweezer(l0, c0, l1, c1, tol):
    """Two candles bottoming at (roughly) the same low, with the second
    closing higher than the first - a classic tweezer-bottom reversal."""
    lows_match = abs(l0 - l1) / max(l0, 1e-9) <= tol
    reversal = c1 > c0
    return lows_match and reversal


def _bearish_tweezer(h0, c0, h1, c1, tol):
    highs_match = abs(h0 - h1) / max(h0, 1e-9) <= tol
    reversal = c1 < c0
    return highs_match and reversal


def _bullish_confirmation(df, pos, tol):
    """Check for a bullish engulfing or tweezer-bottom ending at bar `pos`."""
    if pos < 1:
        return False
    o0, c0, l0 = df["open"].iloc[pos - 1], df["close"].iloc[pos - 1], df["low"].iloc[pos - 1]
    o1, c1, l1 = df["open"].iloc[pos], df["close"].iloc[pos], df["low"].iloc[pos]
    return (_bullish_engulfing(o0, c0, o1, c1)
            or _bullish_tweezer(l0, c0, l1, c1, tol))


def signals_mtf(dfs, htf_list=None, confirm_list=None,
                order=config.SWING_ORDER, tol=config.ZONE_TOL_PCT):
    """Multi-timeframe version of `signals`.

    dfs: dict of {timeframe_name: dataframe}, all for the same symbol,
    covering overlapping history. Must include "H1" (the execution
    timeframe the returned signal is indexed on) plus whichever
    timeframes are listed in htf_list/confirm_list.

    Structure: support/resistance zones and the trendline are built only
    from swing points on htf_list (default config.HTF_LIST - W1/D1/H4).
    A level only counts if the bigger picture shows it.

    Entry: price sits at a zone with trendline confluence, AND at least
    one of confirm_list (default config.CONFIRM_LIST - H4/H1) shows a
    bullish engulfing or tweezer-bottom pattern completing right there.
    Exit: same as the single-timeframe version - close back below the
    support that triggered entry, or a bearish rejection at resistance.

    This is heavier to compute than `signals()` and still long-only.
    Treat it as a stricter, more selective sibling, not a replacement -
    compare backtests of both before deciding which one to trust.
    """
    htf_list = htf_list or config.HTF_LIST
    confirm_list = confirm_list or config.CONFIRM_LIST
    exec_df = dfs["H1"]
    ts = exec_df.index
    n = len(exec_df)

    swings = {tf: find_swings_ts(dfs[tf], order) for tf in htf_list if tf in dfs}
    ptr = {tf: {"high": 0, "low": 0} for tf in swings}

    support_zones, resistance_zones = [], []
    trend_pool_lows = []

    lows = exec_df["low"].values
    highs = exec_df["high"].values
    closes = exec_df["close"].values

    want = np.zeros(n, dtype=int)
    in_position = False
    entry_support = None

    for t in range(n):
        now = ts[t]

        for tf, (sh, sl) in swings.items():
            while ptr[tf]["low"] < len(sl) and sl[ptr[tf]["low"]][2] <= now:
                _merge_zone(support_zones, sl[ptr[tf]["low"]][1], tol)
                trend_pool_lows.append((sl[ptr[tf]["low"]][0], sl[ptr[tf]["low"]][1]))
                ptr[tf]["low"] += 1
            while ptr[tf]["high"] < len(sh) and sh[ptr[tf]["high"]][2] <= now:
                _merge_zone(resistance_zones, sh[ptr[tf]["high"]][1], tol)
                ptr[tf]["high"] += 1

        if in_position:
            rng = highs[t] - lows[t]
            r_zone = _nearest_zone(resistance_zones, highs[t], tol)
            hit_resistance = (
                r_zone is not None and rng > 0
                and (highs[t] - closes[t]) / rng >= config.REJECTION_WICK_FRAC
            )
            broke_support = closes[t] < entry_support * (1 - tol)
            if hit_resistance or broke_support:
                in_position = False
                entry_support = None
                want[t] = 0
            else:
                want[t] = 1
            continue

        zone = _nearest_zone(support_zones, lows[t], tol)
        if zone and zone["touches"] >= config.MIN_TOUCHES:
            trend_val = None
            if len(trend_pool_lows) >= config.TRENDLINE_MIN_POINTS:
                trend_val = _trendline_value_ts(sorted(trend_pool_lows)[-6:], now)
            confluence = (
                trend_val is not None
                and abs(trend_val - zone["price"]) / zone["price"] <= tol
            )
            if confluence:
                confirmed = False
                for tf in confirm_list:
                    if tf not in dfs:
                        continue
                    cdf = dfs[tf]
                    pos = cdf.index.searchsorted(now, side="right") - 1
                    if pos >= 1 and _bullish_confirmation(cdf, pos, config.TWEEZER_TOL_PCT):
                        confirmed = True
                        break
                if confirmed:
                    want[t] = 1
                    in_position = True
                    entry_support = zone["price"]
                    continue

        want[t] = 0

    return pd.Series(want, index=ts).shift(1).fillna(0).astype(int)
