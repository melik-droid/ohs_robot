import random
import threading
import time
from datetime import datetime, timezone

from config.settings import (
    TOPIC_NAV_POSITION,
    TOPIC_NAV_WAYPOINT,
    TOPIC_ROBOT_FEEDBACK,
    TOPIC_ROBOT_COMMAND,
    WAYPOINTS,
    DWELL_MS,
)
from mqtt.client_base import MQTTClientBase
from utils.logger import get_logger

_STATE_IDLE    = "IDLE"
_STATE_MOVING  = "MOVING"
_STATE_DWELLING = "DWELLING"
_STATE_STOPPED = "STOPPED"


class NavigationStub:
    def __init__(self, mqtt_client: MQTTClientBase):
        self._client = mqtt_client
        self._logger = get_logger("mod03.nav")
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._resume_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = _STATE_IDLE

    def start(self):
        self._client.subscribe(TOPIC_ROBOT_COMMAND, self._on_command, qos=0)
        self._stop_event.clear()
        self._resume_event.set()
        self._set_state(_STATE_MOVING)
        self._thread = threading.Thread(
            target=self._patrol_loop, name="mod03-nav", daemon=True
        )
        self._thread.start()
        self._logger.info("[MOD-03] NavigationStub started")

    def stop(self):
        self._stop_event.set()
        self._resume_event.set()  # unblock if waiting
        if self._thread:
            self._thread.join()
        self._logger.info("[MOD-03] NavigationStub stopped")

    def _set_state(self, new_state: str):
        with self._lock:
            self.state = new_state
        self._logger.info("[MOD-03][STATE] -> %s", new_state)

    def _patrol_loop(self):
        waypoint_index = 0
        while not self._stop_event.is_set():
            # Wait while STOPPED
            with self._lock:
                is_stopped = self.state == _STATE_STOPPED
            if is_stopped:
                self._resume_event.wait()
                self._resume_event.clear()
                if self._stop_event.is_set():
                    break
                continue

            waypoint = WAYPOINTS[waypoint_index % len(WAYPOINTS)]
            self._set_state(_STATE_DWELLING)

            ts_ms = int(time.time() * 1000)
            position_payload = {
                "timestamp_ms": ts_ms,
                "waypoint_id": waypoint["id"],
                "x_m": waypoint["x_m"],
                "y_m": waypoint["y_m"],
                "state": "DWELLING",
                "obstacle_cm": random.randint(50, 300),
            }
            self._client.publish(TOPIC_NAV_POSITION, position_payload, qos=0)
            self._client.publish(TOPIC_NAV_WAYPOINT, position_payload, qos=0)

            # Dwell with early exit on stop
            dwell_end = time.time() + DWELL_MS / 1000.0
            while time.time() < dwell_end:
                if self._stop_event.is_set():
                    return
                with self._lock:
                    if self.state == _STATE_STOPPED:
                        break
                time.sleep(0.1)

            with self._lock:
                still_stopped = self.state == _STATE_STOPPED
            if not still_stopped:
                self._set_state(_STATE_MOVING)
                waypoint_index += 1

    def _on_command(self, payload: dict):
        cmd = payload.get("cmd", "").upper()
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        status = "OK"
        detail = ""

        if cmd == "START":
            self._set_state(_STATE_MOVING)
            self._resume_event.set()
            detail = f"Command {cmd} executed. New state: {self.state}"
        elif cmd == "STOP":
            self._set_state(_STATE_STOPPED)
            self._resume_event.clear()
            detail = f"Command {cmd} executed. New state: {self.state}"
        elif cmd == "ALARM":
            self._set_state(_STATE_STOPPED)
            self._resume_event.clear()
            self._logger.warning("[MOD-03][ALARM] ALARM received — robot halted")
            detail = f"Command {cmd} executed. New state: {self.state}"
        else:
            status = "ERROR"
            detail = f"Unknown command: {cmd!r}"
            self._logger.error("[MOD-03] Unknown command: %s", cmd)

        feedback = {
            "correlationId": payload.get("correlationId", "unknown"),
            "status": status,
            "detail": detail,
            "timestamp": ts,
        }
        self._client.publish(TOPIC_ROBOT_FEEDBACK, feedback, qos=0)
