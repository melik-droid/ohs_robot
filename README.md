# OHS Robot — MQTT Communication System

## Raspberry Pi Setup (run once)

```bash
# Mosquitto kurulum
sudo apt install mosquitto mosquitto-clients -y
sudo systemctl enable mosquitto

# Dışarıdan bağlantıya izin ver
echo "listener 1883 0.0.0.0" | sudo tee -a /etc/mosquitto/mosquitto.conf
echo "allow_anonymous true"   | sudo tee -a /etc/mosquitto/mosquitto.conf
sudo systemctl restart mosquitto

# SSH server
sudo systemctl enable ssh
sudo systemctl start ssh

# Log dizini
sudo mkdir -p /var/log/ohs_robot
sudo chown pi:pi /var/log/ohs_robot

# Bağımlılıklar
pip install -r requirements.txt

# Çalıştır
python main.py
```

## Manuel Test Komutları

```bash
# STOP komutu gönder
mosquitto_pub -h localhost -t ohs/robot/command \
  -m '{"cmd":"STOP","correlationId":"test-001","issuedBy":"test","timestamp":"2026-01-01T00:00:00Z"}'

# START komutu gönder
mosquitto_pub -h localhost -t ohs/robot/command \
  -m '{"cmd":"START","correlationId":"test-002","issuedBy":"test","timestamp":"2026-01-01T00:00:00Z"}'

# ALARM komutu gönder
mosquitto_pub -h localhost -t ohs/robot/command \
  -m '{"cmd":"ALARM","correlationId":"test-003","issuedBy":"test","timestamp":"2026-01-01T00:00:00Z"}'

# Tüm topic'leri dinle
mosquitto_sub -h localhost -t "ohs/#" -v
```

## Topic Haritası

| Topic                | Yön       | Modül  | Açıklama                      |
|----------------------|-----------|--------|-------------------------------|
| ohs/ppe/violation    | Publish   | MOD-01 | KKD ihlal tespiti             |
| ohs/env/hazard       | Publish   | MOD-02 | Çevresel tehlike okuması      |
| ohs/nav/position     | Publish   | MOD-03 | Anlık konum ve durum          |
| ohs/nav/waypoint     | Publish   | MOD-03 | Waypoint varış bildirimi      |
| ohs/robot/feedback   | Publish   | MOD-03 | Komut yanıtı                  |
| ohs/robot/command    | Subscribe | MOD-03 | START / STOP / ALARM komutları|
