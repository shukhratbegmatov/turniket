#!/usr/bin/env python3
"""
ЕЭСБО (CultureTicket) <-> ZKTeco C3-200 turniket shlyuzi.

Ishlash tartibi:
  1. QR50BM o'quvchi chekdagi QR-kodni o'qiydi va matnni RS485 (USB adapter) orqali
     shu kompyuterga yuboradi.
  2. Skript QR matnidan "&ticket_id=...(&is_museum=true)" ni ajratib oladi.
  3. ЕЭСБО API: PUT /api/CultureTicket/ValidateTicketAsync  {"hashCode": ...}
  4. success=true bo'lsa -> C3 panelga (192.168.1.201:4370) "eshikni och" buyrug'i,
     rele N soniya yopiladi va turniket ochiladi.

Ishga tushirish:
  python turnstile_gateway.py                  # oddiy rejim (config.ini dan)
  python turnstile_gateway.py --test-open      # faqat panelni sinash: turniketni ochadi
  python turnstile_gateway.py --stdin          # QR o'quvchisiz: QR matnini klaviaturadan kiriting
"""
import argparse
import configparser
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qsl

import requests
from c3 import C3, controldevice, consts

HERE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("gateway")


# --------------------------------------------------------------------------- config
def load_config(path):
    cfg = configparser.ConfigParser()
    if not cfg.read(path, encoding="utf-8"):
        sys.exit(f"Config topilmadi: {path}  (config.example.ini dan nusxa oling)")
    return cfg


