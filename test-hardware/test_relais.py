# Importing necessary libraries for hardware control and asynchronous operations
from machine import Pin
import time

# GPIO pin setup for various components connected to the microcontroller.
PIN_BUZZER = Pin(15, Pin.OUT)  # Buzzer pin, set as output.
PIN_BUTTON = Pin(16, Pin.IN, Pin.PULL_UP)  # Button pin, set as input with pull-up resistor.

# Pins for controlling valves or other actuators.
PIN_VALVE1 = Pin(0, Pin.OUT)  # Valve 1 control pin.
PIN_VALVE2 = Pin(1, Pin.OUT)  # Valve 2 control pin.
PIN_VALVE3 = Pin(2, Pin.OUT)  # Valve 3 control pin.
PIN_VALVE4 = Pin(3, Pin.OUT)  # Valve 4 control pin.

PIN_PUMP = Pin(4, Pin.OUT)  # Pump controll pin.

# Initialize and turn off all relays
PIN_VALVE1.value(1)
PIN_VALVE2.value(1)
PIN_VALVE3.value(1)
PIN_VALVE4.value(1)
PIN_PUMP.value(0)

# Toggle all relays one after another to check connections
while True:

     PIN_VALVE1.toggle()
     time.sleep(2)

     PIN_VALVE2.toggle()
     time.sleep(2)

     PIN_VALVE3.toggle()
     time.sleep(2)

     PIN_VALVE4.toggle()
     time.sleep(2)

     PIN_PUMP.toggle()
     time.sleep(2)