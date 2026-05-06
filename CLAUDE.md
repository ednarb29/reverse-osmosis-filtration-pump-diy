# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Runtime environment

This is **MicroPython** code targeting a **Raspberry Pi Pico**, not standard CPython. Key implications:

- `main.py` runs automatically at boot when uploaded to the Pico's filesystem. The runtime entry point is gated on `if __name__ == '__main__': main()` so the module is importable for tests.
- Imports like `machine`, `uasyncio`, `ujson` are MicroPython-only — they will not resolve on a stock desktop Python interpreter. The `sim/` directory provides drop-in mocks (`sim/machine.py`, `sim/uasyncio.py`, `sim/ujson.py`) so `main` can be imported under CPython for tests.
- Iteration on hardware: edit → upload to Pico (e.g. via Thonny or `mpremote`) → observe serial output (`print(...)` calls go to USB serial).
- Iteration off hardware: `python3 -m unittest discover -s tests` runs the full behavioural suite in a few seconds. See [tests/test_sequences.py](tests/test_sequences.py) for what's covered (normal completion, cancellation safety, pump-deadhead avoidance, config persistence, ticks_diff wraparound).
- `config.json` is created and persisted **on the Pico's flash** (not in this repo). The defaults in `CONFIG` at the top of [main.py](main.py) only apply on first run / when the file is missing. `write_config` is atomic (tmp file + rename) so a power loss mid-write cannot corrupt the file.

## Hardware pin map (from [main.py:58-68](main.py#L58-L68))

| GPIO | Component         | Notes                                              |
|------|-------------------|----------------------------------------------------|
| 0-3  | Valves 1-4        | Relay logic is **inverted** (see below)            |
| 4    | Pump              | Relay logic is **non-inverted** (opposite of valves) |
| 15   | Buzzer (PWM)      | Passive piezo, frequency from `CONFIG['buzzer_frequency']` |
| 16   | Button            | `Pin.PULL_UP`, pressed = LOW (value `0`)           |

**Critical relay polarity gotcha**: the valve relay module is active-low — `_set_valves` writes the **logical NOT** of its arguments, so passing `True` *opens* a valve. The pump relay is the opposite: `set_pump(True)` turns the pump ON. When adding new valve states or new flow modes, always go through `_set_valves(...)` rather than poking pins directly so this inversion stays in one place.

## Architecture: two cooperative async loops + a global state machine

The program is structured around `uasyncio`. `main()` arms the hardware watchdog (`machine.WDT`, 8 s) and starts two long-running tasks plus the deferred post-flush mechanism:

1. **`handle_button()`** — drives `_await_press()` (which classifies short / long / super-long / double-tap), then dispatches via `_dispatch_normal()` or `_dispatch_manual()` depending on `manual_mode`. The `DOUBLE_TAP_WINDOW_MS` (600 ms) wait after a short release is the unavoidable cost of double-tap detection — every short press is delayed by that much before dispatch.
2. **`check_auto_flush()`** — wakes every second; feeds the watchdog; if no task is running, manual mode is off, and no deferred post-flush is busy, then checks whether `auto_flush_sec` has elapsed since the last flush/filter and starts an automatic flush if so.
3. **Deferred post-flush task** (`_deferred_post_flush_cycle`) — spawned in `filter_water`'s `finally` block. Sleeps `CONFIG['deferred_post_flush_sec']`, then runs the membrane post-flush. Cancellable: any new user-initiated cycle calls `await _cancel_pending_post_flush()` first to wait for the deferred to clean up before touching hardware.

State is coordinated through **module-level globals**, not parameters:

