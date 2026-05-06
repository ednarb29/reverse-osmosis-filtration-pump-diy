"""
Behavioural tests for the filtration controller.

Each test runs a real coroutine from main.py against the desktop hardware mocks
in `sim/`, then asserts on the recorded sequence of pin writes. The CONFIG
values are shrunk to milliseconds so the suite finishes in a few seconds.

Pin numbering (matches main.py):
    0,1,2,3 → valves 1..4 (active-low: pin LOW means valve OPEN)
    4       → pump        (active-high: pin HIGH means pump ON)
"""

import conftest  # noqa: F401  installs sys.path and time shims
import asyncio
import os
import unittest

import machine
import main

PIN_VALVE = (0, 1, 2, 3)
PIN_PUMP = 4

# Filter pin events out of the PWM beep noise.
def pin_events(events):
    return [e for e in events if e[0] == 'pin']


def pump_events(events):
    return [e for e in pin_events(events) if e[1] == PIN_PUMP]


def valve_events(events):
    return [e for e in pin_events(events) if e[1] in PIN_VALVE]


# Initial post-reset state: all valves closed (pin HIGH), pump off (pin LOW).
INITIAL_STATE = {0: 1, 1: 1, 2: 1, 3: 1, 4: 0}


def final_pin_state(events):
    """Last-known value of every pin, defaulting to the post-reset initial state.
    A pin missing from the trace just means it was never re-written, i.e. it
    held its initial value the whole cycle."""
    state = dict(INITIAL_STATE)
    for kind, num, val, _t in events:
        if kind == 'pin':
            state[num] = val
    return state


def reset_main_state():
    """Reset module-level state in main.py between tests."""
    machine.reset_events()
    main.last_flush = 0
    main.last_reflush = 0
    main.last_filtering = 0
    main.start_filtering = 0
    main.running_task = main.DummyTask()
    main.running_task_type = None
    main.manual_mode = False
    # Cancel any deferred post-flush left over from a previous test.
    if main._deferred_post_flush_task is not None and not main._deferred_post_flush_task.done():
        main._deferred_post_flush_task.cancel()
    main._deferred_post_flush_task = None

    # Pre-set physical-state truth: pump OFF, valves CLOSED (so close_valves
    # in init doesn't generate noise on the first event).
    main.set_pump(False)
    main.close_valves()
    machine.reset_events()  # discard the reset events


def use_fast_config():
    """Tiny CONFIG values so each phase is ~10–50 ms."""
    main.CONFIG.update({
        'pre_flush_sec': 0.05,
        'post_flush_sec': 0.05,
        'long_flush_sec': 0.10,
        'disposal_sec': 0.05,
        'filter_sec': 0.10,
        'auto_flush_sec': 8 * 60 * 60,  # not exercised in these tests
        'water_clean_sec': 5 * 60,
        'buzzer_frequency': 1500,
        'pump_switch_delay': 5,  # ms
    })
    main.INLET_BLEED_MS = 20
    # Default to "very far in the future" so most tests don't see the deferred
    # post-flush fire spuriously. Tests that exercise the deferred path override.
    main.CONFIG['deferred_post_flush_sec'] = 1000.0
    # Tighter double-tap window so tests run faster than the default 350 ms.
    main.DOUBLE_TAP_WINDOW_MS = 120
    # Tighter debounce so test press helpers don't have to wait 50 ms each.
    # The transient-rejection regression test exercises a 10 ms transient,
    # which is still well below this 30 ms threshold.
    main.BUTTON_DEBOUNCE_MS = 30


class _AsyncTestCase(unittest.TestCase):
    """unittest.TestCase that runs each test through asyncio.run()."""

    def setUp(self):
        reset_main_state()
        use_fast_config()

    def run_async(self, coro):
        # filter_water and friends call event_loop.create_task to schedule the
        # deferred post-flush; bind event_loop to the loop asyncio.run creates.
        async def with_loop():
            main.event_loop = asyncio.get_running_loop()
            try:
                return await coro
            finally:
                main.event_loop = None
        return asyncio.run(with_loop())


class TestNormalCompletion(_AsyncTestCase):

    def test_filter_water_ends_with_pump_off_and_valves_closed(self):
        self.run_async(main.filter_water())

        events = machine.get_events()
        state = final_pin_state(events)

        # Pump OFF at the end (active-high → 0)
        self.assertEqual(state[PIN_PUMP], 0)
        # All valves CLOSED at the end (active-low → 1)
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1, 'valve {} should end closed'.format(v))

    def test_auto_flush_ends_with_pump_off_and_valves_closed(self):
        self.run_async(main.auto_flush_filter())

        state = final_pin_state(machine.get_events())
        self.assertEqual(state[PIN_PUMP], 0)
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1)

    def test_long_flush_actually_runs_the_pump(self):
        """Regression test for the bug where long_flush_filter never turned on the pump."""
        self.run_async(main.long_flush_filter())

        pumps = pump_events(machine.get_events())
        # Need at least one ON event then an OFF event.
        on_events = [e for e in pumps if e[2] == 1]
        off_events = [e for e in pumps if e[2] == 0]
        self.assertTrue(on_events, 'long_flush_filter must turn the pump ON at some point')
        self.assertTrue(off_events, 'long_flush_filter must turn the pump OFF at the end')
        # And the last pump event must be OFF.
        self.assertEqual(pumps[-1][2], 0)


