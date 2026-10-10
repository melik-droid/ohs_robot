import random
import threading
from datetime import datetime, timezone

from config.settings import TOPIC_PPE_VIOLATION, PPE_PUBLISH_INTERVAL
from mqtt.client_base import MQTTClientBase
from utils.logger import get_logger


class PPEDetectionStub:
    def __init__(self, mqtt_client: MQTTClientBase):
        self._client = mqtt_client
        self._logger = get_logger("mod01.ppe")
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="mod01-ppe", daemon=True
        )
        self._thread.start()
        self._logger.info("[MOD-01] PPEDetectionStub started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        self._logger.info("[MOD-01] PPEDetectionStub stopped")

    def _loop(self):
        while not self._stop_event.wait(PPE_PUBLISH_INTERVAL):
            self._publish_violation()

    def _publish_violation(self):
        payload = {
            "class": random.choice(["no_helmet", "no_vest", "no_goggles"]),
            "confidence": round(random.uniform(0.50, 0.99), 4),
            "bounding_box": [
                random.randint(0, 400),
                random.randint(0, 300),
                random.randint(400, 640),
                random.randint(300, 480),
            ],
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        self._logger.info(
            "[MOD-01][PUBLISH] PPE violation: class=%s confidence=%.4f",
            payload["class"], payload["confidence"],
        )
        self._client.publish(TOPIC_PPE_VIOLATION, payload, qos=0)
