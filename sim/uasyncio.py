"""
Mock of MicroPython's `uasyncio` module that delegates to CPython's `asyncio`.

Adds `sleep_ms` (which uasyncio has but asyncio does not) and exposes the same
top-level helpers main.py uses (`get_event_loop`, `create_task`, `sleep`,
`CancelledError`).
"""

import asyncio as _asyncio
from asyncio import (  # noqa: F401  re-export
    CancelledError,
    create_task,
    get_event_loop,
    sleep,
)


async def sleep_ms(ms):
    await _asyncio.sleep(ms / 1000.0)
