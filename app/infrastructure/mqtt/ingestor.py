import logging

log = logging.getLogger(__name__)

_STATUS_DISABLED = "disabled"
_STATUS_CONNECTED = "ok"
_STATUS_RECONNECTING = "reconnecting"
_STATUS_ERROR = "error"


class MqttIngestor:
    """Subscriber MQTT que escucha 40db/sensores/+/lectura y persiste lecturas."""

    def __init__(self):
        self._status = _STATUS_RECONNECTING
        self._client = None
        self._thread = None

    def start(self) -> None:
        import paho.mqtt.client as mqtt
        from app.core.config import settings

        client = mqtt.Client(client_id=settings.mqtt_client_id)
        client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
        client.tls_set()

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        broker_url = settings.mqtt_broker_url.replace("ssl://", "")
        host, port = broker_url.rsplit(":", 1)

        client.connect_async(host, int(port), keepalive=60)
        client.loop_start()
        self._client = client

    def stop(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def status(self) -> str:
        return self._status

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._status = _STATUS_CONNECTED
            client.subscribe("40db/sensores/+/lectura", qos=1)
            log.info("MQTT conectado y suscrito a 40db/sensores/+/lectura")
        else:
            self._status = _STATUS_RECONNECTING
            log.warning("MQTT on_connect rc=%d", rc)

    def _on_disconnect(self, client, userdata, rc):
        self._status = _STATUS_RECONNECTING
        log.warning("MQTT desconectado rc=%d, paho reintentará", rc)

    def _on_message(self, client, userdata, msg):
        import json

        # Extraer sensor_id del topic: 40db/sensores/{sensor_id}/lectura
        parts = msg.topic.split("/")
        if len(parts) != 4:
            log.warning("MQTT topic inesperado: %s", msg.topic)
            return

        sensor_id = parts[2]

        try:
            payload = json.loads(msg.payload)
        except Exception:
            log.warning("MQTT payload no es JSON válido sensor=%s", sensor_id)
            return

        nivel_db = payload.get("nivel_db")
        ts_str = payload.get("timestamp_medicion")

        # Validaciones básicas (iot.md §3.2)
        if nivel_db is None or ts_str is None:
            log.warning("MQTT payload incompleto sensor=%s", sensor_id)
            return
        if not (20 <= float(nivel_db) <= 130):
            log.warning("MQTT nivel_db fuera de rango sensor=%s nivel_db=%s", sensor_id, nivel_db)
            return

        try:
            from app.application.registrar_lectura import registrar_lectura
            registrar_lectura(sensor_id=sensor_id, nivel_db=nivel_db, timestamp_medicion=ts_str)
        except Exception:
            log.exception("MQTT error procesando lectura sensor=%s", sensor_id)
