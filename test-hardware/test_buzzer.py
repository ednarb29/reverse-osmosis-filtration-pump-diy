from machine import Pin, PWM
import time

# Pin-Setup
BUZZER_PIN = 15  # GPIO-Pin, an den der Buzzer angeschlossen ist
buzzer = PWM(Pin(BUZZER_PIN))  # PWM-Objekt erstellen

def play_tone(frequency, duration):
    """
    Plays a tone with a given frequency (Hz) and duration (s).
    """
    buzzer.freq(frequency)  # Set the frequency
    buzzer.duty_u16(32768)  # 50% Duty Cycle (Mean fo 16-Bit-Value: 0 bis 65535)
    time.sleep_ms(duration*1000)  # Play sound for duration
    buzzer.duty_u16(0)  # Turn buzzer off

# Hauptprogramm
try:
    while True:
        print("Buzzer spielt 2 kHz für 1 Sekunde")
        play_tone(2000, 1000)  # 2 kHz für 1 Sekunde
        time.sleep(1)  # Pause

        print("Buzzer spielt 1,5 kHz für 1 Sekunde")
        play_tone(1800, 1000)  # 1,5 kHz für 1 Sekunde
        time.sleep(1)  # Pause

        print("Buzzer spielt 1,5 kHz für 1 Sekunde")
        play_tone(1500, 1000)  # 1,5 kHz für 1 Sekunde
        time.sleep(1)  # Pause

except KeyboardInterrupt:
    print("Programm beendet")
    buzzer.deinit()  # PWM deaktivieren
