from __future__ import annotations

import os
import threading
from collections import deque

os.environ.setdefault("GSK_RENDERER", "gl")

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from .engine import sample_mem

MEM_CSS = b"""
window, window.background, AdwApplicationWindow {
    background-color: #0b0907;
    background-image: radial-gradient(circle at 18% 12%, rgba(245, 158, 11, 0.12), transparent 46%),
                      radial-gradient(circle at 86% 85%, rgba(6, 182, 212, 0.09), transparent 46%);
    color: #fffbeb;
}
headerbar, AdwHeaderBar {
    background: #130f0c;
    border-bottom: 1px solid rgba(245, 158, 11, 0.24);
    color: #fffbeb;
    min-height: 42px;
}
windowcontrols button {
    min-width: 18px;
    min-height: 18px;
    padding: 2px;
    margin: 0 2px;
    border-radius: 9999px;
}
windowcontrols button image {
    -gtk-icon-size: 12px;
}
stackswitcher button {
    border-radius: 7px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 700;
}
stackswitcher button:checked {
    background: rgba(245, 158, 11, 0.24);
    border: 1px solid rgba(251, 191, 36, 0.45);
    color: #fcd34d;
}
.ribbon-box {
    background: #15110e;
    border: 1px solid rgba(245, 158, 11, 0.26);
    border-radius: 10px;
    padding: 10px 14px;
}
.m-card {
    background: #14100d;
    border: 1px solid rgba(245, 158, 11, 0.20);
    border-radius: 10px;
    padding: 13px 16px;
}
.bit-on {
    background: rgba(245, 158, 11, 0.18);
    border: 1px solid rgba(251, 191, 36, 0.40);
    border-radius: 6px;
    padding: 6px 10px;
    color: #fde68a;
    font-family: monospace;
    font-size: 11px;
    font-weight: 700;
}
.bit-off {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 6px;
    padding: 6px 10px;
    color: #78716c;
    font-family: monospace;
    font-size: 11px;
}
.st { font-size: 13.5px; font-weight: 700; color: #fef3c7; }
.ss { font-size: 11px; color: #a8a29e; }
.mono { font-family: monospace; font-size: 12px; color: #f5f5f4; }
.row { padding: 6px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
progressbar trough { background: rgba(255, 255, 255, 0.08); border-radius: 4px; min-height: 6px; }
progressbar progress { background: #f59e0b; border-radius: 4px; min-height: 6px; }
"""


