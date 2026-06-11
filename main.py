"""
Crypto AI Overlay — Windows always-on-top trading signal analyzer.
Uses Bybit public API + parallel NVIDIA NIM & Groq models.
"""
import asyncio
import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

from bybit_client import get_market_data
from ai_analyzer import analyze
from config import COINS, REFRESH_INTERVAL

# ─── Colors ────────────────────────────────────────────────────────────────────
BG         = "#0d0d0d"
BG_PANEL   = "#161616"
BG_HOVER   = "#1e1e1e"
BORDER     = "#2a2a2a"
TEXT_DIM   = "#555555"
TEXT_MID   = "#888888"
TEXT       = "#cccccc"
TEXT_WHITE = "#f0f0f0"
GREEN      = "#00e676"
GREEN_DIM  = "#1b4332"
RED        = "#ff5252"
RED_DIM    = "#4d1a1a"
YELLOW     = "#ffd600"
YELLOW_DIM = "#3d3000"
ACCENT     = "#2979ff"

SIGNAL_COLOR = {
    "BUY":     (GREEN,  GREEN_DIM),
    "SELL":    (RED,    RED_DIM),
    "HOLD":    (YELLOW, YELLOW_DIM),
    "TIMEOUT": (TEXT_DIM, BG_PANEL),
    "ERROR":   (TEXT_DIM, BG_PANEL),
    "?":       (TEXT_DIM, BG_PANEL),
}

WIN_W = 320


class CryptoOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self._configure_window()

        self.q: queue.Queue   = queue.Queue()
        self.selected_coin    = tk.StringVar(value="BTC")
        self.running          = True
        self._refreshing_lock = threading.Lock()
        self._is_busy         = False
        self._drag_x = self._drag_y = 0

        self._build_ui()
        self._bind_drag()
        self._schedule_refresh()
        self._poll_queue()
        self.root.mainloop()

    # ── Window setup ────────────────────────────────────────────────────────────
    def _configure_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.93)
        self.root.configure(bg=BG)
        self.root.geometry(f"+80+80")
        self.root.resizable(False, False)

    def _bind_drag(self):
        self.root.bind("<Button-1>",        self._drag_start)
        self.root.bind("<B1-Motion>",       self._drag_move)

    def _drag_start(self, e):
        self._drag_x = e.x_root - self.root.winfo_x()
        self._drag_y = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    # ── UI Construction ─────────────────────────────────────────────────────────
    def _build_ui(self):
        root = self.root

        # Title bar
        bar = tk.Frame(root, bg=BG_PANEL, height=32)
        bar.pack(fill=tk.X)
        tk.Label(bar, text="◈  CRYPTO AI", bg=BG_PANEL, fg=ACCENT,
                 font=("Consolas", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=6)
        btn_close = tk.Label(bar, text="✕", bg=BG_PANEL, fg=TEXT_MID,
                             font=("Consolas", 10), cursor="hand2")
        btn_close.pack(side=tk.RIGHT, padx=10)
        btn_close.bind("<Button-1>", lambda _: self._quit())

        sep(root)

        # Coin selector
        coin_frame = tk.Frame(root, bg=BG, pady=8)
        coin_frame.pack(fill=tk.X, padx=10)
        self._coin_btns = {}
        for coin in COINS:
            btn = tk.Label(
                coin_frame, text=coin, bg=BG_PANEL, fg=TEXT_MID,
                font=("Consolas", 8, "bold"), width=5, pady=4,
                relief=tk.FLAT, cursor="hand2",
            )
            btn.pack(side=tk.LEFT, padx=2)
            btn.bind("<Button-1>", lambda e, c=coin: self._select_coin(c))
            self._coin_btns[coin] = btn
        self._select_coin("BTC", refresh=False)

        sep(root)

        # Price row
        price_frame = tk.Frame(root, bg=BG, pady=6)
        price_frame.pack(fill=tk.X, padx=12)
        self.lbl_price  = tk.Label(price_frame, text="$—", bg=BG, fg=TEXT_WHITE,
                                   font=("Consolas", 18, "bold"), anchor=tk.W)
        self.lbl_price.pack(side=tk.LEFT)
        self.lbl_change = tk.Label(price_frame, text="", bg=BG, fg=TEXT_MID,
                                   font=("Consolas", 10), anchor=tk.E)
        self.lbl_change.pack(side=tk.RIGHT)

        sep(root)

        # BIG signal
        self.verdict_frame = tk.Frame(root, bg=BG, pady=10)
        self.verdict_frame.pack(fill=tk.X, padx=12)
        self.lbl_signal = tk.Label(
            self.verdict_frame, text="—", bg=BG, fg=TEXT_MID,
            font=("Consolas", 36, "bold"), anchor=tk.CENTER,
        )
        self.lbl_signal.pack(fill=tk.X)
        self.lbl_confidence = tk.Label(
            self.verdict_frame, text="", bg=BG, fg=TEXT_MID,
            font=("Consolas", 9),
        )
        self.lbl_confidence.pack()

        sep(root)

        # Vote bar (BUY / HOLD / SELL)
        vote_frame = tk.Frame(root, bg=BG, pady=4)
        vote_frame.pack(fill=tk.X, padx=12)
        self.lbl_votes = {}
        for sig, clr in [("BUY", GREEN), ("HOLD", YELLOW), ("SELL", RED)]:
            f = tk.Frame(vote_frame, bg=BG)
            f.pack(side=tk.LEFT, expand=True)
            tk.Label(f, text=sig, bg=BG, fg=clr,
                     font=("Consolas", 7, "bold")).pack()
            lbl = tk.Label(f, text="0", bg=BG, fg=TEXT,
                           font=("Consolas", 13, "bold"))
            lbl.pack()
            self.lbl_votes[sig] = lbl

        sep(root)

        # Model list (scrollable via canvas)
        models_header = tk.Frame(root, bg=BG)
        models_header.pack(fill=tk.X, padx=12, pady=(6, 2))
        tk.Label(models_header, text="MODELS", bg=BG, fg=TEXT_DIM,
                 font=("Consolas", 7, "bold")).pack(side=tk.LEFT)
        self.lbl_responded = tk.Label(models_header, text="", bg=BG, fg=TEXT_DIM,
                                      font=("Consolas", 7))
        self.lbl_responded.pack(side=tk.RIGHT)

        self.models_frame = tk.Frame(root, bg=BG)
        self.models_frame.pack(fill=tk.X, padx=10, pady=(0, 6))

        sep(root)

        # Status / timer row
        bottom = tk.Frame(root, bg=BG_PANEL, pady=4)
        bottom.pack(fill=tk.X)
        self.lbl_status = tk.Label(bottom, text="Initialising…", bg=BG_PANEL,
                                   fg=TEXT_DIM, font=("Consolas", 7))
        self.lbl_status.pack(side=tk.LEFT, padx=8)
        self.lbl_timer = tk.Label(bottom, text="", bg=BG_PANEL, fg=TEXT_DIM,
                                  font=("Consolas", 7))
        self.lbl_timer.pack(side=tk.RIGHT, padx=8)

        btn_refresh = tk.Label(bottom, text="↺", bg=BG_PANEL, fg=ACCENT,
                               font=("Consolas", 10), cursor="hand2")
        btn_refresh.pack(side=tk.RIGHT, padx=4)
        btn_refresh.bind("<Button-1>", lambda _: self._trigger_refresh())

    # ── Model rows ──────────────────────────────────────────────────────────────
    def _render_model_rows(self, results: list):
        for w in self.models_frame.winfo_children():
            w.destroy()

        for r in results:
            sig   = r["signal"]
            color, _ = SIGNAL_COLOR.get(sig, (TEXT_DIM, BG))
            row = tk.Frame(self.models_frame, bg=BG)
            row.pack(fill=tk.X, pady=1)

            # colored dot
            tk.Label(row, text="●", bg=BG, fg=color,
                     font=("Consolas", 7)).pack(side=tk.LEFT, padx=(2, 4))
            # model name
            tk.Label(row, text=r["model"], bg=BG, fg=TEXT_MID,
                     font=("Consolas", 7), anchor=tk.W).pack(side=tk.LEFT)
            # latency
            lat_txt = f"{r['latency_ms']}ms" if r.get("ok") else sig
            tk.Label(row, text=lat_txt, bg=BG, fg=TEXT_DIM,
                     font=("Consolas", 7), anchor=tk.E).pack(side=tk.RIGHT, padx=4)
            # signal badge
            tk.Label(row, text=sig, bg=BG, fg=color,
                     font=("Consolas", 7, "bold"), width=4,
                     anchor=tk.E).pack(side=tk.RIGHT)

    # ── Logic ───────────────────────────────────────────────────────────────────
    def _select_coin(self, coin: str, refresh: bool = True):
        self.selected_coin.set(coin)
        for c, btn in self._coin_btns.items():
            btn.configure(
                bg=BG_PANEL if c != coin else ACCENT,
                fg=TEXT_MID  if c != coin else "#000000",
            )
        if refresh:
            self._trigger_refresh()

    def _trigger_refresh(self):
        with self._refreshing_lock:
            if self._is_busy:
                return
            self._is_busy = True
        self._next_refresh = time.time() + REFRESH_INTERVAL
        coin = self.selected_coin.get()
        self.lbl_status.configure(text=f"Fetching {coin}…")
        threading.Thread(target=self._run_analysis, args=(coin,), daemon=True).start()

    def _run_analysis(self, coin: str):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            market = loop.run_until_complete(get_market_data(coin))
            if not market:
                self.q.put({"error": f"Bybit: no data for {coin}"})
                return
            result = loop.run_until_complete(analyze(market))
            result["market"] = market
            self.q.put(result)
        except Exception as e:
            self.q.put({"error": str(e)})
        finally:
            loop.close()
            with self._refreshing_lock:
                self._is_busy = False

    def _schedule_refresh(self):
        self._next_refresh = time.time()
        self._trigger_refresh()

    def _poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                self._apply_result(item)
        except queue.Empty:
            pass

        now = time.time()
        remaining = max(0, self._next_refresh - now)
        self.lbl_timer.configure(text=f"↻ {remaining:.0f}s")
        if remaining <= 0:
            self._trigger_refresh()

        if self.running:
            self.root.after(500, self._poll_queue)

    def _apply_result(self, item: dict):
        if "error" in item:
            self.lbl_status.configure(text=f"✗ {item['error'][:40]}")
            return

        market  = item["market"]
        verdict = item["verdict"]
        conf    = item["confidence"]
        votes   = item["votes"]

        price = market["price"]
        if price >= 1_000:
            price_str = f"${price:,.0f}"
        elif price >= 1:
            price_str = f"${price:,.2f}"
        else:
            price_str = f"${price:.5f}"

        ch24 = market["change_24h"]
        ch1h = market["change_1h"]
        change_str = f"{ch24:+.2f}% 24h  {ch1h:+.2f}% 1h"

        sig_color, sig_bg = SIGNAL_COLOR.get(verdict, (TEXT, BG))

        self.lbl_price.configure(text=price_str)
        self.lbl_change.configure(
            text=change_str,
            fg=GREEN if ch24 >= 0 else RED,
        )
        self.lbl_signal.configure(text=verdict, fg=sig_color)
        self.lbl_confidence.configure(
            text=f"{conf}% confidence  ({item['responded']}/{item['total']} models)",
            fg=sig_color,
        )
        for sig, lbl in self.lbl_votes.items():
            lbl.configure(text=str(votes.get(sig, 0)))

        self._render_model_rows(item["results"])

        ts = time.strftime("%H:%M:%S")
        self.lbl_status.configure(text=f"✓ Updated {ts}")
        self.lbl_responded.configure(
            text=f"{item['responded']}/{item['total']} responded"
        )
        self._next_refresh = time.time() + REFRESH_INTERVAL

    def _quit(self):
        self.running = False
        self.root.destroy()


# ── Helpers ─────────────────────────────────────────────────────────────────────
def sep(parent):
    tk.Frame(parent, bg=BORDER, height=1).pack(fill=tk.X)


if __name__ == "__main__":
    CryptoOverlay()
