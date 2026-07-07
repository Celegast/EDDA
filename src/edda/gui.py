"""EDDA desktop control panel — tkinter GUI, no Flask required."""

from __future__ import annotations

import calendar as _cal
import math
import os
import queue
import struct
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
import webbrowser
from datetime import date as _date, datetime as _datetime
from pathlib import Path
from tkinter import messagebox, ttk

from . import __version__ as _VERSION
from .config import (
    _EDDA_DIR,
    get_active_commander, get_commander_db_path, get_selected_commanders,
    get_ui_state, list_commanders,
    set_active_commander, set_selected_commanders, set_ui_state,
)

# ── Colour palette ─────────────────────────────────────────────────────────────
_BG     = "#0d1117"
_SURF   = "#161b22"
_SURF2  = "#21262d"
_BORDER = "#30363d"
_TEXT   = "#e6edf3"
_MUTED  = "#8b949e"
_ACCENT = "#58a6ff"
_GREEN  = "#3fb950"
_ORANGE = "#f0883e"
_RED    = "#f85149"
_FONT   = ("Segoe UI", 9)
_FONT_B = ("Segoe UI", 9, "bold")
_FONT_S = ("Segoe UI", 8)
_MONO   = ("Consolas", 9)


# ── ICO generation ─────────────────────────────────────────────────────────────

