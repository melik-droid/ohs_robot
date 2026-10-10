"""
inference.py — MOD-01 Vision-Based PPE Detection
Raspberry Pi 5 İSG Denetim Robotu · MOD-01

Public API:
    init(model_path, mqtt_broker, mqtt_port, connect_mqtt)
    ppe_run_inference(frame, image_path)  → ppe_result_t (dict)
    capture_frame()                        → numpy BGR array | None
    nav_waypoint_cb(waypoint_id)           → ppe_result_t  (MOD-03 callback)

MOD-03 Kullanım Örneği:
    from inference import init, nav_waypoint_cb
    init()
    result = nav_waypoint_cb(waypoint_id="wp_01")
    # result["violations"] listesi ihlalleri içerir

MQTT Topic : ohs/ppe/violation  (QoS 0)
Tetikleyici: MOD-03 DWELLING state → nav_waypoint_cb()
"""

import json
import logging
import os
import time

import cv2
import numpy as np
import onnxruntime as ort
import paho.mqtt.client as mqtt

# ── Loglama ──────────────────────────────────────────────────────────────────
_log_level = os.environ.get("PPE_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s [MOD-01] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=getattr(logging, _log_level, logging.INFO),
)
logger = logging.getLogger("mod01.ppe")

# ── Konfigürasyon (env var öncelikli) ────────────────────────────────────────
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_PATH   = os.environ.get("PPE_MODEL_PATH",   os.path.join(_MODULE_DIR, "best.onnx"))
MQTT_BROKER  = os.environ.get("PPE_MQTT_BROKER",  "localhost")
MQTT_PORT    = int(os.environ.get("PPE_MQTT_PORT", "1883"))
MQTT_TOPIC   = "ohs/ppe/violation"
ONNX_THREADS = int(os.environ.get("PPE_ONNX_THREADS", "2"))   # Pi 5 ≤70% çekirdek hedefi
IMG_SIZE     = 1024                                            # eğitim imgsz ile aynı

CLASSES = {
    0: "Hardhat",
    1: "NO-Hardhat",
    2: "Safety Vest",
    3: "NO-Safety Vest",
    4: "Goggles",
    5: "NO-Goggles",
    6: "Person",
}

VIOLATION_CLASSES = {1, 3, 5}   # NO-Hardhat, NO-Safety Vest, NO-Goggles

# Sınıf-bazlı confidence eşikleri (evaluate.py sonuçlarına göre optimize)
CLASS_THRESHOLDS = {
    0: 0.45,   # Hardhat       — kafa FP'e eğilimli
    1: 0.45,   # NO-Hardhat
    2: 0.25,   # Safety Vest   — büyük nesne
    3: 0.25,   # NO-Safety Vest
    4: 0.35,   # Goggles
    5: 0.35,   # NO-Goggles    — 0.15 çok FP üretiyordu
    6: 0.35,   # Person
}

NMS_IOU_THRESHOLD = 0.45

# ── PiCamera2 güvenli import ──────────────────────────────────────────────────
try:
    from picamera2 import Picamera2
    _HAS_PICAM = True
except ImportError:
    _HAS_PICAM = False

# ── Modül-seviyesi durum ──────────────────────────────────────────────────────
_session       = None    # ort.InferenceSession
_input_name    = None
_mqtt_client   = None
_mqtt_connected = False
_picam         = None    # Picamera2 örneği (lazy init, tekrar kullanılır)
_initialized   = False


# ── Init ──────────────────────────────────────────────────────────────────────

