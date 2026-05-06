# Reverse Osmosis Filtration System Control for Raspberry Pi Pico

## Program Summary

This script is designed for a Raspberry Pi Pico running [MicroPython](https://micropython.org/) 
(yet should be compatible with other platforms running MicroPython), 
with the goal of controlling a set of 4 valves and a pump for a reverse osmosis filtration system. 
The system is controlled with one button and offers the following main features:

- Automatic flushing of the osmosis membrane every few hours to prevent germ development in the filters.
- Automatic disposal of the first filtered water (which contains more particles due to the lowered pressure in the osmosis membrane during idle time).
- Setting a fixed time interval for water filtration to yield a specific amount of water, which can be stored via a long button press.
- Deferred membrane post-flush — the user gets their water immediately and the post-flush runs in the background a configurable time later (useful for camper / mobile setups where you want to power down quickly).
- Manual mode (entered via double-tap) for direct pump on/off toggling without any pre/post-flush ramp — used for the manufacturer's disinfection procedure where 150–200 ml of water needs to be pushed through after injecting hydrogen peroxide.

The script is structured to be asynchronous, allowing it to handle multiple operations efficiently without blocking the main execution flow.

My final system looked like shown in the following two images:

![DIY reverse osmosis system with automatization features](images/IMG_4790.jpeg)

![DIY reverse osmosis system with automatization features](images/IMG_4791.jpeg)

![DIY reverse osmosis system with automatization features](images/IMG_4792.jpeg)

![DIY reverse osmosis system with automatization features](images/IMG_4793.jpeg)


## Schema

Here is the overview of how the valves are used in the filtration process. (The valve numbering is from the original repository and changed in my code - see pictures above.)

![Schema of the DIY reverse osmosis system with automatization features](images/schema.png)


## Hardware parts

For the full system, I used the following hardware parts:
- A reverse osmosis system such as the [Aquamichel Mini](https://www.lebendiges-trinkwasser.shop/shop/aquamichel-mini-teileset/)
- [A self-priming pump 24V](https://www.lebendiges-trinkwasser.shop/shop/pumpe-selbstsaugend-24v-dc/)
- A [pressure gauge](https://www.tooler.de/catalog/product/view/id/263682/) or [this pressure gauge](https://fittingstore.de/products/einbaumanometer-mit-dreikant-frontring-waagerecht) and other connectors for the pump threads etc.
- 24V power supply - I used the [24V 3A Power Supply AveyLum Power](https://amzn.eu/d/cPehZDK)
- A portable box for the whole system to carry and use in a camper etc - I used the [Eurobox NextGen Portable Transport Case, 400 x 300 x 185 mm](https://amzn.eu/d/fMdq8dy)


- Raspberry Pi Pico (or other platform running MicroPython) - I used [Ingcool Pre-soldered Raspberry Pi Pico Board](https://amzn.eu/d/3YGQunV)
- 4 valves for controlling water flow - I used [Solenoid Valve 1/4" DC 24V N/C Normally Closed](https://amzn.eu/d/3zT5nzD) by Gredia.
- Relais module for controlling the valves - I used the [4 channel DC 5V relais module](https://amzn.eu/d/0UkmHZb) by ELEGOO.
- Relais module for controlling the pump - I used the [1-relay, 5V, KY-019 Parent relay](https://amzn.eu/d/h1QWOz9) by AZDelivery.
- Button for user interaction - I used a [simple button](https://amzn.eu/d/iUaOajc).
- Buzzer for audio feedback - I used the [KY-006 Passive Piezo Buzzer](https://amzn.eu/d/e9L0oB6) by AZDelivery.
- DC-DC Step-down converter module to provide the correct voltage for the Raspberry Pi Pico (taking it from the 24V power supply) - I used the [LM2596S DC-DC Power Supply Adapter Step Down](https://amzn.eu/d/2kVXOn0) by AZDelivery.
- A Raspberry Pi Pico Screw Expansion Board - I used the [GPIO Expansion Board](https://amzn.eu/d/49239PA).
- A suitable case - I used the waterproofed [Transparent 200 x 120 x 56 Industrial Housing IP66](https://amzn.eu/d/aowSbms) along with a thin wooden plate on which I could mount the modules to with screws.
- [1/4" tubes and connectors](https://amzn.eu/d/1vY9WBC).

## Configuration

The script uses a configuration file (`config.json`) for various timing operations. 
You can modify these settings in the configuration file to adapt the system to your specific requirements. 
The file is created if it does not exist. It is persistently stored on the Raspberry Pi Pico.

The file contains the following parameters:
- `pre_flush_sec`: Time in seconds for the pre-flush operation of the membrane.
- `post_flush_sec`: Time in seconds for the post-flush operation of the membrane.
- `long_flush_sec`: Time in seconds for the long-flush operation (default 15 minutes), triggered by a super-long button press.
- `disposal_sec`: Time in seconds for the disposal operation of the first filtered water.
- `filter_sec`: Time in seconds for the filter operation.
- `auto_flush_sec`: Time in seconds between automatic flushing (Default 8 hours).
- `water_clean_sec`: Time in seconds within which a follow-up filtration skips the pre-flush.
- `deferred_post_flush_sec`: Delay in seconds between a filter cycle ending and the membrane post-flush running in the background. Default 180 (3 minutes) for stationary use. For portable / camper use where you want to power down shortly after filtering, lower this (e.g. 15) so the post-flush completes sooner.
- `buzzer_frequency`: Frequency in Hz for the buzzer tone.
- `pump_switch_delay`: Time in milliseconds to delay pump switch actions before/after valves.
- `inlet_bleed_ms`: Time in milliseconds to leave the non-inlet valves open after the pump stops, so membrane back-pressure can bleed through V2 to the drain before all valves close. Default 5000 (5 s). Increase if you hear residual pressure on the next cycle's first valve open.

## Usage

To use the script:

1. Ensure you have a Raspberry Pi Pico connected to the necessary hardware components (valves, button, buzzer, pump).
2. Upload the script to your Raspberry Pi Pico running MicroPython.
3. Optionally: Adapt the configuration with your desired timing settings.
4. The system will perform automatic flushing, water disposal, and filtration based on your configuration.

## Button Controls

A printable quick-reference is in [docs/button_reference.md](docs/button_reference.md).

Four press gestures are recognised:

- **Short press** (< 0.8 s)
- **Long press** (0.8 s – 5 s)
- **Super-long press** (≥ 5 s)
- **Double-tap** (two short presses within 600 ms)

When the system is idle:
- **Short press:** Initiates water filtration for the configured duration.
- **Long press:** Initiates a long water filtration (1 hour).
- **Super-long press:** Initiates a long flush of the membrane (`long_flush_sec`, default 15 minutes). Useful after replacing the membrane or pre-filter stages.
- **Double-tap:** Enters **manual mode** — see below.

During filtration:
- **Short press:** Stops the filtration process.
- **Long press:** Stops the filtration process and saves the elapsed filtration time as the new filtration interval to the configuration file (clamped to 30 s – 1 h).
- **Super-long press:** Stops the filtration and starts a long flush.

During the auto-injected **pre-flush** before a filter cycle (the brief flush + disposal phase that runs before filtering when the membrane has been idle):
- **Short press:** Skips the pre-flush and goes straight to filtration.
- **Long press:** Skips the pre-flush and starts a 1-hour filtration.
- **Super-long press:** Cancels and starts a long flush.

During a standalone flush (an automatic flush or a long-flush you started with super-long press):
- **Short press:** Cancels the flush. No follow-on cycle.
- **Long press:** Cancels the flush. No follow-on cycle.
- **Super-long press:** Cancels and starts a fresh long flush.

### Manual mode (double-tap from idle)

Manual mode gives you direct toggle control of the pump and is intended for the disinfection procedure (steps 2 and 4 from the Aquamichel handbook), where you need to push 150–200 ml through the system after each H₂O₂ injection.

While in manual mode:
- **Short press:** Toggles the pump on/off in filter configuration. **No pre-flush, no post-flush, no deferred work.** The pump just runs while it's on.
- **Long press:** Exits manual mode (pump shuts off and valves close cleanly first).
- The auto-flush timer is paused — useful for the 1-hour H₂O₂ soak step where you don't want a background flush to fire.

### Deferred post-flush

After every filter cycle the membrane post-flush is **scheduled for later** (default `deferred_post_flush_sec` = 180 s, configurable). The pump shuts off and valves close immediately so you can take your water; a short while later the system runs its post-flush in the background. If you start a new cycle before the post-flush fires, the deferred task is cancelled and the new cycle takes over.

For portable / camper-van use, set `deferred_post_flush_sec` to a small value (e.g. 15) in `config.json` so you don't have to wait around to power down.

## Process flow

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

The diagram source lives at [docs/flowchart.md](docs/flowchart.md). A pre-rendered PNG is at [images/flowchart.png](images/flowchart.png) — regenerate it after any change with:

```bash
npx -p @mermaid-js/mermaid-cli mmdc -i docs/flowchart.md -o images/flowchart.png -b transparent
```

## License

This project is licensed under the GNU Public License v3 - see the [LICENSE](LICENSE) file for details.
