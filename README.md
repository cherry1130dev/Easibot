# Easibot: AI-Powered Multilingual Interactive Assistant Robot 🤖

An intelligent, sensor-equipped assistant robot built for **Raspberry Pi Zero 2 W** (512 MB RAM). Easibot detects nearby users via an ultrasonic proximity sensor, processes and translates voice or web queries across **English, Telugu (`తెలుగు`), and Hindi (`हिंदी`)** using **Google Gemini 2.5 Flash (`google-genai` SDK)**, expresses emotions with animated robot eyes and subtitles on a **2.8" SPI TFT LCD (ILI9341)**, and speaks through a **Bluetooth speaker with mic**.

Includes a complete **Laptop Mock Mode (`MOCK_HARDWARE=true`)** for seamless testing on Windows, macOS, and Linux before deploying to physical hardware.

---

## 🌟 Key Features

- **Multilingual AI & Translation Engine (`core/gemini_service.py`):**
  - Powered by the official `google-genai` Python SDK (`from google import genai`) with model `gemini-2.5-flash`.
  - Supports English (`en`), Telugu (`te`), and Hindi (`hi`), including code-mixed Indian vernacular speech (e.g., *"weather ela undi?"*, *"aaj ka din kaisa rahega?"*).
  - Returns structured Pydantic JSON with `detected_language`, `reply_native` (in native script), `reply_english`, `reply_romanized` (Latin phonetic transliteration for safe screen rendering), and `emotion` (`happy`, `thinking`, `listening`, `speaking`, `neutral`).
  - **Native Gemini Audio Input:** Sends recorded `.wav` bytes directly to Gemini 2.5 Flash for multimodal speech recognition and understanding—eliminating heavy local STT models that would exhaust the Pi Zero 2 W's 512 MB RAM.

- **Voice Pipeline (`core/audio_service.py`):**
  - **Audio Capture:** Records 16 kHz 16-bit mono voice clips via `sounddevice` or ALSA `arecord` on wake/trigger.
  - **Speech Synthesis (TTS):** Uses Microsoft `edge-tts` with high-definition neural voices (`te-IN-ShrutiNeural`, `hi-IN-SwaraNeural`, `en-IN-NeerjaNeural`), with automatic fallback to `gTTS`.
  - **Audio Playback:** Clean playback through PipeWire / PulseAudio / ALSA on Raspberry Pi or Windows Media Player / ffplay on laptops.

- **2.8" SPI TFT LCD Controller (`hardware/tft_display.py`):**
  - Drives ILI9341 (`KMRTM28028-SPI`, 320x240 landscape) using `adafruit-circuitpython-rgb-display` and `Pillow`.
  - **Top Status Bar:** Operational status (READY, LISTENING, THINKING, SPEAKING), active language badge, and real-time ultrasonic distance.
  - **Expressive Robot Eyes:** Fluid animated eyes with specular highlights, realistic blinks, soundwave arcs, and emotional transitions (`happy`, `thinking`, `listening`, `speaking`, `neutral`).
  - **Multilingual Subtitle Box:** Wrapped dialogue overlay with automatic fallback to `reply_romanized` if Indic font shaping (`libraqm`) is missing.

- **Ultrasonic Proximity Wake-Up (`hardware/ultrasonic.py`):**
  - Continuous non-blocking distance sampling via `HC-SR04` and `gpiozero.DistanceSensor`.
  - Automatically wakes robot when a person approaches within **60 cm** (configurable), displays a greeting, speaks a welcome prompt, and opens the mic.
  - Built-in **15-second cooldown timer** prevents repeated nuisance triggers.

- **Real-Time Web Chat Dashboard (`web/app.py`):**
  - Dark-mode responsive control center running on port `5000`.
  - Live conversation chat with translation cards and pronunciation hints.
  - Language selector (`Auto`, `English`, `తెలుగు`, `हिंदी`).
  - "Speak reply on Robot Speaker" toggle and "Trigger Voice Listen" remote button.
  - **Live TFT Screen Mirror:** Streamlined preview of the robot's physical LCD right in your browser.
  - Proximity test controls for simulation and debugging.

---

## 📐 Hardware Architecture & Pinout

