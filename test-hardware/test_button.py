# Importing necessary libraries for hardware control and asynchronous operations
from machine import Pin
import time

PIN_BUTTON = Pin(16, Pin.IN, Pin.PULL_UP)  # Button pin, set as input with pull-up resistor.
PIN_PUMP = Pin(4, Pin.OUT)  # Pump controll pin.

# Initial states
PIN_PUMP.value(0)
print("Initial state: Pump is OFF")

# Function to toggle the relay
def toggle_relay():
    state = PIN_PUMP.value()  # Toggle the state
    PIN_PUMP.value(not state)  # Update relay pin
    if state:
        print("Pump is now ON")
    else:
        print("Pump is now OFF")

# Main loop
try:
    while True:
        if PIN_BUTTON.value() == 0:  # Button is pressed (value is LOW with pull-up)
            print("Button pressed!")
            toggle_relay()  # Toggle the relay
            time.sleep(0.3)  # Debounce delay
        time.sleep(0.05)  # Small delay to avoid busy looping
except KeyboardInterrupt:
    print("Program stopped")
