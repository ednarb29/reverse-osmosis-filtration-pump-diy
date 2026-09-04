"""
Program Summary:

This script is designed for a Raspberry Pi Pico runing MicroPython with the
goal of controlling a set of 4 valves and a pump for a reverse osmosis filtration system.
The system is controlled with one button. Its main features are:
- Automatic flushing of the osmosis membrane every few hours to avoid the
  development of germs in the different filters.
- Automatic disposal of the first filtered water (that contains more
  particles due to the lowered pressure in the osmosis membrane during its
  idle time).
- Setting a fixed time interval for water filtration to yield a specific
  amount of water. This time interval can be stored via a long button press.

The script is structured to be asynchronous, allowing it to handle multiple
operations efficiently without blocking the main execution flow.
"""

# Importing necessary libraries for hardware control and asynchronous operations
import os
import time
import uasyncio
import ujson
from machine import Pin, PWM

# Configuration values with default settings.
# These settings are used for various timing operations in the script and can be overridden by an external configuration file.
CONFIG_FILE = 'config.json'  # Name of the external configuration file.
CONFIG = {
    'pre_flush_sec': 10,        # Time in seconds for the pre-flush operation of the membrane. Default: 10s
    'post_flush_sec': 30,       # Time in seconds for the post-flush operation of the membrane. Default: 30s
    'long_flush_sec': 15 * 60,  # Time in seconds for the long-flush operation of the membrane. Default: 15 min
    'disposal_sec': 60,         # Time in seconds for the disposal operation of the first filtered water. Default: 60s
    'filter_sec': 12 * 60,      # Time in seconds for the filter operation. Default: 12 min
    'auto_flush_sec': 8 * 60 * 60,      # Time in seconds between automatic flushing (Default 8 hours).
    'water_clean_sec': 5 * 60,          # Time in seconds for water cleaning operation. Default: 5 min
    'deferred_post_flush_sec': 30,  # Delay between a filter cycle ending and the membrane post-flush
                                        # firing in the background. Lower this (e.g. 15) for portable
                                        # use where you want to power off shortly after filtering. (Default: 30 s)
    'buzzer_frequency': 1500,           # Frequency in Hz for the buzzer tone. Default 1500 Hz
    'pump_switch_delay': 1000,          # Time in milliseconds to delay pump switch actions before/after valves.
                                            # Default: 1000ms
    'inlet_bleed_ms': 5000              # How long to leave the non-inlet valves open after the pump stops,
                                            # to bleed membrane back-pressure through V2 to the drain.
                                            # Sits between pump-OFF and all-valves-closed. Default: 5000ms.
}

# Test config
""" CONFIG = {
    'pre_flush_sec': 10,
    'post_flush_sec': 10,
    'long_flush_sec': 20,
    'disposal_sec': 10,
    'filter_sec': 20,
    'auto_flush_sec': 120,
    'water_clean_sec': 30,
    'deferred_post_flush_sec': 30,
    'buzzer_frequency': 1500,
    'pump_switch_delay': 1000,
    'inlet_bleed_ms': 5000
} """

# Bounds applied when the user saves a new filter duration via long-press during filtering.
# Prevents accidentally storing a near-zero or absurdly long value.
FILTER_SEC_MIN = 30
FILTER_SEC_MAX = 60 * 60

# Window after a short button press during which a second short press counts as
# a double-tap. Single short presses get dispatched after this window expires,
# so this value also bounds the latency on every short press. 600 ms is a
# comfortable physical-button timing; tighter (e.g. 350 ms) feels snappier on
# single presses but makes double-tapping a panel button physically hard.
DOUBLE_TAP_WINDOW_MS = 600

# After detecting a state change on the button pin, wait this long and re-check
# before accepting it. Filters out brief electrical transients — typically EMI
# from the valve / pump relays coupling onto the button cable, which would
# otherwise register as a phantom button press right after each relay switch.
BUTTON_DEBOUNCE_MS = 50

