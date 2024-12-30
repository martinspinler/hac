import time
import threading
import json

import paho.mqtt.client as mqtt_client
from bsbcontroller.types import Command


class MqttBsbClient(threading.Thread):
    items = {}
    translations = {}
    corrections = {}
    enabled_requests = {}

    def __init__(self, bsb):
        threading.Thread.__init__(self)

        client = self._client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION1, "bsb")

        client.on_connect = self._on_connect
        client.on_message = self._on_message

        self._bsb = bsb

        self._values = {}
        self._prefix = "home/boiler"
        self._enabled_topics = []

    def connect(self, addr, port):
        while True:
            try:
                self._client.connect(addr, port, 60)
            except ConnectionRefusedError:
                time.sleep(5)
                continue
            else:
                break

    def loop_forever(self):
        self._client.loop_forever()

    def _on_connect(self, client, userdata, flags, rc):
        self._client.subscribe("#")
        self._bsb.callbacks.append(self._bsb_callback)
        self._bsb.loggers.append(self._bsb_log)

        self.setup_mqtt_ha_discovery()
        for request, template, *opt in self.items:
            self._bsb.get_value(request)

    def _on_message(self, client, userdata, msg):
        topic = msg.topic

        if topic.startswith(f"{self._prefix}/") and topic.endswith("/set"):
            request = topic.removeprefix(f"{self._prefix}/").removesuffix("/set")
            request = self.translations.get(request, request)

            if request in self.enabled_requests:
                func = self.enabled_requests[request]
                val = msg.payload.decode()
                if func is not None:
                    val = func(val)
                self._bsb.set_value(request, val)

    def _bsb_callback(self, name, value):
        request = self.translations.get(name, name)
        if request in self._enabled_topics:
            added = False
            if request not in self._values:
                self._values[request] = None
                added = True

            if request in self.corrections:
                value = self.corrections[request](value)

            if value != self._values[request] or added:
                self._values[request] = value
                self._client.publish(f"{self._prefix}/{request}/state", value, retain=True)

    def _bsb_log(self, telegram):
        if telegram.cmd in [Command.INF]:
            self._bsb_callback(telegram.name, telegram.value)

    def _publish_config(self, request, payload_template, component="sensor"):
        name = self.translations.get(request, request)
        payload = payload_template | {
            "~": f"{self._prefix}/{name}",
            "name": name,
            "uniq_id": name,
        }

        self._client.publish(topic=f"homeassistant/{component}/boiler/{name}/config", payload=json.dumps(payload), qos=0, retain=True)
        self._enabled_topics.append(request)

    def setup_mqtt_ha_discovery(self):
        for request, template, *opt in self.items:
            kwargs = opt[0] if opt else {}
            #print(name, template, kwargs)
            self._publish_config(request, template, **kwargs)
