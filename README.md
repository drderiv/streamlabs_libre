# StreamLabs Libre: Home Assistant Integration & Controller

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue)](https://www.home-assistant.io/)

**StreamLabs Libre** is a modern, subscription-free Home Assistant integration and standalone automation suite for StreamLabs Water Monitors and Shutoff Valves (StreamLabs Monitor & StreamLabs Control).

The official Home Assistant core integration lacks shutoff valve actuation and omits real-time flow telemetry. **StreamLabs Libre** implements the mobile application's cloud telemetry and authentication to bring native shutoff valve actuation, home/away mode switching, and real-time consumption sensors directly into Home Assistant.

---

## Key Features

- 🚰 **Native Valve Platform (`valve`):** Full open/close actuation of the motorized shutoff valve named **Water valve** matching the mobile app UI, with native Home Assistant valve controls (`mdi:valve-open`, `mdi:valve-closed`).
- 🏠 **Monitoring Mode (`select`):** Select between **Home** and **Away** modes directly from dashboards with instant optimistic UI updates and automated mode shifts based on home occupancy.
- 🌡️ **Environmental Telemetry Sensors (`sensor`):**
  - **Room Temperature** (`sensor.*_room_temperature`, °F / °C)
  - **Room Humidity** (`sensor.*_room_humidity`, %)
  - **Water Pressure** (`sensor.*_water_pressure`, psi)
  - **Water Temperature** (`sensor.*_water_temperature`, °F / °C)
- 💧 **Water Usage & Consumption Sensors (`sensor`):** 
  - Daily water consumption (gallons)
  - Monthly water consumption (gallons)
  - Yearly water consumption (gallons)
  - Location water usage today
- ⚡ **Binary Sensors (`binary_sensor`):**
  - Instantaneous water flow detection (`mdi:water-pump`)
  - Cloud connection status
  - Away mode state indicator (disabled by default in favor of the primary `select` control)
- ⚙️ **Configurable Polling Options Flow:** Adjust the update interval dynamically from 10 to 300 seconds (default: 60s) directly via **Configure** in Home Assistant.
- 🛠️ **Diagnostic Services:** Trigger remote calibration or routine drip detection runs (`run_drip_detect`, `calibrate`).
- 📍 **Multi-Location Support:** Seamlessly choose which locations to monitor during setup if your account has multiple homes or properties.
- 🔐 **AWS Cognito SRP Flow:** Direct, decoupled token exchange using `pycognito` and automated 3600-second session renewals.

---

## Installation

### Method 1: HACS (Recommended)

1. Open **HACS** in your Home Assistant instance.
2. Click the three dots in the top right corner and select **Custom repositories**.
3. Paste the URL of this repository: `https://github.com/drderiv/streamlabs_libre`
4. Select category: **Integration**.
5. Click **Add**, find **StreamLabs Libre**, and click **Download**.
6. Restart Home Assistant.

### Method 2: Manual Installation

1. Copy the `custom_components/streamlabs_libre` directory from this repository into your Home Assistant `<config>/custom_components/` directory:
   ```bash
   cp -r custom_components/streamlabs_libre /path/to/homeassistant/config/custom_components/
   ```
2. Restart Home Assistant.

---

## Configuration

1. In the Home Assistant UI, navigate to **Settings** -> **Devices & Services**.
2. Click **Add Integration** and search for **StreamLabs Libre**.
3. Enter your StreamLabs mobile application login credentials (email and password).
4. If your account contains multiple locations, select the location(s) you wish to monitor.
5. The devices, valve entities, and telemetry sensors will automatically appear under your Home Assistant devices.

### Polling Frequency (Options Flow)

To customize how frequently Home Assistant polls the StreamLabs cloud for telemetry updates:
1. Go to **Settings** -> **Devices & Services** -> **StreamLabs Libre**.
2. Click **Configure** on the integration entry.
3. Set your desired **Scan interval (seconds)** (between `10` and `300` seconds; defaults to `60` seconds).
4. Click **Submit**—Home Assistant will immediately reload the coordinator with the new polling interval.


---

## CLI Usage

For command-line testing or shell automation, a standalone CLI controller is included in `cli/streamlabs_cli.py`:

```bash
# Set your environment variables
export STREAMLABS_USER="user@example.com"
export STREAMLABS_PASS="your_password"

# Query account locations and device IDs
python3 cli/streamlabs_cli.py locations

# Query device status
python3 cli/streamlabs_cli.py status

# Actuate valve (open or close)
python3 cli/streamlabs_cli.py --device "<DEVICE_ID>" valve close
python3 cli/streamlabs_cli.py --device "<DEVICE_ID>" valve open

# Change monitoring mode (home or away)
python3 cli/streamlabs_cli.py --device "<DEVICE_ID>" mode away

# Fetch volumetric water usage breakdown
python3 cli/streamlabs_cli.py --device "<DEVICE_ID>" usage
```

---

## Discovered Hardware Commands

The StreamLabs API supports direct hardware maintenance routines via `POST /devices/{id}/command`:

| Command | Wire Payload | Purpose |
| :--- | :--- | :--- |
| **Set Valve** | `{"command": "set valve", "parameters": {"position": "open"\|"close"}}` | Actuates motorized valve |
| **Set Mode** | `{"mode": "home"\|"away"}` (PUT `/settings`) | Configures leak alert sensitivity |
| **Drip Detect** | `{"command": "run drip detect"}` | Performs a diagnostic slow-drip test |
| **Calibrate** | `{"command": "calibrate"}` | Triggers flow sensor recalibration |
| **Identify** | `{"command": "identify"}` | Blinks LED hardware ring |

---

## Completed Deliverables & Roadmap

- [x] Native Home Assistant HACS Integration (`custom_components/streamlabs_libre`)
- [x] Native `ValveEntity` with zero subscription requirement (named **Water valve**)
- [x] Environmental Telemetry: Room Temp, Room Humidity, Water Temp, Water Pressure
- [x] Optimistic UI mode switching (`Home` / `Away`)
- [x] Dynamic Polling Options Flow (`scan_interval` 10s–300s)
- [x] Multi-location selection flow
- [x] Standalone CLI controller (`streamlabs_cli.py`)
- [x] Standalone Dockerized MQTT Bridge service with Home Assistant MQTT Auto-Discovery ([mqtt_bridge/README.md](mqtt_bridge/README.md))

---

## License and Legal

This project is licensed under the [Apache License 2.0](LICENSE).  
Portions of the entity boilerplate are adapted from Home Assistant Core under the Apache License 2.0.
This integration is an independent open-source project and is not affiliated with, endorsed by, or supported by Chubb Limited or StreamLabs, Inc. All product names, trademarks, and registered trademarks are property of their respective owners.
