# Moody edge firmware (ESP32-S3-BOX-3)

ESP-IDF v5.5 firmware, MIT licensed. Full guide: [docs/05-setup-device.md](../docs/05-setup-device.md).

| File | Purpose |
|---|---|
| `main/main.c` | application state machine (connecting → idle → listening → thinking → speaking) |
| `main/audio.c` | ES7210 mic → ESP-SR AFE (WakeNet9 "Hi ESP" + VAD); speaker playback; half-duplex |
| `main/link.c` | WSS client with mutual TLS (`moody.v1` sub-protocol) |
| `main/provision.c` | USB provisioning: on-device key generation, CSR, encrypted NVS |
| `main/ota.c` | signed OTA from the gateway with rollback |
| `main/ui.c` | LVGL UI: large text, red border while the mic streams, tap-to-talk, 10 s factory reset |
| `main/net.c` | Wi-Fi (WPA2/WPA3, PMF) + SNTP |
| `tools/provision.py` | host side of provisioning (signs the CSR with the device CA) |
| `sdkconfig.defaults` | development configuration |
| `sdkconfig.defaults.release` | Secure Boot V2, Flash Encryption (release), NVS encryption, secure download mode |

```bash
docker run --rm -v "$PWD":/project -w /project espressif/idf:v5.5.6 idf.py set-target esp32s3 build
```
