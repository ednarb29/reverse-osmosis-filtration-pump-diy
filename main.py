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
from machine import Pin, PWM
import time
import uasyncio
import ujson

# Configuration values with default settings.
# These settings are used for various timing operations in the script and can be overridden by an external configuration file.
CONFIG_FILE = 'config.json'  # Name of the external configuration file.
CONFIG = {
    'pre_flush_sec': 10,        # Time in seconds for the pre-flush operation of the membrane. Default: 10s
    'post_flush_sec': 30,       # Time in seconds for the post-flush operation of the membrane. Default: 30s
    'long_flush_sec': 15 * 60,  # Time in seconds for the long-flush operation of the membrane. Default: 15 min
    'disposal_sec': 60,         # Time in seconds for the disposal operation of the first filtered water. Default: 60s
    'filter_sec': 12 * 60,      # Time in seconds for the filter operation. Default: 120s
    'auto_flush_sec': 8 * 60 * 60,  # Time in seconds between automatic flushing (Default 8 hours).
    'water_clean_sec': 5 * 60,      # Time in seconds for water cleaning operation. Default: 5 min
    'buzzer_frequency': 1500,       # Frequency in Hz for the buzzer tone. Default 2000 Hz
    'pump_switch_delay': 1000       # Time in milliseconds to delay pump switch actions before/after valves.
                                        # Default: 1000ms
}

# Configuration values only for testing
# CONFIG = {
#     'pre_flush_sec': 10,      # Time in seconds for the pre-flush operation of the membrane. Default: 10s
#     'post_flush_sec': 10,     # Time in seconds for the post-flush operation of the membrane. Default: 30s
#     'long_flush_sec': 15,     # Time in seconds for the long-flush operation of the membrane. Default: 15 min
#     'disposal_sec': 10,       # Time in seconds for the disposal operation of the first filtered water. Default: 60s
#     'filter_sec': 10,         # Time in seconds for the filter operation. Default: 120s
#     'auto_flush_sec': 60,         # Time in seconds between automatic flushing (Default 8 hours).
#     'water_clean_sec': 10,        # Time in seconds for water cleaning operation. Default: 5 min
#     'buzzer_frequency': 1000,     # Frequency in Hz for the buzzer tone. Default 2000 Hz
#     'pump_switch_delay': 1000     # Time in milliseconds to delay pump switch actions before/after valves.
#                                       # Default: 1000ms
# }

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

# last_flush stores the timestamp of the last automatic flush operation.
# Initial value of 0 indicates that no flush has occurred yet or the system is
# in its initial state.
last_flush = 0

# last_reflush tracks the timestamp of the last reflush operation.
# A reflush operation takes place after a first filtration interval. It flushes
# the system to allow for an extended period of immediate filtration when
# pressing the button. The initial zero value signifies that a reflush operation
# has not yet been performed since the system started or was reset.
last_reflush = 0

# last_filtering holds the timestamp of the last filtering operation.
# The script uses this to track the time since the last filtering action and to
# decide when to perform the next auto flushing.
last_filtering = 0

# start_filtering holds the timestamp of the last filter operation start.
# The script uses this to measure the filter duration length and to update the short button press filter duration.
start_filtering = 0

# running_task is initialized as a DummyTask() object.
# This object represents the current task that is running which can be queried
# to be finished (or ready) or not.
running_task = DummyTask()

# running_task_type is set to None, indicating that there is no current task type defined.
# This variable identifies the type of task currently being executed as string.
running_task_type = None


def read_config():
    """
    Reads configuration settings from an external JSON file.

    This function attempts to open and read a JSON file specified by the global variable CONFIG_FILE.
    If successful, it parses the JSON content into a Python dictionary and returns it. This allows
    the program to use externally defined configurations, providing flexibility and ease of adjustments
    without modifying the code.

    Returns:
        dict: A dictionary containing configuration settings. If the file reading fails (e.g., file not found),
        the function returns an empty dictionary as a fallback, ensuring the program continues to run with
        default settings.

    Exception Handling:
        OSError: This exception is caught to handle cases where the file might not exist or be accessible.
        Instead of crashing the program, the function silently passes the exception and returns an empty
        dictionary. This design choice prioritizes the program's continuous operation, but it may be worth
        logging such errors for debugging and maintenance purposes.
    """
    try:
        with open(CONFIG_FILE, 'r') as f:
            config_data = f.read()
            config = ujson.loads(config_data)
            return config
    except OSError:
        pass
    return {}


