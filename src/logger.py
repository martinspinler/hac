import time
import datetime
import logging
from os import linesep


import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import json

from bsbcontroller.types import Command
from bsbcontroller.telegram import Telegram


logger = logging.getLogger("HAC")


class HttpLogHandler(BaseHTTPRequestHandler):
    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()

    def do_HEAD(self):
        self._set_headers()

    def do_GET(self):
        self._set_headers()
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        logs = self.server.logger.logs
        bsb = self.server.logger.bsb

        if query.get("get"):
            req = query.get("get")[0]
            val = bsb.get_value(req)
            self.wfile.write(json.dumps(val, indent=4).encode('utf8'))
            return
        elif query.get("set"):
            req = query.get("set")[0]
            val = query.get("val")[0]
            try:
                val = json.loads(val)
            except Exception:
                try:
                    val = json.loads(val.lower())
                except Exception:
                    pass
            bsb.set_value(req, val)
            return

        log = query.get("log", logs.keys())
        msg = query.get("msg", [])
        ex_msg = query.get("exclude", [])

        val = {
            lk: [
                str(t) for t in lv if (not msg or t.name in msg) and (t.name not in ex_msg)
            ] for lk, lv in logs.items() if lk in log
        }

        try:
            self.wfile.write(json.dumps(val, indent=4).encode('utf8'))
        except IOError:
            pass


class ThreadHttpLogServer(threading.Thread):
    def __init__(self, logger, addr='', port=8008):
        threading.Thread.__init__(self)

        self.logger = logger
        self.addr = addr
        self.port = port
        self.daemon = True
        self.start()

    def run(self):
        server = self.server = HTTPServer((self.addr, self.port), HttpLogHandler)
        server.logger = self.logger
        server.serve_forever()


class TelegramLogger:
    def __init__(self, bsb, filters):
        self.bsb = bsb
        bsb.loggers.append(self.log_callback)

        filename = "/srv/hac/telegram_log.json"

        self.logs = {k: [] for k in filters.keys()}
        self.filters = filters

        if False:
            try:
                self.file = open(filename)
                for ln in self.file.readlines():
                    try:
                        m = json.loads(ln)
                    except Exception as e:
                        logger.warning(f"Can't load json: {e}")
                        continue

                    ts = datetime.datetime.fromtimestamp(m['timestamp'])
                    t = Telegram.from_raw(bytes(m['telegram_raw']), timestamp=ts)

                    self._append_log(t)
                self.file.close()
            except Exception as e:
                logger.warning(f"Can't load json: {e}")

        self.file = open("/srv/hac/telegram_log.json", "a")

    def log_callback(self, t):
        o = {
            "timestamp": time.time(),
            "telegram_raw": list(t.to_raw())
        }

        self._append_log(t)

    def _append_log(self, t):
        for k, (fn, max_cnt) in self.filters.items():
            log = self.logs[k]
            if fn(t):
                log.append(t)
                if len(log) > max_cnt:
                    log.pop(0)


class MyLogger(TelegramLogger):
    def __init__(self, bsb):
        filters = {
            "all": (self.filter_all, 300),
            "inf": (self.filter_inf, 3000),
            "unk": (self.filter_unk, 3000),
            "nol": (self.filter_nol, 3000),
        }
        super().__init__(bsb, filters)

    def filter_all(self, t):
        if t.cmd == Command.QUR and t.src == 0x42:
            return False
        return True

    def filter_nol(self, t):
        if t.cmd == Command.QUR and t.src == 0x42:
            return False
        if t.cmd == Command.ANS and t.dst == 0x42:
            return False

        return True

    def filter_inf(self, t):
        if t.cmd != Command.INF:
            return False

        ignored = ["room1_temp_status", "datetime", "hc2_status", "hc3_status"]
        if t.name in ignored:
            return False

        return True

    def filter_unk(self, t):
        if not self.filter_inf(t):
            return False

        if t.name == "status_msg1":
            if t.data in [[x, 0, 0, 0x59] for x in [0, 0x4, 0x14]]:
                return False
        elif t.name == "hot_water_status":
            if t.data in [[0, x] for x in [0x45, 0x4d]]:
                return False
        elif t.name == "hc1_status":
            if t.data in [[0, x] for x in [0x45, 0x4d]]:
                return False
        #else:
        #    return False

        return True