- `running_task` — the currently running `uasyncio.Task` (or a `DummyTask` sentinel that is always `done()`). The button handler cancels this directly.
- `running_task_type` — one of `'FILTERING'`, `'PRE_FLUSHING'`, `'FLUSHING'`, `'MANUAL_IDLE'`, `'MANUAL_RUNNING'`, or `None`. Used by the button handler to decide context-sensitive actions (e.g. long-press during FILTERING saves the elapsed time as the new `filter_sec`). `'PRE_FLUSHING'` is the auto-injected pre-flush sub-step inside `filter_water` — short/long press skips ahead to the filter phase. `'FLUSHING'` is a standalone flush (`auto_flush_filter` or `long_flush_filter`) — short/long press just cancels with no follow-on, since the user explicitly asked for that flush (or it was auto-triggered).
- `manual_mode` — True while the user is in the toggle-style manual mode entered via double-tap. While this is set, `check_auto_flush` skips the auto-flush check.
- `_deferred_post_flush_task` — the pending or running deferred post-flush task, or `None`. Cancelled-and-awaited via `_cancel_pending_post_flush()` before any new cycle starts; cancelled-and-replaced via `_schedule_deferred_post_flush()` at the end of each filter cycle.
- `last_flush`, `last_reflush`, `last_filtering`, `start_filtering` — timestamps used to decide whether a pre-flush is needed before filtering and when auto-flush is due.

When extending behavior, **set `running_task_type` at the start of any new top-level coroutine** and use the `try/finally` pattern already in `filter_water` / `auto_flush_filter` / `long_flush_filter` to guarantee the pump turns OFF and valves close even on cancellation. **Always `await _cancel_pending_post_flush()` before spawning a new task that touches the hardware** — otherwise a deferred post-flush in its pump-on phase will race the new task's pre-flush ramp.

## Valve choreography

The four valve "modes" are encoded as helper functions, not as a state enum. Each filtration cycle composes them:

- `set_valves_to_flush()` — bypass membrane to drain (used for pre-flush, post-flush, long-flush)
- `set_valves_to_disposal()` — divert first filtered water (high particle content after idle)
- `set_valves_to_filter()` — normal filtration path
- `close_inlet_valve()` — closes inlet but leaves others open to **bleed system pressure** before fully closing
- `close_valves()` — all closed (default idle state)

The phased valve closing at the end of every cycle (pump off → wait `pump_switch_delay` → close inlet only → wait `INLET_BLEED_MS` ≈ 2 s → close all) intentionally releases pressure from the membrane and is load-bearing — don't simplify it. It lives in the `_clean_shutdown()` helper which is invoked from the `finally` block of `filter_water`, `auto_flush_filter`, and `long_flush_filter` so cancellation can never leave the pump running.

`INLET_BLEED_MS` is a module-level constant (not in `CONFIG`) so tests can shrink it without changing user-visible config keys.

## Pump-switch ordering invariant

Every pump transition is wrapped with `await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])` (default 1000 ms) **after setting valves but before turning the pump on**, and again **after turning the pump off but before closing valves**. This protects the pump from being run against closed valves (deadhead) and the valve solenoids from being switched under full pressure. Preserve this ordering when adding new flow phases.

Both `close_valves()` and `close_inlet_valve()` also include a safety check that force-shuts the pump if it was somehow left on — keep this guard.

## Button semantics (dispatched by [`_dispatch_normal`](main.py) / [`_dispatch_manual`](main.py))

| Press           | Idle                                  | FILTERING                                          | PRE_FLUSHING (pre-flush of a filter cycle)       | FLUSHING (auto-flush / long-flush)        | MANUAL                                |
|-----------------|---------------------------------------|----------------------------------------------------|--------------------------------------------------|--------------------------------------------|----------------------------------------|
| Short (<0.8 s)  | Start `filter_water()`                | Cancel filtering                                   | Skip pre-flush, jump to filter phase             | Cancel only (no follow-on)                 | Toggle pump on/off (no pre/post-flush) |
| Long (0.8–5 s)  | Start 1-hour filter                   | Cancel + persist elapsed as new `filter_sec`       | Skip pre-flush, start 1-hour filter              | Cancel only (no follow-on)                 | Exit manual mode                       |
| Super-long (≥5 s)| Start `long_flush_filter()` (15 min) | Cancel + start long flush                          | Cancel + start long flush                        | Cancel + start long flush                  | Exit manual mode                       |
| Double-tap      | Enter MANUAL mode                     | (ignored)                                          | (ignored)                                        | (ignored)                                  | (ignored)                              |