class TestCancellationSafety(_AsyncTestCase):
    """Exercises the finally-block cleanup paths."""

    async def _start_then_cancel(self, coro_fn, wait_seconds):
        task = asyncio.create_task(coro_fn())
        main.running_task = task
        await asyncio.sleep(wait_seconds)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, BaseException):
            pass

    def test_filter_water_cancelled_mid_filter_lands_in_safe_state(self):
        # 50 ms in, the filter is mid-cycle. Cancel and verify cleanup.
        self.run_async(self._start_then_cancel(main.filter_water, 0.05))

        state = final_pin_state(machine.get_events())
        self.assertEqual(state[PIN_PUMP], 0, 'pump must be OFF after cancel')
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1, 'valve {} must end closed'.format(v))

    def test_auto_flush_cancelled_lands_in_safe_state(self):
        # Regression test for issue #2: cleanup was in `try`, not `finally`.
        self.run_async(self._start_then_cancel(main.auto_flush_filter, 0.05))

        state = final_pin_state(machine.get_events())
        self.assertEqual(state[PIN_PUMP], 0)
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1)

    def test_long_flush_cancelled_lands_in_safe_state(self):
        self.run_async(self._start_then_cancel(main.long_flush_filter, 0.03))

        state = final_pin_state(machine.get_events())
        self.assertEqual(state[PIN_PUMP], 0)
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1)


class TestPumpSwitchOrdering(_AsyncTestCase):
    """The pump must never run with all valves closed (deadhead protection)."""

    def assert_pump_never_deadheads(self, events):
        """At every moment the pump is ON, at least one valve must be OPEN (=0)."""
        pin_state = {0: 1, 1: 1, 2: 1, 3: 1, 4: 0}  # valves closed, pump off
        for kind, num, val, _t in events:
            if kind != 'pin':
                continue
            pin_state[num] = val
            pump_on = pin_state[4] == 1
            any_valve_open = any(pin_state[v] == 0 for v in PIN_VALVE)
            if pump_on:
                self.assertTrue(
                    any_valve_open,
                    'pump turned ON while all valves were closed (deadhead!): state={}'.format(pin_state),
                )

    def test_filter_water_never_deadheads(self):
        self.run_async(main.filter_water())
        self.assert_pump_never_deadheads(machine.get_events())

    def test_auto_flush_never_deadheads(self):
        self.run_async(main.auto_flush_filter())
        self.assert_pump_never_deadheads(machine.get_events())

    def test_long_flush_never_deadheads(self):
        self.run_async(main.long_flush_filter())
        self.assert_pump_never_deadheads(machine.get_events())


