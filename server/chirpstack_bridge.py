from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import ssl
import time
import urllib.error
import urllib.request

import paho.mqtt.client as mqtt


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def forward_uplink(event: dict) -> None:
    api_url = required("MOLIDO_CHIRPSTACK_INGEST_URL")
    secret = required("MOLIDO_CHIRPSTACK_INGEST_SECRET")
    if len(secret) < 32:
        raise RuntimeError("MOLIDO_CHIRPSTACK_INGEST_SECRET must contain at least 32 characters")
    body = json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    signed = timestamp.encode() + b"." + nonce.encode() + b"." + body
    signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        api_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-ChirpStack-Signature": f"{timestamp}:{nonce}:{signature}",
        },
        method="POST",
    )
    context = ssl.create_default_context(cafile=os.environ.get("MOLIDO_API_CA_CERT") or None)
    with urllib.request.urlopen(request, timeout=10, context=context) as response:
        if response.status not in (200, 201):
            raise RuntimeError(f"Molido API returned HTTP {response.status}")
        response.read(4096)


def main() -> None:
    host = required("CHIRPSTACK_MQTT_HOST")
    port = int(os.environ.get("CHIRPSTACK_MQTT_PORT", "8883"))
    username = required("CHIRPSTACK_MQTT_USERNAME")
    password = required("CHIRPSTACK_MQTT_PASSWORD")
    ca_cert = required("CHIRPSTACK_MQTT_CA_CERT")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="molido-agro-chirpstack-bridge")
    client.username_pw_set(username, password)
    client.tls_set(ca_certs=ca_cert, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.tls_insecure_set(False)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            raise RuntimeError(f"ChirpStack MQTT connection rejected: {reason_code}")
        client.subscribe("application/+/device/+/event/up", qos=1)

    def on_message(client, userdata, message):
        try:
            event = json.loads(message.payload.decode("utf-8"))
            device_info = event.get("deviceInfo") or {}
            if not device_info.get("devEui") or "fCnt" not in event:
                raise ValueError("Uplink is missing deviceInfo.devEui or fCnt")
            forward_uplink(event)
        except (ValueError, KeyError, urllib.error.URLError, RuntimeError) as exc:
            # Do not log payloads, credentials, or decoded agricultural telemetry.
            print(f"Uplink forwarding failed: {type(exc).__name__}: {exc}", flush=True)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
