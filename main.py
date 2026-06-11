"""
Crypto AI Overlay — Windows always-on-top trading signal analyzer.
FastAPI backend on localhost:8765, SSE stream → tkinter UI.
"""
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
import requests
import uvicorn

from server import app
from config import ALL_MODELS, COINS

SERVER_PORT = 8765
SERVER_URL  = f"http://127.0.0.1:{SERVER_PORT}"

# ── Palette ──────────────────────────────────────────────────────────────────
BG        = "#0a0a0f"
BG2       = "#12121a"
BG3       = "#1a1a26"
BORDER    = "#2a2a3a"
DIM       = "#3a3a5a"
MID       = "#6a6a9a"
TEXT      = "#c0c0d8"
WHITE     = "#f0f0ff"
GREEN     = "#00e676"
GREEN_BG  = "#001a0d"
RED       = "#ff4444"
RED_BG    = "#1a0000"
YELLOW    = "#ffcc00"
YELLOW_BG = "#1a1500"
BLUE      = "#4488ff"
PURPLE    = "#aa66ff"

SIGNAL_FG = {"BUY": GREEN, "SELL": RED, "HOLD": YELLOW}
SIGNAL_BG = {"BUY": GREEN_BG, "SELL": RED_BG, "HOLD": YELLOW_BG}

WIN_W = 420


