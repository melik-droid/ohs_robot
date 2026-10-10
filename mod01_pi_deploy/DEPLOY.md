# MOD-01 — Raspberry Pi 5 Deploy Rehberi

## Gereksinimler

- Raspberry Pi 5 (4 GB+ RAM önerilir)
- Pi OS Bookworm (64-bit)
- Raspberry Pi Kamera Modülü (CSI/LibCamera uyumlu)
- Python 3.11 (Bookworm'da varsayılan)

---

## 1. Sistem Paketleri

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-picamera2 mosquitto mosquitto-clients python3-venv
sudo systemctl enable --now mosquitto
```

---

## 2. Kamerayı Etkinleştir

```bash
sudo raspi-config
# → Interface Options → Camera → Enable
sudo reboot
```

Doğrulama (reboot sonrası):
```bash
libcamera-hello --timeout 3000
```

---

## 3. Dosyaları Kopyala

Geliştirici makinesinden:
```bash
rsync -av --exclude='venv/' --exclude='*.zip' --exclude='__pycache__/' \
  ~/Desktop/ceng/ pi@raspberrypi.local:/home/pi/ceng/
```

Kopyalanacak kritik dosyalar:
- `best.onnx` (~12 MB)
- `inference.py`
- `service.py`
- `evaluate.py`
- `mod01-ppe.service`
- `requirements.txt`

---

## 4. Python Sanal Ortam

```bash
cd /home/pi/ceng
python3 -m venv venv --system-site-packages   # system-site-packages: picamera2 erişimi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> **Not:** `--system-site-packages` ile `apt`'ten kurulan `picamera2` venv içinde görünür.

---

## 5. Smoke Test (PiCamera2 ile)

```bash
cd /home/pi/ceng && source venv/bin/activate
python service.py --once
```

Beklenen çıktı:
```
[service] MOD-01 PPE Servisi başlatıldı.
[smoke_wp_0001]  XXX.Xms  temiz | tespitler: N
==================================================
Çalıştırma özeti (1 inference)
  Ortalama latency : XXX.X ms
  Hedef <500ms    : ✅ PASS     ← Pi 5 CPU hedefi
==================================================
```

---

## 6. Latency & CPU Doğrulama

```bash
# 10 frame ile latency istatistiği
python service.py --image ppe_dataset/test/images/<bir_gorsel>.jpg --once
# veya kamera ile
python service.py --once

# CPU kullanımı (ayrı terminal)
htop
```

**Hedefler:**
| Metrik | Hedef |
|---|---|
| Inference latency | < 500 ms |
| CPU (tek çekirdek) | ≤ 70% |

> Latency > 500ms ise: `PPE_ONNX_THREADS=4` dene veya 640px export'a geç (`best_640.onnx`).

---

## 7. MQTT Smoke Test

İki terminal:
```bash
# Terminal 1 — dinle
mosquitto_sub -t ohs/ppe/violation -v

# Terminal 2 — tetikle (kamera olmadan)
python service.py --image ppe_dataset/test/images/<ihlal_iceren>.jpg --once
```

Beklenen payload:
```json
{
  "class": "NO-Hardhat",
  "confidence": 0.617,
  "bounding_box": [1233, 247, 1450, 478],
  "timestamp": "2026-06-02T10:00:00Z"
}
```

---

## 8. systemd Servisi

```bash
sudo cp /home/pi/ceng/mod01-ppe.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mod01-ppe
sudo systemctl status mod01-ppe
```

Log izleme:
```bash
journalctl -u mod01-ppe -f
```

Reboot testi:
```bash
sudo reboot
# 30 saniye sonra
journalctl -u mod01-ppe --since "5 minutes ago"
```

---

## 9. MOD-03 Entegrasyonu (same-process)

MOD-03 Python kodunda:
```python
from inference import init, nav_waypoint_cb

# Robot başlangıcında bir kere çağır
init()

# DWELLING state'ine girildiğinde
def on_waypoint_reached(waypoint_id: str):
    result = nav_waypoint_cb(waypoint_id=waypoint_id)
    if result["violations"]:
        # Kendi MQTT publish'in veya UI güncellemen
        handle_violations(result["violations"])
    return result
```

---

## 10. Ortam Değişkenleri (İnce Ayar)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `PPE_MODEL_PATH` | `<script_dizini>/best.onnx` | ONNX model dosyası |
| `PPE_MQTT_BROKER` | `localhost` | Broker IP/hostname |
| `PPE_MQTT_PORT` | `1883` | Broker portu |
| `PPE_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `PPE_ONNX_THREADS` | `2` | Inference thread sayısı |

---

## Bilinen Sınırlılıklar

| Risk | Açıklama |
|---|---|
| R-01-05 | NO-Safety Vest mAP 0.706 (hedef 0.82) — bilinen limitasyon |
| Model boyutu | 12 MB (spec <10 MB — kabul edildi) |
| Box kalitesi | Model GT'den tighter kutular üretiyor; alarm konumu doğru |
| R-01-03 | Tek frame — v0.2'de burst mod planlanıyor |