def _make_ico() -> bytes:
    """32×32 ICO: 8-pointed navigation star, warm-white core → blue body + halo."""
    W = H = 32
    BG    = (0x17, 0x11, 0x0d)  # #0d1117  (BGR)
    BLUE  = (0xff, 0xa6, 0x58)  # #58a6ff  (BGR)
    WHITE = (0xff, 0xf6, 0xee)  # warm near-white core (BGR)

    cx = cy = (W - 1) / 2.0

    def lerp(a, b, t: float):
        t = max(0.0, min(1.0, t))
        return (int(a[0] + (b[0]-a[0])*t),
                int(a[1] + (b[1]-a[1])*t),
                int(a[2] + (b[2]-a[2])*t))

    def star_r(theta: float, n: int, r_out: float, r_in: float) -> float:
        """Smooth n-pointed star boundary radius at angle theta."""
        return r_in + (r_out - r_in) * (math.cos(n * theta) + 1) / 2

    rows = []
    for y in range(H - 1, -1, -1):   # ICO rows are bottom-up
        row = bytearray()
        for x in range(W):
            dx, dy = x - cx, y - cy
            r     = math.hypot(dx, dy) + 1e-9
            theta = math.atan2(dy, dx)

            # 8-pointed star = union of two 4-point stars (0° and 45°)
            b_axis = star_r(theta,             4, 13.0, 4.0)  # long cardinal tips
            b_diag = star_r(theta - math.pi/4, 4,  8.0, 4.0)  # shorter diagonal tips
            boundary = max(b_axis, b_diag)

            if r <= boundary:
                # Bright white core fades to BLUE toward the tips
                core_t = max(0.0, 1.0 - r / 6.5) ** 1.4
                c = lerp(BLUE, WHITE, core_t * 0.85)
            else:
                dist = r - boundary
                if dist < 4.5:
                    # Soft atmospheric halo
                    halo = ((4.5 - dist) / 4.5) ** 2.5 * 0.50
                    c = lerp(BG, BLUE, halo)
                else:
                    c = BG

            row += bytes([c[0], c[1], c[2], 0xFF])
        rows.append(bytes(row))

    pixel_data = b"".join(rows)
    bih = struct.pack("<IiiHHIIiiII", 40, W, H * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    row_stride = ((W + 31) // 32) * 4
    and_mask   = b"\x00" * (row_stride * H)
    img   = bih + pixel_data + and_mask
    hdr   = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", W, H, 0, 0, 1, 32, len(img), 22)
    return hdr + entry + img


def _make_tk_icon(root: tk.Misc) -> tk.PhotoImage:
    """Same star design as a PhotoImage — no file, no Explorer lock."""
    W = H = 32
    BG    = (0x0d, 0x11, 0x17)  # RGB: #0d1117
    BLUE  = (0x58, 0xa6, 0xff)  # RGB: #58a6ff
    WHITE = (0xee, 0xf6, 0xff)  # RGB: warm near-white

    cx = cy = (W - 1) / 2.0

    def lerp(a, b, t):
        t = max(0.0, min(1.0, t))
        return (int(a[0]+(b[0]-a[0])*t),
                int(a[1]+(b[1]-a[1])*t),
                int(a[2]+(b[2]-a[2])*t))

    def star_r(theta, n, r_out, r_in):
        return r_in + (r_out - r_in) * (math.cos(n * theta) + 1) / 2

    rows = []
    for y in range(H):               # top-down for PhotoImage
        row = []
        for x in range(W):
            dx, dy = x - cx, y - cy
            r     = math.hypot(dx, dy) + 1e-9
            theta = math.atan2(dy, dx)
            b_axis = star_r(theta,             4, 13.0, 4.0)
            b_diag = star_r(theta - math.pi/4, 4,  8.0, 4.0)
            bnd    = max(b_axis, b_diag)
            if r <= bnd:
                t = max(0.0, 1.0 - r / 6.5) ** 1.4
                c = lerp(BLUE, WHITE, t * 0.85)
            elif r - bnd < 4.5:
                c = lerp(BG, BLUE, ((4.5 - (r - bnd)) / 4.5) ** 2.5 * 0.5)
            else:
                c = BG
            row.append(f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}")
        rows.append("{" + " ".join(row) + "}")

    img = tk.PhotoImage(width=W, height=H, master=root)
    img.put("\n".join(rows))
    return img


# ── Desktop shortcut installer ─────────────────────────────────────────────────

def _install_shortcut() -> tuple[bool, str]:
    """Create a Desktop shortcut that the user can right-click → Pin to taskbar.

    Returns (success, message).  Windows-only; harmless no-op elsewhere.
    """
    if sys.platform != "win32":
        return False, "Windows only"

    pythonw = (Path(sys.executable).parent / "pythonw.exe").resolve()
    if not pythonw.exists():
        return False, f"pythonw.exe not found next to {sys.executable}"

    # Write the new star ICO — delete old file first to bust Explorer's icon cache
    ico = (_EDDA_DIR / "edda.ico").resolve()
    ico_err = ""
    try:
        _EDDA_DIR.mkdir(parents=True, exist_ok=True)
        if ico.exists():
            ico.unlink()
        ico.write_bytes(_make_ico())
    except Exception as _e:
        ico_err = str(_e)

    cwd = Path.cwd().resolve()

    # Resolve Desktop via Shell API (handles OneDrive-redirected Desktops)
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(0, 0x10, 0, 0, buf)
        desktop = Path(buf.value)
    except Exception:
        desktop = Path.home() / "Desktop"

    lnk_path = desktop / "EDDA Control Panel.lnk"

    def _esc(p: str) -> str:
        return str(p).replace("'", "''")

    ico_arg = f"$sc.IconLocation = '{_esc(ico)}'\n" if not ico_err else ""
    ps = (
        f"$sh = New-Object -ComObject WScript.Shell\n"
        f"$sc = $sh.CreateShortcut('{_esc(lnk_path)}')\n"
        f"$sc.TargetPath = '{_esc(pythonw)}'\n"
        f"$sc.Arguments = '-c \"from edda.gui import main; main()\"'\n"
        f"$sc.WorkingDirectory = '{_esc(cwd)}'\n"
        f"{ico_arg}"
        f"$sc.Description = 'EDDA Control Panel'\n"
        f"$sc.Save()\n"
    )

    import tempfile
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False, encoding="utf-8")
    tmp.write(ps)
    tmp.close()
    try:
        r = subprocess.run(
            ["powershell", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", tmp.name],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            try:
                import ctypes
                SHCNF_PATHW = 0x0005
                # Notify Explorer about the updated ico and the (re)created lnk
                if not ico_err:
                    ctypes.windll.shell32.SHChangeNotify(
                        0x00002000,   # SHCNE_UPDATEITEM
                        SHCNF_PATHW, str(ico), None)
                ctypes.windll.shell32.SHChangeNotify(
                    0x00000002,   # SHCNE_CREATE
                    SHCNF_PATHW, str(lnk_path), None)
            except Exception:
                pass
            note = f" (icon write failed: {ico_err})" if ico_err else ""
            return True, str(lnk_path) + note
        return False, (r.stderr.strip() or r.stdout.strip() or "unknown error")
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


# ── Theme ──────────────────────────────────────────────────────────────────────

def _theme(root: tk.Tk) -> None:
    root.configure(bg=_BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".",
        background=_SURF, foreground=_TEXT, fieldbackground=_BG,
        bordercolor=_BORDER, troughcolor=_BG,
        darkcolor=_BORDER, lightcolor=_SURF2,
        selectbackground=_ACCENT, selectforeground=_BG, font=_FONT)
    s.configure("TFrame",      background=_SURF)
    s.configure("Dark.TFrame", background=_BG)
    s.configure("TLabel",      background=_SURF, foreground=_TEXT, font=_FONT)
    s.configure("Dim.TLabel",  background=_SURF, foreground=_MUTED, font=_FONT_S)
    s.configure("TLabelframe", background=_SURF, bordercolor=_BORDER, relief="flat")
    s.configure("TLabelframe.Label",
        background=_SURF, foreground=_MUTED, font=("Segoe UI", 8, "bold"))
    s.configure("TButton",
        background=_SURF2, foreground=_TEXT, bordercolor=_BORDER,
        relief="flat", padding=(8, 4), font=_FONT)
    s.map("TButton",
          background=[("active", "#2d333b"), ("pressed", _BORDER)],
          foreground=[("active", _ACCENT)],
          bordercolor=[("active", _ACCENT)])
    s.configure("Run.TButton",
        background=_ACCENT, foreground=_BG, bordercolor=_ACCENT,
        relief="flat", padding=(10, 4), font=_FONT_B)
    s.map("Run.TButton",
          background=[("active", "#4a90e2"), ("pressed", "#3070c0")],
          foreground=[("active", _BG)])
    s.configure("TEntry",
        fieldbackground=_BG, foreground=_TEXT,
        bordercolor=_BORDER, insertcolor=_TEXT, font=_FONT)
    s.map("TEntry", bordercolor=[("focus", _ACCENT)])
    s.configure("TCheckbutton", background=_SURF, foreground=_TEXT, font=_FONT)
    s.map("TCheckbutton",
          background=[("active", _SURF)], foreground=[("active", _ACCENT)])
    s.configure("TScrollbar",
        background=_SURF2, troughcolor=_BG,
        arrowcolor=_MUTED, bordercolor=_BORDER, relief="flat")
    s.map("TScrollbar", background=[("active", _BORDER)])
    s.configure("TSeparator", background=_BORDER)


# ── Custom icon button ─────────────────────────────────────────────────────────

class _IconBtn(tk.Frame):
    """Flat button with separately-rendered emoji icon + text label."""

    def __init__(self, parent: tk.Widget, icon: str, text: str,
                 command, **kw) -> None:
        super().__init__(parent, bg=_SURF2, cursor="hand2",
                         highlightthickness=1,
                         highlightbackground=_BORDER, **kw)
        self._cmd = command
        self._on = False
        self._icon = tk.Label(self, text=icon, bg=_SURF2, fg=_TEXT,
                              font=("Segoe UI Emoji", 13))
        self._icon.pack(side="left", padx=(10, 3), pady=5)
        self._lbl = tk.Label(self, text=text, bg=_SURF2, fg=_TEXT, font=_FONT)
        self._lbl.pack(side="left", padx=(0, 10), pady=5)
        for w in (self, self._icon, self._lbl):
            w.bind("<Button-1>", lambda _: self._cmd())
            w.bind("<Enter>",    lambda _: self._hover(True))
            w.bind("<Leave>",    lambda _: self._hover(False))

    def _apply(self, bg: str, fg: str, border: str) -> None:
        self.config(bg=bg, highlightbackground=border)
        self._icon.config(bg=bg, fg=fg)
        self._lbl.config(bg=bg, fg=fg)

    def _hover(self, on: bool) -> None:
        if not self._on:
            self._apply(_SURF2 if not on else "#2d333b",
                        _TEXT  if not on else _ACCENT,
                        _BORDER)

    def set_active(self, on: bool) -> None:
        self._on = on
        if on:
            self._apply("#1c2333", _ACCENT, _ACCENT)
        else:
            self._apply(_SURF2, _TEXT, _BORDER)


# ── Calendar date-entry widget ─────────────────────────────────────────────────

class _DateEntry(tk.Frame):
    """Entry + calendar popup for YYYY-MM-DD date selection."""

    def __init__(self, parent: tk.Widget, value: str = "", **kw) -> None:
        super().__init__(parent, bg=_SURF, **kw)
        self._var = tk.StringVar(value=value)
        self._e = ttk.Entry(self, textvariable=self._var, width=12)
        self._e.pack(side="left")
        btn = tk.Label(self, text="\U0001f4c5", bg=_SURF, fg=_MUTED,
                       font=("Segoe UI Emoji", 11), cursor="hand2")
        btn.pack(side="left", padx=(4, 0))
        btn.bind("<Button-1>", lambda _: self._open())

    def get(self) -> str:
        return self._var.get().strip()

    def set(self, v: str) -> None:
        self._var.set(v)

    def _open(self) -> None:
        try:
            cur = _datetime.strptime(self._var.get()[:10], "%Y-%m-%d").date()
        except Exception:
            cur = _date.today()

        top = tk.Toplevel(self, bg=_SURF2)
        top.title("")
        top.resizable(False, False)
        top.transient(self.winfo_toplevel())
        top.grab_set()
        top.geometry(
            f"+{self.winfo_rootx()}"
            f"+{self.winfo_rooty() + self.winfo_height() + 4}")

        _y = tk.IntVar(value=cur.year)
        _m = tk.IntVar(value=cur.month)

        MONTHS = ["January", "February", "March", "April",
                  "May", "June", "July", "August",
                  "September", "October", "November", "December"]

        nav = tk.Frame(top, bg=_SURF2)
        nav.pack(fill="x", padx=6, pady=(6, 2))
        hdr = tk.Label(nav, text="", bg=_SURF2, fg=_TEXT, font=_FONT_B)
        hdr.pack(side="left", expand=True)

        cal_f = tk.Frame(top, bg=_SURF2)
        cal_f.pack(padx=6, pady=(0, 6))

        def _refresh() -> None:
            for w in cal_f.winfo_children():
                w.destroy()
            y, m = _y.get(), _m.get()
            hdr.config(text=f"{MONTHS[m - 1]} {y}")
            for col, d in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
                tk.Label(cal_f, text=d, bg=_SURF2, fg=_MUTED, font=_FONT_S,
                         width=3).grid(row=0, column=col, padx=1, pady=1)
            for row, week in enumerate(_cal.monthcalendar(y, m)):
                for col, day in enumerate(week):
                    if day == 0:
                        tk.Label(cal_f, text="", bg=_SURF2, width=3).grid(
                            row=row + 1, column=col, padx=1, pady=1)
                        continue
                    is_sel = cur == _date(y, m, day)
                    bg = _ACCENT if is_sel else _SURF2
                    fg = _BG     if is_sel else _TEXT
                    lbl = tk.Label(cal_f, text=str(day), bg=bg, fg=fg,
                                   font=_FONT, width=3, cursor="hand2")
                    lbl.grid(row=row + 1, column=col, padx=1, pady=1)
                    def _pick(d=day, y=y, m=m) -> None:
                        self._var.set(f"{y:04d}-{m:02d}-{d:02d}")
                        top.destroy()
                    lbl.bind("<Button-1>", lambda e, f=_pick: f())

        def _prev() -> None:
            y, m = _y.get(), _m.get()
            if m == 1:
                _y.set(y - 1); _m.set(12)
            else:
                _m.set(m - 1)
            _refresh()

        def _next() -> None:
            y, m = _y.get(), _m.get()
            if m == 12:
                _y.set(y + 1); _m.set(1)
            else:
                _m.set(m + 1)
            _refresh()

        tk.Button(nav, text="◀", bg=_SURF2, fg=_TEXT, relief="flat", bd=0,
                  cursor="hand2", command=_prev, font=_FONT).pack(side="left")
        tk.Button(nav, text="▶", bg=_SURF2, fg=_TEXT, relief="flat", bd=0,
                  cursor="hand2", command=_next, font=_FONT).pack(side="right")
        _refresh()


# ── Per-task field definitions ─────────────────────────────────────────────────
# (field_key, ui_config_key, default_value, placeholder_or_None)
_TASK_FIELDS: dict[str, list[tuple]] = {
    "import": [
        ("journal_dir",  "import_journal_dir",  "",    "default: ED saved games"),
        ("force",        "import_force",         False, None),
        ("auto_import",  "import_auto_import",   False, None),
        ("poll_minutes", "import_poll_minutes",  "",    "0 = off"),
    ],
    "dashboard": [
        ("out",          "dashboard_out",          "dashboard.html", None),
        ("poll_minutes", "dashboard_poll_minutes", "",               "0 = off"),
        ("open_after",   "dashboard_open_after",   False,            None),
    ],
    "stratum": [
        ("min_temp",   "stratum_min_temp",   "165",                 None),
        ("max_temp",   "stratum_max_temp",   "",                    "no limit"),
        ("out",        "stratum_out",        "stratum_report.html", None),
        ("open_after", "stratum_open_after", False,                 None),
    ],
    "charts": [
        ("out",        "charts_out",        "output", None),
        ("open_after", "charts_open_after", False,    None),
    ],
    "trip": [
        ("from",       "trip_from",       "", "YYYY-MM-DD"),
        ("to",         "trip_to",         "", "YYYY-MM-DD"),
        ("html_out",   "trip_html_out",   "", "trip_report.html"),
        ("systems",    "trip_systems",    False, None),
        ("open_after", "trip_open_after", False, None),
    ],
}
_TASK_FUNCS = {
    "import": "cmd_import", "dashboard": "cmd_dashboard",
    "stratum": "cmd_stratum", "charts": "cmd_charts", "trip": "cmd_trip",
}
_OPEN_FIELD = {
    "dashboard": "out", "stratum": "out",
    "trip": "html_out", "charts": "out",
}
_DATE_FIELDS = {("trip", "from"), ("trip", "to")}


class _App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"EDDA Control Panel  v{_VERSION}")
        self.geometry("800x700")
        self.resizable(True, True)
        _theme(self)
        self._queue: queue.Queue = queue.Queue()
        self._task_thread: threading.Thread | None = None
        self._qb_proc: subprocess.Popen | None = None
        self._commanders: list[str] = []
        self._cmdr_check_vars: dict[str, tk.BooleanVar] = {}
        self._cmdr_row_lbls: dict[str, tk.Label] = {}
        self._cmdr_selected_name: str | None = None
        self._widgets: dict[str, dict] = {}
        self._frames:  dict[str, ttk.Frame] = {}
        self._current_task: str | None = None
        self._poll_timers: dict[str, str | None] = {}
        self._ui = get_ui_state()
        self._build()
        self._refresh_commanders()
        self._toggle("import")
        self._poll()
        if self._widgets["import"]["auto_import"].get():
            self.after(500, lambda: self._run("import"))

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Commander
        cf = ttk.LabelFrame(self, text="COMMANDER", padding=(8, 6))
        cf.pack(fill="x", padx=12, pady=(12, 4))
        inner = ttk.Frame(cf)
        inner.pack(fill="x")

        lb_wrap = tk.Frame(inner, bg=_BG, highlightthickness=1,
                           highlightbackground=_BORDER)
        lb_wrap.pack(side="left", fill="both", expand=True)
        self._cmdr_canvas = tk.Canvas(
            lb_wrap, bg=_BG, highlightthickness=0, height=82,
        )
        cmdr_vsb = ttk.Scrollbar(lb_wrap, orient="vertical",
                                  command=self._cmdr_canvas.yview)
        cmdr_vsb.pack(side="right", fill="y")
        self._cmdr_canvas.pack(side="left", fill="both", expand=True)
        self._cmdr_canvas.configure(yscrollcommand=cmdr_vsb.set)

        self._cmdr_inner = tk.Frame(self._cmdr_canvas, bg=_BG)
        self._cmdr_canvas_win = self._cmdr_canvas.create_window(
            (0, 0), window=self._cmdr_inner, anchor="nw")
        self._cmdr_inner.bind(
            "<Configure>",
            lambda e: self._cmdr_canvas.configure(
                scrollregion=self._cmdr_canvas.bbox("all")))
        self._cmdr_canvas.bind(
            "<Configure>",
            lambda e: self._cmdr_canvas.itemconfig(
                self._cmdr_canvas_win, width=e.width))

        rp = ttk.Frame(inner)
        rp.pack(side="left", padx=(10, 0), fill="y")
        ttk.Button(rp, text="Set Active", command=self._switch_cmdr).pack()
        self._cmdr_lbl = ttk.Label(rp, text="", style="Dim.TLabel")
        self._cmdr_lbl.pack(pady=(6, 0))

        # Tasks
        tf = ttk.LabelFrame(self, text="TASKS", padding=(8, 6))
        tf.pack(fill="x", padx=12, pady=4)
        br = ttk.Frame(tf)
        br.pack(fill="x")
        self._task_btns: dict[str, _IconBtn] = {}
        for icon, lbl, key in [
            ("\U0001f4be", "Import Journals",  "import"),
            ("\U0001f4ca", "Build Dashboard",  "dashboard"),
            ("\U0001f30e", "Stratum Report",   "stratum"),
            ("\U0001f4c8", "Build Charts",     "charts"),
            ("\U0001f559", "Trip Report",      "trip"),
        ]:
            b = _IconBtn(br, icon, lbl, command=lambda k=key: self._toggle(k))
            b.pack(side="left", padx=3, pady=2)
            self._task_btns[key] = b
        ttk.Separator(tf, orient="horizontal").pack(fill="x", pady=(8, 2))
        self._opts_wrap = ttk.Frame(tf)
        self._opts_wrap.pack(fill="x")
        self._build_opts()

        # Utility bar: Query Builder + shortcut installer
        qf = ttk.Frame(self)
        qf.pack(fill="x", padx=12, pady=2)
        ttk.Button(qf, text="Open Query Builder →",
                   command=self._open_qb).pack(side="left")
        ttk.Button(qf, text="↺", width=3,
                   command=self._restart_qb).pack(side="left", padx=(2, 0))
        self._qb_lbl = ttk.Label(qf, text="", style="Dim.TLabel")
        self._qb_lbl.pack(side="left", padx=8)
        ttk.Button(qf, text="Check for Updates",
                   command=self._check_updates).pack(side="right", padx=(4, 0))
        ttk.Button(qf, text="Create Desktop Shortcut",
                   command=self._create_shortcut).pack(side="right")

        # Output
        of = ttk.LabelFrame(self, text="OUTPUT", padding=(8, 6))
        of.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        top = ttk.Frame(of)
        top.pack(fill="x")
        ttk.Button(top, text="Clear", command=self._clear).pack(side="right")
        wrap = ttk.Frame(of, style="Dark.TFrame")
        wrap.pack(fill="both", expand=True, pady=(4, 0))
        sb = ttk.Scrollbar(wrap, orient="vertical")
        sb.pack(side="right", fill="y")
        self._txt = tk.Text(
            wrap, wrap="word", state="disabled", bg=_BG, fg=_TEXT,
            font=_MONO, relief="flat", borderwidth=0,
            insertbackground=_TEXT, yscrollcommand=sb.set,
        )
        self._txt.pack(fill="both", expand=True)
        sb.config(command=self._txt.yview)
        for tag, fg in [("err", _RED), ("ok", _GREEN),
                        ("hdr", _ACCENT), ("warn", _ORANGE), ("dim", _MUTED)]:
            self._txt.tag_configure(tag, foreground=fg)

    def _entry(self, parent: tk.Widget, label: str,
               value: str, ph: str = "") -> tk.StringVar:
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text=label, width=28, anchor="w",
                  style="Dim.TLabel").pack(side="left")
        v = tk.StringVar(value=value if value else (ph or ""))
        e = ttk.Entry(f, textvariable=v, width=36)
        e.pack(side="left")
        if ph and not value:
            e.config(foreground=_MUTED)
            def _fi(_, _e=e, _ph=ph):
                if _e.get() == _ph:
                    _e.delete(0, "end")
                    _e.config(foreground=_TEXT)
            def _fo(_, _e=e, _ph=ph):
                if not _e.get().strip():
                    _e.delete(0, "end"); _e.insert(0, _ph)
                    _e.config(foreground=_MUTED)
            e.bind("<FocusIn>", _fi)
            e.bind("<FocusOut>", _fo)
        return v

    def _date_entry(self, parent: tk.Widget, label: str,
                    value: str) -> _DateEntry:
        f = ttk.Frame(parent)
        f.pack(fill="x", pady=2)
        ttk.Label(f, text=label, width=28, anchor="w",
                  style="Dim.TLabel").pack(side="left")
        de = _DateEntry(f, value=value)
        de.pack(side="left")
        return de

    def _check(self, parent: tk.Widget, label: str,
               value: bool) -> tk.BooleanVar:
        v = tk.BooleanVar(value=value)
        ttk.Checkbutton(parent, text=label, variable=v).pack(anchor="w", pady=2)
        return v

    def _build_opts(self) -> None:
        ui = self._ui
        labels: dict[str, str] = {
            "journal_dir":  "Journal directory",
            "force":        "Force re-import all files",
            "auto_import":  "Auto-import on startup",
            "poll_minutes": "Auto-poll (min, 0 = off)",
            "out":          "Output file",
            "min_temp":     "Min temperature (K)",
            "max_temp":     "Max temperature (K)",
            "html_out":     "HTML output file",
            "from":         "From (YYYY-MM-DD)",
            "to":           "To   (YYYY-MM-DD)",
            "systems":      "List all systems visited",
            "open_after":   "Open in browser when done",
        }
        for key, fields in _TASK_FIELDS.items():
            f = ttk.Frame(self._opts_wrap)
            w: dict = {}
            for fk, uk, default, ph in fields:
                stored = ui.get(uk)
                lbl = ("Open output folder when done"
                       if fk == "open_after" and key == "charts"
                       else labels[fk])
                if isinstance(default, bool):
                    val = bool(stored) if stored is not None else default
                    w[fk] = self._check(f, lbl, val)
                elif (key, fk) in _DATE_FIELDS:
                    val = str(stored) if stored else default
                    w[fk] = self._date_entry(f, lbl, val)
                else:
                    val = str(stored) if stored else default
                    w[fk] = self._entry(f, lbl, val, ph or "")
            ttk.Button(f, text={
                "import": "Run Import", "dashboard": "Build Dashboard",
                "stratum": "Build Report", "charts": "Build Charts",
                "trip": "Build Trip Report",
            }[key], style="Run.TButton",
                command=lambda k=key: self._run(k)).pack(anchor="w", pady=(10, 2))
            self._frames[key] = f
            self._widgets[key] = w

    # ── Commander ──────────────────────────────────────────────────────────────

    def _refresh_commanders(self) -> None:
        self._commanders = list_commanders()
        active = get_active_commander()
        saved_sel = set(get_selected_commanders())

        for w in self._cmdr_inner.winfo_children():
            w.destroy()
        self._cmdr_check_vars.clear()
        self._cmdr_row_lbls.clear()

        for name in self._commanders:
            is_checked = name in saved_sel if saved_sel else name == active
            var = tk.BooleanVar(value=is_checked)
            self._cmdr_check_vars[name] = var

            row = tk.Frame(self._cmdr_inner, bg=_BG, cursor="hand2")
            row.pack(fill="x")

            def _on_toggle(n=name) -> None:
                checked = [c for c, v in self._cmdr_check_vars.items() if v.get()]
                set_selected_commanders(checked)

            cb = tk.Checkbutton(
                row, variable=var,
                bg=_BG, activebackground=_BG,
                selectcolor=_ACCENT, relief="flat", bd=0,
                command=lambda n=name: _on_toggle(n),
            )
            cb.pack(side="left", padx=(4, 0))

            is_active = name == active
            lbl = tk.Label(
                row,
                text=f"{'●' if is_active else '○'}  {name}",
                bg=_BG, fg=_GREEN if is_active else _TEXT,
                font=_FONT,
            )
            lbl.pack(side="left", padx=(2, 6))
            self._cmdr_row_lbls[name] = lbl

            def _select(_, n=name) -> None:
                self._cmdr_selected_name = n
                self._highlight_cmdr()

            for w in (row, lbl, cb):
                w.bind("<Button-1>", _select)

        if self._cmdr_selected_name not in self._commanders:
            self._cmdr_selected_name = active
        self._highlight_cmdr()
        self._cmdr_lbl.config(text=f"Active: {active or '(none)'}")

    def _highlight_cmdr(self) -> None:
        active = get_active_commander()
        for name, lbl in self._cmdr_row_lbls.items():
            is_active = name == active
            if name == self._cmdr_selected_name:
                lbl.config(bg=_SURF2)
                lbl.master.config(bg=_SURF2)
            else:
                lbl.config(bg=_BG, fg=_GREEN if is_active else _TEXT)
                lbl.master.config(bg=_BG)

    def _switch_cmdr(self) -> None:
        if not self._cmdr_selected_name:
            messagebox.showinfo("EDDA", "Click a commander row to select it.")
            return
        set_active_commander(self._cmdr_selected_name)
        self._refresh_commanders()
        self._log(f"Active commander: {self._cmdr_selected_name}\n", "ok")

    # ── Task options ───────────────────────────────────────────────────────────

    def _toggle(self, key: str) -> None:
        for k, f in self._frames.items():
            f.pack_forget()
            self._task_btns[k].set_active(False)
        if self._current_task == key:
            self._current_task = None
            return
        self._current_task = key
        self._frames[key].pack(fill="x", pady=(4, 2))
        self._task_btns[key].set_active(True)

    def _val(self, key: str, fk: str, ph: str = "") -> str | bool:
        v = self._widgets[key][fk]
        if isinstance(v, tk.BooleanVar):
            return v.get()
        s = v.get().strip()
        return "" if (not s or s == ph) else s

    def _save(self, key: str) -> None:
        updates: dict = {}
        for fk, uk, default, ph in _TASK_FIELDS[key]:
            v = self._val(key, fk, ph or "")
            updates[uk] = v
        set_ui_state(updates)
        self._ui.update(updates)

    def _build_args(self, key: str) -> list[str] | None:
        g = lambda fk, ph="": self._val(key, fk, ph)
        args: list[str] = []

        if key != "import":
            checked = [n for n, v in self._cmdr_check_vars.items() if v.get()]
            for n in checked:
                args += ["--db", str(get_commander_db_path(n))]

        if key == "import":
            jdir = g("journal_dir", "default: ED saved games")
            if jdir:
                args += ["--journal-dir", str(jdir)]
            if g("force"):
                args.append("--force")

        elif key == "dashboard":
            out = g("out")
            if out:
                args += ["--out", str(out)]

        elif key == "stratum":
            if g("min_temp"):
                args += ["--min-temp", str(g("min_temp"))]
            mt = g("max_temp", "no limit")
            if mt:
                args += ["--max-temp", str(mt)]
            if g("out"):
                args += ["--out", str(g("out"))]

        elif key == "charts":
            if g("out"):
                args += ["--out", str(g("out"))]

        elif key == "trip":
            fr = g("from", "YYYY-MM-DD")
            to = g("to",   "YYYY-MM-DD")
            if not fr or not to:
                messagebox.showwarning("EDDA",
                    "Trip report requires both From and To dates.")
                return None
            args += ["--from", fr, "--to", to]
            ho = g("html_out", "trip_report.html")
            if ho:
                args += ["--html", ho]
            if g("systems"):
                args.append("--systems")

        self._save(key)
        return args

    def _open_path(self, key: str) -> str | None:
        if "open_after" not in self._widgets.get(key, {}):
            return None
        if not self._val(key, "open_after"):
            return None
        fk = _OPEN_FIELD.get(key)
        if not fk:
            return None
        ph = {"html_out": "trip_report.html", "out": ""}.get(fk, "")
        return str(self._val(key, fk, ph)) or None

    def _poll_interval(self, key: str) -> float:
        if "poll_minutes" not in self._widgets.get(key, {}):
            return 0.0
        try:
            return max(0.0, float(self._val(key, "poll_minutes", "0 = off") or 0))
        except ValueError:
            return 0.0

    def _schedule_poll(self, key: str) -> None:
        mins = self._poll_interval(key)
        if mins <= 0:
            return
        ms = int(mins * 60_000)
        self._log(f"  (auto-poll: next {key} in {mins:.0f} min)\n", "dim")
        tid = self.after(ms, lambda k=key: self._run(k))
        self._poll_timers[key] = tid

    # ── Task runner ────────────────────────────────────────────────────────────

    def _run(self, key: str) -> None:
        if self._task_thread and self._task_thread.is_alive():
            messagebox.showinfo("EDDA", "A task is already running.")
            return
        args = self._build_args(key)
        if args is None:
            return
        open_path = self._open_path(key)
        func = _TASK_FUNCS[key]
        code = f"from edda.cli import {func}; {func}({args!r})"
        self._log(f"\n> {key}  {' '.join(args)}\n", "hdr")

        def _go() -> None:
            try:
                proc = subprocess.Popen(
                    [sys.executable, "-c", code],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    cwd=str(Path.cwd()),
                )
                for line in proc.stdout:
                    self._queue.put(("line", line))
                if proc.wait() == 0 and open_path:
                    self._queue.put(("open", open_path))
            except Exception as exc:
                self._queue.put(("line", f"ERROR: {exc}\n"))
            finally:
                self._queue.put(("done", key))

        self._task_thread = threading.Thread(target=_go, daemon=True)
        self._task_thread.start()

    # ── Update check ──────────────────────────────────────────────────────────

    def _check_updates(self) -> None:
        self._log(f"> EDDA v{_VERSION} — checking for updates…\n", "hdr")

        def _go() -> None:
            try:
                r = subprocess.run(
                    ["git", "fetch", "--quiet"],
                    capture_output=True, text=True, timeout=30,
                    cwd=str(Path.cwd()),
                )
                if r.returncode != 0:
                    self._queue.put(("line",
                        f"git fetch failed: {r.stderr.strip() or 'unknown error'}\n"))
                    return
                r2 = subprocess.run(
                    ["git", "log", "HEAD..@{u}", "--oneline"],
                    capture_output=True, text=True, timeout=10,
                    cwd=str(Path.cwd()),
                )
                commits = r2.stdout.strip()
                if commits:
                    self._queue.put(("line",
                        f"Updates available:\n{commits}\n"
                        f"Run update.bat / update.ps1 / update.sh to apply.\n"))
                else:
                    self._queue.put(("line", "Already up to date.\n"))
            except FileNotFoundError:
                self._queue.put(("line",
                    "git not found — cannot check for updates.\n"))
            except Exception as exc:
                self._queue.put(("line", f"Update check failed: {exc}\n"))

        threading.Thread(target=_go, daemon=True).start()

    # ── Desktop shortcut ──────────────────────────────────────────────────────

    def _create_shortcut(self) -> None:
        ok, msg = _install_shortcut()
        if ok:
            self._log(
                f"> Desktop shortcut created:\n"
                f"  {msg}\n"
                f"  Right-click it on your Desktop → Pin to taskbar.\n", "ok")
        else:
            self._log(f"> Shortcut failed: {msg}\n", "err")

    # ── Query Builder ──────────────────────────────────────────────────────────

    def _open_qb(self) -> None:
        self._start_qb(open_browser=True)

    def _kill_qb(self) -> None:
        if self._qb_proc and self._qb_proc.poll() is None:
            self._qb_proc.terminate()
        self._qb_proc = None
        self._qb_lbl.config(text="")
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["powershell", "-NonInteractive", "-Command",
                     "Get-NetTCPConnection -LocalPort 5000 -State Listen "
                     "-ErrorAction SilentlyContinue | "
                     "Select-Object -ExpandProperty OwningProcess | "
                     "ForEach-Object { Stop-Process -Id $_ -Force }"],
                    capture_output=True, timeout=10,
                )
            except Exception:
                pass

    def _restart_qb(self) -> None:
        self._kill_qb()
        self._qb_lbl.config(text="Stopping…")
        self._wait_port_free()

    def _wait_port_free(self, n: int = 0) -> None:
        """Poll until port 5000 is free, then start the new server."""
        try:
            urllib.request.urlopen("http://localhost:5000/", timeout=0.5)
            # Still responding — keep waiting (max 5 s)
            if n < 10:
                self.after(500, lambda: self._wait_port_free(n + 1))
            else:
                self._qb_lbl.config(text="Could not stop server.")
        except Exception:
            # Port is free — start fresh
            self._start_qb(open_browser=True)

    def _start_qb(self, open_browser: bool = True) -> None:
        url = "http://localhost:5000/query-builder"
        if open_browser:
            try:
                urllib.request.urlopen("http://localhost:5000/", timeout=1)
                # Server already running and we didn't kill it — just open
                webbrowser.open(url)
                self._qb_lbl.config(text="Running at :5000")
                return
            except Exception:
                pass
        self._qb_lbl.config(text="Starting…")
        code = "from edda.serve import main as _m; _m(['--port','5000','--no-browser'])"
        self._qb_proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(Path.cwd()),
        )

        def _wait(n: int = 0) -> None:
            try:
                urllib.request.urlopen("http://localhost:5000/", timeout=1)
                if open_browser:
                    webbrowser.open(url)
                self._qb_lbl.config(text="Running at :5000")
            except Exception:
                if n < 30:
                    self.after(1000, lambda: _wait(n + 1))
                else:
                    self._qb_lbl.config(text="Failed to start.",
                                        foreground=_RED)
        self.after(1000, _wait)

    # ── Output ─────────────────────────────────────────────────────────────────

    def _log(self, text: str, tag: str = "") -> None:
        if not tag:
            if text.startswith(("ERROR", "Traceback", "  File ")):
                tag = "err"
            elif text.startswith(("WARNING", "Warning")):
                tag = "warn"
            elif text.startswith("==="):
                tag = "hdr"
            elif text.startswith(("[", ">")):
                tag = "dim"
        self._txt.config(state="normal")
        self._txt.insert("end", text, tag or ())
        self._txt.see("end")
        self._txt.config(state="disabled")

    def _clear(self) -> None:
        self._txt.config(state="normal")
        self._txt.delete("1.0", "end")
        self._txt.config(state="disabled")

    def _poll(self) -> None:
        try:
            while True:
                kind, data = self._queue.get_nowait()
                if kind == "done":
                    self._log("> Done.\n", "ok")
                    self._schedule_poll(data)
                elif kind == "open":
                    p = Path(data)
                    self._log(f"> Opening {data}\n", "dim")
                    if p.is_dir():
                        os.startfile(data)
                    else:
                        webbrowser.open(p.resolve().as_uri())
                else:
                    self._log(data)
        except queue.Empty:
            pass
        self.after(100, self._poll)


def main(argv: list[str] | None = None) -> None:
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "EDDA.ControlPanel.1")
    except Exception:
        pass

    app = _App()

    # Set window/taskbar icon directly from a PhotoImage — no file, no lock.
    try:
        app._ico_img = _make_tk_icon(app)  # keep reference to prevent GC
        app.wm_iconphoto(True, app._ico_img)
    except Exception:
        pass

    app.mainloop()
