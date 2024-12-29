#!/usr/bin/env python3
import time
import datetime
import logging

from bsbcontroller import Bsb
from bsbcontroller.types import Command
from bsbcontroller.datatypes import TFOpMode

from logger import ThreadHttpLogServer, MyLogger
from mqtt import MqttBsbClient
from functools import partial

import mqtt_templates as tl


logger = logging.getLogger("HAC")
logging.basicConfig(level=logging.INFO)

client_ip, client_port = "127.0.0.1", 1883
bsb_port = "/dev/ttyAMA3"

list_hc_modes = list(TFOpMode.values.values())

boiler_requests = [
    ("room1_temp",               600, tl.meas),
    ("room2_temp",               600, tl.meas),
    ("outer_temp",               600, tl.meas),
    ("boiler_temp",               60, tl.temp | tl.prec(2)),
    ("boiler_return_temp",        60, tl.temp | tl.prec(2)),
    ("flue_temp",                 60, tl.temp | tl.prec(2)),
    ("boiler_water_temp",         60, tl.temp | tl.prec(2)),
    ("pump_modulation_pct",       60, tl.base | tl.power_factor),
    ("burner_modulation_pct",     60, tl.base | tl.power_factor),
    ("burner_start_count",       300, tl.base | tl.total_increasing),
    ("gas_consumption",          300, tl.base | tl.total_increasing | tl.energy),
    ("water_pressure",           300, tl.meas | tl.pressure),
    ("hc_boiler_status",          30, tl.base),
    ("hc1_mode",                  60, tl.base),
    ("hc2_mode",                  60, tl.base),
    ("room1_temp_req",          None, tl.temp | tl.req_temp, dict(component="number")),
    ("room2_temp_req",          None, tl.temp | tl.req_temp, dict(component="number")),
    ("hc1_operating_mode",      None, tl.base | tl.req | {"options": list_hc_modes}, dict(component="select")),
    ("hc2_operating_mode",      None, tl.base | tl.req | {"options": list_hc_modes}, dict(component="select")),
    ("hc2_enabled",             None, tl.base | tl.req, dict(component="switch")),
    ("hot_water_push",          None, tl.base | tl.req, dict(component="button")),
    ("hc1_rampup_max_temp",     None, tl.temp | tl.req_temp | dict(min=30, max=60, step=2), dict(component="number")),
    ("hc2_rampup_max_temp",     None, tl.temp | tl.req_temp | dict(min=30, max=60, step=2), dict(component="number")),
]

monitored_items = {name: time for name, time, *_ in boiler_requests}

monitored_items |= {
    "room2_req_comfort_temp": None,
    "room2_req_reduced_temp": None,
}


class MyMqttBsbClient(MqttBsbClient):
    items = [(name, template, *params) for name, _, template, *params in boiler_requests]
    corrections = {
        "pump_modulation_pct":      lambda x: x or 0,
        "burner_modulation_pct":    lambda x: x or 0,
        "hc2_enabled":              lambda x: "ON" if x else "OFF",
    }
    translations = {
        "room1_temp_status":        "room1_temp",
        "outer_temp":               "outside_temperature",
        "hc_boiler_status":         "boiler_heating_status",
    }
    enabled_requests = {
        "room1_temp_req": float,
        "hc1_rampup_max_temp": float,
        "hc1_operating_mode": None,
        "hc2_operating_mode": None,
        "hc2_enabled": lambda x: x == "ON",
        "hot_water_push": lambda x: x == "PRESS",
    }


def bsb_onetime_init(bsb):
    bsb.set_value("datetime", datetime.datetime.now())

    #bsb.set_value("hc2_enabled", False)
    #bsb.set_value("hot_water_push", True)
    #bsb.set_value('room1_req_comfort_temp', 20.0)
    #bsb.set_value("room2_temp_status", 25.0, cmd=Command.INF)
    #bsb.set_value('hc1_operating_mode', 'reduced')
    #bsb.set_value('hc2_enabled', False)
    #bsb.set_value('hc2_operating_level', 'comfort')
    #bsb.set_value("room2_temp_status", 18.25)

    #bsb.get_value("hc1_status_qa")
    #bsb.get_value("status_msg2_qa")
    #bsb.get_value("hc1_time_prog_mon")

    #bsb.set_value('room1_req_comfort_temp', 20.0)
    #bsb.set_value('hc1_operating_mode', 'automatic')
    #bsb.set_value('hot_water_operating_mode', True)

    #days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    #for i in days[0:5]: bsb.set_value(f'hc1_time_prog_{i}', '5:00-6:30 16:00-22:00')
    #for i in days[5:7]: bsb.set_value(f'hc1_time_prog_{i}', '6:30-22:00')

    #for i in days[0:5]: bsb.set_value(f'hot_water_time_prog_{i}', '5:20-6:30 16:00-22:30')
    #for i in days[5:7]: bsb.set_value(f'hot_water_time_prog_{i}', '6:30-8:30 11:00-13:00 16:00-22:00')

    #bsb.set_value("hc1_time_prog_mon", "05:00-06:30 16:00-22:00")
    #bsb.get_value('hc1_time_prog_mon')


class MyBsbHandler():
    react = {
        "hc1_status": "room1_temp_req",
        "hc2_status": "room2_temp_req",
    }
    ignored = [
        Command.QUR,
    ]

    def __init__(self, bsb):
        def sag(bsb, req): # sleep and get
            time.sleep(2)
            bsb.get_value(req)

        self._bsb = bsb
        self._react = {k: partial(sag, bsb, v) for k, v in self.react.items()}

    def bsb_log_handler(self, telegram):
        if telegram.cmd not in self.ignored:
            logger.info(str(telegram))

        if telegram.name in self._react:
            # The program can have changed the requested temperature
            self._react[telegram.name]()


def main():
    bsb = Bsb(bsb_port)
    bsb.set_monitored(monitored_items)

    bsb.loggers.append(MyBsbHandler(bsb).bsb_log_handler)
    ThreadHttpLogServer(MyLogger(bsb))

    bsb.start()

    bsb_onetime_init(bsb)
    client = MyMqttBsbClient(bsb)
    client.connect(client_ip, client_port)

    try:
        client.loop_forever()
    except Exception:
        bsb.stop()
        raise


if __name__ == "__main__":
    main()