Long-press during FILTERING is the **only** way `config.json` gets written from user input — that is the "calibrate the filter duration" flow. The new value is clamped to `[FILTER_SEC_MIN, FILTER_SEC_MAX]` (30 s – 1 h).

The PRE_FLUSHING vs. FLUSHING distinction matters for cancel semantics: a pre-flush is auto-injected before a filter cycle, so the natural impatient-user gesture is "skip it and just filter" (short = filter, long = 1-hour filter). A standalone flush (auto-flush or super-long-pressed long flush) was explicitly requested or system-triggered, so a plain cancel is the natural gesture instead. Super-long press always overrides and starts a long flush regardless of state, because the user explicitly asked for one.

MANUAL mode is the "no membrane care" mode used during the manufacturer's disinfection procedure (see the AquaMichel Mini handbook). Single short presses toggle pump ON/OFF in filter configuration with **no pre-flush, no post-flush, no deferred work, no auto-flush check**. Long-press exits cleanly. Auto-flush is paused for the duration so it can't fire during the 1-hour H₂O₂ soak step.

## test-hardware/

Standalone MicroPython scripts to bring up individual peripherals on a fresh Pico. They are not a test suite — each is a manual smoke test you upload as `main.py` (or run interactively) to verify wiring before deploying the real `main.py`. They use blocking `time.sleep` and infinite loops; do not import from them.

## tests/ and sim/

`tests/` holds the desktop unittest suite (~30 tests, ~30 s wall time). `sim/` holds the MicroPython mock modules it relies on (`machine`, `uasyncio`, `ujson`). Tests assert on the recorded sequence of pin writes — every `Pin.value(...)` call lands in `machine._events` with a timestamp.

Invariants the suite enforces (any new flow code must preserve them):

1. **Safe end state** — after any exit path (normal completion *or* cancellation), pump=OFF and all valves=CLOSED. ([`TestNormalCompletion`](tests/test_sequences.py), [`TestCancellationSafety`](tests/test_sequences.py))
2. **No deadhead** — the pump is never ON while all four valves are CLOSED. ([`TestPumpSwitchOrdering`](tests/test_sequences.py))
3. **Pressure-bleed window** — at the moment the pump turns OFF, at least one valve is open, AND there's at least `pump_switch_delay + INLET_BLEED_MS` between pump-OFF and the first all-valves-closed moment. ([`TestPumpValveSequencing`](tests/test_sequences.py))
4. **No rapid pump cycling** — after a pump-OFF event, the pump must not turn back ON inside the bleed window. Catches cancel-and-replace races. ([`TestButtonHandler`](tests/test_sequences.py), [`TestDeferredPostFlush`](tests/test_sequences.py))
5. **Auto-flush respect** — `check_auto_flush` skips when manual mode is active or a deferred post-flush is pending. ([`TestManualMode`](tests/test_sequences.py), [`TestAutoFlushTimer`](tests/test_sequences.py))
6. **Atomic config persistence** — corrupted `config.json` is tolerated; writes use tmp + rename. ([`TestConfigPersistence`](tests/test_sequences.py))

The fast test config in `tests/test_sequences.py::use_fast_config` shrinks all `*_sec` values to 0.05–0.10 s, `pump_switch_delay` to 5 ms, `INLET_BLEED_MS` to 20 ms, and `DOUBLE_TAP_WINDOW_MS` to 120 ms so the suite finishes in seconds.

## Project conventions

- All comments and docstrings in this repo are in English; the README is also English. Keep contributions consistent.
- Default `CONFIG` values are tuned for stationary production use. For mobile / camper use, lower `deferred_post_flush_sec` (e.g. 15) in `config.json` so the post-flush completes promptly after the user takes their water.
- For development iteration, override `CONFIG` values via `config.json` rather than editing the defaults in `main.py` — that way your test settings persist across reflashes and don't accidentally ship to other users.
