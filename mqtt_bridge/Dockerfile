FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies
COPY mqtt_bridge/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY custom_components /app/custom_components
COPY mqtt_bridge /app/mqtt_bridge

# Run MQTT Bridge
ENTRYPOINT ["python3", "-m", "mqtt_bridge.bridge"]
