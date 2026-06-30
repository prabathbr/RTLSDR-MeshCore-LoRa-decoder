"""Shared IQ / lorarx helpers for meshcore_win (Windows RTL-SDR path)."""

from __future__ import annotations

import json
import logging
import socket
import sys
import threading
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

IF_RATE = 1_000_000

# AU915 narrow MeshCore (bands.json: meshcore 916575000)
DEFAULT_FREQ = 916_575_000
DEFAULT_BW = 6          # lorarx index 6 = 62.5 kHz
DEFAULT_SPREADING = (7,)
DEFAULT_CR = None       # read CR from LoRa header
DEFAULT_MESHCORE_NET = 18
DEFAULT_HEX_VIEW = 5

logger = logging.getLogger("meshcore_common")


def find_lorarx() -> str:
    """Prefer ./bin/lorarx.exe next to project root."""
    base = Path(__file__).resolve().parent.parent / "bin"
    local = base / "lorarx.exe"
    if local.is_file():
        return str(local)
    return "lorarx.exe"


class TcpFanout:
    """Broadcast newline-terminated text to all connected TCP clients."""

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(8)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info("TCP output listening on %s:%d", host, port)

    def _accept_loop(self) -> None:
        while True:
            try:
                client, _addr = self._sock.accept()
            except OSError:
                return
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self._lock:
                self._clients.append(client)

    def publish(self, line: str) -> None:
        payload = (line.rstrip("\n") + "\n").encode("utf-8")
        dead: list[socket.socket] = []
        with self._lock:
            for client in self._clients:
                try:
                    client.sendall(payload)
                except OSError:
                    dead.append(client)
            for client in dead:
                self._clients.remove(client)
                client.close()

    def close(self) -> None:
        with self._lock:
            for client in self._clients:
                client.close()
            self._clients.clear()
        self._sock.close()


def build_lorarx_cmd(
    lorarx: str,
    sample_rate: int,
    bandwidth: int,
    spreading: Iterable[int],
    sync_word: int = DEFAULT_HEX_VIEW,
    coding_rate: Optional[int] = DEFAULT_CR,
    net_id: Optional[int] = DEFAULT_MESHCORE_NET,
    chirp_ppm: Optional[float] = None,
) -> list[str]:
    """Build lorarx command line for MeshCore."""
    cmd = [
        lorarx,
        "-i",
        "-",
        "-r",
        str(sample_rate),
        "-f",
        "f32",
        "-v",
        "-N",
        "-Q",
        "-H",
        str(sync_word),
        "-W",
        "50",
        "-b",
        str(bandwidth),
    ]
    if net_id is not None:
        cmd += ["-X", str(net_id)]
    if chirp_ppm is not None and abs(chirp_ppm) > 0.001:
        cmd += ["-P", f"{chirp_ppm:.3f}"]
    if coding_rate is not None:
        cmd += ["-c", str(coding_rate)]
    for sf in spreading:
        cmd += ["-s", str(sf)]
    cmd += ["-j", "-"]
    return cmd


def decimate_iq(iq: np.ndarray, input_rate: int, output_rate: int) -> np.ndarray:
    if input_rate == output_rate:
        return iq
    if input_rate % output_rate != 0:
        raise ValueError(
            f"input rate {input_rate} must be an integer multiple of {output_rate}"
        )
    factor = input_rate // output_rate
    padded = np.pad(iq, (0, (-len(iq)) % factor), mode="constant")
    shaped = padded.reshape(-1, factor)
    return shaped.mean(axis=1)


def shift_iq(
    iq: np.ndarray, sample_rate: int, offset_hz: float, phase: float
) -> tuple[np.ndarray, float]:
    if offset_hz == 0.0:
        return iq, phase
    rot = np.exp(
        -1j
        * (
            2.0
            * np.pi
            * offset_hz
            * (np.arange(len(iq), dtype=np.float64) / sample_rate)
            + phase
        )
    ).astype(np.complex64)
    new_phase = (
        phase + 2.0 * np.pi * offset_hz * (len(iq) / sample_rate)
    ) % (2.0 * np.pi)
    return iq * rot, new_phase


def enrich_packet(line: str, frequency_hz: int) -> str:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return line
    obj.setdefault("mode", "MESHCORE")
    obj.setdefault("freq", frequency_hz)
    obj.setdefault("region", "AU915")
    return json.dumps(obj, separators=(",", ":"))
