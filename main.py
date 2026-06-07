import time
import csv
import board
import busio
import serial
import pynmea2
from datetime import datetime
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_ads1x15 import ads1x15

i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS1115(i2c)

channels = {
    "Seat 1": AnalogIn(ads, ads1x15.Pin.A0),
    "Seat 2": AnalogIn(ads, ads1x15.Pin.A1),
    "Seat 3": AnalogIn(ads, ads1x15.Pin.A2),
    "Seat 4": AnalogIn(ads, ads1x15.Pin.A3),
}

THRESHOLD = 0.15
previous_states = {name: False for name in channels}
LOG_FILE = "occupancy_log.csv"

def read_gps(port="/dev/ttyS0", baudrate=9600):
    try:
        with serial.Serial(port, baudrate=baudrate, timeout=1) as gps:
            for _ in range(10):
                line = gps.readline().decode("ascii", errors="replace").strip()
                if line.startswith("$GPRMC") or line.startswith("$GPGGA"):
                    try:
                        msg = pynmea2.parse(line)
                        if hasattr(msg, "latitude") and msg.latitude:
                            return msg.latitude, msg.longitude
                    except pynmea2.ParseError:
                        pass
    except serial.SerialException:
        pass
    return None, None

def log_to_csv(timestamp, lat, lon, states, readings):
    file_exists = False
    try:
        with open(LOG_FILE, "r") as f:
            file_exists = True
    except FileNotFoundError:
        pass

    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "timestamp", "latitude", "longitude",
                "seat1_status", "seat1_voltage",
                "seat2_status", "seat2_voltage",
                "seat3_status", "seat3_voltage",
                "seat4_status", "seat4_voltage",
            ])
        writer.writerow([
            timestamp,
            lat if lat is not None else "",
            lon if lon is not None else "",
            "OCCUPIED" if states["Seat 1"] else "empty", readings["Seat 1"],
            "OCCUPIED" if states["Seat 2"] else "empty", readings["Seat 2"],
            "OCCUPIED" if states["Seat 3"] else "empty", readings["Seat 3"],
            "OCCUPIED" if states["Seat 4"] else "empty", readings["Seat 4"],
        ])

print("Monitoring seat occupancy...")
print(f"Logging to: {LOG_FILE}")

while True:
    readings = {name: ch.voltage for name, ch in channels.items()}
    current_states = {name: v > THRESHOLD for name, v in readings.items()}

    if current_states != previous_states:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lat, lon = read_gps()
        gps_str = f"{lat:.6f}, {lon:.6f}" if lat is not None else "no fix"

        print(f"\n[{timestamp}] Occupancy change detected:")
        print(f"  GPS: {gps_str}")
        print("-" * 40)
        for name in channels:
            status = "OCCUPIED" if current_states[name] else "empty   "
            print(f"  [{status}] {name}: {readings[name]:.3f} V")

        log_to_csv(timestamp, lat, lon, current_states, readings)
        print(f"  Logged to {LOG_FILE}")

        previous_states = current_states.copy()

    time.sleep(0.4)