# GPIO pin setup for various components connected to the microcontroller.
PIN_BUZZER = Pin(15, Pin.OUT)  # Buzzer pin, set as output.
BUZZER = PWM(Pin(PIN_BUZZER))  # Create PWM-Object
PIN_BUTTON = Pin(16, Pin.IN, Pin.PULL_UP)  # Button pin, set as input with pull-up resistor.

# Pins for controlling valves or other actuators.
PIN_VALVE1 = Pin(0, Pin.OUT)  # Valve 1 control pin.
PIN_VALVE2 = Pin(1, Pin.OUT)  # Valve 2 control pin.
PIN_VALVE3 = Pin(2, Pin.OUT)  # Valve 3 control pin.
PIN_VALVE4 = Pin(3, Pin.OUT)  # Valve 4 control pin.
PIN_PUMP = Pin(4, Pin.OUT)  # Pump 1 control pin.

# Class representing a dummy placeholder for no actual task.
# A dummy task is always indicated as "done".
class DummyTask():
    def done(self):
        return True


# Initialization of Time Tracking and Task Management Variables

last_flush = 0
last_reflush = 0
last_filtering = 0
start_filtering = 0

running_task = DummyTask()
running_task_type = None

# True while the user is in the manual-toggle mode (entered via double-tap from
# idle). In manual mode, button presses directly toggle the pump on/off without
# any pre-flush, post-flush, or auto-flush running in the background.
manual_mode = False

# Background task scheduled at the end of every filter cycle — sleeps for
# DEFERRED_POST_FLUSH_SEC then runs a membrane post-flush. Cancelled if any new
# user-initiated operation starts before it fires. None when no post-flush is pending.
_deferred_post_flush_task = None

# Set by main() at startup; referenced by handle_button / check_auto_flush to spawn child tasks.
event_loop = None

# Hardware watchdog. Initialised in main() (None when running under tests so the
# desktop sim never installs a real WDT). Fed every second by check_auto_flush —
# if the event loop hangs, the Pico reboots and init() returns to a safe state.
_WDT = None
WDT_TIMEOUT_MS = 8000


def read_config():
    """
    Reads configuration settings from an external JSON file.

    Returns the parsed dict on success, or {} if the file is missing, unreadable,
    or contains invalid JSON. Falling back to defaults is preferred over crashing
    at boot if config.json was corrupted by a power loss mid-write.
    """
    try:
        with open(CONFIG_FILE, 'r') as f:
            config_data = f.read()
        return ujson.loads(config_data)
    except (OSError, ValueError):
        return {}


def write_config(config):
    """
    Atomically persists the configuration dict to CONFIG_FILE.

    Writes to a temporary file first, then renames over the destination, so a
    power loss during the write leaves either the old file or the new file —
    never a half-written one that read_config would have to discard.
    """
    tmp_path = CONFIG_FILE + '.tmp'
    with open(tmp_path, 'w') as f:
        f.write(ujson.dumps(config))
    try:
        os.rename(tmp_path, CONFIG_FILE)
    except OSError:
        # Some filesystems (older MicroPython builds) refuse to rename over an
        # existing file. Fall back to remove + rename. Slightly less atomic but
        # still better than truncating the original in place.
        try:
            os.remove(CONFIG_FILE)
        except OSError:
            pass
        os.rename(tmp_path, CONFIG_FILE)


def _set_valves(v1, v2, v3, v4):
    """
    Internal convenient function that controls the state of the 4 valves based on the arguments.

    The valve relay module is active-low, so each PIN is driven to the logical NOT
    of its boolean argument. Passing True opens the corresponding valve.
    """
    PIN_VALVE1.value(not v1)
    PIN_VALVE2.value(not v2)
    PIN_VALVE3.value(not v3)
    PIN_VALVE4.value(not v4)


def set_pump(p):
    """
    Controls the state of the pump.

    The pump relay is active-high (opposite polarity to the valve relays):
    True turns the pump ON, False turns it OFF.
    """
    print('  pump', 'ON' if p else 'OFF')
    PIN_PUMP.value(bool(p))