def write_config(config):
    """
    Writes the provided configuration settings to an external JSON file.

    This function takes a dictionary of configuration settings, converts it into a JSON string,
    and writes it to the file specified by the CONFIG_FILE global variable. This allows for
    persisting updated configurations externally, making them available for subsequent runs
    of the program or other related systems.

    Args:
        config (dict): A dictionary containing configuration settings to be written.
    """
    config_data = ujson.dumps(config)
    with open(CONFIG_FILE, 'w') as f:
        f.write(config_data)


def _set_valves(v1, v2, v3, v4):
    """
    Internal convenient function that controls the state of the 4 valves based on the arguments.

    Each parameter (v1, v2, v3, v4) corresponds to a specific valve and determines its state.
    The function uses the 'value' method of each PIN_VALVE object to set the state. Notably,
    the actual state is set to the logical NOT of the input parameters. This implies that a
    True value in any argument will turn OFF the corresponding valve, and a False will turn it ON.

    Args:
        v1, v2, v3, v4 (bool): Boolean values indicating the desired state of valves 1, 2, 3, and 4,
                               respectively. True to turn OFF the valve, False to turn it ON.
    """
    PIN_VALVE1.value(not v1)
    PIN_VALVE2.value(not v2)
    PIN_VALVE3.value(not v3)
    PIN_VALVE4.value(not v4)


def set_pump(p):
    """
    Internal convenient function that controls the state of the pump based on the argument.

    Each parameter (p1) corresponds to a specific pump and determines its state.
    The function uses the 'value' method of each PIN_PUMP object to set the state. Notably,
    the actual state is set to the logical NOT of the input parameters. This implies that a
    True value in any argument will turn OFF the corresponding pump, and a False will turn it ON.
    This relay acts to the opposite logic of the valve relays. So False indecates OFF, True indicates ON.

    Args:
        p (bool): Boolean values indicating the desired state of pump 1
                               False to turn OFF the pump, True to turn it ON.
    """
    print('  pump', 'ON' if p else 'OFF')
    PIN_PUMP.value(p)


def close_valves():
    """
    Closes all valves.

    This function calls the _set_valves function with all arguments set to False,
    effectively turning all the valves ON (closed state) as per the _set_valves logic.
    """

    if PIN_PUMP.value():
        print('Pump has not been turned off yet. Safety shut down!')
        PIN_PUMP.value(False)

    _set_valves(False, False, False, False)


def close_inlet_valve():
    """
    Closes the inlet valve and keeps other valves open do drain all remaining pressure from the system.
    """

    if PIN_PUMP.value():
        print('Pump has not been turned off yet. Safety shut down!')
        PIN_PUMP.value(False)

    _set_valves(False, True, False, False)


def set_valves_to_flush():
    """
    Configures valves for the flushing operation.

    This function sets the first two valves to an OFF (open) state and the last two valves
    to an ON (closed) state, tailored for the flushing process.
    """
    _set_valves(True, True, False, False)


def set_valves_to_disposal():
    """
    Sets valves configuration for the disposal operation.

    Adjusts the valve states specifically for disposing the filtered water. Here, valves 1
    and 3 are set to OFF (open), while valves 2 and 4 are ON (closed).
    """
    _set_valves(True, False, False, True)


def set_valves_to_filter():
    """
    Configures the valves for the filtering process.

    For the filtering operation, this function opens valves 1 and 4 (setting them to OFF),
    while closing valves 2 and 3 (setting them to ON).
    """
    _set_valves(True, False, True, False)


def init():
    """
    Initializes the system by turning the pump off, setting valves to a closed state and loading configuration settings.

    The function outputs messages to indicate the progress of these actions, aiding in debugging and
    monitoring the initialization process.
    """
    print('Set valves to be closed and pump to be turned OFF.')
    set_pump(False)
    close_valves()
    CONFIG.update(read_config())
    print('config read: {}'.format(CONFIG))