### Raspberry Pi Zero 2 W GPIO Pin Mapping

| Peripheral | Component Pin | Raspberry Pi Zero 2 W Pin | BCM GPIO | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **2.8" SPI TFT LCD** | `VCC` | Pin 1 | 3.3V | Power supply |
| *(KMRTM28028-SPI)* | `GND` | Pin 6 | Ground | Common Ground |
| *(ILI9341 Driver)* | `CS` | Pin 24 | GPIO 8 | SPI Chip Enable 0 (CE0) |
| | `RESET` | Pin 22 | GPIO 25 | Hardware Reset |
| | `DC / RS` | Pin 18 | GPIO 24 | Data / Command select |
| | `SDI (MOSI)`| Pin 19 | GPIO 10 | SPI MOSI |
| | `SCK` | Pin 23 | GPIO 11 | SPI Clock |
| | `LED` | Pin 12 | GPIO 18 | Backlight PWM or 3.3V |
| **HC-SR04 Ultrasonic**| `VCC` | Pin 2 | 5.0V | 5V Sensor Supply |
| | `GND` | Pin 9 | Ground | Sensor Ground |
| | `TRIG` | Pin 16 | GPIO 23 | Trigger pulse output |
| | `ECHO` | Pin 13 | GPIO 27 | **Via 1kΩ / 2kΩ voltage divider!** |
| **Bluetooth Audio** | BT Speaker & Mic | Wireless | Bluetooth 4.2 / BLE | PipeWire / PulseAudio default sink/source |

> [!CAUTION]
> **Voltage Warning for HC-SR04 ECHO Pin:**
> The `HC-SR04` Echo pin outputs 5V logic. Raspberry Pi Zero 2 W GPIO pins are strictly **3.3V tolerant**. You **must** connect a voltage divider between the sensor's `ECHO` pin and `GPIO 27`:
> - Connect `ECHO` to a **1kΩ** resistor.
> - Connect the other end of the 1kΩ resistor to `GPIO 27` and a **2kΩ** resistor.
> - Connect the other end of the 2kΩ resistor to `GND`.
> This safely scales 5V down to ~3.3V ($5\text{V} \times \frac{2\text{k}\Omega}{1\text{k}\Omega + 2\text{k}\Omega} = 3.33\text{V}$).

---

## 📁 Project Directory Structure

```
Easibot/
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore rules
├── requirements.txt          # Python dependencies
├── config.py                 # Central configuration (pins, audio, languages, thresholds)
├── main.py                   # Master application orchestrator & background thread coordinator
├── core/
│   ├── __init__.py
│   ├── gemini_service.py     # google-genai SDK (gemini-2.5-flash text & audio multimodal API)
│   ├── audio_service.py      # Voice recording, edge-tts / gTTS synthesis, audio playback
│   └── state_manager.py      # Thread-safe global robot state, emotions, and message history
├── hardware/
│   ├── __init__.py
│   ├── tft_display.py        # 2.8" ILI9341 SPI driver, expressive animated eyes & Indic subtitles
│   ├── ultrasonic.py         # HC-SR04 driver via gpiozero with proximity wake-up loop
│   └── mock_hardware.py      # Laptop simulation layer (TFT screen mirror & simulated proximity)
├── web/
│   ├── __init__.py
│   ├── app.py                # Flask server, REST API & Server-Sent Events (SSE)
│   ├── static/
│   │   ├── css/style.css     # Cyberpunk dark mode dashboard styles
│   │   └── js/app.js         # Real-time state sync, chat interaction, and audio triggers
│   └── templates/
│       └── index.html        # Responsive mobile-friendly dashboard UI
├── scripts/
│   ├── setup_rpi.sh          # One-click Raspberry Pi OS setup (Bookworm/Trixie)
│   ├── setup_bluetooth.sh    # Bluetooth speaker & microphone pairing wizard
│   ├── run_service.sh        # Application launch wrapper
│   └── easibot.service       # systemd unit for autonomous 24/7 startup on boot
├── assets/
│   └── fonts/                # Multilingual TrueType fonts directory
└── tests/
    ├── test_gemini.py        # Unit tests for Gemini JSON schemas & language fallbacks
    ├── test_audio.py         # Unit tests for audio recording & TTS mappings
    └── test_hardware_mock.py # Unit tests for state machine, display rendering & web API
```