def init(model_path=None, mqtt_broker=None, mqtt_port=None, connect_mqtt=True):
    """
    Model ve MQTT bağlantısını kur. Servis başlangıcında veya ilk
    ppe_run_inference() çağrısında otomatik tetiklenir.

    Args:
        model_path:   ONNX dosya yolu (varsayılan: PPE_MODEL_PATH env / best.onnx)
        mqtt_broker:  Broker adresi   (varsayılan: PPE_MQTT_BROKER env / localhost)
        mqtt_port:    Broker portu    (varsayılan: PPE_MQTT_PORT env / 1883)
        connect_mqtt: False → sadece model yükle, MQTT bağlanma (test için)
    """
    global _session, _input_name, _mqtt_client, _mqtt_connected, _initialized

    if _initialized:
        return

    _mp   = model_path  or MODEL_PATH
    _host = mqtt_broker or MQTT_BROKER
    _port = mqtt_port   or MQTT_PORT

    # Model
    logger.info("Model yükleniyor: %s", _mp)
    _opts = ort.SessionOptions()
    _opts.intra_op_num_threads = ONNX_THREADS
    _session = ort.InferenceSession(
        _mp,
        sess_options=_opts,
        providers=["CPUExecutionProvider"],
    )
    _input_name = _session.get_inputs()[0].name
    logger.info(
        "Model yüklendi — giriş: %s, çıkış: %s",
        _session.get_inputs()[0].shape,
        [o.shape for o in _session.get_outputs()],
    )

    # MQTT
    if connect_mqtt:
        _mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        _mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

        def _on_connect(client, userdata, flags, reason_code, properties):
            global _mqtt_connected
            if reason_code == 0:
                _mqtt_connected = True
                logger.info("MQTT bağlandı: %s:%s", _host, _port)
            else:
                _mqtt_connected = False
                logger.warning("MQTT bağlantı başarısız, kod: %s", reason_code)

        def _on_disconnect(client, userdata, flags, reason_code, properties):
            global _mqtt_connected
            _mqtt_connected = False
            if reason_code != 0:
                logger.warning("MQTT bağlantı kesildi (kod %s), yeniden deneniyor…", reason_code)

        _mqtt_client.on_connect    = _on_connect
        _mqtt_client.on_disconnect = _on_disconnect

        try:
            _mqtt_client.connect_async(_host, _port, keepalive=60)
            _mqtt_client.loop_start()
            logger.info("MQTT bağlantı isteği gönderildi: %s:%s", _host, _port)
        except Exception as exc:
            logger.warning("MQTT başlatılamadı (%s), publish devre dışı", exc)
            _mqtt_connected = False

    _initialized = True


def _ensure_init():
    """Lazy init — ilk kullanımda otomatik çağrılır."""
    if not _initialized:
        init()


# ── Kamera ───────────────────────────────────────────────────────────────────

def capture_frame():
    """
    Kameradan tek BGR kare yakalar.

    Dönüş:
        numpy array (H, W, 3) BGR | None (kamera yoksa)

    Pi'de Picamera2 kullanılır (apt ile kurulur).
    Mac/test ortamında None döner — image_path ile test için.
    """
    global _picam
    if not _HAS_PICAM:
        logger.warning("PiCamera2 bulunamadı — image_path ile test moduna geç")
        return None

    if _picam is None:
        _picam = Picamera2()
        cfg = _picam.create_still_configuration(
            main={"size": (IMG_SIZE, IMG_SIZE), "format": "RGB888"}
        )
        _picam.configure(cfg)
        _picam.start()
        time.sleep(0.2)   # kamera hazır olana kadar bekle
        logger.info("PiCamera2 başlatıldı (%dx%d)", IMG_SIZE, IMG_SIZE)

    rgb = _picam.capture_array()            # RGB numpy array
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return bgr


# ── Preprocess / Postprocess ──────────────────────────────────────────────────

def _preprocess(frame):
    """BGR frame → model giriş tensörü. Orijinal boyutu da döndürür."""
    orig_h, orig_w = frame.shape[:2]
    img = cv2.resize(frame, (IMG_SIZE, IMG_SIZE))     # stretch (eğitimle uyumlu)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))
    img = np.expand_dims(img, axis=0)
    return img, orig_w, orig_h