class _SequencingAssertionsMixin:
    """Shared pump/valve-sequencing assertions, used by multiple test classes."""

    def assert_pump_transitions_have_open_valves(self, events):
        """Every time the pump pin is written, the valve state at that moment
        (just before the transition) must have at least one valve OPEN.
        Captures both 'pump must not be turned ON into closed valves'
        (deadhead) and 'pump must not be turned OFF with all valves closed'
        (pressure trap)."""
        valve_state = {v: INITIAL_STATE[v] for v in PIN_VALVE}
        for kind, num, val, t in events:
            if kind != 'pin':
                continue
            if num == PIN_PUMP:
                open_valves = [v for v in PIN_VALVE if valve_state[v] == 0]
                self.assertTrue(
                    open_valves,
                    'pump pin written to {} at t={} with all valves closed; '
                    'valve_state={}'.format(val, t, valve_state),
                )
            elif num in PIN_VALVE:
                valve_state[num] = val

    def assert_no_rapid_pump_cycling(self, events):
        """No pump-OFF must be followed by a pump-ON sooner than the configured
        bleed window. Catches races where a cancelled task's cleanup interleaves
        with a replacement task's pre-flush ramp, e.g. cancelled task turns the
        pump off while the replacement task immediately turns it back on."""
        pump_evs = [e for e in events if e[0] == 'pin' and e[1] == PIN_PUMP]
        last_off_t = None
        min_gap_ms = (main.CONFIG['pump_switch_delay'] + main.INLET_BLEED_MS) * 0.7
        for e in pump_evs:
            if e[2] == 0:
                last_off_t = e[3]
            elif e[2] == 1 and last_off_t is not None:
                gap_ms = (e[3] - last_off_t) * 1000
                self.assertGreaterEqual(
                    gap_ms, min_gap_ms,
                    'pump cycled OFF -> ON in {:.1f} ms (less than the {:.1f} ms '
                    'bleed window) — likely a cancel/replace race'.format(gap_ms, min_gap_ms),
                )

    def assert_bleed_window_keeps_valve_open(self, events):
        """At the moment the pump turns OFF, at least one valve must be open,
        AND the time between pump-OFF and the moment all valves first become
        closed must be at least `pump_switch_delay + INLET_BLEED_MS` — that's
        the pressure-bleed window."""
        pin_evs = [e for e in events if e[0] == 'pin']

        last_pump_off_t = None
        for e in pin_evs:
            if e[1] == PIN_PUMP and e[2] == 0:
                last_pump_off_t = e[3]
        self.assertIsNotNone(last_pump_off_t, 'no pump-OFF event in trace')

        # Valve state at the moment of last pump-off (replay up to that time).
        valve_state = {v: INITIAL_STATE[v] for v in PIN_VALVE}
        for e in pin_evs:
            if e[3] >= last_pump_off_t:
                break
            if e[1] in PIN_VALVE:
                valve_state[e[1]] = e[2]
        open_at_pump_off = [v for v in PIN_VALVE if valve_state[v] == 0]
        self.assertTrue(
            open_at_pump_off,
            'pump turned OFF with all valves closed: pressure cannot bleed',
        )

        # Continue forward; find first moment all valves are closed simultaneously.
        all_closed_t = None
        for e in pin_evs:
            if e[3] < last_pump_off_t:
                continue
            if e[1] in PIN_VALVE:
                valve_state[e[1]] = e[2]
                if all(valve_state[v] == 1 for v in PIN_VALVE):
                    all_closed_t = e[3]
                    break

        self.assertIsNotNone(
            all_closed_t,
            'valves never all close after pump-off — system left in unsafe state',
        )

        window_ms = (all_closed_t - last_pump_off_t) * 1000
        # Tolerate scheduler jitter: real wait is pump_switch_delay + INLET_BLEED_MS;
        # 70% of that is well above any realistic asyncio overhead.
        min_window = (main.CONFIG['pump_switch_delay'] + main.INLET_BLEED_MS) * 0.7
        self.assertGreaterEqual(
            window_ms, min_window,
            'pressure-bleed window was only {:.1f} ms; expected >= {:.1f} ms '
            '(pump_switch_delay + INLET_BLEED_MS)'.format(window_ms, min_window),
        )


class TestPumpValveSequencing(_SequencingAssertionsMixin, _AsyncTestCase):
    """Pressure-release invariants around pump on/off transitions."""

    def test_filter_water_pump_transitions(self):
        self.run_async(main.filter_water())
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_bleed_window_keeps_valve_open(evs)

    def test_auto_flush_pump_transitions(self):
        self.run_async(main.auto_flush_filter())
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_bleed_window_keeps_valve_open(evs)

    def test_long_flush_pump_transitions(self):
        self.run_async(main.long_flush_filter())
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_bleed_window_keeps_valve_open(evs)

    def test_pump_off_precedes_inlet_close_by_pump_switch_delay(self):
        """The clean shutdown must wait `pump_switch_delay` ms between turning
        the pump off and starting to change valve states, so residual pressure
        has time to drop."""
        self.run_async(main.auto_flush_filter())
        pin_evs = [e for e in machine.get_events() if e[0] == 'pin']

        last_pump_off_t = None
        for e in pin_evs:
            if e[1] == PIN_PUMP and e[2] == 0:
                last_pump_off_t = e[3]
        self.assertIsNotNone(last_pump_off_t)

        first_valve_after = None
        for e in pin_evs:
            if e[1] in PIN_VALVE and e[3] > last_pump_off_t:
                first_valve_after = e[3]
                break
        self.assertIsNotNone(first_valve_after, 'no valve transition after pump-off')

        gap_ms = (first_valve_after - last_pump_off_t) * 1000
        self.assertGreaterEqual(
            gap_ms, main.CONFIG['pump_switch_delay'] * 0.8,
            'gap between pump-off and first valve change was {} ms; '
            'expected >= {} ms'.format(gap_ms, main.CONFIG['pump_switch_delay']),
        )


async def _noop():
    pass


