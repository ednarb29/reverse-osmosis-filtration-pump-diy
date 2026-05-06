# Button Quick Reference

One button, four gestures. The system beeps to confirm what it heard.

## Gestures

| Gesture        | Hold time      | Beep       |
|----------------|----------------|------------|
| Short press    | under 0.8 s    | 1 short    |
| Long press     | 0.8 s to 5 s   | 1 long     |
| Super-long     | 5 s or more    | 1 very long (1 s) |
| Double-tap     | two short presses within 0.6 s | 2 short |

After a filter cycle finishes, you also hear three long beeps.

## What each gesture does

### From idle

| Press        | Effect                                                          |
|--------------|-----------------------------------------------------------------|
| Short        | Filter for `filter_sec` (default 12 min)                        |
| Long         | Filter for 1 hour                                               |
| Super-long   | Long flush (`long_flush_sec`, default 15 min)                   |
| Double-tap   | Enter manual mode (see below)                                   |

If the system has been idle longer than `water_clean_sec` (default 5 min), a
short pre-flush plus disposal runs before the filter phase. This protects you
from drinking the first stagnant water from the membrane.

### While filtering (pump running, water coming out)

| Press        | Effect                                                          |
|--------------|-----------------------------------------------------------------|
| Short        | Stop. Clean shutdown.                                           |
| Long         | Stop AND save the elapsed time as the new `filter_sec` (clamped to 30 s to 1 hour). Use this to calibrate "fill my bottle" duration. |
| Super-long   | Stop and start a long flush.                                    |

After every filter cycle the membrane post-flush runs in the background,
configured by `deferred_post_flush_sec` (default 3 min). Camper / portable
setups should set this to 15 s in `config.json` so the system is ready to
power down sooner.

### While the pre-flush is running (before a filter cycle, valves in flush mode)

| Press        | Effect                                                          |
|--------------|-----------------------------------------------------------------|
| Short        | Skip the pre-flush, go straight to filtering.                   |
| Long         | Skip the pre-flush, start a 1-hour filter.                      |
| Super-long   | Cancel and start a long flush.                                  |

### While a standalone flush is running (auto-flush, or long-flush you started with super-long press)

| Press        | Effect                                                          |
|--------------|-----------------------------------------------------------------|
| Short        | Cancel. Returns to idle. No follow-on filter.                   |
| Long         | Cancel. Returns to idle. No follow-on filter.                   |
| Super-long   | Cancel and start a fresh long flush.                            |

## Manual mode (double-tap from idle)

Manual mode is for the manufacturer's disinfection procedure (steps 2 and 4
of the AquaMichel Mini handbook), where you push 150 to 200 ml of water
through the system after each H2O2 injection.

| Press        | Effect                                                          |
|--------------|-----------------------------------------------------------------|
| Short        | Toggle pump on/off in filter configuration. NO pre-flush, NO post-flush, NO deferred work. |
| Long         | Exit manual mode. Pump shuts off cleanly first.                 |
| Super-long   | Exit manual mode.                                               |
| Double-tap   | Ignored.                                                        |

While in manual mode, the auto-flush timer is paused. This is what makes the
1-hour H2O2 soak step safe (no surprise flush in the middle of it).

## Background behavior

- **Auto-flush:** every `auto_flush_sec` (default 8 hours) the system runs a
  full pre-flush + disposal + post-flush cycle on its own to keep the
  membrane fresh. The timer resets after every flush or filter.
- **Deferred post-flush:** after a filter cycle, the membrane post-flush is
  scheduled to run `deferred_post_flush_sec` later. This lets you take your
  water immediately and the system handles the membrane care in the
  background. Starting a new cycle cancels the pending post-flush.

## Failure cues to listen for

| Sound                                       | What it means                              |
|---------------------------------------------|--------------------------------------------|
| Pump straining / no airflow                 | Pump running with all valves closed (deadhead). Should be impossible; if you hear it, power off and check the relay wiring. |
| Rapid relay chatter                         | Cancel-and-replace race. Should be smooth click sequences only. |
| Pump turns off and immediately on again     | Bleed window not respected. Should always be at least 3 s between off and on. |
| No greeting beep on power-up                | Buzzer wiring or MicroPython boot issue.   |