class MemoryMapRibbon(Gtk.DrawingArea):
    """Full-width proportional RAM segmentation bar: Active RSS, Page Cache, ZRAM, Free."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 78)
        self.set_hexpand(True)
        self._tot = 32.0
        self._used = 8.0
        self._cache = 12.0
        self._zram_compr_gb = 0.0
        self._avail = 24.0
        self.set_draw_func(self._draw)

    def update(self, tot_g: float, used_g: float, cache_g: float, zram_compr_gb: float, avail_g: float) -> None:
        self._tot = max(1.0, tot_g)
        self._used = max(0.0, used_g)
        self._cache = max(0.0, cache_g)
        self._zram_compr_gb = max(0.0, zram_compr_gb)
        self._avail = max(0.0, avail_g)
        self.queue_draw()

    def _draw(self, _a, cr: cairo.Context, w: int, h: int) -> None:
        cr.set_source_rgba(0.06, 0.04, 0.04, 0.0)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        bx, by, bw, bh = 2.0, 22.0, max(60.0, w - 4.0), 26.0
        rss_f = min(1.0, self._used / self._tot)
        z_f = min(1.0 - rss_f, self._zram_compr_gb / self._tot)
        c_f = min(1.0 - rss_f - z_f, self._cache / self._tot)
        free_f = max(0.0, 1.0 - rss_f - z_f - c_f)

        cr.set_source_rgba(0.96, 0.90, 0.78, 0.95)
        cr.set_font_size(11.0)
        cr.move_to(bx, 14.0)
        cr.show_text(
            f"PHYSICAL MEMORY MAP ({self._tot:.2f} GB Total)  —  Active Used: {self._used:.2f} GB  •  Page Cache: {self._cache:.2f} GB  •  Available Headroom: {self._avail:.2f} GB"
        )

        # Bar segments
        x = bx
        for frac, rgba in (
            (rss_f, (0.96, 0.62, 0.04, 0.92)),
            (z_f, (0.66, 0.33, 0.97, 0.92)),
            (c_f, (0.02, 0.71, 0.83, 0.85)),
            (free_f, (0.06, 0.35, 0.25, 0.55)),
        ):
            seg_w = bw * frac
            if seg_w > 0.5:
                cr.set_source_rgba(*rgba)
                cr.rectangle(x, by, seg_w, bh)
                cr.fill()
                x += seg_w

        # Legend row under bar
        lx = bx
        ly = by + bh + 18.0
        items = [
            ((0.96, 0.62, 0.04), f"Active RSS ({rss_f * 100:.0f}%)"),
            ((0.66, 0.33, 0.97), f"ZRAM Pool ({self._zram_compr_gb:.2f} GB)"),
            ((0.02, 0.71, 0.83), f"Reclaimable Cache ({c_f * 100:.0f}%)"),
            ((0.06, 0.72, 0.51), f"Unallocated Free ({free_f * 100:.0f}%)"),
        ]
        for rgb, lbl in items:
            cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.95)
            cr.rectangle(lx, ly - 8, 9, 9)
            cr.fill()
            cr.set_source_rgba(0.84, 0.82, 0.78, 0.92)
            cr.set_font_size(10.0)
            cr.move_to(lx + 14, ly)
            cr.show_text(lbl)
            lx += max(155.0, (bw - 20.0) / 4.0)


class ZramComparisonCanvas(Gtk.DrawingArea):
    """Visualizes ZRAM uncompressed vs compressed byte sizes and ratio."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 145)
        self.set_hexpand(True)
        self._orig = 0.0
        self._compr = 0.0
        self._ratio = 1.0
        self._algo = "[zstd]"
        self.set_draw_func(self._draw)

    def update(self, orig_mb: float, compr_mb: float, ratio: float, algo: str) -> None:
        self._orig = orig_mb
        self._compr = compr_mb
        self._ratio = ratio
        self._algo = algo
        self.queue_draw()

    def _draw(self, _a, cr: cairo.Context, w: int, h: int) -> None:
        cr.set_source_rgba(0.05, 0.04, 0.03, 0.95)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        saved = max(0.0, self._orig - self._compr)
        peak = max(100.0, self._orig, self._compr)
        bx, bw = 16.0, max(60.0, w - 165.0)

        bars = [
            ("Original Data", self._orig, (0.96, 0.62, 0.04)),
            ("ZRAM Pool", self._compr, (0.66, 0.33, 0.97)),
            ("RAM Saved", saved, (0.06, 0.72, 0.51)),
        ]
        for i, (lbl, val, rgb) in enumerate(bars):
            y = 18.0 + i * 38.0
            cr.set_source_rgba(0.84, 0.82, 0.78, 0.90)
            cr.set_font_size(10.5)
            cr.move_to(bx, y)
            cr.show_text(f"{lbl}: {val:.1f} MB")

            cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
            cr.rectangle(bx, y + 6, bw, 12)
            cr.fill()
            fill_w = bw * min(1.0, val / peak) if val > 0 else 4.0
            cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 0.92)
            cr.rectangle(bx, y + 6, fill_w, 12)
            cr.fill()

        # Right Ratio Badge
        rx = bx + bw + 18.0
        cr.set_source_rgba(0.66, 0.33, 0.97, 0.16)
        cr.rectangle(rx, 16.0, max(95.0, w - rx - 14.0), h - 32.0)
        cr.fill()
        cr.set_source_rgba(0.95, 0.90, 1.0, 0.96)
        cr.set_font_size(24.0)
        cr.move_to(rx + 14, h * 0.52)
        cr.show_text(f"{self._ratio:.2f}x")
        cr.set_source_rgba(0.80, 0.74, 0.90, 0.90)
        cr.set_font_size(10.5)
        cr.move_to(rx + 14, h * 0.52 + 20)
        cr.show_text(f"Codec: {self._algo}")