---

## 💻 Quickstart: Running on Laptop Mock Mode

You can test and run Easibot on your laptop (Windows / macOS / Linux) without any physical Raspberry Pi hardware.

### 1. Clone & Set Up Environment
```bash
git clone https://github.com/your-username/Easibot.git
cd Easibot

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Open `.env` and set your Google Gemini API key:
```ini
GEMINI_API_KEY=AIzaSy...your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
MOCK_HARDWARE=true
```

### 3. Run Unit Tests
```bash
python -m unittest discover -s tests
```

### 4. Launch Easibot
```bash
python main.py
```
Open your browser to:
**`http://localhost:5000`**

From the dashboard you can:
- Chat with Easibot in **English, Telugu (`తెలుగు`), or Hindi (`हिंदी`)**.
- Watch the **Live 2.8" TFT Screen Mirror** update in real-time.
- Click **"Test Person Approach (45cm)"** to simulate the ultrasonic proximity sensor triggering an autonomous wake-up!
- Click **"Trigger Voice Listen"** to test microphone recording.

---

## 🍓 Step-by-Step Deployment on Raspberry Pi Zero 2 W

### Step 1: Flash Raspberry Pi OS
1. Flash **Raspberry Pi OS Lite or Desktop (Bookworm / Trixie, 64-bit or 32-bit)** to a high-speed MicroSD card (A1/A2 recommended).
2. Configure Wi-Fi and SSH during flashing using Raspberry Pi Imager.
3. Power up the Raspberry Pi Zero 2 W and SSH into it:
   ```bash
   ssh pi@raspberrypi.local
   ```

### Step 2: Run One-Click Setup Script
Clone this repository and run `scripts/setup_rpi.sh`:
```bash
git clone https://github.com/your-username/Easibot.git
cd Easibot
chmod +x scripts/*.sh

# Run system setup (enables SPI/I2C, installs Indic fonts, ZRAM, and dependencies)
./scripts/setup_rpi.sh
```

### Step 3: Configure `.env`
```bash
cp .env.example .env
nano .env
```
Update `.env` with your settings:
```ini
GEMINI_API_KEY=your_actual_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
MOCK_HARDWARE=false
```

### Step 4: Pair Bluetooth Speaker & Mic
Put your Bluetooth speaker into pairing mode and run the interactive pairing script:
```bash
./scripts/setup_bluetooth.sh
```
Follow the prompt to enter your speaker's MAC address (`AA:BB:CC:DD:EE:FF`). The script pairs, trusts, connects, and configures PipeWire / PulseAudio default sinks.

### Step 5: Test Execution
```bash
source venv/bin/activate
python main.py
```
Check that the 2.8" TFT LCD lights up with robot eyes and status bar, and that approaching the HC-SR04 triggers a voice prompt.

### Step 6: Enable Autonomous Boot (systemd service)
To run Easibot automatically whenever the Raspberry Pi boots:
```bash
sudo cp scripts/easibot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable easibot.service
sudo systemctl start easibot.service
```

View live logs anytime via:
```bash
journalctl -u easibot.service -f
```

---

## ⚡ Raspberry Pi Zero 2 W Performance Optimizations

Because the Raspberry Pi Zero 2 W has **512 MB of RAM**, the following optimizations are implemented:
1. **Zero Local Speech-to-Text Overhead:**
   Audio recordings are transmitted directly as raw bytes to `gemini-2.5-flash` using native multimodal capabilities. This saves ~350 MB of RAM compared to running local Whisper or Vosk models.
2. **ZRAM Compression:**
   `scripts/setup_rpi.sh` configures `zramswap` with LZ4 compression, providing an effective ~1 GB of compressed memory without wearing out the MicroSD card.
3. **Throttled SPI Render Loop:**
   The ILI9341 display runs at an optimized 16 FPS using PIL dirty region tracking and 24 MHz SPI clock speed, keeping CPU usage below 12%.

---

## 📄 License
MIT License. Built for makers, robotics enthusiasts, and multilingual AI developers.