class _ButtonHandlerHarness:
    """Helper for tests that drive handle_button. Patches beeps to no-ops so
    the test runs in milliseconds, sets up event_loop reference, and provides
    a method for simulating a button press of arbitrary duration."""

    @staticmethod
    def install_patches():
        # Save originals so the test can reset state cleanly between runs.
        _ButtonHandlerHarness._saved = {
            'short_beep': main.short_beep,
            'long_beep': main.long_beep,
            'super_long_beep': main.super_long_beep,
            'finish_beeps': main.finish_beeps,
            'greeting_beeps': main.greeting_beeps,
        }
        main.short_beep = _noop
        main.long_beep = _noop
        main.super_long_beep = _noop
        main.finish_beeps = _noop
        main.greeting_beeps = _noop
        main.event_loop = asyncio.get_running_loop()

    @staticmethod
    def restore_patches():
        for k, v in _ButtonHandlerHarness._saved.items():
            setattr(main, k, v)

    @staticmethod
    async def press(ms):
        """Drive the button pin LOW for `ms` ms, then release. Includes a
        post-release settle long enough for handle_button to (a) finish its
        50 ms poll detecting the release, (b) clear the double-tap window
        (DOUBLE_TAP_WINDOW_MS), (c) beep, and (d) dispatch the action."""
        main.PIN_BUTTON._value = 0
        await asyncio.sleep(ms / 1000.0)
        main.PIN_BUTTON._value = 1
        await asyncio.sleep(main.DOUBLE_TAP_WINDOW_MS / 1000.0 + 0.15)

    @staticmethod
    async def double_tap(ms_each=60, gap_ms=80):
        """Two short presses within DOUBLE_TAP_WINDOW_MS — registered as a
        double-tap by handle_button. The gap must be > 2 × BUTTON_DEBOUNCE_MS
        so the release of the first press settles before the second press
        starts (otherwise the debounce filter would conflate them into one
        long press). Includes a settle so the dispatch finishes before
        this returns."""
        main.PIN_BUTTON._value = 0
        await asyncio.sleep(ms_each / 1000.0)
        main.PIN_BUTTON._value = 1
        await asyncio.sleep(gap_ms / 1000.0)
        main.PIN_BUTTON._value = 0
        await asyncio.sleep(ms_each / 1000.0)
        main.PIN_BUTTON._value = 1
        await asyncio.sleep(0.2)

    @staticmethod
    async def wait_until_idle(timeout_s=3.0):
        """Wait until any active running_task finishes. Caller must ensure a
        task has actually been dispatched first (use press() which settles
        long enough for handle_button to act, or sleep before calling)."""
        deadline = asyncio.get_running_loop().time() + timeout_s
        while not main.running_task.done():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError('running_task did not finish within {}s'.format(timeout_s))
            await asyncio.sleep(0.02)


