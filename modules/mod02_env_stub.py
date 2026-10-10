"""
MOD-02 Çevresel Sensör Modülü - Gerçek Donanım Entegrasyonu
Sensörler: DHT22 (sıcaklık/nem), MQ135 (gaz/hava kalitesi), KY038 (ses)
"""

import threading
from datetime import datetime, timezone

try:
    import Adafruit_DHT
except ImportError:
    Adafruit_DHT = None

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

from config.settings import (
    TOPIC_ENV_HAZARD,
    THRESHOLD_TEMP_C,
    THRESHOLD_HUMIDITY,
    THRESHOLD_GAS_PPM,
    THRESHOLD_NOISE_DB,
    DHT22_PIN,
    MQ135_DO_PIN,
    KY038_DO_PIN,
    SENSOR_PUBLISH_INTERVAL,
)
from mqtt.client_base import MQTTClientBase
from utils.logger import get_logger


class EnvSensorModule:
    """
    Gerçek DHT22, MQ135 ve KY038 sensörlerinden veri okuyup
    ohs/env/hazard topic'ine publish eden modül.
    """

    def __init__(self, mqtt_client: MQTTClientBase):
        self._client = mqtt_client
        self._logger = get_logger("mod02.env")
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._setup_gpio()

    # ------------------------------------------------------------------
    # GPIO Kurulum
    # ------------------------------------------------------------------

    def _setup_gpio(self):
        if GPIO is None:
            self._logger.warning("[MOD-02] RPi.GPIO bulunamadı, GPIO başlatılamadı.")
            return
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(MQ135_DO_PIN, GPIO.IN)
            GPIO.setup(KY038_DO_PIN, GPIO.IN)
            self._logger.info(
                "[MOD-02] GPIO pinleri hazır. MQ135=%s, KY038=%s",
                MQ135_DO_PIN, KY038_DO_PIN,
            )
        except Exception as exc:
            self._logger.error("[MOD-02] GPIO kurulum hatası: %s", exc)

    # ------------------------------------------------------------------
    # Thread Yönetimi
    # ------------------------------------------------------------------

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="mod02-env", daemon=True
        )
        self._thread.start()
        self._logger.info("[MOD-02] EnvSensorModule started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        self._cleanup_gpio()
        self._logger.info("[MOD-02] EnvSensorModule stopped")

    def _cleanup_gpio(self):
        if GPIO is not None:
            try:
                GPIO.cleanup()
            except Exception as exc:
                self._logger.warning("[MOD-02] GPIO cleanup hatası: %s", exc)

    # ------------------------------------------------------------------
    # Ana Döngü
    # ------------------------------------------------------------------

    def _loop(self):
        while not self._stop_event.wait(SENSOR_PUBLISH_INTERVAL):
            self._read_and_publish_all()

    def _read_and_publish_all(self):
        # DHT22 tek okumada hem sıcaklık hem nem verir
        temp, humidity = self._read_dht22()
        if temp is not None:
            self._publish_sensor_value(
                sensor="dht22", metric="temperature",
                value=temp, threshold=THRESHOLD_TEMP_C, unit="°C",
            )
        if humidity is not None:
            self._publish_sensor_value(
                sensor="dht22", metric="humidity",
                value=humidity, threshold=THRESHOLD_HUMIDITY, unit="%",
            )

        gas_hazard = self._read_gas_hazard()
        if gas_hazard is not None:
            value = THRESHOLD_GAS_PPM + 50 if gas_hazard else THRESHOLD_GAS_PPM - 50
            self._publish_sensor_value(
                sensor="mq135", metric="gas_ppm",
                value=value, threshold=THRESHOLD_GAS_PPM, unit="ppm",
            )

        noise_hazard = self._read_noise_hazard()
        if noise_hazard is not None:
            value = THRESHOLD_NOISE_DB + 10 if noise_hazard else THRESHOLD_NOISE_DB - 10
            self._publish_sensor_value(
                sensor="ky038", metric="noise_db",
                value=value, threshold=THRESHOLD_NOISE_DB, unit="dB",
            )

    # ------------------------------------------------------------------
    # Sensör Okuma Fonksiyonları
    # ------------------------------------------------------------------

    def _read_dht22(self) -> tuple[float | None, float | None]:
        """DHT22'den (temperature_C, humidity_pct) döner; hata varsa (None, None)."""
        if Adafruit_DHT is None:
            self._logger.warning("[MOD-02] Adafruit_DHT kütüphanesi yok.")
            return None, None
        try:
            humidity, temperature = Adafruit_DHT.read_retry(
                Adafruit_DHT.DHT22, DHT22_PIN
            )
            temp = round(float(temperature), 2) if temperature is not None else None
            hum = round(float(humidity), 2) if humidity is not None else None
            if temp is None:
                self._logger.warning("[MOD-02] DHT22 sıcaklık verisi boş döndü.")
            if hum is None:
                self._logger.warning("[MOD-02] DHT22 nem verisi boş döndü.")
            return temp, hum
        except Exception as exc:
            self._logger.error("[MOD-02] DHT22 okuma hatası: %s", exc)
            return None, None

    def _read_gas_hazard(self) -> bool | None:
        """MQ135 DO pini: LOW → eşik aşıldı (True), HIGH → normal (False)."""
        if GPIO is None:
            self._logger.warning("[MOD-02] GPIO yok, MQ135 okunamıyor.")
            return None
        try:
            return GPIO.input(MQ135_DO_PIN) == GPIO.LOW
        except Exception as exc:
            self._logger.error("[MOD-02] MQ135 okuma hatası: %s", exc)
            return None

    def _read_noise_hazard(self) -> bool | None:
        """KY038 DO pini: LOW → eşik aşıldı (True), HIGH → sessiz (False)."""
        if GPIO is None:
            self._logger.warning("[MOD-02] GPIO yok, KY038 okunamıyor.")
            return None
        try:
            return GPIO.input(KY038_DO_PIN) == GPIO.LOW
        except Exception as exc:
            self._logger.error("[MOD-02] KY038 okuma hatası: %s", exc)
            return None

    # ------------------------------------------------------------------
    # MQTT Publish
    # ------------------------------------------------------------------

    def _publish_sensor_value(self, sensor: str, metric: str,
                               value: float, threshold: float, unit: str):
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        payload = {
            "timestamp": ts,
            "sensor": sensor,
            "metric": metric,
            "value": round(value, 2),
            "threshold": threshold,
            "unit": unit,
            "hazard": value >= threshold,
        }

        if payload["hazard"]:
            self._logger.warning(
                "[MOD-02][HAZARD] sensor=%s metric=%s value=%s %s (eşik: %s)",
                sensor, metric, value, unit, threshold,
            )
        else:
            self._logger.debug(
                "[MOD-02] sensor=%s metric=%s value=%s %s", sensor, metric, value, unit
            )

        self._client.publish(TOPIC_ENV_HAZARD, payload, qos=0)