async def greeting_beeps():
    """
    Plays a sequence of 1x short beep and 1x long beep as a greeting.
    """
    BUZZER.freq(CONFIG['buzzer_frequency'])  # Set the frequency
    BUZZER.duty_u16(32768)  # Turn buzzer on with 50% Duty Cycle (Mean fo 16-Bit-Value: 0 bis 65535)
    await uasyncio.sleep(0.1)
    BUZZER.duty_u16(0)  # Turn buzzer off
    await uasyncio.sleep(0.1)
    BUZZER.duty_u16(32768)  # Turn buzzer on with 50% Duty Cycle (Mean fo 16-Bit-Value: 0 bis 65535)
    await uasyncio.sleep(0.5)
    BUZZER.duty_u16(0)  # Turn buzzer off


async def finish_beeps():
    """
    Plays a sequence of 3x long beeps to indicate completion.
    """
    BUZZER.freq(CONFIG['buzzer_frequency'])  # Set the frequency
    BUZZER.duty_u16(32768)  # Turn buzzer on with 50% Duty Cycle (Mean fo 16-Bit-Value: 0 bis 65535)
    await uasyncio.sleep(0.4)
    BUZZER.duty_u16(0)  # Turn buzzer off
    await uasyncio.sleep(0.2)
    BUZZER.duty_u16(32768)  # Turn buzzer on with 50% Duty Cycle (Mean fo 16-Bit-Value: 0 bis 65535)
    await uasyncio.sleep(0.4)
    BUZZER.duty_u16(0)  # Turn buzzer off
    await uasyncio.sleep(0.2)
    BUZZER.duty_u16(32768)  # Turn buzzer on with 50% Duty Cycle (Mean fo 16-Bit-Value: 0 bis 65535)
    await uasyncio.sleep(0.4)
    BUZZER.duty_u16(0)  # Turn buzzer off


async def short_beep():
    """
    Emits a short beep after a short button press.
    """
    BUZZER.freq(CONFIG['buzzer_frequency'])  # Set the frequency
    BUZZER.duty_u16(32768)  # Turn buzzer on with 50% Duty Cycle (Mean fo 16-Bit-Value: 0 bis 65535)
    await uasyncio.sleep(0.2)
    BUZZER.duty_u16(0)  # Turn buzzer off


async def long_beep():
    """
    Emits a long beep after a long button press.
    """
    BUZZER.freq(CONFIG['buzzer_frequency'])  # Set the frequency
    BUZZER.duty_u16(32768)  # Turn buzzer on with 50% Duty Cycle (Mean fo 16-Bit-Value: 0 bis 65535)
    await uasyncio.sleep(0.5)
    BUZZER.duty_u16(0)  # Turn buzzer off


async def super_long_beep():
    """
    Emits a long beep after a long button press.
    """
    BUZZER.freq(CONFIG['buzzer_frequency'])  # Set the frequency
    BUZZER.duty_u16(32768)  # Turn buzzer on with 50% Duty Cycle (Mean fo 16-Bit-Value: 0 bis 65535)
    await uasyncio.sleep(1)
    BUZZER.duty_u16(0)  # Turn buzzer off


async def auto_flush_filter():
    """
    Asynchronous function to perform an auto flushing operation of the filtration system.

    This function manages the process of flushing the osmosis membrane and dispose filtered water.
    It controls the valves' states to facilitate these operations and uses asynchronous sleeping to
    maintain them for configured durations. The operation timestamps and task types are updated accordingly.

    The function uses global variables 'last_flush' and 'running_task_type' to track the time of the last
    flush and the current type of task being executed, respectively.
    """

    # Print the operation's starting message and set the current task type.
    print('auto_flush_filter')
    global last_flush, running_task_type
    running_task_type = 'FLUSHING'        # Update the task type to 'FLUSHING'.

    try:
        # Start the flushing process of the osmosis membrane.
        print('  pre-flush osmose membrane (' + str(CONFIG['pre_flush_sec']) + 's)')
        set_valves_to_flush()
        await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])
        set_pump(True)
        await uasyncio.sleep(CONFIG['pre_flush_sec'])

        # Dispose filtered water.
        print('  dispose filtered water (' + str(CONFIG['disposal_sec']) + 's)')
        set_valves_to_disposal()
        await uasyncio.sleep(CONFIG['disposal_sec'])

        # Finish with flushing process of the osmosis membrane.
        print('  post-flush osmose membrane (' + str(CONFIG['post_flush_sec']) + 's)')
        set_valves_to_flush()
        await uasyncio.sleep(CONFIG['post_flush_sec'])

        set_pump(False)
        await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])

        print('  closing inlet valve!')
        close_inlet_valve()
        await uasyncio.sleep_ms(2000)

        print('  closing valves!')
        close_valves()
        print('\n')

    finally:
        # Update the timestamp of the last flush and reset the valves to their closed state.
        last_flush = time.time()


