# StreamLabs Libre: Home Assistant Integration & Controller

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.8%2B-blue)](https://www.home-assistant.io/)

**StreamLabs Libre** is a subscription-free Home Assistant integration and standalone automation suite for StreamLabs Water Monitors and Shutoff Valves (StreamLabs Monitor & StreamLabs Control).

The official Home Assistant core integration lacks shutoff valve actuation and omits real-time flow telemetry. **StreamLabs Libre** implements nothing more than the free mobile application's cloud telemetry (less the WebSocket-based flow rate monitoring which is replaced with a REST-based estimate; see below) and authentication to bring native shutoff valve actuation, home/away mode switching, and real-time consumption sensors directly into Home Assistant.

---

## Key Features

- 🚰 **Native Valve Platform (`valve`):** Full open/close actuation of the motorized shutoff valve named **Water valve** matching the mobile app UI, with native Home Assistant valve controls (`mdi:valve-open`, `mdi:valve-closed`).
- 🏠 **Monitoring Mode (`select`):** Select between **Home** and **Away** modes directly from dashboards with instant UI updates and automated mode shifts based on home occupancy.
- 🌡️ **Environmental Telemetry Sensors (`sensor`):**
  - **Room Temperature** (`sensor.*_room_temperature`, °F / °C)
  - **Room Humidity** (`sensor.*_room_humidity`, %)
  - **Water Pressure** (`sensor.*_water_pressure`, psi)
  - **Water Temperature** (`sensor.*_water_temperature`, °F / °C)
- 💧 **Water Usage & Consumption Sensors (`sensor`):** 
  - **Estimated flow rate** (`sensor.*_estimated_flow_rate`, gpm / gal/min)
  - Daily water consumption (gallons)
  - Monthly water consumption (gallons)
  - Yearly water consumption (gallons, matching mobile app 13-month rolling history)
  - Location water usage today
- ⚡ **Binary Sensors (`binary_sensor`):**
  - Instantaneous water flow detection (`mdi:water-pump`)
  - Cloud connection status
  - Away mode state indicator (disabled by default in favor of the primary `select` control)
- ⚙️ **Dual-Rate Dynamic Polling Options Flow:**
  - **Water off interval**: Polling frequency when water is idle (10s–300s, default: 60s) to keep cloud traffic light.
  - **Water on interval**: Rapid polling frequency when water is actively running (10s–300s, default: 15s) to dynamically measure flow rate in real time.
  - **Smart Cache Optimization**: During rapid water-on polling, heavy historical and environmental endpoints are cached, limiting active bursts to just 2 lightweight requests per poll.
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

### Dual Polling Frequencies & Flow Rate Estimation (Options Flow)

To customize how frequently Home Assistant polls the StreamLabs cloud and configure real-time flow estimation:
1. Go to **Settings** -> **Devices & Services** -> **StreamLabs Libre**.
2. Click **Configure** on the integration entry.
3. Set your desired intervals:
   - **Water off polling interval (seconds)**: Used when water is idle (`10` to `300` seconds; defaults to `60` seconds).
   - **Water on polling interval (seconds)**: Used when water is running (`10` to `300` seconds; defaults to `15` seconds).
4. Click **Submit**—Home Assistant will immediately reload the coordinator.

**How Flow Rate Estimation Works**:
When water starts flowing, the coordinator dynamically accelerates to the rapid **Water on interval**. To guarantee reliable readings free of cloud artifacts, flow rate estimation implements two signal-smoothing stages:
1. **Pre-Sync Backlog Absorption (No Initial Spikes):** When flow begins, the cloud usage counter may lag behind the flow state. Rather than calculating rate across that delayed initial jump, the coordinator absorbs the first usage increment as the synchronized baseline, preventing false spike alarms (e.g. 13+ gpm).
2. **Double-Interval Moving Window (Jitter Smoothing):** During continuous flow, StreamLabs cloud packet batching can produce complementary high/low readings across adjacent single polls (e.g. 1.9 gpm followed by 3.0 gpm). The coordinator calculates flow rate across a **2-poll moving window** ($\approx 2 \times \text{Water on interval}$, using actual monotonic timestamps). This mathematically neutralizes packet boundary jitter on every poll without delaying real physical flow rate shifts:
$$\text{Estimated GPM} = \frac{\text{Usage}(t_n) - \text{Usage}(t_{n-2})}{(t_n - t_{n-2}) / 60}$$
When water is turned off, the sensor immediately resets to `0.0 gpm` and the coordinator returns to the gentle **Water off interval**.


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

## Hardware Commands

The StreamLabs API supports direct hardware maintenance routines via `POST /devices/{id}/command`:

| Command | Wire Payload | Purpose |
| :--- | :--- | :--- |
| **Set Valve** | `{"command": "set valve", "parameters": {"position": "open"\|"close"}}` | Actuates motorized valve |
| **Set Mode** | `{"mode": "home"\|"away"}` (PUT `/settings`) | Configures leak alert sensitivity |
| **Drip Detect** | `{"command": "run drip detect"}` | Performs a diagnostic slow-drip test |
| **Calibrate** | `{"command": "calibrate"}` | Triggers flow sensor recalibration |
| **Identify** | `{"command": "identify"}` | Blinks LED hardware ring |

---

## Upgrading to 2.0

Requires Home Assistant 2025.8 or newer. Breaking changes:

- The **Monitoring mode** select now uses the states `home` / `away` (shown as Home / Away in the UI). Update any template or automation that compared against `Home` / `Away`.
- The redundant **Gallons today** sensor and **Away mode** binary sensor were removed (use *Daily water usage* and the *Monitoring mode* select).
- The `streamlabs_libre.*` services now require a `device_id` chosen with the device picker (no more implicit "first device").
- *Monthly water usage* is now `total_increasing`; *Yearly water usage* is a rolling 13-month window and no longer has a state class.
- A changed password now raises a Home Assistant repair/re-authentication prompt, and entities become unavailable after about five consecutive failed polls instead of showing stale data forever.

## License and Legal

This project is licensed under the [Apache License 2.0](LICENSE).  
Portions of the entity boilerplate are adapted from Home Assistant Core under the Apache License 2.0.
This integration is an independent open-source project and is not affiliated with, endorsed by, or supported by Chubb Limited or StreamLabs, Inc. All product names, trademarks, and registered trademarks are property of their respective owners.