class PsiMemoryWaveform(Gtk.DrawingArea):
    """Rolling dual-scale RAM usage % (amber) and Memory PSI avg10 (cyan/red)."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 175)
        self.set_hexpand(True)
        self._ram_pct: deque[float] = deque(maxlen=50)
        self._psi_some: deque[float] = deque(maxlen=50)
        self.set_draw_func(self._draw)

    def push(self, used_pct: float, psi_some: float) -> None:
        self._ram_pct.append(used_pct)
        self._psi_some.append(psi_some)
        self.queue_draw()

    def _draw(self, _a, cr: cairo.Context, w: int, h: int) -> None:
        cr.set_source_rgba(0.05, 0.04, 0.03, 0.95)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        pad_l, pad_r, pad_t, pad_b = 42.0, 12.0, 14.0, 22.0
        cw = max(20.0, w - pad_l - pad_r)
        ch = max(20.0, h - pad_t - pad_b)

        for f in (0.0, 0.5, 1.0):
            y = pad_t + ch * (1.0 - f)
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.14)
            cr.move_to(pad_l, y); cr.line_to(w - pad_r, y); cr.stroke()
            cr.set_source_rgba(0.80, 0.76, 0.72, 0.80)
            cr.set_font_size(9.5)
            cr.move_to(4, y + 3)
            cr.show_text(f"{100 * f:.0f}%")

        if len(self._ram_pct) >= 2:
            n = len(self._ram_pct)
            pts = [(pad_l + (i / (n - 1)) * cw, pad_t + ch * (1.0 - min(1.0, v / 100.0))) for i, v in enumerate(self._ram_pct)]
            grad = cairo.LinearGradient(0, pad_t, 0, pad_t + ch)
            grad.add_color_stop_rgba(0.0, 0.96, 0.62, 0.04, 0.35)
            grad.add_color_stop_rgba(1.0, 0.96, 0.62, 0.04, 0.03)
            cr.set_source(grad)
            cr.move_to(pts[0][0], pad_t + ch)
            for x, y in pts:
                cr.line_to(x, y)
            cr.line_to(pts[-1][0], pad_t + ch)
            cr.close_path(); cr.fill()
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.96)
            cr.set_line_width(2.2)
            cr.move_to(pts[0][0], pts[0][1])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.stroke()

        if len(self._psi_some) >= 2:
            cr.set_source_rgba(0.02, 0.71, 0.83, 0.95)
            cr.set_line_width(1.8)
            n = len(self._psi_some)
            for i, v in enumerate(self._psi_some):
                x = pad_l + (i / (n - 1)) * cw
                y = pad_t + ch * (1.0 - min(1.0, v / 25.0))
                cr.move_to(x, y) if i == 0 else cr.line_to(x, y)
            cr.stroke()


class MemWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="MemPulse", default_width=1120, default_height=730)
        self._busy = False
        self._last_procs: list[dict] = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=170, vexpand=True)
        switcher = Gtk.StackSwitcher(stack=self.stack)
        hb = Adw.HeaderBar(title_widget=switcher)
        hb.pack_start(Gtk.Label(label="MemPulse"))
        root.append(hb)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=14, margin_start=16, margin_end=16)
        root.append(body)

        # Full-Width Proportional Memory Map Ribbon (Replaces 4 top hero cards)
        ribbon_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        ribbon_wrap.add_css_class("ribbon-box")
        self.ribbon = MemoryMapRibbon()
        ribbon_wrap.append(self.ribbon)
        body.append(ribbon_wrap)

        # Tab 1: MGLRU, ZRAM & PSI Analytics
        tab1 = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True, vexpand=True)
        left_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        z_card = self._card("ZRAM Compression & Savings (/sys/block/zram0/mm_stat)", "Effective physical headroom gained via kernel swap compression")
        self.z_canvas = ZramComparisonCanvas()
        z_card.append(self.z_canvas)
        left_col.append(z_card)

        mglru_card = self._card("MGLRU Bitmask Decoder (/sys/kernel/mm/lru_gen/enabled)", "Decoded feature flags active in page reclaim")
        self.mglru_raw = Gtk.Label(label="Bitmask: —", xalign=0.0); self.mglru_raw.add_css_class("mono")
        mglru_card.append(self.mglru_raw)
        bits_row = Gtk.Grid(column_spacing=8, column_homogeneous=True, margin_top=4)
        self.bit_badges: list[Gtk.Label] = []
        for idx, btxt in enumerate(["Bit 0 (0x1): LRU Gen", "Bit 1 (0x2): PTE Walk", "Bit 2 (0x4): Non-leaf Clear"]):
            bl = Gtk.Label(label=btxt, xalign=0.5)
            bl.add_css_class("bit-off")
            bits_row.attach(bl, idx, 0, 1, 1)
            self.bit_badges.append(bl)
        mglru_card.append(bits_row)
        left_col.append(mglru_card)

        right_col = self._card("RAM Usage % & Memory PSI Pressure", "Amber: Physical RAM %  •  Cyan: /proc/pressure/memory some avg10")
        self.psi_wave = PsiMemoryWaveform()
        right_col.append(self.psi_wave)
        self.mem_kv = {}
        for k, label in [
            ("headroom", "Effective Headroom (incl. ZRAM savings)"),
            ("psi_some", "Memory PSI (some avg10 / full avg10)"),
            ("swap", "Swap Usage / Total"),
            ("cache", "Kernel Page Cache"),
        ]:
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            r.add_css_class("row")
            kl = Gtk.Label(label=label, xalign=0.0, hexpand=True); kl.add_css_class("ss")
            vl = Gtk.Label(label="—", xalign=1.0); vl.add_css_class("mono")
            r.append(kl); r.append(vl)
            right_col.append(r)
            self.mem_kv[k] = vl

        tab1.attach(left_col, 0, 0, 1, 1)
        tab1.attach(right_col, 1, 0, 1, 1)

        # Tab 2: Filterable Process RSS & Swap Profiler
        tab2 = self._card("Process Resident RSS & ZRAM Swap Profiler", "Filter live /proc/[pid]/status memory footprint")
        self.search = Gtk.SearchEntry(placeholder_text="Filter process name or PID...")
        self.search.connect("search-changed", lambda *_: self._render_procs())
        tab2.append(self.search)

        self.proc_rows = []
        for i in range(8):
            r = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            r.add_css_class("row")
            h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            nl = Gtk.Label(label=f"#{i + 1} Scanning...", xalign=0.0, hexpand=True); nl.add_css_class("mono")
            vl = Gtk.Label(label="—", xalign=1.0); vl.add_css_class("ss")
            pb = Gtk.ProgressBar()
            h.append(nl); h.append(vl)
            r.append(h); r.append(pb)
            tab2.append(r)
            self.proc_rows.append((nl, vl, pb))

        self.stack.add_titled(tab1, "analytics", "MGLRU & ZRAM")
        self.stack.add_titled(tab2, "procs", "Process RSS & Swap")
        body.append(self.stack)

        self._bind_keys()
        GLib.timeout_add(140, self._warmup_tick)
        GLib.timeout_add(450, self._warmup_tick)
        GLib.timeout_add(1500, self._tick)

    def _bind_keys(self) -> None:
        ctrl = Gtk.EventControllerKey()

        def _on_key(_c, keyval, _code, state):
            if state & Gdk.ModifierType.ALT_MASK:
                if keyval == Gdk.KEY_1:
                    self.stack.set_visible_child_name("analytics"); return True
                if keyval == Gdk.KEY_2:
                    self.stack.set_visible_child_name("procs"); return True
            return False

        ctrl.connect("key-pressed", _on_key)
        self.add_controller(ctrl)

    def _card(self, t: str, s: str) -> Gtk.Box:
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        b.add_css_class("m-card")
        tl = Gtk.Label(label=t, xalign=0.0); tl.add_css_class("st")
        sl = Gtk.Label(label=s, xalign=0.0); sl.add_css_class("ss")
        b.append(tl); b.append(sl)
        return b

    def _render_procs(self) -> None:
        q = self.search.get_text().strip().lower()
        items = [p for p in self._last_procs if not q or q in p["name"].lower() or q in str(p["pid"])]
        top_rss = max(50.0, max((p["rss_mb"] + p["swap_mb"] for p in items), default=50.0))
        for idx, (nl, vl, pb) in enumerate(self.proc_rows):
            if idx < len(items):
                p = items[idx]
                tot = p["rss_mb"] + p["swap_mb"]
                nl.set_label(f"#{idx + 1} {p['name']} (PID {p['pid']})")
                vl.set_label(f"{p['rss_mb']:.1f} MB RSS  •  {p['swap_mb']:.1f} MB Swap")
                pb.set_fraction(min(1.0, max(0.02, tot / top_rss)))
            else:
                nl.set_label("—"); vl.set_label("—"); pb.set_fraction(0.0)

    def _warmup_tick(self) -> bool:
        self._refresh()
        return GLib.SOURCE_REMOVE

    def _tick(self) -> bool:
        self._refresh()
        return GLib.SOURCE_CONTINUE

    def _refresh(self) -> None:
        if self._busy:
            return
        self._busy = True

        def _worker():
            try:
                data = sample_mem()
            except Exception:
                data = None

            def _apply():
                self._busy = False
                if not data:
                    return GLib.SOURCE_REMOVE
                ram = data.get("ram", {})
                tot_g = float(ram.get("total_mb", 0.0)) / 1024.0
                used_g = float(ram.get("used_mb", 0.0)) / 1024.0
                cache_g = float(ram.get("cache_mb", 0.0)) / 1024.0
                avail_g = float(ram.get("avail_mb", 0.0)) / 1024.0
                zr = data.get("zram", {})
                psi = data.get("psi", {})
                sw = data.get("swap", {})

                self.ribbon.update(tot_g, used_g, cache_g, float(zr.get("compr_mb", 0.0)) / 1024.0, avail_g)
                self.z_canvas.update(
                    float(zr.get("orig_mb", 0.0)),
                    float(zr.get("compr_mb", 0.0)),
                    float(zr.get("ratio", 1.0)),
                    str(zr.get("algo", "[zstd]")),
                )

                raw_mglru = str(data.get("mglru", "0")).strip().lower()
                self.mglru_raw.set_label(f"Status: {data.get('mglru_label', raw_mglru)}")
                try:
                    mval = int(raw_mglru, 16) if raw_mglru.startswith("0x") else int(raw_mglru)
                except ValueError:
                    mval = 0
                for idx, badge in enumerate(self.bit_badges):
                    badge.remove_css_class("bit-on")
                    badge.remove_css_class("bit-off")
                    badge.add_css_class("bit-on" if (mval & (1 << idx)) else "bit-off")

                pct = (used_g / tot_g * 100.0) if tot_g > 0 else 0.0
                some10 = float(psi.get("some_avg10", 0.0))
                full10 = float(psi.get("full_avg10", 0.0))
                self.psi_wave.push(pct, some10)

                self.mem_kv["headroom"].set_label(f"{data.get('headroom_gb', avail_g):.2f} GB")
                self.mem_kv["psi_some"].set_label(f"{some10:.2f}% / {full10:.2f}%")
                self.mem_kv["swap"].set_label(f"{float(sw.get('used_mb', 0.0)):.0f} / {float(sw.get('total_mb', 0.0)):.0f} MB")
                self.mem_kv["cache"].set_label(f"{cache_g:.2f} GB")

                self._last_procs = data.get("top_procs", [])
                self._render_procs()
                return GLib.SOURCE_REMOVE

            GLib.idle_add(_apply)

        threading.Thread(target=_worker, daemon=True).start()


class MemApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.lwrlock.MemPulse")

    def do_activate(self):
        p = Gtk.CssProvider()
        p.load_from_data(MEM_CSS)
        d = Gdk.Display.get_default()
        if d:
            Gtk.StyleContext.add_provider_for_display(d, p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = self.props.active_window or MemWindow(self)
        win.present()


def main() -> int:
    return MemApp().run(None)


if __name__ == "__main__":
    raise SystemExit(main())
