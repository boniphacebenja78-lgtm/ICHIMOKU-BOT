"""Live loop against Exness via MetaTrader5. Windows only - see data.py.

DRY_RUN=True logs orders instead of sending them. Leave it True until
you have watched the logs for at least two weeks and they make sense.
"""

import logging
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

import config
import data
import strategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()],
)
log = logging.getLogger("bot")

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
              "H1": 3600, "H4": 14400, "D1": 86400}


class Bot:
    def __init__(self):
        data.connect()
        info = mt5.symbol_info(config.MT5_SYMBOL)
        if info is None:
            raise RuntimeError(f"symbol {config.MT5_SYMBOL} not found - "
                                f"check the exact name in MT5 Market Watch")
        if not info.visible:
            mt5.symbol_select(config.MT5_SYMBOL, True)

        self.units = 0.0
        self.entry = 0.0
        self.stop = 0.0
        self.day = None
        self.day_start_equity = config.EQUITY
        self.equity = config.EQUITY
        self.halted = False

    def _lots(self, units):
        lots = units / config.LOT_SIZE
        lots = max(config.MIN_VOLUME,
                    round(lots / config.VOLUME_STEP) * config.VOLUME_STEP)
        return round(lots, 2)

    def _send(self, order_type, lots, sl=None):
        tick = mt5.symbol_info_tick(config.MT5_SYMBOL)
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": config.MT5_SYMBOL,
            "volume": lots,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 20260930,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if sl is not None:
            req["sl"] = sl
        result = mt5.order_send(req)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            reason = result.comment if result else mt5.last_error()
            log.error(f"order failed: {reason}")
            return None
        return result

    # --- orders -----------------------------------------------------
    def buy(self, price, units):
        lots = self._lots(units)
        stop = price * (1 - config.STOP_LOSS_PCT)
        if config.DRY_RUN:
            log.info(f"[DRY] BUY {lots} lots @ ~{price:.5f} sl={stop:.5f}")
        else:
            result = self._send(mt5.ORDER_TYPE_BUY, lots, sl=stop)
            if result is None:
                return
            log.info(f"LIVE BUY {lots} lots @ {result.price:.5f}")
        self.units, self.entry, self.stop = units, price, stop

    def sell(self, price, reason):
        lots = self._lots(self.units)
        if config.DRY_RUN:
            log.info(f"[DRY] SELL {lots} lots @ ~{price:.5f} ({reason})")
        else:
            result = self._send(mt5.ORDER_TYPE_SELL, lots)
            if result is None:
                return
            log.info(f"LIVE SELL {lots} lots @ {result.price:.5f} ({reason})")
        pnl = (price - self.entry) * self.units
        self.equity += pnl
        log.info(f"trade pnl {pnl:+.2f} | equity {self.equity:.2f}")
        self.units = 0.0

    # --- risk -------------------------------------------------------
    def check_kill_switch(self):
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            self.day = today
            self.day_start_equity = self.equity
            self.halted = False
        loss = self.equity / self.day_start_equity - 1
        if loss <= -config.MAX_DAILY_LOSS and not self.halted:
            self.halted = True
            log.warning(f"KILL SWITCH: down {loss:.2%} today. No new entries.")
        return self.halted

    # --- main -------------------------------------------------------
    def step(self):
        df = data.fetch_recent(config.MT5_SYMBOL, config.MT5_TIMEFRAME, limit=300)
        df = df.iloc[:-1]                      # drop the still-forming candle
        price = float(df["close"].iloc[-1])
        want = int(strategy.signals(df).iloc[-1])

        if self.units > 0 and price <= self.stop:
            self.sell(price, "stop loss")
            return

        halted = self.check_kill_switch()

        if want == 1 and self.units == 0 and not halted:
            stop = price * (1 - config.STOP_LOSS_PCT)
            size = strategy.position_size(self.equity, price, stop)
            if size * price >= 1:              # skip a rounding-to-zero order
                self.buy(price, size)
        elif want == 0 and self.units > 0:
            self.sell(price, "signal flat")
        else:
            state = "long" if self.units else "flat"
            log.info(f"{price:.5f} | signal={want} | {state} | eq {self.equity:.2f}")

    def run(self):
        period = TF_SECONDS[config.MT5_TIMEFRAME]
        mode = "DRY RUN" if config.DRY_RUN else "*** LIVE MONEY ***"
        log.info(f"starting | {config.MT5_SYMBOL} {config.MT5_TIMEFRAME} | {mode}")
        try:
            while True:
                try:
                    self.step()
                except Exception as e:
                    log.exception(f"step failed: {e}")
                sleep = period - (time.time() % period) + 5
                time.sleep(sleep)
        finally:
            mt5.shutdown()


if __name__ == "__main__":
    Bot().run()
