"""
Mock of MicroPython's `machine` module for desktop testing.

Records every Pin write into a global event log so tests can assert on the
sequence of hardware actions without a Pico attached.
"""

import time as _time


_events = []


def reset_events():
    _events.clear()


def get_events():
    return list(_events)


def _now():
    return _time.monotonic()


class Pin:
    OUT = 'OUT'
    IN = 'IN'
    PULL_UP = 'PULL_UP'

    def __init__(self, num, mode=None, pull=None):
        # Support `Pin(other_pin)` wrapping (used by `PWM(Pin(PIN_BUZZER))` in main.py).
        if isinstance(num, Pin):
            self.num = num.num
            self.mode = num.mode
            self.pull = num.pull
            self._value = num._value
        else:
            self.num = num
            self.mode = mode
            self.pull = pull
            self._value = 0

    def value(self, v=None):
        if v is None:
            return self._value
        v = int(bool(v))
        if v != self._value:
            _events.append(('pin', self.num, v, _now()))
        self._value = v

    def toggle(self):
        self.value(not self._value)


class PWM:
    def __init__(self, pin):
        self.pin = pin
        self._freq = 0
        self._duty = 0

    def freq(self, f):
        self._freq = f

    def duty_u16(self, d):
        self._duty = d
        # Buzzer on/off transitions are useful to see in the trace; record them.
        _events.append(('pwm', getattr(self.pin, 'num', None), int(d > 0), _now()))


class WDT:
    """No-op stand-in for the hardware watchdog. Counts feed() calls so tests
    can verify the watchdog is actually being kept alive by the event loop."""

    def __init__(self, id=0, timeout=5000):
        self.id = id
        self.timeout = timeout
        self.feeds = 0

    def feed(self):
        self.feeds += 1
