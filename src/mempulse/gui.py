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
    background-color: #0d0a09;
    background-image: radial-gradient(circle at 18% 15%, rgba(245, 158, 11, 0.14), transparent 48%),
                      radial-gradient(circle at 85% 82%, rgba(56, 189, 248, 0.10), transparent 45%);
    color: #fffbeb;
}
headerbar, AdwHeaderBar {
    background: rgba(18, 14, 12, 0.92);
    border-bottom: 1px solid rgba(245, 158, 11, 0.25);
    color: #fffbeb;
}
.m-card {
    background: rgba(20, 16, 14, 0.94);
    border: 1px solid rgba(245, 158, 11, 0.22);
    border-radius: 16px;
    padding: 15px 18px;
}
.m-hero {
    background: rgba(24, 19, 16, 0.95);
    border: 1px solid rgba(251, 191, 36, 0.28);
    border-radius: 15px;
    padding: 14px 16px;
}
.hk { font-size: 10.5px; font-weight: 700; color: #fbbf24; letter-spacing: 0.7px; }
.hv { font-size: 24px; font-weight: 800; color: #f8fafc; }
.hs { font-size: 11.5px; color: #a8a29e; }
.st { font-size: 14px; font-weight: 700; color: #fef3c7; }
.ss { font-size: 11.5px; color: #a8a29e; }
.row { padding: 6px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06); }
"""


class MemoryStackCanvas(Gtk.DrawingArea):
    """Stacked RAM + PageCache + ZRAM pool bar and live memory sparkline."""

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(-1, 175)
        self.set_hexpand(True)
        self._used = 8.0
        self._cache = 4.0
        self._tot = 32.0
        self._hist: deque[float] = deque(maxlen=50)
        self.set_draw_func(self._draw)

    def update_mem(self, used_gb: float, cache_gb: float, tot_gb: float) -> None:
        self._used = used_gb
        self._cache = cache_gb
        self._tot = max(1.0, tot_gb)
        self._hist.append((used_gb / self._tot) * 100.0)
        self.queue_draw()

    def _draw(self, _a, cr: cairo.Context, w: int, h: int) -> None:
        cr.set_source_rgba(0.06, 0.04, 0.04, 0.90)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        # Stacked Memory Composition Bar
        bx, by, bw, bh = 16.0, 22.0, max(40.0, w - 32.0), 22.0
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.08)
        cr.rectangle(bx, by, bw, bh)
        cr.fill()

        u_frac = min(1.0, self._used / self._tot)
        c_frac = min(1.0 - u_frac, self._cache / self._tot)
        cr.set_source_rgba(0.96, 0.62, 0.04, 0.92)
        cr.rectangle(bx, by, bw * u_frac, bh)
        cr.fill()
        cr.set_source_rgba(0.22, 0.74, 0.97, 0.85)
        cr.rectangle(bx + bw * u_frac, by, bw * c_frac, bh)
        cr.fill()

        cr.set_source_rgba(0.85, 0.85, 0.85, 0.9)
        cr.set_font_size(10.5)
        cr.move_to(bx, by + bh + 18)
        cr.show_text(f"Active RSS: {self._used:.1f} GB  •  Page Cache: {self._cache:.1f} GB  •  Free: {max(0.0, self._tot - self._used):.1f} GB")

        # Rolling usage sparkline
        sy, sh = 74.0, h - 92.0
        if len(self._hist) >= 2 and sh > 10:
            n = len(self._hist)
            pts = [(bx + (i / (n - 1)) * bw, sy + sh * (1.0 - min(1.0, v / 100.0))) for i, v in enumerate(self._hist)]
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.95)
            cr.set_line_width(2.2)
            cr.move_to(pts[0][0], pts[0][1])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.stroke()


class MemWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="MemPulse", default_width=1080, default_height=740)
        self._busy = False
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)
        root.append(Adw.HeaderBar(title_widget=Adw.WindowTitle(title="MemPulse", subtitle="Linux MGLRU, PSI Memory Pressure & ZRAM zstd Analytics")))

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=14, margin_bottom=16, margin_start=18, margin_end=18)
        root.append(body)

        hero = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        c1, self.h_ram, self.h_ram_s = self._hero("ACTIVE RAM", "-- GB", "Available Headroom")
        c2, self.h_zram, self.h_zram_s = self._hero("ZRAM COMPRESSION", "--x", "0 MB -> 0 MB")
        c3, self.h_mglru, self.h_mglru_s = self._hero("KERNEL MGLRU", "Checking...", "/sys/kernel/mm/lru_gen")
        c4, self.h_psi, self.h_psi_s = self._hero("MEMORY PSI", "0.00%", "Full stall: 0.00%")
        for i, c in enumerate((c1, c2, c3, c4)):
            hero.attach(c, i, 0, 1, 1)
        body.append(hero)

        mid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True)
        left = self._card("Unified Memory Stack & Live Usage", "Amber: Active Process RSS • Cyan: Reclaimable Kernel Page Cache")
        self.canvas = MemoryStackCanvas()
        left.append(self.canvas)
        self.head_lbl = Gtk.Label(label="Effective Headroom: calculating...", xalign=0.0)
        self.head_lbl.add_css_class("ss")
        left.append(self.head_lbl)

        right = self._card("Top Memory & Swap Consumers", "Ranked by live RSS + ZRAM Swap footprint (/proc/[pid]/status)")
        self.rows = []
        for i in range(6):
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            r.add_css_class("row")
            nl = Gtk.Label(label=f"#{i + 1} Scanning...", xalign=0.0, hexpand=True)
            vl = Gtk.Label(label="—", xalign=1.0)
            vl.add_css_class("ss")
            r.append(nl); r.append(vl)
            right.append(r)
            self.rows.append((nl, vl))

        mid.attach(left, 0, 0, 1, 1)
        mid.attach(right, 1, 0, 1, 1)
        body.append(mid)

        GLib.timeout_add(1600, self._tick)
        self._refresh()

    def _hero(self, k: str, v: str, s: str):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        b.add_css_class("m-hero")
        kl = Gtk.Label(label=k, xalign=0.0); kl.add_css_class("hk")
        vl = Gtk.Label(label=v, xalign=0.0); vl.add_css_class("hv")
        sl = Gtk.Label(label=s, xalign=0.0, ellipsize=3); sl.add_css_class("hs")
        b.append(kl); b.append(vl); b.append(sl)
        return b, vl, sl

    def _card(self, t: str, s: str) -> Gtk.Box:
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        b.add_css_class("m-card")
        tl = Gtk.Label(label=t, xalign=0.0); tl.add_css_class("st")
        sl = Gtk.Label(label=s, xalign=0.0); sl.add_css_class("ss")
        b.append(tl); b.append(sl)
        return b

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

                self.h_ram.set_label(f"{used_g:.1f} / {tot_g:.0f} GB")
                self.h_ram_s.set_label(f"{avail_g:.1f} GB available • Cache {cache_g:.1f} GB")
                self.h_zram.set_label(f"{float(zr.get('ratio', 1.0)):.2f}x")
                self.h_zram_s.set_label(f"{float(zr.get('orig_mb', 0.0)):.1f} -> {float(zr.get('compr_mb', 0.0)):.1f} MB ({zr.get('algo', 'zstd')})")
                self.h_mglru.set_label("Active" if data.get("mglru_label") != "Disabled" else "Off")
                self.h_mglru_s.set_label(data.get("mglru_label", "Disabled"))
                self.h_psi.set_label(f"{float(psi.get('some_avg10', 0.0)):.2f}%")
                self.h_psi_s.set_label(f"Full thrash avg10: {float(psi.get('full_avg10', 0.0)):.2f}%")

                self.canvas.update_mem(used_g, cache_g, tot_g)
                self.head_lbl.set_label(f"Effective Headroom (incl. ZRAM savings): {data.get('headroom_gb', avail_g):.2f} GB")

                for idx, (nl, vl) in enumerate(self.rows):
                    procs = data.get("top_procs", [])
                    if idx < len(procs):
                        p = procs[idx]
                        nl.set_label(f"{p['name']} (PID {p['pid']})")
                        vl.set_label(f"{p['rss_mb']:.0f} MB RSS • {p['swap_mb']:.1f} MB Swap")
                    else:
                        nl.set_label(f"#{idx + 1} Idle"); vl.set_label("—")
                return GLib.SOURCE_REMOVE

            GLib.idle_add(_apply)

        threading.Thread(target=_worker, daemon=True).start()


class MemApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.lwrlock.MemPulse")

    def do_activate(self):
        p = Gtk.CssProvider(); p.load_from_data(MEM_CSS)
        d = Gdk.Display.get_default()
        if d:
            Gtk.StyleContext.add_provider_for_display(d, p, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = self.props.active_window or MemWindow(self)
        win.present()


def main() -> int:
    return MemApp().run(None)


if __name__ == "__main__":
    raise SystemExit(main())
