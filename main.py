import os
import time
import csv
import json
import board
import busio
import serial
import pynmea2
import boto3
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
from awscrt import mqtt
from awsiot import mqtt_connection_builder
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_ads1x15 import ads1x15

# ── AWS IoT config ──────────────────────────────────────────
ENDPOINT   = "a2yp03pyp0asxs-ats.iot.eu-north-1.amazonaws.com"
CLIENT_ID  = "taxi-pi"
TOPIC      = "taxi/occupancy"
CERT       = "certs/78215a2780dd2b18e48d3a3bb39fcdbc372dbbdf8165ba6086a9680c9ef8d4a8-certificate.pem.crt"
KEY        = "certs/78215a2780dd2b18e48d3a3bb39fcdbc372dbbdf8165ba6086a9680c9ef8d4a8-private.pem.key"
CA         = "certs/AmazonRootCA1.pem"
# ── S3 config ───────────────────────────────────────────────
S3_BUCKET        = "taxi-pi"
S3_PREFIX        = "taxi-logs/"
S3_REGION        = "eu-north-1"
UPLOAD_INTERVAL  = 300                     # seconds (5 minutes)
# ────────────────────────────────────────────────────────────

csv_lock = threading.Lock()

i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS1115(i2c)

channels = {
    "Seat 1": AnalogIn(ads, ads1x15.Pin.A0),
    "Seat 2": AnalogIn(ads, ads1x15.Pin.A1),
    "Seat 3": AnalogIn(ads, ads1x15.Pin.A2),
    "Seat 4": AnalogIn(ads, ads1x15.Pin.A3),
}

THRESHOLD = 0.15
# Calibration: volts → weight in kg (adjust WEIGHT_PER_VOLT to your load cell)
WEIGHT_PER_VOLT = 50.0
previous_states = {name: False for name in channels}
LOG_FILE = "occupancy_log.csv"

def voltage_to_weight(voltage: float) -> int:
    """Convert ADC voltage to weight in kg (numeric 5,0)."""
    return max(0, round(voltage * WEIGHT_PER_VOLT))

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
    location = f"{lat:.6f},{lon:.6f}" if lat is not None else "no fix"
    with csv_lock:
        file_exists = os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["weight", "is_occupied", "time_recorded", "location"])
            for name in channels:
                writer.writerow([
                    voltage_to_weight(readings[name]),
                    states[name],
                    timestamp,
                    location,
                ])

def publish_to_aws(mqtt_conn, timestamp, lat, lon, states, readings):
    location = f"{lat:.6f},{lon:.6f}" if lat is not None else "no fix"
    payload = {
        "seats": [
            {
                "weight": voltage_to_weight(readings[name]),
                "is_occupied": states[name],
                "time_recorded": timestamp,
                "location": location,
            }
            for name in channels
        ]
    }
    mqtt_conn.publish(
        topic=TOPIC,
        payload=json.dumps(payload),
        qos=mqtt.QoS.AT_LEAST_ONCE,
    )
    print(f"  Published to AWS IoT: {TOPIC}")

def upload_csv_to_s3():
    with csv_lock:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
            try:
                s3 = boto3.client("s3", region_name=S3_REGION)
                key = f"{S3_PREFIX}{datetime.now().strftime('%Y%m%d_%H%M%S')}_occupancy.csv"
                s3.upload_file(LOG_FILE, S3_BUCKET, key)
                os.remove(LOG_FILE)
                print(f"  Uploaded CSV to s3://{S3_BUCKET}/{key} and deleted local copy.")
            except Exception as e:
                print(f"  S3 upload failed: {e}")

    next_upload = threading.Timer(UPLOAD_INTERVAL, upload_csv_to_s3)
    next_upload.daemon = True
    next_upload.start()

first_upload = threading.Timer(UPLOAD_INTERVAL, upload_csv_to_s3)
first_upload.daemon = True
first_upload.start()

# Connect to AWS IoT
print("Connecting to AWS IoT Core...")
mqtt_conn = mqtt_connection_builder.mtls_from_path(
    endpoint=ENDPOINT,
    cert_filepath=CERT,
    pri_key_filepath=KEY,
    ca_filepath=CA,
    client_id=CLIENT_ID,
)
connect_future = mqtt_conn.connect()
connect_future.result()
print("Connected to AWS IoT Core.")

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
        publish_to_aws(mqtt_conn, timestamp, lat, lon, current_states, readings)

        previous_states = current_states.copy()

    time.sleep(0.4)