def close_valves():
    """
    Closes all valves. If the pump was somehow left running, force-shut it first.
    """
    if PIN_PUMP.value():
        print('Pump has not been turned off yet. Safety shut down!')
        set_pump(False)

    _set_valves(False, False, False, False)


def close_inlet_valve():
    """
    Closes the inlet valve and keeps the others open to bleed remaining
    pressure from the system before the final close.
    """
    if PIN_PUMP.value():
        print('Pump has not been turned off yet. Safety shut down!')
        set_pump(False)

    _set_valves(False, True, False, False)


def set_valves_to_flush():
    """Configures valves for the flushing operation (bypass membrane)."""
    _set_valves(True, True, False, False)


def set_valves_to_disposal():
    """Configures valves to divert the first filtered water (high particle content)."""
    _set_valves(True, False, False, True)


def set_valves_to_filter():
    """Configures the valves for normal filtration."""
    _set_valves(True, False, True, False)


def init():
    """
    Initializes the system to a safe state at boot: pump off, all valves closed,
    configuration loaded from disk (overlaid on defaults).

    Also seeds last_flush / last_filtering relative to the current RTC time.
    The RP2040 RTC keeps running across soft-resets (e.g. uploading new code
    via Thonny or mpremote), so `time.time()` at boot can be any value. Without
    this seeding, `auto_flush_needed = time.time() - 0 > auto_flush_sec` fires
    immediately on every soft-reboot. The chosen offset (water_clean_sec + 1)
    means the first filter after boot still triggers a pre-flush — the membrane
    has been sitting since power-off and needs it — while the auto-flush timer
    measures from boot, not from epoch.
    """
    global last_flush, last_filtering
    print('Set valves to be closed and pump to be turned OFF.')
    set_pump(False)
    close_valves()
    CONFIG.update(read_config())
    print('config read: {}'.format(CONFIG))
    pseudo_past = time.time() - CONFIG['water_clean_sec'] - 1
    last_flush = pseudo_past
    last_filtering = pseudo_past


async def _clean_shutdown():
    """
    End-of-cycle hardware shutdown. Safe to call from any state.

    Order is load-bearing: pump off first, wait for residual pressure to drop,
    then bleed pressure through the inlet-only-closed configuration, then close
    everything. Used in finally blocks to guarantee a safe state on cancellation.
    """
    set_pump(False)
    await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])

    print('  closing inlet valve!')
    close_inlet_valve()
    await uasyncio.sleep_ms(CONFIG['inlet_bleed_ms'])

    print('  closing valves!')
    close_valves()
    print('\n')


async def greeting_beeps():
    """Plays a sequence of 1x short beep and 1x long beep as a greeting."""
    BUZZER.freq(CONFIG['buzzer_frequency'])
    BUZZER.duty_u16(32768)
    await uasyncio.sleep(0.1)
    BUZZER.duty_u16(0)
    await uasyncio.sleep(0.1)
    BUZZER.duty_u16(32768)
    await uasyncio.sleep(0.5)
    BUZZER.duty_u16(0)


async def finish_beeps():
    """Plays a sequence of 3x long beeps to indicate completion."""
    BUZZER.freq(CONFIG['buzzer_frequency'])
    for _ in range(3):
        BUZZER.duty_u16(32768)
        await uasyncio.sleep(0.4)
        BUZZER.duty_u16(0)
        await uasyncio.sleep(0.2)


async def short_beep():
    """Emits a short beep after a short button press."""
    BUZZER.freq(CONFIG['buzzer_frequency'])
    BUZZER.duty_u16(32768)
    await uasyncio.sleep(0.2)
    BUZZER.duty_u16(0)


async def long_beep():
    """Emits a long beep after a long button press."""
    BUZZER.freq(CONFIG['buzzer_frequency'])
    BUZZER.duty_u16(32768)
    await uasyncio.sleep(0.5)
    BUZZER.duty_u16(0)


