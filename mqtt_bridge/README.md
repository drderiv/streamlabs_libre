# StreamLabs MQTT Bridge

An independent, containerized daemon bridging StreamLabs Water Monitors & Shutoff Valves to any MQTT broker with **Home Assistant MQTT Auto-Discovery**.

---

## Architecture

```mermaid
flowchart LR
    StreamLabsCloud[StreamLabs API<br/>AWS Cognito SRP] <--> Bridge[StreamLabs MQTT Bridge]
    Bridge <--> Broker[MQTT Broker<br/>Mosquitto]
    Broker <--> HA[Home Assistant<br/>MQTT Integration]
```

### Published Topics

| Topic | Type | Description |
| :--- | :--- | :--- |
| `homeassistant/valve/.../config` | Config | Home Assistant MQTT Discovery entity definitions (retained) |
| `streamlabs/<device_id>/state` | State | Device telemetry JSON (valve, mode, flow, usage totals) |
| `streamlabs/<device_id>/availability` | Status | Device online/offline status |
| `streamlabs/bridge/state` | Status | Bridge service LWT status (`online` / `offline`) |
| `streamlabs/<device_id>/valve/set` | Command | Subscribed: `open` or `close` valve |
| `streamlabs/<device_id>/mode/set` | Command | Subscribed: `home` or `away` monitoring mode |
| `streamlabs/<device_id>/command/set` | Command | Subscribed: hardware diagnostics (e.g. `calibrate`, `run drip detect`) |

---

## Deployment Options

### Option 1: Docker Compose (Recommended)

1. Navigate to `mqtt_bridge/`:
   ```bash
   cd mqtt_bridge
   ```
2. Edit `docker-compose.yml` with your StreamLabs credentials and MQTT broker IP.
3. Launch container:
   ```bash
   docker compose up -d
   ```

### Option 2: Systemd Daemon

1. Copy service file:
   ```bash
   sudo cp mqtt_bridge/streamlabs-mqtt.service /etc/systemd/system/
   ```
2. Create environment file `/etc/default/streamlabs-mqtt`:
   ```bash
   STREAMLABS_USER=user@example.com
   STREAMLABS_PASS=your_password
   MQTT_BROKER=localhost
   MQTT_PORT=1883
   ```
3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now streamlabs-mqtt
   ```

### Option 3: Direct CLI

```bash
export STREAMLABS_USER="user@example.com"
export STREAMLABS_PASS="your_password"
export MQTT_BROKER="127.0.0.1"

python3 -m mqtt_bridge.bridge
```
