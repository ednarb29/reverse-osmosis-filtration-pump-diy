# Controller process flow

This is the source of truth for the process-flow diagram embedded in the
[README](../README.md). Edit it here, paste the rendered version into the README,
or convert to PNG with the Mermaid CLI:

```bash
npx -p @mermaid-js/mermaid-cli mmdc -i docs/flowchart.md -o images/flowchart.png
```

## Top-level flow

```mermaid
flowchart TD
    Boot([Boot]) --> Init[init: pump OFF, valves CLOSED, load config.json]
    Init --> Greet[greeting beeps]
    Greet --> WDT[arm watchdog]
    WDT --> Idle((Idle))

    Idle -->|short press| FilterCheck{water_clean_sec<br/>elapsed?}
    Idle -->|long press| LongFilter[1-hour filter]
    Idle -->|super-long| LongFlush[15-min long flush]
    Idle -->|double-tap| Manual((Manual<br/>idle))
    Idle -.->|auto_flush_sec<br/>elapsed| AutoFlush[auto-flush:<br/>pre-flush + disposal + post-flush]

    FilterCheck -->|yes| PreFlush[pre-flush + disposal]
    FilterCheck -->|no| Filter
    PreFlush --> Filter[filter for filter_sec]
    LongFilter --> Filter

    Filter --> FinishBeeps[finish beeps]
    FinishBeeps --> CleanShut[clean shutdown:<br/>pump OFF → bleed → valves CLOSED]
    CleanShut --> SchedDeferred[schedule deferred<br/>post-flush]
    SchedDeferred --> Idle

    LongFlush --> CleanShutLF[clean shutdown]
    CleanShutLF --> Idle

    AutoFlush --> CleanShutAF[clean shutdown]
    CleanShutAF --> Idle

    SchedDeferred -.->|wait deferred_post_flush_sec| DeferredFlush[membrane post-flush]
    DeferredFlush --> CleanShutDP[clean shutdown]
    CleanShutDP --> Idle

    Manual -->|short press| ManualOn[pump ON,<br/>filter valves]
    ManualOn -->|short press| ManualOff[pump OFF,<br/>clean shutdown]
    ManualOff --> Manual
    Manual -->|long press| Idle
    ManualOn -.->|long press| ExitManual[clean shutdown]
    ExitManual --> Idle

    classDef state fill:#e8f5e9,stroke:#388e3c
    classDef action fill:#fff9c4,stroke:#f9a825
    classDef cleanup fill:#fce4ec,stroke:#c2185b
    class Idle,Manual state
    class PreFlush,Filter,LongFilter,LongFlush,AutoFlush,DeferredFlush,ManualOn action
    class CleanShut,CleanShutLF,CleanShutAF,CleanShutDP,ManualOff,ExitManual cleanup
```

Legend:

- **Green nodes** — resting states (idle, manual idle).
- **Yellow nodes** — operating phases (pump on, water moving).
- **Pink nodes** — clean-shutdown phases (pump off, valves bleeding then closing).
- **Solid arrows** — user-initiated transitions.
- **Dashed arrows** — timer-driven transitions (auto-flush timer, deferred post-flush timer, long-press exit from manual mode while pump is on).

## Pump/valve sequencing detail

Every cycle that runs the pump follows the same start/stop ordering invariants.
This subdiagram shows them explicitly because they're load-bearing for hardware
safety:

```mermaid
flowchart LR
    A[set valves to mode] --> B[wait pump_switch_delay]
    B --> C[set_pump True]
    C --> D[do work…]
    D --> E[set_pump False]
    E --> F[wait pump_switch_delay]
    F --> G[close inlet only<br/>V2 stays open as drain]
    G --> H[wait inlet_bleed_ms]
    H --> I[close all valves]
```

- Valves open BEFORE the pump turns on, never the other way around.
- The pump turns OFF before any valve change at the end.
- A bleed window (≥ pump_switch_delay + inlet_bleed_ms) sits between pump-OFF
  and all-valves-closed so residual pressure can escape through V2.
- This logic lives in `_clean_shutdown()` and is invoked from the `finally`
  block of every flow coroutine — cancellation cannot bypass it.