async def super_long_beep():
    """Emits a one-second beep after a super-long button press."""
    BUZZER.freq(CONFIG['buzzer_frequency'])
    BUZZER.duty_u16(32768)
    await uasyncio.sleep(1)
    BUZZER.duty_u16(0)


async def auto_flush_filter():
    """
    Full automatic flush cycle: pre-flush, dispose first water, post-flush, shutdown.
    """
    global last_flush, running_task_type
    print('auto_flush_filter')
    # Subsume any pending deferred post-flush — this cycle does its own membrane care.
    await _cancel_pending_post_flush()
    running_task_type = 'FLUSHING'

    try:
        # pre-flush
        print('  pre-flush osmose membrane (' + str(CONFIG['pre_flush_sec']) + 's)')
        set_valves_to_flush()
        await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])
        set_pump(True)
        await uasyncio.sleep(CONFIG['pre_flush_sec'])

        # dispose first water
        print('  dispose filtered water (' + str(CONFIG['disposal_sec']) + 's)')
        set_valves_to_disposal()
        await uasyncio.sleep(CONFIG['disposal_sec'])

        # post-flush
        print('  post-flush osmose membrane (' + str(CONFIG['post_flush_sec']) + 's)')
        set_valves_to_flush()
        await uasyncio.sleep(CONFIG['post_flush_sec'])

    finally:
        # Cleanup must run on any exit path, including cancellation, so the pump
        # can never be left on with the valves in an arbitrary state.
        try:
            await _clean_shutdown()
        except Exception:
            # Best-effort: if even the shutdown's awaits get cancelled, force the
            # hardware to a safe state synchronously.
            set_pump(False)
            close_valves()
        last_flush = time.time()
        running_task_type = None


async def pre_flush_filter():
    """
    Pre-flush + disposal phase used as a sub-step of filter_water.

    Turns the pump ON and leaves it running; the calling coroutine is responsible
    for transitioning into the next phase and eventually shutting the pump off.
    Not safe to call standalone — for that, use auto_flush_filter or long_flush_filter.

    Sets running_task_type='PRE_FLUSHING' (distinct from 'FLUSHING' used by
    standalone flush cycles) so the button dispatch can treat the two cases
    differently: short-press during pre-flush skips ahead to the filter phase,
    while short-press during a standalone flush just cancels.
    """
    global running_task_type
    running_task_type = 'PRE_FLUSHING'

    print('  pre-flush osmose membrane (' + str(CONFIG['pre_flush_sec']) + 's)')
    set_valves_to_flush()
    await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])
    set_pump(True)
    await uasyncio.sleep(CONFIG['pre_flush_sec'])

    print('  dispose filtered water (' + str(CONFIG['disposal_sec']) + 's)')
    set_valves_to_disposal()
    await uasyncio.sleep(CONFIG['disposal_sec'])


async def post_flush_filter():
    """
    Post-flush phase used as a sub-step of filter_water (pump must already be ON).
    Updates last_flush so the auto-flush timer resets.
    """
    global last_flush, running_task_type
    running_task_type = 'FLUSHING'

    print('  post-flush osmose membrane (' + str(CONFIG['post_flush_sec']) + 's)')
    set_valves_to_flush()
    await uasyncio.sleep(CONFIG['post_flush_sec'])

    last_flush = time.time()


async def long_flush_filter():
    """
    Extended flushing cycle, e.g. after exchanging the membrane or pre-filter stages.
    Drives the pump for long_flush_sec then performs a clean shutdown.
    """
    global last_flush, running_task_type
    # Subsume any pending deferred post-flush — this cycle does its own membrane care.
    await _cancel_pending_post_flush()
    running_task_type = 'FLUSHING'

    try:
        print('  long-flush osmose membrane (' + str(CONFIG['long_flush_sec']) + 's)')
        set_valves_to_flush()
        await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])
        set_pump(True)
        await uasyncio.sleep(CONFIG['long_flush_sec'])

    finally:
        try:
            await _clean_shutdown()
        except Exception:
            set_pump(False)
            close_valves()
        last_flush = time.time()
        running_task_type = None