async def pre_flush_filter():
    """
    Asynchronous function to perform a pre-flushing operation of the filtration system.

    This function manages the process of flushing the osmosis membrane and dispose filtered water before filtering.
    It controls the valves' states to facilitate these operations and uses asynchronous sleeping to
    maintain them for configured durations. The operation timestamps and task types are updated accordingly.

    The function uses global variables 'last_flush' and 'running_task_type' to track the time of the last
    flush and the current type of task being executed, respectively.
    """

    # Print the operation's starting message and set the current task type.
    global last_flush, running_task_type
    running_task_type = 'FLUSHING'        # Update the task type to 'FLUSHING'.

    try:
        # Start the flushing process of the osmosis membrane.
        print('  pre-flush osmose membrane (' + str(CONFIG['pre_flush_sec']) + 's)')
        set_valves_to_flush()
        await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])
        set_pump(True)
        await uasyncio.sleep(CONFIG['pre_flush_sec'])

        # Dispose filtered water.
        print('  dispose filtered water (' + str(CONFIG['disposal_sec']) + 's)')
        set_valves_to_disposal()
        await uasyncio.sleep(CONFIG['disposal_sec'])

    finally:
        # Continue to the filtration process.
        pass


async def post_flush_filter():
    """
    Asynchronous function to perform a flushing operation of the filtration system after filtering water.

    This function manages the process of flushing the osmosis membrane after filtering water.
    It controls the valves' states to facilitate these operations and uses asynchronous sleeping to
    maintain them for configured durations. The operation timestamps and task types are updated accordingly.

    The function uses global variables 'last_flush' and 'running_task_type' to track the time of the last
    flush and the current type of task being executed, respectively.
    """

    # Print the operation's starting message and set the current task type.
    global last_flush, running_task_type
    running_task_type = 'FLUSHING'        # Update the task type to 'FLUSHING'.

    try:
        # Start the flushing process of the osmosis membrane.
        print('  post-flush osmose membrane (' + str(CONFIG['post_flush_sec']) + 's)')
        set_valves_to_flush()
        await uasyncio.sleep(CONFIG['post_flush_sec'])

    finally:
        # Update the timestamp of the last flush and reset the valves to their closed state.
        last_flush = time.time()


async def long_flush_filter():
    """
    Asynchronous function to perform a long flushing operation of the filtration system, e.g. after exchanging
    the membrane and pre-filter stages.

    This function manages the process of flushing the osmosis membrane longer.
    It controls the valves' states to facilitate these operations and uses asynchronous sleeping to
    maintain them for configured durations. The operation timestamps and task types are updated accordingly.

    The function uses global variables 'last_flush' and 'running_task_type' to track the time of the last
    flush and the current type of task being executed, respectively.
    """

    # Print the operation's starting message and set the current task type.
    global last_flush, running_task_type
    running_task_type = 'FLUSHING'        # Update the task type to 'FLUSHING'.

    try:
        # Start the flushing process of the osmosis membrane.
        print('  long-flush osmose membrane (' + str(CONFIG['long_flush_sec']) + 's)')
        set_valves_to_flush()
        await uasyncio.sleep(CONFIG['long_flush_sec'])

    finally:
        # Update the timestamp of the last flush and reset the valves to their closed state.
        last_flush = time.time()


