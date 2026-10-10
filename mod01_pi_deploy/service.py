"""
service.py — MOD-01 Standalone Runner / Pi Smoke-Test

Raspberry Pi 5'te MOD-01'i MOD-03 olmadan bağımsız çalıştırır.
Kameradan sürekli (veya tek seferlik) frame alır, inference yapar, loglar.

Kullanım:
    python service.py                # sürekli döngü (Ctrl+C ile dur)
    python service.py --once         # tek seferlik, latency raporlar
    python service.py --image test.jpg   # kamera yerine dosyadan (Pi'siz test)
    PPE_LOG_LEVEL=DEBUG python service.py --once

Pi üzerinde systemd ile çalışırken:
    journalctl -u mod01-ppe -f
"""

import argparse
import signal
import sys
import time

from inference import init, nav_waypoint_cb, ppe_run_inference, VIOLATION_CLASSES

_running = True


def _handle_signal(sig, frame):
    global _running
    print("\n[service] Durdurma sinyali alındı, çıkılıyor…")
    _running = False


def run(image_path=None, once=False, interval=5.0):
    """
    Args:
        image_path: Belirtilirse kamera yerine bu dosya kullanılır.
        once:       True → tek inference, çık.
        interval:   Döngü aralığı (saniye).
    """
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    connect_mqtt = image_path is None   # dosyadan test ediliyorsa MQTT zorunlu değil
    init(connect_mqtt=connect_mqtt)

    print("[service] MOD-01 PPE Servisi başlatıldı.")
    if image_path:
        print(f"[service] Test modu: {image_path}")
    else:
        print("[service] Kamera modu — Pi'de PiCamera2 kullanılır.")

    latencies = []
    wp_counter = 0

    while _running:
        wp_counter += 1
        wp_id = f"smoke_wp_{wp_counter:04d}"

        if image_path:
            result = ppe_run_inference(image_path=image_path)
        else:
            result = nav_waypoint_cb(waypoint_id=wp_id)

        if result["success"]:
            lat = result["latency_ms"]
            latencies.append(lat)
            viols = result["violations"]
            status = f"İHLAL ({len(viols)}x)" if viols else "temiz"
            print(
                f"[{wp_id}] {lat:6.1f}ms  {status}  "
                f"| tespitler: {len(result['detections'])}"
            )
            if viols:
                for v in viols:
                    print(f"  ⚠️  {v['class']} conf={v['confidence']} box={v['bounding_box']}")
        else:
            print(f"[{wp_id}] inference başarısız")

        if once:
            break

        time.sleep(interval)

    # Özet
    if latencies:
        import numpy as np
        lat = np.array(latencies)
        print(f"\n{'='*50}")
        print(f"Çalıştırma özeti ({len(lat)} inference)")
        print(f"  Ortalama latency : {lat.mean():.1f} ms")
        print(f"  P95 latency      : {float(np.percentile(lat, 95)):.1f} ms")
        print(f"  Min/Max          : {lat.min():.1f} / {lat.max():.1f} ms")
        target = 500.0
        above  = (lat > target).sum()
        print(f"  Hedef <{target:.0f}ms    : {'✅ PASS' if above == 0 else f'⚠️  {above}/{len(lat)} hedef aşıyor'}")
        print(f"{'='*50}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MOD-01 PPE Service Runner")
    parser.add_argument("--once",  action="store_true", help="Tek inference çalıştır ve çık")
    parser.add_argument("--image", default=None,        help="Test görsel dosyası (kamera yerine)")
    parser.add_argument("--interval", type=float, default=5.0, help="Döngü aralığı saniye (varsayılan 5)")
    args = parser.parse_args()

    run(image_path=args.image, once=args.once, interval=args.interval)
