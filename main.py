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
from config import ALL_MODELS, COINS, AI_REFRESH_SEC, LIVE_PRICE_REFRESH_SEC

SERVER_PORT = 8765
SERVER_URL  = f"http://127.0.0.1:{SERVER_PORT}"

# ── Palette ──────────────────────────────────────────────────────────────────
BG        = "#0a0a0f"
BG2       = "#12121a"
BG3       = "#1a1a26"
BORDER    = "#2a2a3a"
BORDER_GLOW = "#4488ff"
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
        self.trade_mode    = "FUTURES"  # "SPOT" or "FUTURES"
        self.position      = None       # None or {"type": "LONG"|"SHORT", "entry_price": float}
        self.current_price = 0.0
        self.running       = True
        
        self._results: dict = {}
        self._q: queue.Queue = queue.Queue()
        self._drag_x = self._drag_y = 0
        self._after_id = None
        
        # Confidence bar animation variables
        self.target_conf_pct = 0.0
        self.current_conf_pct = 0.0

        self._build_ui()
        self._bind_drag()
        self._start_server()
        self._wait_for_server()
        self._start_price_loop()
        self._trigger_analyze()
        self._poll_queue()
        self.root.mainloop()

    # ── Window ────────────────────────────────────────────────────────────────
    def _configure_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
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
        coin_row = tk.Frame(r, bg=BG2, pady=6)
        coin_row.pack(fill=tk.X, padx=10)
        self._coin_btns = {}
        for coin in COINS:
            f = tk.Frame(coin_row, bg=BG3, cursor="hand2")
            f.pack(side=tk.LEFT, padx=3, expand=True, fill=tk.X)
            lbl = tk.Label(f, text=coin, bg=BG3, fg=MID,
                           font=("Consolas", 9, "bold"), pady=5)
            lbl.pack(fill=tk.X)
            
            lbl.bind("<Button-1>", lambda e, c=coin: self._switch_coin(c))
            f.bind("<Button-1>",   lambda e, c=coin: self._switch_coin(c))
            
            # Hover bindings
            f.bind("<Enter>", lambda e, c=coin: self._hover_coin(c, True))
            f.bind("<Leave>", lambda e, c=coin: self._hover_coin(c, False))
            lbl.bind("<Enter>", lambda e, c=coin: self._hover_coin(c, True))
            lbl.bind("<Leave>", lambda e, c=coin: self._hover_coin(c, False))
            
            self._coin_btns[coin] = (f, lbl)
        self._highlight_coin("BTC")
        
        # ── Mode selector (SPOT vs FUTURES) ───────────────────────────────────
        mode_row = tk.Frame(r, bg=BG2, pady=5)
        mode_row.pack(fill=tk.X, padx=10)
        self._mode_btns = {}
        for mode in ("SPOT", "FUTURES"):
            f = tk.Frame(mode_row, bg=BG3, cursor="hand2")
            f.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
            lbl = tk.Label(f, text=mode, bg=BG3, fg=MID,
                           font=("Consolas", 8, "bold"), pady=4)
            lbl.pack(fill=tk.X)
            
            lbl.bind("<Button-1>", lambda e, m=mode: self._switch_mode(m))
            f.bind("<Button-1>",   lambda e, m=mode: self._switch_mode(m))
            
            # Hover bindings
            f.bind("<Enter>", lambda e, m=mode: self._hover_mode(m, True))
            f.bind("<Leave>", lambda e, m=mode: self._hover_mode(m, False))
            lbl.bind("<Enter>", lambda e, m=mode: self._hover_mode(m, True))
            lbl.bind("<Leave>", lambda e, m=mode: self._hover_mode(m, False))
            
            self._mode_btns[mode] = (f, lbl)
        self._highlight_mode("FUTURES")
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

        # ── Virtual Position Panel ─────────────────────────────────────────────
        self.pos_frame = tk.Frame(r, bg=BG, pady=8)
        self.pos_frame.pack(fill=tk.X, padx=14)
        self._build_position_panel()
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
        self.lbl_vote_headers = {}
        for sig, fg, bg in [("BUY", GREEN, BG2), ("HOLD", YELLOW, BG2), ("SELL", RED, BG2)]:
            col = tk.Frame(vote_row, bg=bg)
            col.pack(side=tk.LEFT, expand=True)
            hdr = tk.Label(col, text=sig, bg=bg, fg=fg,
                     font=("Consolas", 8, "bold"))
            hdr.pack()
            self.lbl_vote_headers[sig] = hdr
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
        refresh_btn.bind("<Enter>", lambda _: refresh_btn.configure(fg=WHITE))
        refresh_btn.bind("<Leave>", lambda _: refresh_btn.configure(fg=BLUE))
        
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

    # ── Real-Time Price Polling ────────────────────────────────────────────────
    def _start_price_loop(self):
        def run():
            while self.running:
                try:
                    category = "spot" if self.trade_mode == "SPOT" else "linear"
                    resp = requests.get(f"{SERVER_URL}/market/{self.selected_coin}?category={category}", timeout=1.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        if "error" not in data:
                            self._q.put({"type": "live_price", "coin": self.selected_coin, "data": data})
                except Exception:
                    pass
                time.sleep(LIVE_PRICE_REFRESH_SEC)
        threading.Thread(target=run, daemon=True).start()

    def _trigger_price_update(self):
        def run():
            try:
                category = "spot" if self.trade_mode == "SPOT" else "linear"
                resp = requests.get(f"{SERVER_URL}/market/{self.selected_coin}?category={category}", timeout=1.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if "error" not in data:
                        self._q.put({"type": "live_price", "coin": self.selected_coin, "data": data})
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

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
        
        self.target_conf_pct = 0.0
        self.current_conf_pct = 0.0
        self._conf_bar_fg.place(relwidth=0)
        self.lbl_responded.configure(text="0 / 0")
        
        self._pulse_waiting()
        
        threading.Thread(target=self._stream_analyze,
                         args=(self.selected_coin,), daemon=True).start()

    def _stream_analyze(self, coin: str):
        try:
            category = "spot" if self.trade_mode == "SPOT" else "linear"
            with requests.get(f"{SERVER_URL}/analyze/{coin}?category={category}", stream=True, timeout=30) as resp:
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
            self._q.put({"type": "error", "coin": coin, "msg": str(e)[:60]})

    # ── Queue poll ────────────────────────────────────────────────────────────
    def _poll_queue(self):
        try:
            while True:
                msg = self._q.get_nowait()
                t = msg.get("type")
                msg_coin = msg.get("coin")
                
                # Check for obsolete coin response (avoids coin switching race condition)
                if msg_coin and msg_coin != self.selected_coin:
                    continue
                
                if t == "market" or t == "live_price":
                    self._show_price(msg["data"])
                elif t == "signal":
                    r = msg["result"]
                    self._results[r["model"]] = r
                    self._show_model(r)
                    self._refresh_vote_totals()
                elif t == "done":
                    self._refresh_vote_totals()
                    self.lbl_status.configure(
                        text=f"✓ Done  {time.strftime('%H:%M:%S')}")
                    
                    if self._after_id:
                        try:
                            self.root.after_cancel(self._after_id)
                        except Exception:
                            pass
                    self._after_id = self.root.after(AI_REFRESH_SEC * 1000, self._trigger_analyze)
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
        self.current_price = p
        
        # Format price based on size
        ps = (f"${p:,.0f}" if p >= 1000 else f"${p:,.2f}" if p >= 1 else f"${p:.5f}")
        self.lbl_price.configure(text=ps)
        
        ch24 = d["change_24h"]
        ch1h  = d["change_1h"]
        self.lbl_change_24h.configure(
            text=f"{ch24:+.2f}%  24h", fg=GREEN if ch24 >= 0 else RED)
        self.lbl_change_1h.configure(
            text=f"{ch1h:+.2f}%   1h",  fg=GREEN if ch1h  >= 0 else RED)
            
        self._update_pnl_display()

    def _show_model(self, r: dict):
        row = self._model_rows.get(r["model"])
        if not row:
            return
        sig = r["signal"]
        
        # Display mapped signal for futures if configured
        display_sig = sig
        if self.trade_mode == "FUTURES":
            if sig == "BUY": display_sig = "LONG"
            elif sig == "SELL": display_sig = "SHORT"
            
        clr = SIGNAL_FG.get(sig, DIM)
        row["dot"].configure(fg=clr)
        row["sig"].configure(text=display_sig[:7], fg=clr)
        row["lat"].configure(
            text=f"{r['latency_ms']}ms" if r.get("ok") else (r.get("err", sig)[:10]))

    def _refresh_vote_totals(self):
        votes = [r["signal"] for r in self._results.values()
                 if r["signal"] in ("BUY", "SELL", "HOLD")]
        responded = len(votes)
        total     = len(ALL_MODELS)

        # Update headers dynamically based on mode
        is_futures = (self.trade_mode == "FUTURES")
        self.lbl_vote_headers["BUY"].configure(text="LONG" if is_futures else "BUY")
        self.lbl_vote_headers["SELL"].configure(text="SHORT" if is_futures else "SELL")

        for sig, lv in self.lbl_votes.items():
            cnt = votes.count(sig)
            lv.configure(text=str(cnt) if cnt else "—")
        self.lbl_responded.configure(text=f"{responded} / {total}")

        if not votes:
            return

        verdict, conf = _majority(self._results)
        
        # Map verdict to FUTURES mode names
        display_verdict = verdict
        if is_futures:
            if verdict == "BUY": display_verdict = "LONG"
            elif verdict == "SELL": display_verdict = "SHORT"
            
        fg = SIGNAL_FG.get(verdict, MID)
        bg = SIGNAL_BG.get(verdict, BG)

        self.lbl_signal.configure(text=display_verdict, fg=fg, bg=bg)
        self._sig_frame.configure(bg=bg)
        self.lbl_conf.configure(
            text=f"{conf}% confidence   {responded}/{total} models",
            fg=fg, bg=bg)
            
        # Trigger smooth progress bar animation
        self.target_conf_pct = conf
        self._animate_conf_bar()

    # ── Virtual Position Panel Logic ─────────────────────────────────────────
    def _build_position_panel(self):
        # Clear existing widgets
        for w in self.pos_frame.winfo_children():
            w.destroy()

        if not self.position:
            # Title
            lbl_title = tk.Label(self.pos_frame, text="VIRTUAL TRADE:", bg=BG, fg=DIM, font=("Consolas", 8, "bold"))
            lbl_title.pack(side=tk.LEFT, pady=4)
            
            # Long Button Frame
            btn_long_f = tk.Frame(self.pos_frame, bg=GREEN_BG, highlightbackground=BORDER, highlightthickness=1, cursor="hand2")
            btn_long_f.pack(side=tk.LEFT, padx=(10, 4))
            btn_long = tk.Label(btn_long_f, text="🟢 LONG", bg=GREEN_BG, fg=GREEN, font=("Consolas", 8, "bold"), padx=14, pady=3)
            btn_long.pack()
            
            # Short Button Frame
            btn_short_f = tk.Frame(self.pos_frame, bg=RED_BG, highlightbackground=BORDER, highlightthickness=1, cursor="hand2")
            btn_short_f.pack(side=tk.LEFT, padx=4)
            btn_short = tk.Label(btn_short_f, text="🔴 SHORT", bg=RED_BG, fg=RED, font=("Consolas", 8, "bold"), padx=14, pady=3)
            btn_short.pack()
            
            # Bindings
            btn_long.bind("<Button-1>", lambda e: self._open_position("LONG"))
            btn_long_f.bind("<Button-1>", lambda e: self._open_position("LONG"))
            btn_short.bind("<Button-1>", lambda e: self._open_position("SHORT"))
            btn_short_f.bind("<Button-1>", lambda e: self._open_position("SHORT"))
            
            # Hover bindings
            btn_long.bind("<Enter>", lambda e: (btn_long_f.configure(bg=GREEN), btn_long.configure(bg=GREEN, fg=BG)))
            btn_long.bind("<Leave>", lambda e: (btn_long_f.configure(bg=GREEN_BG), btn_long.configure(bg=GREEN_BG, fg=GREEN)))
            btn_short.bind("<Enter>", lambda e: (btn_short_f.configure(bg=RED), btn_short.configure(bg=RED, fg=BG)))
            btn_short.bind("<Leave>", lambda e: (btn_short_f.configure(bg=RED_BG), btn_short.configure(bg=RED_BG, fg=RED)))
        else:
            pos_type = self.position["type"]
            entry_price = self.position["entry_price"]
            pos_color = GREEN if pos_type == "LONG" else RED
            
            # Info label
            entry_s = (f"${entry_price:,.0f}" if entry_price >= 1000 else f"${entry_price:,.2f}" if entry_price >= 1 else f"${entry_price:.5f}")
            lbl_info = tk.Label(self.pos_frame, text=f"{pos_type} @ {entry_s}", bg=BG, fg=pos_color, font=("Consolas", 9, "bold"))
            lbl_info.pack(side=tk.LEFT, pady=4)
            
            # Live PnL Label
            self.lbl_pnl = tk.Label(self.pos_frame, text="PnL: $0.00 (+0.00%)", bg=BG, fg=MID, font=("Consolas", 9, "bold"))
            self.lbl_pnl.pack(side=tk.LEFT, padx=12, pady=4)
            
            # Close button
            btn_close_f = tk.Frame(self.pos_frame, bg=BG3, highlightbackground=BORDER, highlightthickness=1, cursor="hand2")
            btn_close_f.pack(side=tk.RIGHT, padx=4)
            btn_close = tk.Label(btn_close_f, text="✕ CLOSE", bg=BG3, fg=TEXT, font=("Consolas", 8, "bold"), padx=10, pady=3)
            btn_close.pack()
            
            btn_close.bind("<Button-1>", lambda e: self._close_position())
            btn_close_f.bind("<Button-1>", lambda e: self._close_position())
            btn_close.bind("<Enter>", lambda e: (btn_close_f.configure(bg=RED), btn_close.configure(bg=RED, fg=WHITE)))
            btn_close.bind("<Leave>", lambda e: (btn_close_f.configure(bg=BG3), btn_close.configure(bg=BG3, fg=TEXT)))
            
            self._update_pnl_display()

    def _open_position(self, pos_type: str):
        if self.current_price > 0:
            self.position = {
                "type": pos_type,
                "entry_price": self.current_price,
            }
            self._build_position_panel()

    def _close_position(self):
        self.position = None
        self._build_position_panel()

    def _update_pnl_display(self):
        if not self.position or not hasattr(self, "lbl_pnl") or self.current_price <= 0:
            return
        
        entry = self.position["entry_price"]
        curr = self.current_price
        pos_type = self.position["type"]
        
        if pos_type == "LONG":
            pnl_pct = (curr - entry) / entry * 100
        else:
            pnl_pct = (entry - curr) / entry * 100
            
        # Virtual position margin size assumes $1,000 USD
        pnl_usd = 1000.0 * (pnl_pct / 100.0)
        pnl_color = GREEN if pnl_pct >= 0 else RED
        sign = "+" if pnl_pct >= 0 else ""
        
        self.lbl_pnl.configure(
            text=f"PnL: {sign}${pnl_usd:,.2f} ({sign}{pnl_pct:+.2f}%)",
            fg=pnl_color
        )

    # ── GUI Animations ─────────────────────────────────────────────────────────
    def _animate_conf_bar(self):
        if not hasattr(self, "_conf_bar_fg"):
            return
        diff = self.target_conf_pct - self.current_conf_pct
        if abs(diff) < 0.5:
            self.current_conf_pct = self.target_conf_pct
            self._conf_bar_fg.place(relwidth=self.current_conf_pct / 100.0)
        else:
            self.current_conf_pct += diff * 0.22  # Smooth step interpolation
            self._conf_bar_fg.place(relwidth=self.current_conf_pct / 100.0)
            self.root.after(30, self._animate_conf_bar)

    def _pulse_waiting(self, step=0):
        # Stop pulsing if we are no longer querying (i.e. signal text is not loading state)
        if not self.lbl_signal or self.lbl_signal.cget("text") not in ("…", "WAITING"):
            return
        
        colors = ["#3a3a5a", "#4a4a6e", "#5a5a82", "#6a6a9a", "#5a5a82", "#4a4a6e"]
        color = colors[step % len(colors)]
        self.lbl_signal.configure(fg=color)
        self.lbl_conf.configure(fg=color)
        
        self.root.after(150, lambda: self._pulse_waiting(step + 1))

    # ── Interactive Hover Handlers ───────────────────────────────────────────
    def _hover_coin(self, coin: str, entered: bool):
        if coin == self.selected_coin:
            return
        f, lbl = self._coin_btns[coin]
        if entered:
            f.configure(bg=DIM)
            lbl.configure(bg=DIM, fg=WHITE)
        else:
            f.configure(bg=BG3)
            lbl.configure(bg=BG3, fg=MID)

    def _hover_mode(self, mode: str, entered: bool):
        if mode == self.trade_mode:
            return
        f, lbl = self._mode_btns[mode]
        if entered:
            f.configure(bg=DIM)
            lbl.configure(bg=DIM, fg=WHITE)
        else:
            f.configure(bg=BG3)
            lbl.configure(bg=BG3, fg=MID)

    # ── Coin & Mode Switches ─────────────────────────────────────────────────
    def _switch_coin(self, coin: str):
        if self.selected_coin == coin:
            return
        self.selected_coin = coin
        self._highlight_coin(coin)
        self._trigger_analyze()
        self._trigger_price_update()

    def _highlight_coin(self, coin: str):
        for c, (f, lbl) in self._coin_btns.items():
            if c == coin:
                f.configure(bg=BLUE)
                lbl.configure(bg=BLUE, fg="#000000")
            else:
                f.configure(bg=BG3)
                lbl.configure(bg=BG3, fg=MID)

    def _switch_mode(self, mode: str):
        if self.trade_mode == mode:
            return
        self.trade_mode = mode
        self._highlight_mode(mode)
        
        # Re-map votes for display
        self._refresh_vote_totals()
        
        # Redraw entry tag if active
        if self.position:
            self._build_position_panel()
            
        self._trigger_price_update()

    def _highlight_mode(self, mode: str):
        for m, (f, lbl) in self._mode_btns.items():
            if m == mode:
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