class TestButtonHandler(_SequencingAssertionsMixin, _AsyncTestCase):
    """Drive handle_button with simulated button presses and verify the
    cancel-and-replace orchestration leaves the hardware in a clean state.
    These tests cover the bug-#4 fix (await cancelled task before spawning
    the next one)."""

    def setUp(self):
        super().setUp()
        # Make sure the button reads as released before each test.
        main.PIN_BUTTON._value = 1

    async def _drive(self, scenario_coro):
        _ButtonHandlerHarness.install_patches()
        button_task = asyncio.create_task(main.handle_button())
        try:
            await scenario_coro
        finally:
            button_task.cancel()
            try:
                await button_task
            except (asyncio.CancelledError, BaseException):
                pass
            try:
                await _ButtonHandlerHarness.wait_until_idle(timeout_s=3.0)
            finally:
                _ButtonHandlerHarness.restore_patches()

    def test_short_press_from_idle_starts_filter(self):
        async def scenario():
            await asyncio.sleep(0.05)
            await _ButtonHandlerHarness.press(150)
            # Wait for filter cycle to complete (fast config: ~250 ms total).
            await _ButtonHandlerHarness.wait_until_idle(timeout_s=2.0)

        self.run_async(self._drive(scenario()))
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_bleed_window_keeps_valve_open(evs)
        state = final_pin_state(evs)
        self.assertEqual(state[PIN_PUMP], 0)
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1)

    def test_short_press_during_filtering_cancels_cleanly(self):
        async def scenario():
            await asyncio.sleep(0.05)
            await _ButtonHandlerHarness.press(150)  # short → start filter
            await asyncio.sleep(0.15)               # let it enter filter phase
            await _ButtonHandlerHarness.press(150)  # short → cancel
            await _ButtonHandlerHarness.wait_until_idle(timeout_s=2.0)

        self.run_async(self._drive(scenario()))
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_bleed_window_keeps_valve_open(evs)
        state = final_pin_state(evs)
        self.assertEqual(state[PIN_PUMP], 0)
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1)

    def test_cancel_and_replace_no_hardware_race(self):
        """Regression for bug #4. Press during the PRE_FLUSHING phase of a
        running filter cycle so handle_button's cancel-and-replace branch fires
        (short press during pre-flush cancels and immediately spawns a new
        filter_water that skips ahead to the filter phase). The fix
        `await _wait_for_running_task()` between cancel() and create_task()
        must keep the trace clean — the cancelled task's _clean_shutdown must
        finish before the replacement opens valves and turns the pump back on."""
        # Stretch the pre-flush + disposal so the cycle spends ~1 s in PRE_FLUSHING.
        main.CONFIG['pre_flush_sec'] = 0.5
        main.CONFIG['disposal_sec'] = 0.5

        async def scenario():
            await asyncio.sleep(0.05)
            main.last_flush = 0
            main.last_filtering = 0
            await _ButtonHandlerHarness.press(150)   # start filter (begins with pre-flush)
            await asyncio.sleep(0.4)                 # land in PRE_FLUSHING phase
            await _ButtonHandlerHarness.press(150)   # short → cancel + replace with new filter
            await _ButtonHandlerHarness.wait_until_idle(timeout_s=5.0)

        self.run_async(self._drive(scenario()))
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_bleed_window_keeps_valve_open(evs)
        self.assert_no_rapid_pump_cycling(evs)
        state = final_pin_state(evs)
        self.assertEqual(state[PIN_PUMP], 0)
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1)

    def test_short_press_during_auto_flush_cancels_only(self):
        """Short press during a standalone auto-flush cancels it cleanly and
        does NOT start a follow-on filter cycle. Distinct from short press
        during PRE_FLUSHING (which DOES skip ahead to filter)."""
        async def scenario():
            await asyncio.sleep(0.05)
            # Spawn an auto_flush_filter task directly (rather than via timer).
            main.running_task = asyncio.get_running_loop().create_task(main.auto_flush_filter())
            await asyncio.sleep(0.02)  # let it enter FLUSHING phase
            self.assertEqual(main.running_task_type, 'FLUSHING')
            await _ButtonHandlerHarness.press(150)   # short → cancel only
            await _ButtonHandlerHarness.wait_until_idle(timeout_s=2.0)

        self.run_async(self._drive(scenario()))
        # No follow-on filter must have started.
        self.assertIsNone(main.running_task_type)
        # In particular, after the cancel completes, no new pump-ON event
        # should appear in the trace beyond the bleed window.
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_no_rapid_pump_cycling(evs)
        state = final_pin_state(evs)
        self.assertEqual(state[PIN_PUMP], 0)
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1)

    def test_short_press_during_long_flush_cancels_only(self):
        """Short press during long_flush_filter cancels it cleanly with no
        follow-on cycle — the user explicitly asked for a long flush via
        super-long press, so a plain cancel is the natural undo gesture."""
        # Stretch the long flush so the press lands solidly in its pump-on phase.
        main.CONFIG['long_flush_sec'] = 0.5

        async def scenario():
            await asyncio.sleep(0.05)
            main.running_task = asyncio.get_running_loop().create_task(main.long_flush_filter())
            await asyncio.sleep(0.02)
            self.assertEqual(main.running_task_type, 'FLUSHING')
            await _ButtonHandlerHarness.press(150)   # short → cancel only
            await _ButtonHandlerHarness.wait_until_idle(timeout_s=2.0)

        self.run_async(self._drive(scenario()))
        self.assertIsNone(main.running_task_type)
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_no_rapid_pump_cycling(evs)
        state = final_pin_state(evs)
        self.assertEqual(state[PIN_PUMP], 0)
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1)

    def test_short_button_transient_does_not_register_as_press(self):
        """Regression for hardware EMI: relay coils switching couple onto the
        button line and produce a brief LOW transient on the button pin. The
        debounce in _await_press must filter these out so they don't register
        as a phantom press right after each valve / pump relay click.

        The simulated transient must be long enough that the 50 ms polling
        catches it (so the un-debounced code would treat it as a press) but
        short enough that the debounce window rejects it. Polling cadence is
        50 ms, so we use a 70 ms transient and bump BUTTON_DEBOUNCE_MS to 100
        for this test."""
        main.BUTTON_DEBOUNCE_MS = 100

        async def scenario():
            await asyncio.sleep(0.02)
            main.PIN_BUTTON._value = 0
            await asyncio.sleep(0.070)  # 70 ms transient — caught by polling, rejected by debounce
            main.PIN_BUTTON._value = 1
            # Give handle_button time to either react (bug) or filter it out (fix).
            await asyncio.sleep(0.5)

        self.run_async(self._drive(scenario()))
        # No real task must have been started.
        self.assertTrue(
            isinstance(main.running_task, main.DummyTask) or main.running_task.done(),
            'short EMI-style transient should not have been classified as a press '
            '(running_task={}, type={})'.format(type(main.running_task).__name__, main.running_task_type),
        )
        # And the trace should be empty (the only events would be from a press
        # being acted upon — a beep at minimum, then dispatch).
        self.assertEqual(
            machine.get_events(), [],
            'transient triggered hardware activity it should have been filtered out: {}'.format(
                machine.get_events()
            ),
        )