async def filter_water(duration_sec=None):
    """
    Run a complete filtration cycle: optional pre-flush, filter for `duration_sec`,
    finish beeps, immediate clean shutdown so the user can take their water now.
    The membrane post-flush is scheduled to happen DEFERRED_POST_FLUSH_SEC later
    in the background (cancelled automatically if the user starts a new cycle).
    """
    global last_filtering, start_filtering, running_task_type

    if duration_sec is None:
        duration_sec = CONFIG['filter_sec']

    flush_needed = time.time() - max(last_flush, last_filtering) > CONFIG['water_clean_sec']

    # Cancel any pending deferred post-flush from a previous cycle and wait for
    # its cleanup to land — otherwise this cycle's pre-flush could race with
    # the previous deferred's clean-shutdown over pump and valves.
    await _cancel_pending_post_flush()

    try:
        if flush_needed:
            await pre_flush_filter()

        running_task_type = 'FILTERING'
        start_filtering = time.time()
        print('  filter water: ' + str(duration_sec) + 's')
        set_valves_to_filter()
        await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])
        set_pump(True)
        await uasyncio.sleep(duration_sec)
        print('  filtering done :)')
        await finish_beeps()

    finally:
        try:
            await _clean_shutdown()
        except Exception:
            set_pump(False)
            close_valves()
        last_filtering = time.time()
        running_task_type = None
        # Schedule the membrane post-flush for later. The user gets their water
        # right now; the post-flush hums in the background a few minutes later.
        _schedule_deferred_post_flush()


async def _cancel_pending_post_flush():
    """
    Cancel any pending deferred post-flush AND await its cleanup. Must be
    awaited before spawning a new task that touches the pump or valves —
    otherwise, if the deferred was in its post-flush phase, its `finally`
    cleanup would race with the new task over the hardware.
    """
    global _deferred_post_flush_task
    task = _deferred_post_flush_task
    if task is not None and not task.done():
        task.cancel()
        while not task.done():
            await uasyncio.sleep_ms(50)
    _deferred_post_flush_task = None


def _schedule_deferred_post_flush():
    """
    Spawn a background task that waits then runs a membrane post-flush.
    Caller is responsible for awaiting any prior deferred's cleanup before
    calling this — it does NOT await, just replaces.
    """
    global _deferred_post_flush_task
    if _deferred_post_flush_task is not None and not _deferred_post_flush_task.done():
        _deferred_post_flush_task.cancel()
    _deferred_post_flush_task = event_loop.create_task(_deferred_post_flush_cycle())


async def _deferred_post_flush_cycle():
    """
    Wait CONFIG['deferred_post_flush_sec'], then run a membrane post-flush +
    clean shutdown.

    Bails out silently if cancelled during the wait, or if some other task is
    running by the time the wait completes — that other task will be responsible
    for membrane care.
    """
    global last_flush, running_task_type
    try:
        await uasyncio.sleep(CONFIG['deferred_post_flush_sec'])
    except Exception:
        return

    # Don't fight a running task or manual mode for the hardware.
    if not running_task.done() or manual_mode:
        return

    print('Deferred post-flush starting')
    running_task_type = 'FLUSHING'
    try:
        set_valves_to_flush()
        await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])
        set_pump(True)
        await uasyncio.sleep(CONFIG['post_flush_sec'])
    finally:
        try:
            await _clean_shutdown()
        except Exception:
            set_pump(False)
            close_valves()
        last_flush = time.time()
        running_task_type = None


def is_button_pressed():
    """True if the button is held (LOW with pull-up)."""
    return PIN_BUTTON.value() == 0


async def _wait_for_running_task():
    """
    Polls until running_task is finished. Used after .cancel() to make sure the
    cancelled task's finally cleanup has run before the next task touches the
    same valves and pump.
    """
    while not running_task.done():
        await uasyncio.sleep_ms(50)


