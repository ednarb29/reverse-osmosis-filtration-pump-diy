"""
Test setup. Inserted ahead of `tests/` imports so that:

1. The `sim/` directory is on sys.path so `import machine`, `import uasyncio`,
   `import ujson` resolve to the desktop mocks.
2. The standard `time` module gets `ticks_ms` and `ticks_diff` shims, which
   only exist in MicroPython.
"""

import pathlib
import sys
import time

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SIM_DIR = REPO_ROOT / 'sim'

if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# MicroPython exposes `time.ticks_ms` (millisecond monotonic counter, wraps at
# 2^30) and `time.ticks_diff` (signed difference handling wraparound). The
# standard library has neither, so emulate them.
if not hasattr(time, 'ticks_ms'):
    _TICKS_MAX = 1 << 30
    _TICKS_HALF = 1 << 29

    def _ticks_ms():
        return int(time.monotonic() * 1000) & (_TICKS_MAX - 1)

    def _ticks_diff(a, b):
        diff = (a - b) & (_TICKS_MAX - 1)
        if diff >= _TICKS_HALF:
            diff -= _TICKS_MAX
        return diff

    time.ticks_ms = _ticks_ms
    time.ticks_diff = _ticks_diff