class TestAutoFlushTimer(_SequencingAssertionsMixin, _AsyncTestCase):
    """Verifies check_auto_flush actually triggers an auto-flush when
    auto_flush_sec elapses, and that the resulting cycle is hardware-clean."""

    async def _run_check_loop(self):
        # Force the timer to be 'expired' immediately.
        main.last_flush = 0
        main.last_filtering = 0
        main.CONFIG['auto_flush_sec'] = 0.05
        main.event_loop = asyncio.get_running_loop()

        check_task = asyncio.create_task(main.check_auto_flush())
        try:
            # check_auto_flush polls every 1 second. After up to ~1.2 s it should
            # see the expired timer and create an auto_flush_filter task. With
            # the fast test config the cycle finishes in another ~150 ms.
            for _ in range(40):
                await asyncio.sleep(0.1)
                if main.last_flush > 0 and main.running_task.done():
                    return
            self.fail('auto-flush never triggered within timeout')
        finally:
            check_task.cancel()
            try:
                await check_task
            except (asyncio.CancelledError, BaseException):
                pass

    def test_auto_flush_triggers_after_timer_and_ends_clean(self):
        self.run_async(self._run_check_loop())
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_bleed_window_keeps_valve_open(evs)
        state = final_pin_state(evs)
        self.assertEqual(state[PIN_PUMP], 0)
        for v in PIN_VALVE:
            self.assertEqual(state[v], 1)

    def test_init_seeds_timers_so_auto_flush_does_not_fire_at_boot(self):
        """Regression for the soft-reboot bug: the RP2040 RTC keeps running
        across soft-resets, so `time.time()` at boot is a non-zero value. With
        last_flush=0 and last_filtering=0 (defaults from module load), the
        comparison `time.time() - 0 > auto_flush_sec` would be True at boot
        and fire auto-flush immediately. init() must seed the timers so that
        doesn't happen."""
        # Pretend we have a long-running RTC and call init() — it should leave
        # the timers in a state where auto_flush is NOT triggered.
        main.last_flush = 0
        main.last_filtering = 0
        main.CONFIG['auto_flush_sec'] = 120
        main.CONFIG['water_clean_sec'] = 30

        main.init()

        # The auto-flush check that `check_auto_flush` runs must be False
        # immediately after init, regardless of what time.time() returned.
        import time as _time
        t = _time.time()
        auto_flush_needed = t - max(main.last_flush, main.last_filtering) > main.CONFIG['auto_flush_sec']
        self.assertFalse(auto_flush_needed,
                         'auto_flush would fire immediately after init() — '
                         'last_flush={}, last_filtering={}, t={}'.format(
                             main.last_flush, main.last_filtering, t))

        # The water_clean_sec check (used by filter_water for pre-flush) must
        # be True so the first filter after boot does pre-flush the membrane.
        flush_needed = t - max(main.last_flush, main.last_filtering) > main.CONFIG['water_clean_sec']
        self.assertTrue(flush_needed,
                        'first filter after boot should trigger a pre-flush — '
                        'last_flush={}, last_filtering={}, t={}'.format(
                            main.last_flush, main.last_filtering, t))


class TestManualMode(_SequencingAssertionsMixin, _AsyncTestCase):
    """Double-tap from idle puts the system into a toggle-style manual mode
    used during disinfection. Single press toggles pump on/off with no pre/post
    flush; long press exits."""

    def setUp(self):
        super().setUp()
        main.PIN_BUTTON._value = 1

    async def _drive(self, scenario_coro):
        _ButtonHandlerHarness.install_patches()
        button_task = asyncio.create_task(main.handle_button())
        try:
            await scenario_coro
        finally:
            button_task.cancel()
            try:
                await button_task
            except (asyncio.CancelledError, BaseException):
                pass
            _ButtonHandlerHarness.restore_patches()

    def test_double_tap_from_idle_enters_manual_mode(self):
        async def scenario():
            await asyncio.sleep(0.05)
            await _ButtonHandlerHarness.double_tap()
            self.assertTrue(main.manual_mode, 'manual_mode should be active after double-tap')
            self.assertEqual(main.running_task_type, 'MANUAL_IDLE')

        self.run_async(self._drive(scenario()))

    def test_short_press_in_manual_toggles_pump_with_no_pre_flush(self):
        """In manual mode a short press starts the pump immediately in filter
        configuration — no pre-flush ramp."""
        async def scenario():
            await asyncio.sleep(0.05)
            await _ButtonHandlerHarness.double_tap()  # enter manual
            machine.reset_events()                    # only inspect what happens after entry
            await _ButtonHandlerHarness.press(80)     # toggle ON
            self.assertEqual(main.running_task_type, 'MANUAL_RUNNING')

            # Verify what happened: valves -> filter mode, then pump ON. No
            # flush mode (V1+V2) was used at any point — i.e. no pre-flush.
            evs = [e for e in machine.get_events() if e[0] == 'pin']
            valve_state_history = []
            v = {0: 1, 1: 1, 2: 1, 3: 1}
            for kind, num, val, t in evs:
                if num in PIN_VALVE:
                    v[num] = val
                    valve_state_history.append(dict(v))
            # At no point in the trace should both V1 (pin 0) and V2 (pin 1) be
            # OPEN simultaneously — that's the flush bypass and we're skipping it.
            for vs in valve_state_history:
                both_v1_v2_open = vs[0] == 0 and vs[1] == 0
                self.assertFalse(both_v1_v2_open,
                                 'manual mode should not enter flush configuration; got {}'.format(vs))

            await _ButtonHandlerHarness.press(80)     # toggle OFF
            self.assertEqual(main.running_task_type, 'MANUAL_IDLE')

        self.run_async(self._drive(scenario()))

    def test_long_press_exits_manual_mode_with_clean_state(self):
        async def scenario():
            await asyncio.sleep(0.05)
            await _ButtonHandlerHarness.double_tap()
            await _ButtonHandlerHarness.press(80)     # toggle ON
            await _ButtonHandlerHarness.press(1500)   # long press → exit
            self.assertFalse(main.manual_mode, 'manual_mode should be off after long-press exit')
            self.assertIsNone(main.running_task_type)

        self.run_async(self._drive(scenario()))
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_bleed_window_keeps_valve_open(evs)
        state = final_pin_state(evs)
        self.assertEqual(state[PIN_PUMP], 0)
        for vv in PIN_VALVE:
            self.assertEqual(state[vv], 1)

    def test_check_auto_flush_skipped_during_manual_mode(self):
        """The auto-flush timer must not fire while manual_mode is active —
        otherwise it'd interrupt a disinfection 1-hour soak."""
        async def scenario():
            main.last_flush = 0
            main.last_filtering = 0
            main.CONFIG['auto_flush_sec'] = 0.05  # would fire immediately if unguarded

            check_task = asyncio.create_task(main.check_auto_flush())
            try:
                await asyncio.sleep(0.05)
                await _ButtonHandlerHarness.double_tap()
                self.assertTrue(main.manual_mode)
                # Wait long enough for several check_auto_flush ticks (1 s each).
                await asyncio.sleep(1.5)
                self.assertEqual(main.last_flush, 0,
                                 'auto-flush should not have fired while in manual mode')
            finally:
                check_task.cancel()
                try:
                    await check_task
                except (asyncio.CancelledError, BaseException):
                    pass

        self.run_async(self._drive(scenario()))