async def _wait_for_stable_press():
    """Block until the button has been pressed (LOW) and stayed pressed for at
    least BUTTON_DEBOUNCE_MS. Filters out short electrical transients."""
    while True:
        while not is_button_pressed():
            await uasyncio.sleep_ms(50)
        await uasyncio.sleep_ms(BUTTON_DEBOUNCE_MS)
        if is_button_pressed():
            return  # real press
        # otherwise: transient, loop and keep watching


async def _wait_for_stable_release():
    """Block until the button has been released (HIGH) and stayed released for
    at least BUTTON_DEBOUNCE_MS. Filters out transients during a held press."""
    while True:
        while is_button_pressed():
            await uasyncio.sleep_ms(50)
        await uasyncio.sleep_ms(BUTTON_DEBOUNCE_MS)
        if not is_button_pressed():
            return  # real release
        # otherwise: transient, button still held — keep watching


async def _await_press():
    """
    Block until a button press completes, then return its classification:
    'super_long' (>= 5 s), 'long' (0.8 s – 5 s), 'double_tap' (two short presses
    within DOUBLE_TAP_WINDOW_MS), or 'short'.

    Both press and release detections are debounced — see _wait_for_stable_press
    / _wait_for_stable_release. EMI from the valve / pump relays would otherwise
    show up as a phantom press a fraction of a second after each relay click.

    Single short presses are dispatched only after the double-tap window has
    elapsed — accept ~DOUBLE_TAP_WINDOW_MS of latency on short presses as the
    price of the double-tap gesture.
    """
    await _wait_for_stable_press()

    ms_start = time.ticks_ms()
    await _wait_for_stable_release()
    ms_duration = time.ticks_diff(time.ticks_ms(), ms_start)

    if ms_duration >= 5000:
        return 'super_long'
    if ms_duration > 800:
        return 'long'

    # Short press. Wait briefly to see if a second short press follows.
    wait_start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), wait_start) < DOUBLE_TAP_WINDOW_MS:
        if is_button_pressed():
            # Possible second tap — debounce it too before accepting.
            await uasyncio.sleep_ms(BUTTON_DEBOUNCE_MS)
            if is_button_pressed():
                await _wait_for_stable_release()
                return 'double_tap'
            # else: transient inside the double-tap window, keep watching
        await uasyncio.sleep_ms(20)
    return 'short'


async def _acknowledge(press):
    """Audible feedback for a recognised press."""
    if press == 'super_long':
        print('Super long button press')
        await super_long_beep()
    elif press == 'long':
        print('Long button press')
        await long_beep()
    elif press == 'double_tap':
        print('Double-tap')
        await short_beep()
        await uasyncio.sleep_ms(80)
        await short_beep()
    else:
        print('Short button press')
        await short_beep()


async def _manual_pump_off():
    """Toggle from manual-running to manual-idle: pump off + valves closed."""
    global running_task_type
    print('  manual: pump OFF')
    await _clean_shutdown()
    running_task_type = 'MANUAL_IDLE'


async def _manual_pump_on():
    """Toggle from manual-idle to manual-running: filter valves + pump on."""
    global running_task_type
    print('  manual: pump ON')
    set_valves_to_filter()
    await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])
    set_pump(True)
    running_task_type = 'MANUAL_RUNNING'


async def _dispatch_manual(press):
    """Button dispatch while manual_mode is active."""
    global manual_mode, running_task_type
    if press in ('long', 'super_long'):
        if running_task_type == 'MANUAL_RUNNING':
            await _manual_pump_off()
        running_task_type = None
        manual_mode = False
        print('Exit manual mode')
    elif press == 'short':
        if running_task_type == 'MANUAL_RUNNING':
            await _manual_pump_off()
        else:
            await _manual_pump_on()
    # double_tap: ignored in manual mode


