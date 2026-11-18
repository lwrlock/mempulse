from __future__ import annotations

import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]


def decode_mglru_flags(raw: str) -> str:
    txt = (raw or "").strip().lower()
    if txt in ("", "disabled", "0", "0x0", "0x0000"):
        return "Disabled"
    try:
        val = int(txt, 16) if txt.startswith("0x") else int(txt)
    except ValueError:
        return txt
    feats = []
    if val & 0x01:
        feats.append("LRU Gen")
    if val & 0x02:
        feats.append("PTE Walk")
    if val & 0x04:
        feats.append("Non-leaf Clear")
    return f"{txt} ({' • '.join(feats)})" if feats else txt


def compute_effective_headroom_gb(ram_total_mb: float, ram_used_mb: float, z_orig_mb: float, z_compr_mb: float) -> float:
    saved_mb = max(0.0, z_orig_mb - z_compr_mb)
    free_mb = max(0.0, ram_total_mb - ram_used_mb + saved_mb)
    return round(free_mb / 1024.0, 2)


def sample_mem() -> dict:
    probe = ROOT / "mempulse-probe"
    out = subprocess.check_output([str(probe), "--json"], text=True, timeout=3.0)
    data = json.loads(out)
    data["mglru_label"] = decode_mglru_flags(data.get("mglru", ""))
    ram = data.get("ram", {})
    zr = data.get("zram", {})
    data["headroom_gb"] = compute_effective_headroom_gb(
        float(ram.get("total_mb", 0.0)),
        float(ram.get("used_mb", 0.0)),
        float(zr.get("orig_mb", 0.0)),
        float(zr.get("compr_mb", 0.0)),
    )
    return data