class TestDeferredPostFlush(_SequencingAssertionsMixin, _AsyncTestCase):
    """filter_water now schedules the membrane post-flush to run a few minutes
    after the user takes their water, instead of blocking the cycle."""

    def test_filter_water_does_not_post_flush_inline(self):
        """At the moment filter_water returns, no post-flush has run yet —
        the user gets their pump-off + valves-closed promptly. After V3
        (filter output) closes, V2 (flush bypass) must not re-open: that
        would indicate an inline post-flush the user has to wait through."""
        main.CONFIG['deferred_post_flush_sec'] = 1000.0  # never fires within the test

        self.run_async(main.filter_water())

        evs = [e for e in machine.get_events() if e[0] == 'pin']
        # Find the moment V3 closes for the last time (end of filter phase).
        v3_close_t = None
        for kind, num, val, t in evs:
            if num == 2 and val == 1:
                v3_close_t = t
        self.assertIsNotNone(v3_close_t, 'V3 was never closed — filter phase missing?')

        # After V3 closes, V2 (pin 1) must not transition open (=0). An inline
        # post-flush would open V2 to flush the membrane.
        for kind, num, val, t in evs:
            if t > v3_close_t and num == 1 and val == 0:
                self.fail('V2 reopened at t={} after V3 closed; inline post-flush?'.format(t))

        # And the deferred task must have been scheduled.
        self.assertIsNotNone(main._deferred_post_flush_task,
                             'filter_water did not schedule a deferred post-flush')

    def test_deferred_post_flush_runs_after_delay(self):
        """When the deferred timer expires and nothing else is running, the
        membrane post-flush actually fires."""
        main.CONFIG['deferred_post_flush_sec'] = 0.1  # fires shortly after filter ends

        async def scenario():
            main.event_loop = asyncio.get_running_loop()
            await main.filter_water()
            # filter_water has scheduled the deferred post-flush; wait for it.
            self.assertIsNotNone(main._deferred_post_flush_task)
            for _ in range(60):  # up to 6 s
                await asyncio.sleep(0.1)
                if main._deferred_post_flush_task.done():
                    break
            self.assertTrue(main._deferred_post_flush_task.done(),
                            'deferred post-flush did not finish within timeout')
            # last_flush should have been bumped by the deferred post-flush.
            self.assertGreater(main.last_flush, 0)

        self.run_async(scenario())
        evs = machine.get_events()
        self.assert_pump_transitions_have_open_valves(evs)
        self.assert_bleed_window_keeps_valve_open(evs)
        state = final_pin_state(evs)
        self.assertEqual(state[PIN_PUMP], 0)
        for vv in PIN_VALVE:
            self.assertEqual(state[vv], 1)

    def test_starting_new_filter_cancels_deferred_post_flush(self):
        """If the user kicks off a new filter cycle before the deferred timer
        elapses, the pending post-flush gets cancelled — only the new cycle's
        own deferred post-flush remains."""
        main.CONFIG['deferred_post_flush_sec'] = 5.0  # safely beyond the test window

        async def scenario():
            main.event_loop = asyncio.get_running_loop()
            await main.filter_water()
            first_task = main._deferred_post_flush_task
            self.assertIsNotNone(first_task)
            self.assertFalse(first_task.done())

            # Skip the water_clean_sec check by NOT advancing time; force a fresh
            # pre-flush by resetting the timestamps so flush_needed=True.
            main.last_flush = 0
            main.last_filtering = 0
            await main.filter_water()

            # The first deferred task must have been cancelled by the second cycle.
            self.assertTrue(first_task.done(),
                            'first deferred post-flush task should have been cancelled')
            # And a new one is in place for the second cycle.
            second_task = main._deferred_post_flush_task
            self.assertIsNotNone(second_task)
            self.assertIsNot(second_task, first_task)
            second_task.cancel()
            try:
                await second_task
            except (asyncio.CancelledError, BaseException):
                pass

        self.run_async(scenario())

    def test_new_cycle_during_deferred_post_flush_no_race(self):
        """If a new filter cycle starts while the deferred post-flush is
        ALREADY in its post-flush phase (pump on), the new cycle must wait
        for the cancelled deferred's clean shutdown before it touches the
        hardware — otherwise pump and valves race."""
        # Tiny delay so the deferred fires quickly into post-flush.
        main.CONFIG['deferred_post_flush_sec'] = 0.02
        # Stretch post_flush_sec so we have a wide window to interrupt during
        # the deferred's pump-on phase.
        main.CONFIG['post_flush_sec'] = 0.4

        async def scenario():
            main.event_loop = asyncio.get_running_loop()
            await main.filter_water()
            # Wait long enough that the deferred has woken up and entered its
            # post-flush phase (pump on, valves to flush).
            await asyncio.sleep(0.1)
            # Confirm we're really in the deferred's post-flush phase.
            self.assertEqual(main.running_task_type, 'FLUSHING',
                             'deferred post-flush should be active by now')

            # Kick off a new filter cycle. With the bug, the cancelled deferred's
            # clean shutdown would race with the new cycle's pre-flush ramp.
            main.last_flush = 0
            main.last_filtering = 0
            await main.filter_water()

            # Drain the new cycle's deferred to keep the test clean.
            if main._deferred_post_flush_task is not None:
                main._deferred_post_flush_task.cancel()
                try:
                    await main._deferred_post_flush_task
                except (asyncio.CancelledError, BaseException):
                    pass

        self.run_async(scenario())
        evs = machine.get_events()
        # The race manifests as a tight pump OFF -> ON cycle (the cancelled
        # deferred's _clean_shutdown turns pump off while the new cycle's
        # pre-flush ramp turns it back on).
        self.assert_no_rapid_pump_cycling(evs)
        self.assert_pump_transitions_have_open_valves(evs)