def _postprocess(outputs, orig_w, orig_h):
    """
    Model çıktısını işler; kutuları orijinal görsel boyutuna ölçekler.
    Sınıf-bazlı threshold ve sınıf-duyarlı NMS uygular.
    """
    predictions = outputs[0][0].T   # (21504, 11): [cx, cy, w, h, c0..c6]

    scale_x = orig_w / IMG_SIZE
    scale_y = orig_h / IMG_SIZE

    per_class = {cid: {"boxes": [], "scores": []} for cid in CLASSES}

    for pred in predictions:
        class_scores = pred[4:]
        class_id     = int(np.argmax(class_scores))
        confidence   = float(class_scores[class_id])

        if confidence < CLASS_THRESHOLDS[class_id]:
            continue

        cx, cy, w, h = pred[0], pred[1], pred[2], pred[3]
        x1 = int(np.clip((cx - w / 2) * scale_x, 0, orig_w))
        y1 = int(np.clip((cy - h / 2) * scale_y, 0, orig_h))
        x2 = int(np.clip((cx + w / 2) * scale_x, 0, orig_w))
        y2 = int(np.clip((cy + h / 2) * scale_y, 0, orig_h))

        per_class[class_id]["boxes"].append([x1, y1, x2, y2])
        per_class[class_id]["scores"].append(confidence)

    # Sınıf-duyarlı NMS (positional args zorunlu — keyword arg hata verir)
    results = []
    for class_id, data in per_class.items():
        boxes  = data["boxes"]
        scores = data["scores"]
        if not boxes:
            continue
        raw     = cv2.dnn.NMSBoxes(boxes, scores, CLASS_THRESHOLDS[class_id], NMS_IOU_THRESHOLD)
        indices = np.array(raw).flatten() if len(raw) > 0 else []
        for i in indices:
            results.append({
                "class_id":    class_id,
                "class":       CLASSES[class_id],
                "confidence":  round(scores[i], 3),
                "bounding_box": boxes[i],   # [x1, y1, x2, y2] — orijinal piksel
            })

    return results


# ── Public API ────────────────────────────────────────────────────────────────

def ppe_run_inference(frame=None, image_path=None):
    """
    PPE ihlal tespiti yapar ve MQTT'ye publish eder.

    Args:
        frame:      numpy BGR array (PiCamera2 veya MOD-03'ten)
        image_path: test için dosya yolu (frame yoksa kullanılır)

    Dönüş (ppe_result_t):
        {
            "success":    bool,
            "detections": [ {"class_id", "class", "confidence", "bounding_box"}, … ],
            "violations": [ … yalnızca class_id ∈ {1,3,5} … ],
            "latency_ms": float,
            "frame_size": [w, h]
        }
    """
    _ensure_init()
    t0 = time.perf_counter()

    if frame is None and image_path is not None:
        frame = cv2.imread(image_path)

    if frame is None:
        logger.error("Görsel bulunamadı — frame=None ve image_path=%s", image_path)
        return {"success": False, "detections": [], "violations": [],
                "latency_ms": 0.0, "frame_size": [0, 0]}

    img, orig_w, orig_h = _preprocess(frame)
    outputs    = _session.run(None, {_input_name: img})
    detections = _postprocess(outputs, orig_w, orig_h)

    violations = [d for d in detections if d["class_id"] in VIOLATION_CLASSES]

    if violations:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for v in violations:
            payload = {
                "class":        v["class"],
                "confidence":   v["confidence"],
                "bounding_box": v["bounding_box"],
                "timestamp":    ts,
            }
            logger.info("İhlal tespit edildi: %s", payload)
            if _mqtt_connected and _mqtt_client is not None:
                _mqtt_client.publish(MQTT_TOPIC, json.dumps(payload), qos=0)
    else:
        logger.debug("İhlal yok")

    latency_ms = (time.perf_counter() - t0) * 1000

    return {
        "success":    True,
        "detections": detections,
        "violations": violations,
        "latency_ms": round(latency_ms, 1),
        "frame_size": [orig_w, orig_h],
    }


def nav_waypoint_cb(waypoint_id=None):
    """
    MOD-03 DWELLING state callback — robot bir waypoint'e ulaşınca çağrılır.

    MOD-03 Kullanım:
        from inference import init, nav_waypoint_cb
        init()
        ...
        result = nav_waypoint_cb(waypoint_id="wp_factory_floor_01")

    Args:
        waypoint_id: opsiyonel string (loglama için)

    Dönüş:
        ppe_result_t dict — bkz. ppe_run_inference()
    """
    logger.info("Waypoint tetikleyici: %s", waypoint_id)
    frame = capture_frame()
    return ppe_run_inference(frame=frame)


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    init()
    result = ppe_run_inference(image_path="test.jpg")
    if result["success"]:
        print(f"\nLatency    : {result['latency_ms']} ms")
        print(f"Frame size : {result['frame_size']}")
        print(f"Tespitler  : {len(result['detections'])}")
        for d in result["detections"]:
            tag = "⚠️ İHLAL" if d["class_id"] in VIOLATION_CLASSES else "   "
            print(f"  {tag} {d['class']:20s} conf={d['confidence']} box={d['bounding_box']}")
