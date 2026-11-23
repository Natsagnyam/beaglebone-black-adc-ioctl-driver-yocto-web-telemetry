#!/usr/bin/env python3
"""Web server and telemetry API for BeagleBone frequency driver with Virtual POT."""

import fcntl
import json
import math
import os
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
INDEX_HTML = WEB_DIR / "index.html"
DEVICE_PATH = os.getenv("BBB_FREQ_DEVICE", "/dev/bbb_freq")
HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT", "8000"))

IOCTL_REQ_ENV = os.getenv("BBB_FREQ_IOCTL_REQ")
IOCTL_FMT_ENV = os.getenv("BBB_FREQ_IOCTL_FMT")

MIN_HZ = 45.0
MAX_HZ = 65.0
ADC_MAX = 4095

POT_LOCK = threading.Lock()
VIRTUAL_POT_ADC = None  # None = auto sine wave; 0..4095 = manual virtual POT


def adc_to_freq_hz(adc_raw: int) -> float:
    clamped = max(0, min(ADC_MAX, int(adc_raw)))
    return round(MIN_HZ + (clamped / ADC_MAX) * (MAX_HZ - MIN_HZ), 3)


def freq_to_adc_raw(freq_hz: float) -> int:
    clamped_hz = max(MIN_HZ, min(MAX_HZ, float(freq_hz)))
    return int(round(((clamped_hz - MIN_HZ) / (MAX_HZ - MIN_HZ)) * ADC_MAX))


def use_mock() -> bool:
    forced = os.getenv("MOCK_TELEMETRY", "0").strip().lower() in ("1", "true", "yes", "on")
    return forced or not os.path.exists(DEVICE_PATH)


def read_mock_telemetry() -> dict:
    now_ms = int(time.time() * 1000)
    with POT_LOCK:
        manual_adc = VIRTUAL_POT_ADC

    if manual_adc is not None:
        adc_raw = max(0, min(ADC_MAX, int(manual_adc)))
        return {
            "adc_raw": adc_raw,
            "frequency_hz": adc_to_freq_hz(adc_raw),
            "timestamp_ms": now_ms,
            "mode": "virtual-pot",
        }

    elapsed = time.monotonic()
    freq_hz = round(50.0 + 0.25 * math.sin(2.0 * math.pi * 0.2 * elapsed), 3)
    return {
        "adc_raw": freq_to_adc_raw(freq_hz),
        "frequency_hz": freq_hz,
        "timestamp_ms": now_ms,
        "mode": "auto-mock",
    }


def read_hardware_telemetry() -> dict:
    now_ms = int(time.time() * 1000)

    if IOCTL_REQ_ENV and IOCTL_FMT_ENV:
        req = int(IOCTL_REQ_ENV, 0)
        buf = bytearray(struct.calcsize(IOCTL_FMT_ENV))
        with open(DEVICE_PATH, "rb+", buffering=0) as dev:
            fcntl.ioctl(dev.fileno(), req, buf, True)
        unpacked = struct.unpack(IOCTL_FMT_ENV, buf)
        adc_raw = int(unpacked[0])
        freq_hz = round(float(unpacked[1]), 3)
        ts_ms = int(unpacked[2]) if len(unpacked) > 2 else now_ms
        return {
            "adc_raw": adc_raw,
            "frequency_hz": freq_hz,
            "timestamp_ms": ts_ms,
            "mode": "hardware-ioctl",
        }

    with open(DEVICE_PATH, "rb", buffering=0) as dev:
        raw_bytes = dev.read(256)

    text = raw_bytes.decode("utf-8", errors="ignore").strip()
    if text.startswith("{"):
        payload = json.loads(text)
        payload.setdefault("timestamp_ms", now_ms)
        payload.setdefault("mode", "hardware")
        return payload

    parts = text.replace(",", " ").split()
    if len(parts) >= 2:
        return {
            "adc_raw": int(float(parts[0])),
            "frequency_hz": round(float(parts[1]), 3),
            "timestamp_ms": now_ms,
            "mode": "hardware",
        }

    raise ValueError(f"Unrecognized payload from {DEVICE_PATH}: {text!r}")


def get_telemetry() -> dict:
    if use_mock():
        return read_mock_telemetry()
    try:
        return read_hardware_telemetry()
    except OSError:
        return read_mock_telemetry()


class TelemetryHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status_code: int, content_type: str, body: bytes) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == "/api/frequency":
            try:
                self._send_json(200, get_telemetry())
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return

        if path in ("/", "/index.html"):
            if INDEX_HTML.is_file():
                self._send_bytes(200, "text/html; charset=utf-8", INDEX_HTML.read_bytes())
            else:
                self._send_json(404, {"error": f"Missing {INDEX_HTML.name}"})
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        global VIRTUAL_POT_ADC
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(length) if length > 0 else b"{}"

        if path == "/api/pot/reset":
            with POT_LOCK:
                VIRTUAL_POT_ADC = None
            self._send_json(200, get_telemetry())
            return

        if path == "/api/pot":
            try:
                payload = json.loads(raw_body.decode("utf-8") or "{}")
                if "adc_raw" in payload:
                    adc_val = int(payload["adc_raw"])
                elif "pot" in payload:
                    adc_val = int(round(float(payload["pot"]) * ADC_MAX))
                else:
                    self._send_json(400, {"error": "Provide adc_raw (0..4095) or pot (0..1)"})
                    return

                with POT_LOCK:
                    VIRTUAL_POT_ADC = max(0, min(ADC_MAX, adc_val))
                self._send_json(200, get_telemetry())
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return

        self._send_json(404, {"error": "Not found"})

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - - [{self.log_date_time_string()}] {fmt % args}", flush=True)


def main() -> None:
    mode_label = "mock" if use_mock() else f"device ({DEVICE_PATH})"
    server = ThreadingHTTPServer((HOST, PORT), TelemetryHandler)
    print(f"Serving on http://{HOST}:{PORT} [telemetry={mode_label}]", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