class TestConfigPersistence(unittest.TestCase):
    """write_config should be atomic; read_config should tolerate corruption."""

    def setUp(self):
        # Run inside a tmp dir so we don't pollute the repo.
        self._cwd = os.getcwd()
        self._tmpdir = os.path.join('/tmp', 'roconfig-test-{}'.format(os.getpid()))
        os.makedirs(self._tmpdir, exist_ok=True)
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._cwd)
        for fn in os.listdir(self._tmpdir):
            os.remove(os.path.join(self._tmpdir, fn))
        os.rmdir(self._tmpdir)

    def test_round_trip(self):
        main.write_config({'filter_sec': 123})
        self.assertEqual(main.read_config(), {'filter_sec': 123})

    def test_overwrite(self):
        main.write_config({'filter_sec': 1})
        main.write_config({'filter_sec': 2})
        self.assertEqual(main.read_config(), {'filter_sec': 2})

    def test_corrupted_json_returns_defaults(self):
        with open(main.CONFIG_FILE, 'w') as f:
            f.write('{not valid json')
        # Must not raise; returns {} so CONFIG defaults are kept.
        self.assertEqual(main.read_config(), {})

    def test_missing_file_returns_defaults(self):
        # Make sure no config file exists.
        if os.path.exists(main.CONFIG_FILE):
            os.remove(main.CONFIG_FILE)
        self.assertEqual(main.read_config(), {})


class TestButtonPressMeasurement(unittest.TestCase):
    """ms_duration must use ticks_diff to handle ticks_ms() wraparound."""

    def test_ticks_diff_handles_wraparound(self):
        import time
        # Press starts near the wrap boundary, ends just past it.
        # ticks_ms() wraps at 2^30 in MicroPython; our shim uses the same modulus.
        ticks_max = 1 << 30
        start = ticks_max - 100
        end = 200  # i.e. wrapped past zero by 200
        # A bare subtraction would give a hugely negative number; ticks_diff fixes it.
        self.assertGreater(time.ticks_diff(end, start), 0)
        self.assertEqual(time.ticks_diff(end, start), 300)


if __name__ == '__main__':
    unittest.main()
