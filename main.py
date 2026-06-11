"""
Crypto AI Overlay — Windows always-on-top trading signal analyzer.
Each model runs its own independent async loop:
  fetch market → query AI → update UI → repeat immediately
UI updates live as responses arrive, no waiting for all models.
"""
import asyncio
import queue
import threading
import time
import tkinter as tk

import aiohttp

from bybit_client import get_market_data
from ai_analyzer import query_once, majority_signal
from config import COINS, ALL_MODELS, MARKET_REFRESH_SEC

# ── Colors ──────────────────────────────────────────────────────────────────────
BG       = "#0d0d0d"
BG_PANEL = "#161616"
BORDER   = "#222222"
TEXT_DIM = "#444444"
TEXT_MID = "#777777"
TEXT     = "#bbbbbb"
WHITE    = "#f0f0f0"
GREEN    = "#00e676"
RED      = "#ff5252"
YELLOW   = "#ffd600"
ACCENT   = "#2979ff"

SIGNAL_FG = {"BUY": GREEN, "SELL": RED, "HOLD": YELLOW}

WIN_W = 330


class CryptoOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self._configure_window()

        # shared state — written by bg threads, read by UI poll
        self.selected_coin  = tk.StringVar(value="BTC")
        self.running        = True
        self._market: dict  = {}           # latest market snapshot
        self._results: dict = {}           # model_name → latest result dict
        self._q: queue.Queue = queue.Queue()
        self._drag_x = self._drag_y = 0

        self._build_ui()
        self._bind_drag()

        # start one bg thread per model + one market fetcher
        self._start_loops()
        self._poll_queue()
        self.root.mainloop()

    # ── Window ───────────────────────────────────────────────────────────────────
    def _configure_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.93)
        self.root.configure(bg=BG)
        self.root.geometry("+80+80")
        self.root.resizable(False, False)

    def _bind_drag(self):
        for w in (self.root, self._title_bar):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, e):
        self._drag_x = e.x_root - self.root.winfo_x()
        self._drag_y = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    # ── UI ───────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root

        # title bar
        self._title_bar = tk.Frame(r, bg=BG_PANEL, height=30)
        self._title_bar.pack(fill=tk.X)
        tk.Label(self._title_bar, text="◈  CRYPTO AI", bg=BG_PANEL, fg=ACCENT,
                 font=("Consolas", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=5)
        x_btn = tk.Label(self._title_bar, text="✕", bg=BG_PANEL, fg=TEXT_MID,
                         font=("Consolas", 10), cursor="hand2")
        x_btn.pack(side=tk.RIGHT, padx=10)
        x_btn.bind("<Button-1>", lambda _: self._quit())

        _sep(r)

        # coin buttons
        coin_row = tk.Frame(r, bg=BG, pady=7)
        coin_row.pack(fill=tk.X, padx=8)
        self._coin_btns = {}
        for coin in COINS:
            b = tk.Label(coin_row, text=coin, bg=BG_PANEL, fg=TEXT_MID,
                         font=("Consolas", 8, "bold"), width=5, pady=3,
                         cursor="hand2")
            b.pack(side=tk.LEFT, padx=2)
            b.bind("<Button-1>", lambda e, c=coin: self._switch_coin(c))
            self._coin_btns[coin] = b
        self._highlight_coin("BTC")

        _sep(r)

        # price row
        price_row = tk.Frame(r, bg=BG, pady=5)
        price_row.pack(fill=tk.X, padx=12)
        self.lbl_price  = tk.Label(price_row, text="$—", bg=BG, fg=WHITE,
                                   font=("Consolas", 18, "bold"), anchor=tk.W)
        self.lbl_price.pack(side=tk.LEFT)
        self.lbl_change = tk.Label(price_row, text="", bg=BG, fg=TEXT_MID,
                                   font=("Consolas", 9), anchor=tk.E)
        self.lbl_change.pack(side=tk.RIGHT)

        _sep(r)

        # big signal
        sig_frame = tk.Frame(r, bg=BG, pady=8)
        sig_frame.pack(fill=tk.X, padx=12)
        self.lbl_signal = tk.Label(sig_frame, text="—", bg=BG, fg=TEXT_MID,
                                   font=("Consolas", 38, "bold"))
        self.lbl_signal.pack(fill=tk.X)
        self.lbl_conf   = tk.Label(sig_frame, text="Waiting for models…", bg=BG,
                                   fg=TEXT_MID, font=("Consolas", 8))
        self.lbl_conf.pack()

        _sep(r)

        # vote counters
        vote_row = tk.Frame(r, bg=BG, pady=3)
        vote_row.pack(fill=tk.X, padx=12)
        self.lbl_votes = {}
        for sig, clr in [("BUY", GREEN), ("HOLD", YELLOW), ("SELL", RED)]:
            col = tk.Frame(vote_row, bg=BG)
            col.pack(side=tk.LEFT, expand=True)
            tk.Label(col, text=sig, bg=BG, fg=clr,
                     font=("Consolas", 7, "bold")).pack()
            lv = tk.Label(col, text="0", bg=BG, fg=TEXT,
                          font=("Consolas", 14, "bold"))
            lv.pack()
            self.lbl_votes[sig] = lv

        _sep(r)

        # model list header
        hdr = tk.Frame(r, bg=BG)
        hdr.pack(fill=tk.X, padx=12, pady=(5, 1))
        tk.Label(hdr, text="MODELS", bg=BG, fg=TEXT_DIM,
                 font=("Consolas", 7, "bold")).pack(side=tk.LEFT)
        self.lbl_responded = tk.Label(hdr, text="0/0 responded", bg=BG,
                                      fg=TEXT_DIM, font=("Consolas", 7))
        self.lbl_responded.pack(side=tk.RIGHT)

        # model rows (one per model, created once)
        self._model_rows: dict = {}
        models_frame = tk.Frame(r, bg=BG)
        models_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        for m in ALL_MODELS:
            row = tk.Frame(models_frame, bg=BG)
            row.pack(fill=tk.X, pady=1)
            dot  = tk.Label(row, text="●", bg=BG, fg=TEXT_DIM,
                            font=("Consolas", 7))
            dot.pack(side=tk.LEFT, padx=(2, 4))
            name = tk.Label(row, text=m["name"], bg=BG, fg=TEXT_MID,
                            font=("Consolas", 7), anchor=tk.W)
            name.pack(side=tk.LEFT)
            lat  = tk.Label(row, text="…", bg=BG, fg=TEXT_DIM,
                            font=("Consolas", 7))
            lat.pack(side=tk.RIGHT, padx=4)
            sig  = tk.Label(row, text="—", bg=BG, fg=TEXT_DIM,
                            font=("Consolas", 7, "bold"), width=5, anchor=tk.E)
            sig.pack(side=tk.RIGHT)
            self._model_rows[m["name"]] = {"dot": dot, "lat": lat, "sig": sig}

        _sep(r)

        # status bar
        bar = tk.Frame(r, bg=BG_PANEL, pady=3)
        bar.pack(fill=tk.X)
        self.lbl_status = tk.Label(bar, text="Starting…", bg=BG_PANEL,
                                   fg=TEXT_DIM, font=("Consolas", 7))
        self.lbl_status.pack(side=tk.LEFT, padx=8)
        self.lbl_time = tk.Label(bar, text="", bg=BG_PANEL, fg=TEXT_DIM,
                                 font=("Consolas", 7))
        self.lbl_time.pack(side=tk.RIGHT, padx=8)

    # ── Background loops ─────────────────────────────────────────────────────────
    def _start_loops(self):
        """One thread per model + one thread for market data."""
        threading.Thread(target=self._market_loop, daemon=True).start()
        for model in ALL_MODELS:
            threading.Thread(target=self._model_loop, args=(model,), daemon=True).start()

    def _market_loop(self):
        """Continuously refresh market data and push to queue."""
        while self.running:
            coin = self.selected_coin.get()
            loop = asyncio.new_event_loop()
            try:
                data = loop.run_until_complete(get_market_data(coin))
                if data:
                    self._market = data
                    self._q.put({"type": "market", "data": data})
            except Exception:
                pass
            finally:
                loop.close()
            time.sleep(MARKET_REFRESH_SEC)

    def _model_loop(self, model: dict):
        """Each model: query → update UI → query again immediately."""
        # stagger startup so models don't all hammer APIs at once
        import random
        time.sleep(random.uniform(0, 1.5))

        while self.running:
            market = self._market
            if not market:
                time.sleep(0.5)
                continue

            loop = asyncio.new_event_loop()
            try:
                async def _run(m=model, mkt=market):
                    async with aiohttp.ClientSession() as session:
                        return await query_once(session, m, mkt)
                result = loop.run_until_complete(_run())
                self._results[model["name"]] = result
                self._q.put({"type": "model", "result": result})
            except Exception as e:
                self._results[model["name"]] = {
                    "model": model["name"], "signal": "ERR",
                    "latency_ms": 0, "ok": False, "err": str(e)[:40],
                }
                self._q.put({"type": "model", "result": self._results[model["name"]]})
            finally:
                loop.close()

            # tiny pause before next request to avoid rate-limits
            time.sleep(0.5)

    # ── UI updates ───────────────────────────────────────────────────────────────
    def _poll_queue(self):
        try:
            while True:
                msg = self._q.get_nowait()
                if msg["type"] == "market":
                    self._update_price(msg["data"])
                elif msg["type"] == "model":
                    self._update_model_row(msg["result"])
                    self._update_vote_totals()
        except queue.Empty:
            pass

        self.lbl_time.configure(text=time.strftime("%H:%M:%S"))
        if self.running:
            self.root.after(200, self._poll_queue)

    def _update_price(self, d: dict):
        price = d["price"]
        price_str = (f"${price:,.0f}" if price >= 1000
                     else f"${price:,.2f}" if price >= 1
                     else f"${price:.5f}")
        self.lbl_price.configure(text=price_str)
        ch = d["change_24h"]
        self.lbl_change.configure(
            text=f"{ch:+.2f}% 24h  {d['change_1h']:+.2f}% 1h",
            fg=GREEN if ch >= 0 else RED,
        )
        self.lbl_status.configure(text=f"✓ {d['symbol']} live")

    def _update_model_row(self, r: dict):
        row = self._model_rows.get(r["model"])
        if not row:
            return
        sig = r["signal"]
        clr = SIGNAL_FG.get(sig, TEXT_DIM)
        row["dot"].configure(fg=clr)
        row["sig"].configure(text=sig, fg=clr)
        lat_txt = f"{r['latency_ms']}ms" if r.get("ok") else sig[:7]
        row["lat"].configure(text=lat_txt)

    def _update_vote_totals(self):
        results = self._results
        votes = [r["signal"] for r in results.values() if r["signal"] in ("BUY", "SELL", "HOLD")]
        responded = len(votes)
        total     = len(ALL_MODELS)

        for sig, lbl in self.lbl_votes.items():
            lbl.configure(text=str(votes.count(sig)))

        self.lbl_responded.configure(text=f"{responded}/{total} responded")

        if not votes:
            return

        verdict, conf = majority_signal(results)
        clr = SIGNAL_FG.get(verdict, TEXT_MID)
        self.lbl_signal.configure(text=verdict, fg=clr)
        self.lbl_conf.configure(
            text=f"{conf}% confidence  ({responded}/{total} models)",
            fg=clr,
        )

    # ── Coin switch ──────────────────────────────────────────────────────────────
    def _switch_coin(self, coin: str):
        self.selected_coin.set(coin)
        self._highlight_coin(coin)
        # clear old results when switching coin
        self._results.clear()
        self._market = {}
        for row in self._model_rows.values():
            row["dot"].configure(fg=TEXT_DIM)
            row["sig"].configure(text="—", fg=TEXT_DIM)
            row["lat"].configure(text="…")
        self.lbl_signal.configure(text="—", fg=TEXT_MID)
        self.lbl_conf.configure(text="Switching coin…", fg=TEXT_MID)
        for lbl in self.lbl_votes.values():
            lbl.configure(text="0")

    def _highlight_coin(self, coin: str):
        for c, btn in self._coin_btns.items():
            btn.configure(bg=ACCENT if c == coin else BG_PANEL,
                          fg="#000000" if c == coin else TEXT_MID)

    def _quit(self):
        self.running = False
        self.root.destroy()


def _sep(parent):
    tk.Frame(parent, bg=BORDER, height=1).pack(fill=tk.X)


if __name__ == "__main__":
    CryptoOverlay()
