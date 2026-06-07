import time
import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_ads1x15 import ads1x15

# Initialize I2C and ADS1115
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS1115(i2c)
channel = AnalogIn(ads, ads1x15.Pin.A0)

# Set a minimum voltage threshold to trigger a "press"
# Adjust this value based on your circuit's ambient noise
THRESHOLD = 0.15 

print("Waiting for pressure on the FSR sensor...")

while True:
    voltage = channel.voltage
    raw_value = channel.value
    
    # Only process data if voltage is above our threshold
    if voltage > THRESHOLD:
        print(f"[PRESSED] Voltage: {voltage:.3f} V | Raw: {raw_value}")
        
        # Insert your taxi logic here (e.g., start a meter, register a passenger)
        
    time.sleep(0.1)  # Quick check every 100ms

