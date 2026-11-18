# MemPulse

[![License: MIT](https://img.shields.io/badge/License-MIT-amber.svg)](LICENSE)
[![Engine: C + MGLRU/ZRAM](https://img.shields.io/badge/Engine-C%20%2B%20MGLRU%2FZRAM-f59e0b.svg)](#)

**Real-time Linux MGLRU (`lru_gen`), Memory PSI (`/proc/pressure/memory`), and `zstd` ZRAM Compression Analytics Suite built in C and Python/GTK4.**

<p align="center">
  <img src="docs/screenshots/showcase.gif" alt="MemPulse Telemetry Showcase" width="900"/>
</p>

## Highlights

- **MGLRU Bitmask Telemetry:** Decodes `/sys/kernel/mm/lru_gen/enabled` (`0x0007` → LRU Gen • PTE Walk • Non-leaf Clear).
- **Live ZRAM Compression Ratio:** Reads `/sys/block/zram0/mm_stat` to compute effective physical RAM headroom gained via compression.
- **Memory Thrash Early Warning (`PSI`):** Tracks `some` and `full` `avg10` memory pressure alongside stacked RSS + Page Cache visualization and top RSS/Swap consumers.

## Build & Run

```bash
make test
./mempulse-probe --json
PYTHONPATH=src /usr/bin/python3 -m mempulse.gui
```

MIT License — Copyright (c) 2026 Furkan (**lwrlock**). Built with assistance from Google DeepMind Antigravity.
