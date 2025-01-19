from machine import Pin
import uasyncio
import utime

# settings
led = Pin(25, Pin.OUT)
button = Pin(16, Pin.IN, Pin.PULL_UP)

# coroutine: blink on a timer
async def blink(delay):
    while True:
        led.toggle()
        await uasyncio.sleep(delay)

# coroutine: only return on button press
async def wait_button():
    button_prev = button.value()
    timestamp = utime.ticks_ms()
    while (button.value() == 1) or (button.value() == button_prev):
        button_prev = button.value()
        await uasyncio.sleep(0.04)

# coroutine: entry point for asyncio program
async def main():

    # start coroutine as a task and immediately return
    uasyncio.create_task(blink(0.5))

    # main loop
    while True:
        await wait_button()
        print("Pressed!")

# start event loop and run entry point coroutine
uasyncio.run(main())