async def _dispatch_normal(press):
    """Button dispatch while not in manual mode."""
    global running_task, manual_mode, running_task_type

    if press == 'double_tap':
        # Enter manual mode only from a quiet idle state. Ignore otherwise.
        if running_task.done():
            await _cancel_pending_post_flush()
            manual_mode = True
            running_task_type = 'MANUAL_IDLE'
            print('Enter manual mode')
        return

    if not running_task.done():
        cancelled_type = running_task_type

        # Capture the elapsed filter time BEFORE awaiting the cancelled task,
        # because that wait will run a clean shutdown that takes a few seconds.
        save_filter_sec = press == 'long' and cancelled_type == 'FILTERING'
        if save_filter_sec:
            new_filter_sec = max(FILTER_SEC_MIN, min(FILTER_SEC_MAX, time.time() - start_filtering))

        print('\n')
        print('Cancel task {}'.format(cancelled_type))
        running_task.cancel()
        await _wait_for_running_task()

        if save_filter_sec:
            CONFIG['filter_sec'] = new_filter_sec
            write_config(CONFIG)
            print('  save new time interval: {}'.format(new_filter_sec))

        if press == 'super_long':
            print('  long flushing')
            running_task = event_loop.create_task(long_flush_filter())
        elif press == 'long' and cancelled_type == 'PRE_FLUSHING':
            # User is impatient with the pre-flush before a 1-hour filter — skip
            # straight to the filter phase. Only triggers for the auto-injected
            # pre-flush inside filter_water, NOT for standalone flush cycles.
            print('  cancel pre-flush and long filter')
            running_task = event_loop.create_task(filter_water(60 * 60))
        elif press == 'short' and cancelled_type == 'PRE_FLUSHING':
            # Same as above but for a normal-duration filter.
            print('  cancel pre-flush and filter')
            running_task = event_loop.create_task(filter_water())
        # Short / long press during a standalone flush (auto_flush_filter or
        # long_flush_filter): just cancel, no follow-on. The user explicitly
        # asked for that flush via super-long or it was auto-triggered, so the
        # natural cancel meaning is "stop and idle" rather than "skip and filter."

    else:  # idle
        await _cancel_pending_post_flush()
        if press == 'super_long':
            running_task = event_loop.create_task(long_flush_filter())
            print('  long flushing')
        elif press == 'long':
            running_task = event_loop.create_task(filter_water(60 * 60))
            print('  long filtering')
        else:  # short
            running_task = event_loop.create_task(filter_water())
            print('  filtering')


async def handle_button():
    """First main loop for handling button press events."""
    while True:
        press = await _await_press()
        await _acknowledge(press)
        if manual_mode:
            await _dispatch_manual(press)
        else:
            await _dispatch_normal(press)


async def check_auto_flush():
    """Second main loop to control automatic flush operations of the system.
    Also feeds the hardware watchdog every tick — if this loop ever stops
    running, the WDT will trigger a reboot which returns to a safe state."""
    global running_task
    while True:
        await uasyncio.sleep(1)
        if _WDT is not None:
            _WDT.feed()
        deferred_busy = (_deferred_post_flush_task is not None
                         and not _deferred_post_flush_task.done())
        if not running_task.done() or manual_mode or deferred_busy:
            continue

        t = time.time()
        auto_flush_needed = t - max(last_flush, last_filtering) > CONFIG['auto_flush_sec']
        if auto_flush_needed:
            print('AUTO FLUSHING')
            running_task = event_loop.create_task(auto_flush_filter())


def main():
    """Entry point. Wrapped in a function so tests can import this module without
    starting the event loop or arming the hardware watchdog."""
    global event_loop, _WDT
    init()
    event_loop = uasyncio.get_event_loop()
    event_loop.run_until_complete(greeting_beeps())

    # Arm the hardware watchdog AFTER the slow boot path (init + greeting beeps),
    # so a slow boot can't fire it. Once enabled the WDT cannot be disabled.
    try:
        from machine import WDT
        _WDT = WDT(timeout=WDT_TIMEOUT_MS)
        print('Watchdog enabled ({} ms)'.format(WDT_TIMEOUT_MS))
    except (ImportError, OSError, AttributeError):
        # WDT not available on this platform; tolerable in dev/sim.
        _WDT = None

    event_loop.create_task(handle_button())
    event_loop.create_task(check_auto_flush())
    event_loop.run_forever()


if __name__ == '__main__':
    main()