async def filter_water(duration_sec=None):
    """
    Asynchronous function to perform water filtering.

    Initiates the water filtering process with a specified duration. If the duration is not provided,
    it defaults to a value from the configuration. The function also checks if a membrane flush is needed
    before starting the filtering. It updates global tracking variables and handles the valve states for filtering.

    Args:
        duration_sec (int, optional): The duration for which the water should be filtered. Defaults to None,
                                      in which case it uses the 'filter_sec' value from CONFIG.
    """
    global last_filtering, start_filtering, running_task_type
    # print('  Start filtering')

    # Determine the filtering duration based on the provided argument or default configuration.
    if duration_sec is None:
        duration_sec = CONFIG['filter_sec']

    # Check if flushing the membrane is required before filtering.
    flush_needed = time.time() - max(last_flush, last_filtering) > CONFIG['water_clean_sec']
    if flush_needed:
        await pre_flush_filter()

    # Execute the filtering process.
    try:
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
        # Update the timestamp of the last filtering and reset the valves to their closed state.
        await post_flush_filter()

        set_pump(False)
        await uasyncio.sleep_ms(CONFIG['pump_switch_delay'])

        print('  closing inlet valve!')
        close_inlet_valve()
        await uasyncio.sleep_ms(2000)

        print('  closing valves!')
        close_valves()
        last_filtering = time.time()
        print('\n')


def is_button_pressed():
    """
    Check if the button is pressed.

    Returns:
        bool: True if the button is pressed (LOW state), False otherwise.
    """
    return PIN_BUTTON.value() == 0


async def handle_button():
    """
    First main loop for handling button press events.
    """
    global running_task
    while True:
        # wait for the button to be pressed
        while not is_button_pressed():
            await uasyncio.sleep_ms(50)

        # wait for the button to be released
        ms_start = time.ticks_ms()
        while is_button_pressed():
            await uasyncio.sleep_ms(50)
        ms_end = time.ticks_ms()
        ms_duration = ms_end - ms_start

        # do the beep
        super_long_pressed = ms_duration >= 5000
        long_pressed = 800 < ms_duration < 5000
        if super_long_pressed:
            print('Super long button press')
            await super_long_beep()
        elif long_pressed:
            print('Long button press')
            await long_beep()
        else:
            print('Short button press')
            await short_beep()

        # decide upon the action
        if not running_task.done():  # running tasks exists
            print('\n')
            print('Cancel task {}'.format(running_task_type))
            running_task.cancel()  # the running task is always canceled

            if super_long_pressed:
                print('  long flushing')
                running_task = event_loop.create_task(long_flush_filter())
            elif long_pressed and running_task_type == 'FILTERING':
                # save the new time interval for filtering
                CONFIG['filter_sec'] = time.time() - start_filtering
                write_config(CONFIG)
                print('  save new time interval: {}'.format(CONFIG['filter_sec']))
            elif long_pressed and running_task_type == 'FLUSHING':
                # filter directly the water for a long time
                print('  cancel flush and long filter')
                running_task = event_loop.create_task(filter_water(60 * 60))
            elif running_task_type == 'FLUSHING':
                # filter directly the water
                print('  cancel flush and filter')
                running_task = event_loop.create_task(filter_water())

        else:  # no running tasks - the system is idle
            if super_long_pressed:  # long flushing the membrane
                running_task = event_loop.create_task(long_flush_filter())
                print('  long flushing')
            elif long_pressed:  # long filter water
                running_task = event_loop.create_task(filter_water(60 * 60))
                print('  long filtering')
            else:  # short filter water
                running_task = event_loop.create_task(filter_water())
                print('  filtering')


async def check_auto_flush():
    """
    Second main loop to control automatic flush operations of the system.
    """
    global last_flush, last_reflush, running_task
    while True:
        await uasyncio.sleep(1)
        if not running_task.done():
            # don't do any flushing if a task is running
            # ... the program should never come to this point here ;)
            continue

        # check whether we need to do some auto-flushing
        t = time.time()
        auto_flush_needed = t - max(last_flush, last_filtering) > CONFIG['auto_flush_sec']
        if auto_flush_needed:
            print('AUTO FLUSHING')
            running_task = event_loop.create_task(auto_flush_filter())


# init and run all co-routines
init()
event_loop = uasyncio.get_event_loop()
event_loop.run_until_complete(greeting_beeps())
event_loop.create_task(handle_button())
event_loop.create_task(check_auto_flush())
event_loop.run_forever()