def setup_logging(cfg):
    level = getattr(logging, cfg.get("general", "log_level", fallback="INFO").upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    fh = RotatingFileHandler(os.path.join(HERE, "gateway.log"),
                             maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    logging.getLogger("c3").setLevel(logging.WARNING)


# --------------------------------------------------------------------------- QR parsing
def normalize_hash(raw: str):
    """QR matnidan ЕЭСБО hashCode yasaydi.

    Qabul qilinadigan ko'rinishlar:
      &ticket_id=UUID
      ticket_id=UUID&is_museum=true
      https://.../?ticket_id=UUID&agent=X   (agentning qo'shimcha parametrlari tashlab yuboriladi)
      UUID                                 (faqat kodning o'zi)
    """
    s = raw.strip().strip("\x00\x02\x03\r\n")
    if not s:
        return None
    if "?" in s:
        s = s.split("?", 1)[1]
    params = dict(parse_qsl(s.lstrip("&"), keep_blank_values=True))
    ticket_id = params.get("ticket_id")
    if not ticket_id:
        # Faqat GUID o'qilgan bo'lsa
        if len(s) == 36 and s.count("-") == 4:
            ticket_id = s
        else:
            return None
    h = f"&ticket_id={ticket_id}"
    if params.get("is_museum", "").lower() == "true":
        h += "&is_museum=true"
    return h


# --------------------------------------------------------------------------- ЕЭСБО API
class TicketApi:
    def __init__(self, cfg):
        a = cfg["api"]
        self.base = a["base_url"].rstrip("/")
        self.login = a["login"]
        self.password = a["password"]
        self.timeout = a.getfloat("timeout", 8)
        self.token_ttl = a.getint("token_refresh_minutes", 60) * 60
        self.verify_tls = a.getboolean("verify_tls", True)
        self.s = requests.Session()
        self.token = None
        self.token_time = 0
        self.lock = threading.Lock()

    def _url(self, path):
        return f"{self.base}/api/CultureTicket/{path}"

    def authenticate(self):
        r = self.s.post(self._url("Token"),
                        json={"login": self.login, "password": self.password},
                        timeout=self.timeout, verify=self.verify_tls)
        r.raise_for_status()
        data = r.json()
        tok = (data.get("result") or {}).get("accessToken")
        if not tok:
            raise RuntimeError(f"Token olinmadi: {data.get('error')}")
        self.token = tok
        self.token_time = time.time()
        log.info("ЕЭСБО: token olindi")

    def _headers(self):
        with self.lock:
            if not self.token or time.time() - self.token_time > self.token_ttl:
                self.authenticate()
            return {"Authorization": f"Bearer {self.token}"}

    def _call(self, method, path, body):
        for attempt in (1, 2):
            r = self.s.request(method, self._url(path), json=body,
                               headers=self._headers(),
                               timeout=self.timeout, verify=self.verify_tls)
            if r.status_code == 401 and attempt == 1:
                log.warning("401 — token yangilanmoqda")
                self.token = None
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {"error": {"message": r.text[:300]}}

    def ticket_info(self, hash_code):
        return self._call("POST", "TicketInfoAsync", {"hashCode": hash_code})

    def validate(self, hash_code):
        return self._call("PUT", "ValidateTicketAsync", {"hashCode": hash_code})


# --------------------------------------------------------------------------- C3 panel
class Panel:
    def __init__(self, cfg):
        p = cfg["panel"]
        self.host = p.get("ip", "192.168.1.201")
        self.port = p.getint("port", 4370)
        self.password = p.get("comm_password", "") or None
        self.door = p.getint("door", 1)
        self.open_seconds = p.getint("open_seconds", 5)
        self.dev = None
        self.lock = threading.Lock()

    def _ensure(self):
        if self.dev is not None and self.dev.is_connected():
            return
        self.dev = C3(self.host, self.port)
        if not self.dev.connect(self.password):
            self.dev = None
            raise ConnectionError(f"C3 panelga ulanib bo'lmadi {self.host}:{self.port}")
        log.info("C3 panel ulandi: %s SN=%s", self.host, self.dev.serial_number)

    def open(self):
        cmd = controldevice.ControlDeviceOutput(
            self.door, consts.ControlOutputAddress.DOOR_OUTPUT, self.open_seconds)
        with self.lock:
            for attempt in (1, 2):
                try:
                    self._ensure()
                    self.dev.control_device(cmd)
                    log.info("TURNIKET OCHILDI (eshik %d, %d s)", self.door, self.open_seconds)
                    return True
                except Exception as e:
                    log.error("Panel xatosi (%d-urinish): %s", attempt, e)
                    try:
                        if self.dev:
                            self.dev.disconnect()
                    except Exception:
                        pass
                    self.dev = None
            return False

    def keepalive_loop(self):
        """Panel sessiyasi uzilib qolmasligi uchun har 20 s da so'rov yuboradi."""
        while True:
            time.sleep(20)
            with self.lock:
                try:
                    self._ensure()
                    self.dev.get_rt_log()
                except Exception as e:
                    log.warning("Panel keepalive: %s", e)
                    self.dev = None


# --------------------------------------------------------------------------- QR sources
def serial_reader(cfg, on_code):
    import serial
    r = cfg["reader"]
    port = r["serial_port"]
    baud = r.getint("baudrate", 9600)
    while True:
        try:
            with serial.Serial(port, baud, timeout=0.15) as ser:
                log.info("QR o'quvchi ulandi: %s @ %d", port, baud)
                buf = b""
                while True:
                    chunk = ser.read(512)
                    if chunk:
                        buf += chunk
                        # Qator oxiri bo'lsa — darhol
                        while b"\r" in buf or b"\n" in buf:
                            idx = min(i for i in (buf.find(b"\r"), buf.find(b"\n")) if i >= 0)
                            line, buf = buf[:idx], buf[idx + 1:]
                            if line.strip():
                                on_code(line.decode("utf-8", "ignore"))
                    elif buf:
                        # Terminator yo'q, lekin pauza bo'ldi — butun paketni olamiz
                        on_code(buf.decode("utf-8", "ignore"))
                        buf = b""
        except Exception as e:
            log.error("Serial port xatosi (%s): %s — 3 s dan keyin qayta", port, e)
            time.sleep(3)


def stdin_reader(on_code):
    print("QR matnini kiriting (Ctrl+C — chiqish):")
    for line in sys.stdin:
        if line.strip():
            on_code(line)


# --------------------------------------------------------------------------- main logic
class Gateway:
    def __init__(self, cfg):
        self.api = TicketApi(cfg)
        self.panel = Panel(cfg)
        self.check_info = cfg.getboolean("general", "call_ticket_info", fallback=False)
        self.debounce = cfg.getfloat("general", "same_code_ignore_seconds", fallback=4)
        self.last = {}
        self.busy = threading.Lock()

    def handle(self, raw):
        hash_code = normalize_hash(raw)
        if not hash_code:
            log.warning("Noma'lum QR: %r", raw[:120])
            return
        now = time.time()
        if now - self.last.get(hash_code, 0) < self.debounce:
            return  # o'quvchi bir kodni ketma-ket bir necha marta yuboradi
        self.last[hash_code] = now
        if not self.busy.acquire(blocking=False):
            log.info("Oldingi so'rov tugamagan, o'tkazildi")
            return
        try:
            self._process(hash_code)
        finally:
            self.busy.release()

    def _process(self, hash_code):
        log.info("QR: %s", hash_code)
        try:
            if self.check_info:
                code, info = self.api.ticket_info(hash_code)
                log.info("TicketInfo [%s]: %s", code, str(info)[:400])
                if code != 200 or info.get("error"):
                    log.warning("RAD ETILDI (info): %s", (info.get("error") or {}).get("message"))
                    return
            code, res = self.api.validate(hash_code)
        except Exception as e:
            log.error("ЕЭСБО bilan aloqa yo'q: %s — turniket OCHILMADI", e)
            return
        ok = code == 200 and not res.get("error") and (res.get("result") or {}).get("success")
        if ok:
            log.info("BILET QABUL QILINDI")
            self.panel.open()
        else:
            msg = (res.get("error") or {}).get("message") or res
            log.warning("RAD ETILDI [%s]: %s", code, msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default=os.path.join(HERE, "config.ini"))
    ap.add_argument("--test-open", action="store_true", help="faqat turniketni ochib ko'rish")
    ap.add_argument("--test-api", action="store_true", help="faqat ЕЭСБО token/GetMe sinovi")
    ap.add_argument("--stdin", action="store_true", help="QR ni klaviaturadan kiritish")
    args = ap.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg)

    if args.test_open:
        sys.exit(0 if Panel(cfg).open() else 1)

    gw = Gateway(cfg)

    if args.test_api:
        gw.api.authenticate()
        r = gw.api.s.get(gw.api._url("GetMe/GetMe"), headers=gw.api._headers(),
                         timeout=gw.api.timeout, verify=gw.api.verify_tls)
        print(r.status_code, r.text[:800])
        return

    try:
        gw.api.authenticate()
    except Exception as e:
        log.error("Boshlang'ich token olinmadi (keyinroq qayta uriniladi): %s", e)
    try:
        gw.panel._ensure()
    except Exception as e:
        log.error("%s", e)
    threading.Thread(target=gw.panel.keepalive_loop, daemon=True).start()

    if args.stdin:
        stdin_reader(gw.handle)
    else:
        serial_reader(cfg, gw.handle)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
