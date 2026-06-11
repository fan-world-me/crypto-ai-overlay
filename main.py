"""
Crypto AI Overlay — Windows always-on-top trading signal analyzer.
Architecture:
  - FastAPI server runs in a background thread (localhost:8765)
  - SSE stream delivers model results as they arrive
  - tkinter UI updates in real-time via queue
"""
import json
import queue
import threading
import time
import tkinter as tk
import requests
import uvicorn

from server import app
from config import ALL_MODELS, COINS

SERVER_PORT = 8765
SERVER_URL  = f"http://127.0.0.1:{SERVER_PORT}"

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


def _majority(results: dict) -> tuple[str, int]:
    votes = [r["signal"] for r in results.values() if r["signal"] in ("BUY", "SELL", "HOLD")]
    if not votes:
        return "—", 0
    buy  = votes.count("BUY")
    sell = votes.count("SELL")
    hold = votes.count("HOLD")
    total = len(votes)
    if buy >= sell and buy >= hold:
        return "BUY",  round(buy  / total * 100)
    if sell >= buy  and sell >= hold:
        return "SELL", round(sell / total * 100)
    return "HOLD", round(hold / total * 100)


class CryptoOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self._configure_window()

        self.selected_coin = "BTC"
        self.running       = True
        self._results: dict = {}
        self._q: queue.Queue = queue.Queue()
        self._drag_x = self._drag_y = 0

        self._build_ui()
        self._bind_drag()
        self._start_server()
        self._wait_for_server()
        self._trigger_analyze()
        self._poll_queue()
        self.root.mainloop()

    # ── Window ────────────────────────────────────────────────────────────────
    def _configure_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.93)
        self.root.configure(bg=BG)
        self.root.geometry("+80+80")
        self.root.resizable(False, False)

    def _bind_drag(self):
        for w in (self.root, self._title_bar):
            w.bind("<Button-1>", lambda e: (setattr(self, '_drag_x', e.x_root - self.root.winfo_x()),
                                            setattr(self, '_drag_y', e.y_root - self.root.winfo_y())))
            w.bind("<B1-Motion>", lambda e: self.root.geometry(
                f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}"))

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root

        self._title_bar = tk.Frame(r, bg=BG_PANEL, height=30)
        self._title_bar.pack(fill=tk.X)
        tk.Label(self._title_bar, text="◈  CRYPTO AI", bg=BG_PANEL, fg=ACCENT,
                 font=("Consolas", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=5)
        x = tk.Label(self._title_bar, text="✕", bg=BG_PANEL, fg=TEXT_MID,
                     font=("Consolas", 10), cursor="hand2")
        x.pack(side=tk.RIGHT, padx=10)
        x.bind("<Button-1>", lambda _: self._quit())

        _sep(r)

        coin_row = tk.Frame(r, bg=BG, pady=7)
        coin_row.pack(fill=tk.X, padx=8)
        self._coin_btns = {}
        for coin in COINS:
            b = tk.Label(coin_row, text=coin, bg=BG_PANEL, fg=TEXT_MID,
                         font=("Consolas", 8, "bold"), width=5, pady=3, cursor="hand2")
            b.pack(side=tk.LEFT, padx=2)
            b.bind("<Button-1>", lambda e, c=coin: self._switch_coin(c))
            self._coin_btns[coin] = b
        self._highlight_coin("BTC")

        _sep(r)

        pr = tk.Frame(r, bg=BG, pady=5)
        pr.pack(fill=tk.X, padx=12)
        self.lbl_price  = tk.Label(pr, text="$—", bg=BG, fg=WHITE,
                                   font=("Consolas", 18, "bold"), anchor=tk.W)
        self.lbl_price.pack(side=tk.LEFT)
        self.lbl_change = tk.Label(pr, text="", bg=BG, fg=TEXT_MID,
                                   font=("Consolas", 9), anchor=tk.E)
        self.lbl_change.pack(side=tk.RIGHT)

        _sep(r)

        sf = tk.Frame(r, bg=BG, pady=8)
        sf.pack(fill=tk.X, padx=12)
        self.lbl_signal = tk.Label(sf, text="—", bg=BG, fg=TEXT_MID,
                                   font=("Consolas", 38, "bold"))
        self.lbl_signal.pack(fill=tk.X)
        self.lbl_conf   = tk.Label(sf, text="Connecting to server…", bg=BG,
                                   fg=TEXT_MID, font=("Consolas", 8))
        self.lbl_conf.pack()

        _sep(r)

        vr = tk.Frame(r, bg=BG, pady=3)
        vr.pack(fill=tk.X, padx=12)
        self.lbl_votes = {}
        for sig, clr in [("BUY", GREEN), ("HOLD", YELLOW), ("SELL", RED)]:
            col = tk.Frame(vr, bg=BG)
            col.pack(side=tk.LEFT, expand=True)
            tk.Label(col, text=sig, bg=BG, fg=clr,
                     font=("Consolas", 7, "bold")).pack()
            lv = tk.Label(col, text="0", bg=BG, fg=TEXT,
                          font=("Consolas", 14, "bold"))
            lv.pack()
            self.lbl_votes[sig] = lv

        _sep(r)

        hdr = tk.Frame(r, bg=BG)
        hdr.pack(fill=tk.X, padx=12, pady=(5, 1))
        tk.Label(hdr, text="MODELS", bg=BG, fg=TEXT_DIM,
                 font=("Consolas", 7, "bold")).pack(side=tk.LEFT)
        self.lbl_responded = tk.Label(hdr, text="0/0", bg=BG, fg=TEXT_DIM,
                                      font=("Consolas", 7))
        self.lbl_responded.pack(side=tk.RIGHT)

        self._model_rows: dict = {}
        mf = tk.Frame(r, bg=BG)
        mf.pack(fill=tk.X, padx=10, pady=(0, 5))
        for m in ALL_MODELS:
            row = tk.Frame(mf, bg=BG)
            row.pack(fill=tk.X, pady=1)
            dot  = tk.Label(row, text="●", bg=BG, fg=TEXT_DIM, font=("Consolas", 7))
            dot.pack(side=tk.LEFT, padx=(2, 4))
            tk.Label(row, text=m["name"], bg=BG, fg=TEXT_MID,
                     font=("Consolas", 7), anchor=tk.W).pack(side=tk.LEFT)
            lat  = tk.Label(row, text="…", bg=BG, fg=TEXT_DIM, font=("Consolas", 7))
            lat.pack(side=tk.RIGHT, padx=4)
            sig  = tk.Label(row, text="—", bg=BG, fg=TEXT_DIM,
                            font=("Consolas", 7, "bold"), width=5, anchor=tk.E)
            sig.pack(side=tk.RIGHT)
            self._model_rows[m["name"]] = {"dot": dot, "lat": lat, "sig": sig}

        _sep(r)

        bar = tk.Frame(r, bg=BG_PANEL, pady=3)
        bar.pack(fill=tk.X)
        self.lbl_status = tk.Label(bar, text="Starting server…", bg=BG_PANEL,
                                   fg=TEXT_DIM, font=("Consolas", 7))
        self.lbl_status.pack(side=tk.LEFT, padx=8)
        self.lbl_time   = tk.Label(bar, text="", bg=BG_PANEL, fg=TEXT_DIM,
                                   font=("Consolas", 7))
        self.lbl_time.pack(side=tk.RIGHT, padx=8)
        refresh_btn = tk.Label(bar, text="↺", bg=BG_PANEL, fg=ACCENT,
                               font=("Consolas", 10), cursor="hand2")
        refresh_btn.pack(side=tk.RIGHT, padx=4)
        refresh_btn.bind("<Button-1>", lambda _: self._trigger_analyze())

    # ── Server ────────────────────────────────────────────────────────────────
    def _start_server(self):
        def run():
            uvicorn.run(app, host="127.0.0.1", port=SERVER_PORT,
                        log_level="error", access_log=False)
        threading.Thread(target=run, daemon=True).start()

    def _wait_for_server(self):
        """Block tkinter start until FastAPI is ready."""
        for _ in range(40):
            try:
                requests.get(f"{SERVER_URL}/health", timeout=0.5)
                self.lbl_status.configure(text="✓ Server ready")
                return
            except Exception:
                time.sleep(0.25)
        self.lbl_status.configure(text="⚠ Server not responding")

    # ── Analysis ──────────────────────────────────────────────────────────────
    def _trigger_analyze(self):
        self._results.clear()
        for row in self._model_rows.values():
            row["dot"].configure(fg=TEXT_DIM)
            row["sig"].configure(text="—", fg=TEXT_DIM)
            row["lat"].configure(text="…")
        self.lbl_signal.configure(text="…", fg=TEXT_MID)
        self.lbl_conf.configure(text="Querying models…", fg=TEXT_MID)
        for lv in self.lbl_votes.values():
            lv.configure(text="0")
        threading.Thread(target=self._stream_analyze,
                         args=(self.selected_coin,), daemon=True).start()

    def _stream_analyze(self, coin: str):
        try:
            with requests.get(f"{SERVER_URL}/analyze/{coin}", stream=True, timeout=30) as resp:
                for raw in resp.iter_lines():
                    if not self.running:
                        break
                    if not raw:
                        continue
                    line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    if not line.startswith("data: "):
                        continue
                    msg = json.loads(line[6:])
                    self._q.put(msg)
        except Exception as e:
            self._q.put({"type": "error", "msg": str(e)[:60]})

    # ── Queue poll ────────────────────────────────────────────────────────────
    def _poll_queue(self):
        try:
            while True:
                msg = self._q.get_nowait()
                t = msg.get("type")
                if t == "market":
                    self._show_price(msg["data"])
                elif t == "signal":
                    self._show_model(msg["result"])
                    self._refresh_vote_totals()
                elif t == "done":
                    self._refresh_vote_totals()
                    self.lbl_status.configure(
                        text=f"✓ Done  {time.strftime('%H:%M:%S')}")
                    self.root.after(5000, self._trigger_analyze)
                elif t == "error":
                    self.lbl_status.configure(text=f"✗ {msg['msg'][:40]}")
        except queue.Empty:
            pass

        self.lbl_time.configure(text=time.strftime("%H:%M:%S"))
        if self.running:
            self.root.after(200, self._poll_queue)

    def _show_price(self, d: dict):
        p = d["price"]
        ps = (f"${p:,.0f}" if p >= 1000 else f"${p:,.2f}" if p >= 1 else f"${p:.5f}")
        self.lbl_price.configure(text=ps)
        ch = d["change_24h"]
        self.lbl_change.configure(
            text=f"{ch:+.2f}% 24h  {d['change_1h']:+.2f}% 1h",
            fg=GREEN if ch >= 0 else RED,
        )

    def _show_model(self, r: dict):
        row = self._model_rows.get(r["model"])
        if not row:
            return
        clr = SIGNAL_FG.get(r["signal"], TEXT_DIM)
        row["dot"].configure(fg=clr)
        row["sig"].configure(text=r["signal"][:7], fg=clr)
        row["lat"].configure(text=f"{r['latency_ms']}ms" if r.get("ok") else r["signal"][:6])

    def _refresh_vote_totals(self):
        votes = [r["signal"] for r in self._results.values()
                 if r["signal"] in ("BUY", "SELL", "HOLD")]
        responded = len(votes)
        total     = len(ALL_MODELS)
        for sig, lv in self.lbl_votes.items():
            lv.configure(text=str(votes.count(sig)))
        self.lbl_responded.configure(text=f"{responded}/{total} responded")
        if not votes:
            return
        verdict, conf = _majority(self._results)
        clr = SIGNAL_FG.get(verdict, TEXT_MID)
        self.lbl_signal.configure(text=verdict, fg=clr)
        self.lbl_conf.configure(
            text=f"{conf}% confidence  ({responded}/{total} models)", fg=clr)

    # ── Coin switch ───────────────────────────────────────────────────────────
    def _switch_coin(self, coin: str):
        self.selected_coin = coin
        self._highlight_coin(coin)
        self._trigger_analyze()

    def _highlight_coin(self, coin: str):
        for c, b in self._coin_btns.items():
            b.configure(bg=ACCENT if c == coin else BG_PANEL,
                        fg="#000000" if c == coin else TEXT_MID)

    def _quit(self):
        self.running = False
        self.root.destroy()


def _sep(parent):
    tk.Frame(parent, bg=BORDER, height=1).pack(fill=tk.X)


if __name__ == "__main__":
    CryptoOverlay()