def _majority(results: dict):
    votes = [r["signal"] for r in results.values() if r["signal"] in ("BUY", "SELL", "HOLD")]
    if not votes:
        return "—", 0
    buy, sell, hold = votes.count("BUY"), votes.count("SELL"), votes.count("HOLD")
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
        self.root.attributes("-alpha", 0.95)
        self.root.configure(bg=BG)
        self.root.geometry("+60+60")
        self.root.resizable(False, False)

    def _bind_drag(self):
        for w in (self.root, self._title_bar):
            w.bind("<Button-1>",  lambda e: (
                setattr(self, "_drag_x", e.x_root - self.root.winfo_x()),
                setattr(self, "_drag_y", e.y_root - self.root.winfo_y())))
            w.bind("<B1-Motion>", lambda e: self.root.geometry(
                f"+{e.x_root-self._drag_x}+{e.y_root-self._drag_y}"))

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root

        # ── Title bar ─────────────────────────────────────────────────────────
        self._title_bar = tk.Frame(r, bg=BG2, height=36)
        self._title_bar.pack(fill=tk.X)
        self._title_bar.pack_propagate(False)
        tk.Label(self._title_bar, text="◈", bg=BG2, fg=BLUE,
                 font=("Consolas", 12, "bold")).pack(side=tk.LEFT, padx=(12, 4), pady=6)
        tk.Label(self._title_bar, text="CRYPTO AI SIGNALS", bg=BG2, fg=WHITE,
                 font=("Consolas", 10, "bold")).pack(side=tk.LEFT, pady=6)
        x = tk.Label(self._title_bar, text="  ✕  ", bg=BG2, fg=MID,
                     font=("Consolas", 11), cursor="hand2")
        x.pack(side=tk.RIGHT, padx=4)
        x.bind("<Button-1>", lambda _: self._quit())
        x.bind("<Enter>", lambda _: x.configure(fg=RED))
        x.bind("<Leave>", lambda _: x.configure(fg=MID))
        _line(r, BORDER)

        # ── Coin selector ──────────────────────────────────────────────────────
        coin_row = tk.Frame(r, bg=BG2, pady=8)
        coin_row.pack(fill=tk.X, padx=10)
        self._coin_btns = {}
        for coin in COINS:
            f = tk.Frame(coin_row, bg=BG3, cursor="hand2")
            f.pack(side=tk.LEFT, padx=3)
            lbl = tk.Label(f, text=coin, bg=BG3, fg=MID,
                           font=("Consolas", 9, "bold"), padx=10, pady=5)
            lbl.pack()
            lbl.bind("<Button-1>", lambda e, c=coin: self._switch_coin(c))
            f.bind("<Button-1>",   lambda e, c=coin: self._switch_coin(c))
            self._coin_btns[coin] = (f, lbl)
        self._highlight_coin("BTC")
        _line(r, BORDER)

        # ── Price ──────────────────────────────────────────────────────────────
        price_block = tk.Frame(r, bg=BG, pady=10)
        price_block.pack(fill=tk.X, padx=14)
        self.lbl_price = tk.Label(price_block, text="$——", bg=BG, fg=WHITE,
                                  font=("Consolas", 26, "bold"), anchor=tk.W)
        self.lbl_price.pack(side=tk.LEFT)
        right_col = tk.Frame(price_block, bg=BG)
        right_col.pack(side=tk.RIGHT)
        self.lbl_change_24h = tk.Label(right_col, text="——  24h", bg=BG, fg=DIM,
                                       font=("Consolas", 9), anchor=tk.E)
        self.lbl_change_24h.pack(anchor=tk.E)
        self.lbl_change_1h  = tk.Label(right_col, text="——  1h",  bg=BG, fg=DIM,
                                       font=("Consolas", 9), anchor=tk.E)
        self.lbl_change_1h.pack(anchor=tk.E)
        _line(r, BORDER)

        # ── BIG Signal ─────────────────────────────────────────────────────────
        self._sig_frame = tk.Frame(r, bg=BG, pady=12)
        self._sig_frame.pack(fill=tk.X, padx=14)
        self.lbl_signal = tk.Label(self._sig_frame, text="WAITING", bg=BG, fg=DIM,
                                   font=("Consolas", 44, "bold"), anchor=tk.CENTER)
        self.lbl_signal.pack(fill=tk.X)
        self.lbl_conf = tk.Label(self._sig_frame, text="Querying AI models…",
                                 bg=BG, fg=MID, font=("Consolas", 9))
        self.lbl_conf.pack()

        # confidence bar
        bar_frame = tk.Frame(r, bg=BG, pady=4)
        bar_frame.pack(fill=tk.X, padx=14)
        self._conf_bar_bg = tk.Frame(bar_frame, bg=BG3, height=6)
        self._conf_bar_bg.pack(fill=tk.X)
        self._conf_bar_fg = tk.Frame(self._conf_bar_bg, bg=DIM, height=6)
        self._conf_bar_fg.place(x=0, y=0, relheight=1, relwidth=0)

        _line(r, BORDER)

        # ── Vote counters ──────────────────────────────────────────────────────
        vote_row = tk.Frame(r, bg=BG2, pady=8)
        vote_row.pack(fill=tk.X)
        self.lbl_votes = {}
        for sig, fg, bg in [("BUY", GREEN, BG2), ("HOLD", YELLOW, BG2), ("SELL", RED, BG2)]:
            col = tk.Frame(vote_row, bg=bg)
            col.pack(side=tk.LEFT, expand=True)
            tk.Label(col, text=sig, bg=bg, fg=fg,
                     font=("Consolas", 8, "bold")).pack()
            lv = tk.Label(col, text="—", bg=bg, fg=WHITE,
                          font=("Consolas", 20, "bold"))
            lv.pack()
            self.lbl_votes[sig] = lv
        _line(r, BORDER)

        # ── Models section ────────────────────────────────────────────────────
        hdr = tk.Frame(r, bg=BG)
        hdr.pack(fill=tk.X, padx=14, pady=(8, 4))
        tk.Label(hdr, text="AI MODELS", bg=BG, fg=DIM,
                 font=("Consolas", 8, "bold")).pack(side=tk.LEFT)
        self.lbl_responded = tk.Label(hdr, text="0 / 0", bg=BG, fg=DIM,
                                      font=("Consolas", 8))
        self.lbl_responded.pack(side=tk.RIGHT)

        self._model_rows: dict = {}
        mf = tk.Frame(r, bg=BG)
        mf.pack(fill=tk.X, padx=10, pady=(0, 6))

        prev_provider = None
        for m in ALL_MODELS:
            prov = m["provider"]
            if prov != prev_provider:
                prov_label = "● NVIDIA NIM" if prov == "nvidia" else "● GROQ"
                prov_color = BLUE if prov == "nvidia" else PURPLE
                tk.Label(mf, text=prov_label, bg=BG, fg=prov_color,
                         font=("Consolas", 7, "bold")).pack(
                    anchor=tk.W, padx=6, pady=(4, 1))
                prev_provider = prov

            row = tk.Frame(mf, bg=BG2, pady=3)
            row.pack(fill=tk.X, padx=4, pady=1)
            dot  = tk.Label(row, text="◆", bg=BG2, fg=DIM, font=("Consolas", 7))
            dot.pack(side=tk.LEFT, padx=(8, 5))
            name = tk.Label(row, text=m["name"].replace("NIM ", "").replace("Groq ", ""),
                            bg=BG2, fg=TEXT, font=("Consolas", 8), anchor=tk.W)
            name.pack(side=tk.LEFT)
            lat  = tk.Label(row, text="", bg=BG2, fg=DIM, font=("Consolas", 7))
            lat.pack(side=tk.RIGHT, padx=6)
            sig  = tk.Label(row, text="—", bg=BG2, fg=DIM,
                            font=("Consolas", 8, "bold"), width=5, anchor=tk.E)
            sig.pack(side=tk.RIGHT, padx=4)
            self._model_rows[m["name"]] = {"dot": dot, "lat": lat, "sig": sig, "row": row}

        _line(r, BORDER)

        # ── Status bar ────────────────────────────────────────────────────────
        bar = tk.Frame(r, bg=BG2, pady=4)
        bar.pack(fill=tk.X)
        self.lbl_status = tk.Label(bar, text="Starting…", bg=BG2, fg=DIM,
                                   font=("Consolas", 7))
        self.lbl_status.pack(side=tk.LEFT, padx=10)
        refresh_btn = tk.Label(bar, text="↺ refresh", bg=BG2, fg=BLUE,
                               font=("Consolas", 7), cursor="hand2")
        refresh_btn.pack(side=tk.RIGHT, padx=10)
        refresh_btn.bind("<Button-1>", lambda _: self._trigger_analyze())
        self.lbl_time = tk.Label(bar, text="", bg=BG2, fg=DIM, font=("Consolas", 7))
        self.lbl_time.pack(side=tk.RIGHT, padx=4)

    # ── Server ────────────────────────────────────────────────────────────────
    def _start_server(self):
        def run():
            uvicorn.run(app, host="127.0.0.1", port=SERVER_PORT,
                        log_level="error", access_log=False)
        threading.Thread(target=run, daemon=True).start()

    def _wait_for_server(self):
        self.lbl_status.configure(text="Starting local server…")
        self.root.update()
        for _ in range(40):
            try:
                requests.get(f"{SERVER_URL}/health", timeout=0.5)
                self.lbl_status.configure(text="✓ Server ready")
                return
            except Exception:
                time.sleep(0.25)
        self.lbl_status.configure(text="⚠ Server timeout")

    # ── Analysis ──────────────────────────────────────────────────────────────
    def _trigger_analyze(self):
        self._results.clear()
        for row in self._model_rows.values():
            row["dot"].configure(fg=DIM)
            row["sig"].configure(text="—", fg=DIM)
            row["lat"].configure(text="")
            row["row"].configure(bg=BG2)
        for lv in self.lbl_votes.values():
            lv.configure(text="—")
        self.lbl_signal.configure(text="…", fg=DIM, bg=BG)
        self._sig_frame.configure(bg=BG)
        self.lbl_conf.configure(text="Querying AI models…", fg=MID, bg=BG)
        self._conf_bar_fg.place(relwidth=0)
        self.lbl_responded.configure(text="0 / 0")
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
                    self._q.put(json.loads(line[6:]))
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
                    r = msg["result"]
                    self._results[r["model"]] = r    # ← fix: store result
                    self._show_model(r)
                    self._refresh_vote_totals()
                elif t == "done":
                    self._refresh_vote_totals()
                    self.lbl_status.configure(
                        text=f"✓ Done  {time.strftime('%H:%M:%S')}")
                    self.root.after(5000, self._trigger_analyze)
                elif t == "error":
                    self.lbl_status.configure(text=f"✗ {msg['msg'][:44]}")
        except queue.Empty:
            pass

        self.lbl_time.configure(text=time.strftime("%H:%M:%S"))
        if self.running:
            self.root.after(200, self._poll_queue)

    # ── Display helpers ───────────────────────────────────────────────────────
    def _show_price(self, d: dict):
        p = d["price"]
        ps = (f"${p:,.0f}" if p >= 1000 else f"${p:,.2f}" if p >= 1 else f"${p:.5f}")
        self.lbl_price.configure(text=ps)
        ch24 = d["change_24h"]
        ch1h  = d["change_1h"]
        self.lbl_change_24h.configure(
            text=f"{ch24:+.2f}%  24h", fg=GREEN if ch24 >= 0 else RED)
        self.lbl_change_1h.configure(
            text=f"{ch1h:+.2f}%   1h",  fg=GREEN if ch1h  >= 0 else RED)

    def _show_model(self, r: dict):
        row = self._model_rows.get(r["model"])
        if not row:
            return
        sig = r["signal"]
        clr = SIGNAL_FG.get(sig, DIM)
        row["dot"].configure(fg=clr)
        row["sig"].configure(text=sig[:7], fg=clr)
        row["lat"].configure(
            text=f"{r['latency_ms']}ms" if r.get("ok") else (r.get("err", sig)[:10]))

    def _refresh_vote_totals(self):
        votes = [r["signal"] for r in self._results.values()
                 if r["signal"] in ("BUY", "SELL", "HOLD")]
        responded = len(votes)
        total     = len(ALL_MODELS)

        for sig, lv in self.lbl_votes.items():
            cnt = votes.count(sig)
            lv.configure(text=str(cnt) if cnt else "—")
        self.lbl_responded.configure(text=f"{responded} / {total}")

        if not votes:
            return

        verdict, conf = _majority(self._results)
        fg = SIGNAL_FG.get(verdict, MID)
        bg = SIGNAL_BG.get(verdict, BG)

        self.lbl_signal.configure(text=verdict, fg=fg, bg=bg)
        self._sig_frame.configure(bg=bg)
        self.lbl_conf.configure(
            text=f"{conf}% confidence   {responded}/{total} models",
            fg=fg, bg=bg)
        self._conf_bar_fg.configure(bg=fg)
        self._conf_bar_fg.place(relwidth=conf / 100)

    # ── Coin switch ───────────────────────────────────────────────────────────
    def _switch_coin(self, coin: str):
        self.selected_coin = coin
        self._highlight_coin(coin)
        self._trigger_analyze()

    def _highlight_coin(self, coin: str):
        for c, (f, lbl) in self._coin_btns.items():
            if c == coin:
                f.configure(bg=BLUE)
                lbl.configure(bg=BLUE, fg="#000000")
            else:
                f.configure(bg=BG3)
                lbl.configure(bg=BG3, fg=MID)

    def _quit(self):
        self.running = False
        self.root.destroy()


def _line(parent, color):
    tk.Frame(parent, bg=color, height=1).pack(fill=tk.X)


if __name__ == "__main__":
    CryptoOverlay()
