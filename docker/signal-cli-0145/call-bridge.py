#!/usr/bin/env python3
"""Minimal, owner-only Signal voice-call proof of concept.

Subscribes directly to signal-cli's JSON-RPC daemon, accepts calls from
BRIEFING_RECIPIENT, records the remote audio, plays a local WAV, then hangs up.
It intentionally does not invoke the LLM yet: this proves Signal/RingRTC and
PulseAudio transport before the conversational loop is coupled to it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import time
from pathlib import Path


RPC_HOST = os.getenv("SIGNAL_CALL_RPC_HOST", "127.0.0.1")
RPC_PORT = int(os.getenv("SIGNAL_CALL_RPC_PORT", "6001"))
OWNER = os.getenv("BRIEFING_RECIPIENT", "").strip()
OWNER_ENV_FILE = Path(os.getenv("SIGNAL_CALL_ENV_FILE", "/run/config/signal-bot.env"))
GREETING = Path(os.getenv("SIGNAL_CALL_GREETING", "/usr/local/share/signal-call-greeting.wav"))
PLAYBACK_SECONDS = float(os.getenv("SIGNAL_CALL_PLAYBACK_SECONDS", "1"))
CAPTURE_DIR = Path(os.getenv("SIGNAL_CALL_CAPTURE_DIR", "/tmp/signal-call-captures"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("signal-call-bridge")


def normalize_number(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    digits = re.sub(r"\D", "", value)
    return f"+{digits}" if digits else ""


def read_env_file(name: str) -> str:
    """Read one setting from the shared bot env without exporting its secrets."""
    try:
        lines = OWNER_ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    prefix = f"{name}="
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value.strip()
    return ""


def is_owner(event: dict) -> bool:
    return bool(OWNER) and normalize_number(event.get("number")) == normalize_number(OWNER)


class Rpc:
    def __init__(self) -> None:
        self.sock = socket.create_connection((RPC_HOST, RPC_PORT), timeout=10)
        self.sock.settimeout(None)
        self.stream = self.sock.makefile("rwb", buffering=0)
        self.next_id = 0
        self.responses: dict[int, dict] = {}

    def close(self) -> None:
        self.stream.close()
        self.sock.close()

    def send(self, method: str, params: dict | None = None) -> int:
        self.next_id += 1
        message = {"jsonrpc": "2.0", "method": method, "id": self.next_id}
        if params:
            message["params"] = params
        self.stream.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        return self.next_id

    def read(self) -> dict:
        line = self.stream.readline()
        if not line:
            raise ConnectionError("signal-cli JSON-RPC connection closed")
        return json.loads(line)

    def request(self, method: str, params: dict | None = None) -> object:
        request_id = self.send(method, params)
        while True:
            message = self.read()
            if message.get("id") != request_id:
                # No calls can arrive before subscribeCallEvents returns. Later
                # requests are issued only from within the event loop.
                continue
            if "error" in message:
                raise RuntimeError(f"{method}: {message['error']}")
            return message.get("result")


class CallBridge:
    def __init__(self, rpc: Rpc) -> None:
        self.rpc = rpc
        self.active_call: int | str | None = None
        self.capture: subprocess.Popen | None = None

    def call_method(self, method: str, call_id: int | str) -> None:
        self.rpc.send(method, {"call-id": call_id})

    def stop_capture(self) -> None:
        if self.capture and self.capture.poll() is None:
            self.capture.terminate()
            try:
                self.capture.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.capture.kill()
        self.capture = None

    def on_event(self, event: dict) -> None:
        state = event.get("state")
        call_id = event.get("callId")
        log.info("call=%s state=%s peer=%s outgoing=%s", call_id, state, event.get("number") or event.get("uuid"), event.get("isOutgoing"))

        if state == "RINGING_INCOMING":
            if self.active_call is not None or not is_owner(event):
                log.warning("rejecting unauthorized or concurrent incoming call %s", call_id)
                self.call_method("rejectCall", call_id)
                return
            self.active_call = call_id
            self.call_method("acceptCall", call_id)
            return

        if call_id != self.active_call:
            return

        if state == "CONNECTED":
            input_device = event.get("inputDeviceName")
            output_device = event.get("outputDeviceName")
            if not input_device or not output_device:
                log.error("connected call has no audio devices")
                self.call_method("hangupCall", call_id)
                return

            CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            capture_path = CAPTURE_DIR / f"call-{call_id}.wav"
            self.capture = subprocess.Popen([
                "parecord", f"--device={output_device}.monitor", "--rate=48000",
                "--channels=1", "--format=s16le", "--file-format=wav", str(capture_path),
            ])
            time.sleep(max(0, PLAYBACK_SECONDS))
            playback_device = f"sink_for_{input_device}"
            result = subprocess.run(["paplay", f"--device={playback_device}", str(GREETING)], check=False)
            if result.returncode:
                log.error("greeting playback failed with status %s", result.returncode)
            self.call_method("hangupCall", call_id)
            return

        if state == "ENDED":
            self.stop_capture()
            self.active_call = None


def run() -> None:
    global OWNER
    OWNER = OWNER or read_env_file("BRIEFING_RECIPIENT")
    if not OWNER:
        raise SystemExit("BRIEFING_RECIPIENT is required; refusing to accept any calls")
    if not GREETING.is_file():
        raise SystemExit(f"call greeting does not exist: {GREETING}")

    while True:
        rpc = None
        bridge = None
        try:
            rpc = Rpc()
            bridge = CallBridge(rpc)
            rpc.request("subscribeCallEvents")
            log.info("subscribed to Signal calls; authorized caller is %s", normalize_number(OWNER))
            while True:
                message = rpc.read()
                if message.get("method") == "callEvent":
                    bridge.on_event(message.get("params", {}).get("callEvent", {}))
        except Exception:
            log.exception("call bridge disconnected; retrying")
            if bridge:
                bridge.stop_capture()
            if rpc:
                try:
                    rpc.close()
                except OSError:
                    pass
            time.sleep(5)


if __name__ == "__main__":
    run()
