# Easibot: Headless AI Multilingual Assistant Robot 🤖

A lightweight, single-file AI voice assistant robot built for **Raspberry Pi Zero W / Zero 2 W** (512 MB RAM). Detects users at close range (`10–15 cm`) via an ultrasonic sensor, captures speech in **English, Telugu (`తెలుగు`), and Hindi (`हिंदी`)** via **Google Gemini 3.5 Flash-Lite**, renders animated eyes and a response-based UI on a **2.8" SPI TFT LCD (ILI9341)**, and speaks through a **Bluetooth speaker / neckband or USB audio**.

---

## 🌟 Features

* **Single-File Architecture ([main.py](file:///c:/Users/chara/Desktop/Easibot/main.py)):** Zero bloat, minimal RAM footprint, no web dashboard overhead.
* **Fast Gemini 3.5 Flash-Lite + Predefined Study Concepts:** Instant `0 ms` local answers for greetings and study topics (`hi`, `diode`, `resistor`, `capacitor`, `raspberry pi`, `mitochondria`, etc.), and ~1.5s AI replies for everything else.
* **Close-Range Ultrasonic Trigger (`10–15 cm`):** Wakes the robot when you place/wave your hand within `15 cm`. Can interrupt while **`thinking`**, and **never interrupts while `speaking`**.
* **Continuous Multi-Turn Chat:** Remembers conversation context (`chat_history`) and automatically listens for follow-up questions with a live countdown progress bar on the TFT screen.
* **Response-Based Dynamic TFT UI:** Shows expressive animated eyes when idle/listening/thinking, and switches to a full-screen wrapped answer card when responding.
* **Auto-Switching Audio:** Automatically uses **USB Mic** (`arecord`) or **Bluetooth Neckband Mic** (`pactl`/`parecord`) and routes TTS (`edge-tts` → `gTTS` → `espeak`) to your Bluetooth or system speaker.

---

## 📐 Raspberry Pi GPIO Pinout

| Peripheral | Pin | Raspberry Pi Pin | BCM GPIO | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **2.8" TFT LCD** (`ILI9341`) | `VCC` | Pin 1 | 3.3V | Power |
| | `GND` | Pin 6 | GND | Common Ground |
| | `CS` | Pin 24 | GPIO 8 | SPI CE0 |
| | `RESET` | Pin 22 | GPIO 25 | Hardware Reset |
| | `DC / RS` | Pin 18 | GPIO 24 | Data/Command |
| | `MOSI` | Pin 19 | GPIO 10 | SPI MOSI |
| | `SCK` | Pin 23 | GPIO 11 | SPI Clock |
| | `LED` | Pin 12 | GPIO 18 | Backlight (or 3.3V) |
| **HC-SR04 Ultrasonic** | `VCC` | Pin 2 | 5.0V | Must be 5V |
| | `GND` | Pin 9 | GND | Common Ground |
| | `TRIG` | Pin 16 | GPIO 23 | (or GPIO 13 via `PIN_TRIG=13`) |
| | `ECHO` | Pin 13 | GPIO 27 | **Via 1kΩ / 2kΩ voltage divider!** (or GPIO 16 via `PIN_ECHO=16`) |

---

## 📁 Clean Project Structure

```text
Easibot/
├── .env.example              # Environment configuration template
├── .gitignore
├── README.md
├── main.py                   # Complete single-file robot application
├── requirements.txt          # Minimal Python dependencies
├── scripts/
│   ├── setup_rpi.sh          # Raspberry Pi OS setup (SPI, fonts, ZRAM, audio)
│   ├── setup_bluetooth.sh    # Bluetooth speaker/neckband pairing helper
│   ├── test_hardware.py      # Standalone TFT, ultrasonic, and audio diagnostic
│   ├── run_service.sh        # Launch wrapper
│   └── easibot.service       # systemd boot service
└── tests/
    └── test_easibot.py       # Unit tests
```

---

## 🚀 Quickstart on Raspberry Pi

```bash
git clone https://github.com/cherry1130dev/Easibot.git
cd Easibot
chmod +x scripts/*.sh
./scripts/setup_rpi.sh
cp .env.example .env
nano .env   # Add GEMINI_API_KEY and set MOCK_HARDWARE=false
source venv/bin/activate
python main.py
```
