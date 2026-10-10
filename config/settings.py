import os


MQTT_BROKER_HOST = "localhost"
MQTT_BROKER_PORT = 1883
MQTT_CLIENT_ID_PREFIX = "ohs_robot"

TOPIC_PPE_VIOLATION  = "ohs/ppe/violation"
TOPIC_ENV_HAZARD     = "ohs/env/hazard"
TOPIC_NAV_POSITION   = "ohs/nav/position"
TOPIC_NAV_WAYPOINT   = "ohs/nav/waypoint"
TOPIC_ROBOT_FEEDBACK = "ohs/robot/feedback"
TOPIC_ROBOT_COMMAND  = "ohs/robot/command"

PPE_PUBLISH_INTERVAL = 10   # seconds
ENV_PUBLISH_INTERVAL = 2    # seconds
NAV_PUBLISH_INTERVAL = 8    # seconds

WAYPOINTS = [
    {"id": 0, "x_m": 0.0, "y_m": 0.0},
    {"id": 1, "x_m": 2.0, "y_m": 0.0},
    {"id": 2, "x_m": 2.0, "y_m": 3.0},
    {"id": 3, "x_m": 0.0, "y_m": 3.0},
]
DWELL_MS = 3000

THRESHOLD_TEMP_C   = 60.0   # °C üstü tehlikeli
THRESHOLD_HUMIDITY = 85.0   # % üstü tehlikeli
THRESHOLD_GAS_PPM  = 400.0  # ppm üstü tehlikeli
THRESHOLD_NOISE_DB = 85.0   # dB üstü tehlikeli

# Raspberry Pi BCM pin numaraları
DHT22_PIN    = 4    # fiziksel pin 7
MQ135_DO_PIN = 17   # fiziksel pin 11
KY038_DO_PIN = 27   # fiziksel pin 13

SENSOR_PUBLISH_INTERVAL = 2.0  # saniye

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE_PATH = os.path.join(PROJECT_ROOT, "logs", "ohs_robot.log")
