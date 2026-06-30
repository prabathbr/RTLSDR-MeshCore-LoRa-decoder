#!/usr/bin/env python3
"""
Windows MeshCore decoder for RTL-SDR (NESDR Smart v5, etc.)

  pyrtlsdr  ->  IQ shift/decimate  ->  lorarx.exe  ->  JSON  ->  MeshCore parse

Defaults: AU915 narrow — 916.575 MHz, 62.5 kHz (lorarx -b 6), SF7, explicit LoRa header

Prerequisites:
  1. Build lorarx:  invoke_build.cmd   (needs VS2019 vcvars64)
  2. Zadig WinUSB driver on the RTL-SDR
  3. librtlsdr.dll in bin/ (from rtlsdr-bin-w64_static.zip)
  4. conda env meshcore-decode + pip install -r requirements.txt
  5. See README.md in project root
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
_BIN_DIR = _ROOT / "bin"


def _setup_windows_dlls() -> None:
    """Load librtlsdr.dll from ./bin (osmocom rtlsdr-bin-w64_static.zip)."""
    if sys.platform != "win32" or not _BIN_DIR.is_dir():
        return
    bin_path = str(_BIN_DIR)
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(bin_path)
    os.environ["PATH"] = bin_path + os.pathsep + os.environ.get("PATH", "")


_setup_windows_dlls()

from meshcore_common import (
    DEFAULT_BW,
    DEFAULT_CR,
    DEFAULT_FREQ,
    DEFAULT_HEX_VIEW,
    DEFAULT_SPREADING,
    IF_RATE,
    TcpFanout,
    build_lorarx_cmd,
    decimate_iq,
    find_lorarx,
    shift_iq,
)
from meshcore_packet import JsonCaptureFile, build_packet_output, set_channel_keys
from meshcore_crypto import load_channel_keys_file, parse_channel_key_spec

_CHANNELS_FILE = _ROOT / "channels.txt"

DEFAULT_MESHCORE_NET = 18
MESHCORE_CRC_OK = 1

try:
    from rtlsdr import RtlSdr
except ImportError as exc:
    RtlSdr = None
    _RTL_IMPORT_ERROR = exc
else:
    _RTL_IMPORT_ERROR = None

logger = logging.getLogger("meshcore_win")


def find_lorarx_win() -> str:
    for name in ("lorarx.exe", "lorarx"):
        p = _BIN_DIR / name
        if p.is_file():
            return str(p)
    return find_lorarx()


def resample_iq(
    iq: np.ndarray, input_rate: float, output_rate: int
) -> np.ndarray:
    if abs(input_rate - output_rate) < 0.5:
        return iq
    in_rate = int(round(input_rate))
    if in_rate % output_rate == 0:
        return decimate_iq(iq, in_rate, output_rate)
    try:
        from math import gcd

        from scipy.signal import resample_poly

        g = gcd(in_rate, output_rate)
        return resample_poly(iq, output_rate // g, in_rate // g).astype(
            np.complex64
        )
    except ImportError:
        raise RuntimeError(
            f"SDR rate {input_rate:.3f} is not an integer multiple of {output_rate}. "
            "Install scipy: pip install scipy"
        )


class IqShiftTracker:
    """Shift IQ upstream to center MeshCore in lorarx (near-miss or valid CRC)."""

    def __init__(
        self,
        initial_hz: float = 0.0,
        alpha: float = 0.3,
        min_snr_valid: float = 4.0,
        min_snr_near: float = 3.0,
        tune_valid: bool = False,
        tune_near_miss: bool = True,
    ):
        self._lock = threading.Lock()
        self._shift_hz = initial_hz
        self._alpha = alpha
        self._min_snr_valid = min_snr_valid
        self._min_snr_near = min_snr_near
        self._tune_valid = tune_valid
        self._tune_near_miss = tune_near_miss
        self._last_log_hz = initial_hz

    def update(
        self,
        net: Optional[int],
        crc: Optional[int],
        afc_hz: Optional[float],
        snr: Optional[float],
    ) -> None:
        if net != DEFAULT_MESHCORE_NET or afc_hz is None:
            return
        use = False
        from_valid = False
        if self._tune_valid and crc == MESHCORE_CRC_OK:
            if snr is None or snr >= self._min_snr_valid:
                use = True
                from_valid = True
        elif self._tune_near_miss and crc == 0:
            if snr is not None and snr >= self._min_snr_near:
                use = True
        if not use:
            return
        with self._lock:
            self._shift_hz += self._alpha * (float(afc_hz) - self._shift_hz)
            if abs(self._shift_hz - self._last_log_hz) > 400:
                label = "AFC track" if from_valid else "IQ auto-shift"
                logger.info("%s: %.0f Hz", label, self._shift_hz)
                self._last_log_hz = self._shift_hz

    def get(self) -> float:
        with self._lock:
            return self._shift_hz


def sample_rate_chirp_ppm(actual_hz: float, nominal_hz: int) -> float:
    if nominal_hz <= 0:
        return 0.0
    return (actual_hz / float(nominal_hz) - 1.0) * 1_000_000.0


def resolve_chirp_ppm(
    rtl_ppm: int,
    chirp_ppm_arg: Optional[float],
    actual_hz: float,
    nominal_hz: int,
) -> float:
    """Match earlier meshcore_win: --ppm applies to RTL and lorarx -P unless overridden."""
    if chirp_ppm_arg is not None:
        return float(chirp_ppm_arg)
    rate_ppm = sample_rate_chirp_ppm(actual_hz, nominal_hz)
    if rtl_ppm:
        return float(rtl_ppm) + rate_ppm
    return rate_ppm


def build_lorarx_cmd_au(
    lorarx: str,
    freq_hz: int,
    bw: int,
    spreading: tuple[int, ...],
    cr: Optional[int],
    hex_view: int,
    net_id: Optional[int],
    chirp_ppm: Optional[float],
) -> list[str]:
    cmd = build_lorarx_cmd(
        lorarx, IF_RATE, bw, spreading, hex_view, cr, net_id, chirp_ppm
    )
    mhz = freq_hz / 1_000_000.0
    cmd += ["-M", f"{mhz:.3f}"]
    return cmd


def is_valid_meshcore_frame(obj: dict) -> bool:
    if obj.get("net") != DEFAULT_MESHCORE_NET:
        return False
    crc = obj.get("crc")
    return crc == MESHCORE_CRC_OK


class NearMissLogger:
    def __init__(self, interval_s: float = 5.0, auto_shift_hint: bool = True):
        self._interval_s = interval_s
        self._auto_shift_hint = auto_shift_hint
        self._last = 0.0
        self._lock = threading.Lock()

    def maybe_log(self, obj: dict) -> None:
        if obj.get("net") != DEFAULT_MESHCORE_NET or obj.get("crc") != 0:
            return
        snr = obj.get("snr")
        if isinstance(snr, (int, float)) and snr < 0:
            return
        now = time.time()
        with self._lock:
            if now - self._last < self._interval_s:
                return
            self._last = now
        afc_hz = obj.get("afc")
        logger.info(
            "near-miss: sync ok, CRC bad — snr=%s afc=%s (auto-shift is %s)",
            snr,
            afc_hz,
            "on" if self._auto_shift_hint else "off",
        )


def format_packet_json(record: dict, *, pretty: bool) -> str:
    if pretty:
        return json.dumps(record, indent=2, ensure_ascii=False)
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False)


def emit_console_packet(
    line: str, fanout: Optional[TcpFanout], packet_gap: bool
) -> None:
    print(line, flush=True)
    if packet_gap:
        print(flush=True)
    if fanout is not None:
        fanout.publish(line)


def lorarx_reader(
    process: subprocess.Popen,
    frequency_hz: int,
    fanout: Optional[TcpFanout],
    parse_app: bool,
    strict: bool,
    analyze: bool,
    packet_gap: bool,
    pretty_console: bool,
    capture: Optional[JsonCaptureFile],
    shifter: Optional[IqShiftTracker],
    near_miss: NearMissLogger,
) -> None:
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            print(line, flush=True)
            continue

        obj.setdefault("mode", "MESHCORE")
        obj.setdefault("freq", frequency_hz)
        obj.setdefault("region", "AU915")

        if shifter is not None:
            afc_val = obj.get("afc")
            if isinstance(afc_val, (int, float)):
                snr_val = obj.get("snr")
                snr_f = float(snr_val) if isinstance(snr_val, (int, float)) else None
                shifter.update(obj.get("net"), obj.get("crc"), float(afc_val), snr_f)

        if strict and not is_valid_meshcore_frame(obj):
            if analyze and obj.get("net") == DEFAULT_MESHCORE_NET:
                record = build_packet_output(obj, parse_meshcore=False)
                if capture is not None:
                    capture.append(record)
                emit_console_packet(
                    format_packet_json(record, pretty=pretty_console),
                    fanout,
                    packet_gap,
                )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "drop frame net=%s crc=%s snr=%s afc=%s",
                    obj.get("net"),
                    obj.get("crc"),
                    obj.get("snr"),
                    obj.get("afc"),
                )
            continue

        if parse_app:
            record = build_packet_output(obj, parse_meshcore=True)
            if capture is not None:
                capture.append(record)
            out = format_packet_json(record, pretty=pretty_console)
        else:
            out = format_packet_json(obj, pretty=pretty_console)

        emit_console_packet(out, fanout, packet_gap)


class RtlSdrSource:
    def __init__(
        self,
        freq: int,
        rate: int,
        gain: Optional[float],
        ppm: int,
        device_index: int,
    ):
        if RtlSdr is None:
            raise RuntimeError(
                f"pyrtlsdr required: pip install pyrtlsdr ({_RTL_IMPORT_ERROR})"
            )
        self.sdr = RtlSdr(device_index=device_index)
        self.sdr.sample_rate = rate
        self.sdr.center_freq = freq
        if ppm:
            self.sdr.freq_correction = ppm
        if gain is not None:
            self.sdr.gain = gain
        else:
            self.sdr.gain = "auto"
        self.sample_rate_actual = float(self.sdr.sample_rate)
        self.sample_rate = int(round(self.sample_rate_actual))
        self.center_freq = int(self.sdr.center_freq)
        logger.info(
            "RTL-SDR: %d Hz, %.3f sps, gain=%s, ppm=%d",
            self.center_freq,
            self.sample_rate_actual,
            self.sdr.gain,
            ppm,
        )

    def read(self, num_samples: int) -> np.ndarray:
        return self.sdr.read_samples(num_samples).astype(np.complex64)

    def close(self) -> None:
        try:
            self.sdr.close()
        except Exception:
            pass


def load_channel_keys(args: argparse.Namespace) -> dict[int, bytes]:
    keys: dict[int, bytes] = {}
    if args.channels_file and Path(args.channels_file).is_file():
        keys = load_channel_keys_file(args.channels_file)
        logger.info("Loaded %d channel key(s) from %s", len(keys), args.channels_file)
    elif _CHANNELS_FILE.is_file() and not args.channel_key:
        keys = load_channel_keys_file(_CHANNELS_FILE)
        logger.info("Loaded %d channel key(s) from %s", len(keys), _CHANNELS_FILE)
    for spec in args.channel_key:
        ch_hash, key = parse_channel_key_spec(spec)
        keys[ch_hash] = key
    return keys


def run(args: argparse.Namespace, stop: threading.Event) -> int:
    lorarx = args.lorarx
    if not Path(lorarx).is_file() and lorarx == find_lorarx():
        lorarx = find_lorarx_win()

    source = RtlSdrSource(
        args.freq, args.rate, args.gain, args.ppm, args.device_index
    )

    chirp_ppm = resolve_chirp_ppm(
        args.ppm, args.chirp_ppm, source.sample_rate_actual, args.rate
    )
    if abs(chirp_ppm) > 0.001:
        logger.info("lorarx chirp correction: %.2f ppm", chirp_ppm)

    cmd = build_lorarx_cmd_au(
        lorarx,
        args.freq,
        args.bw,
        tuple(args.spreading),
        args.cr,
        args.sync,
        args.net,
        chirp_ppm if abs(chirp_ppm) > 0.001 else None,
    )
    logger.info("lorarx: %s", " ".join(cmd))

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        bufsize=0,
        creationflags=creationflags,
    )
    assert process.stdin is not None

    fanout = None
    if args.tcp_out:
        fanout = TcpFanout(args.tcp_bind, args.tcp_out)

    shifter: Optional[IqShiftTracker] = None
    if args.track_afc or args.auto_shift:
        shifter = IqShiftTracker(
            args.shift_hz,
            tune_valid=args.track_afc,
            tune_near_miss=args.auto_shift,
            min_snr_valid=args.afc_min_snr,
            min_snr_near=args.near_miss_min_snr,
        )

    near_miss = NearMissLogger(auto_shift_hint=args.auto_shift)

    capture: Optional[JsonCaptureFile] = None
    if args.output:
        capture = JsonCaptureFile(Path(args.output))
        logger.info("Capturing packets to %s (%d existing)", args.output, len(capture))

    reader = threading.Thread(
        target=lorarx_reader,
        args=(
            process,
            args.freq,
            fanout,
            args.parse,
            args.strict,
            args.analyze,
            args.packet_gap,
            args.pretty_console,
            capture,
            shifter,
            near_miss,
        ),
        daemon=True,
    )
    reader.start()

    phase = 0.0
    read_samples = max(source.sample_rate // 4, 8192)

    try:
        while not stop.is_set():
            iq = source.read(read_samples)
            if iq.size == 0:
                continue
            shift_hz = shifter.get() if shifter is not None else args.shift_hz
            iq, phase = shift_iq(iq, source.sample_rate_actual, shift_hz, phase)
            iq = resample_iq(iq, source.sample_rate_actual, IF_RATE)
            process.stdin.write(iq.tobytes())
    finally:
        process.stdin.close()
        source.close()
        process.wait()
        reader.join(timeout=2)
        if fanout is not None:
            fanout.close()
    return process.returncode or 0


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="MeshCore decoder for Windows RTL-SDR + lorarx.exe (AU915 narrow default)",
    )
    p.add_argument("--freq", type=int, default=DEFAULT_FREQ)
    p.add_argument(
        "--rate",
        type=int,
        default=1_000_000,
        help="RTL-SDR sample rate (default 1 Msps, no decimation; or 2048000 with scipy)",
    )
    p.add_argument("--gain", type=float, default=None, help="RF gain (default: auto)")
    p.add_argument("--ppm", type=int, default=0, help="RTL-SDR ppm + lorarx -P (unless --chirp-ppm set)")
    p.add_argument(
        "--chirp-ppm",
        type=float,
        default=None,
        help="lorarx -P chirp rate ppm (default: auto from actual sample rate)",
    )
    p.add_argument(
        "--shift-hz",
        type=float,
        default=0.0,
        help="Manual IQ mixer offset Hz (also AFC track starting point)",
    )
    p.add_argument(
        "--track-afc",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Also tune IQ shift from crc=1 frames (default: off)",
    )
    p.add_argument(
        "--auto-shift",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto IQ shift from net=18 near-miss frames (default: on)",
    )
    p.add_argument(
        "--afc-min-snr",
        type=float,
        default=4.0,
        help="Min SNR (dB) for crc=1 AFC tuning",
    )
    p.add_argument(
        "--near-miss-min-snr",
        type=float,
        default=3.0,
        help="Min SNR (dB) for near-miss auto-shift",
    )
    p.add_argument("--device-index", type=int, default=0)
    p.add_argument("--bw", type=int, default=DEFAULT_BW)
    p.add_argument("--spreading", type=int, nargs="+", default=list(DEFAULT_SPREADING))
    p.add_argument("--cr", type=int, default=0, help="LoRa CR 5-8; 0 = read from header (default)")
    p.add_argument("--net", type=int, default=DEFAULT_MESHCORE_NET, help="MeshCore net id for lorarx -X")
    p.add_argument("--hex-view", type=int, default=DEFAULT_HEX_VIEW, dest="sync")
    p.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Only print frames with net=18 and crc=1 (default: on)",
    )
    p.add_argument(
        "--analyze",
        action="store_true",
        help="Also print net=18 frames with failed CRC (lora PHY only, for tuning)",
    )
    p.add_argument("--lorarx", default=find_lorarx_win())
    p.add_argument(
        "--parse",
        action="store_true",
        default=True,
        help="Parse MeshCore application layer (default: on)",
    )
    p.add_argument("--raw-json", action="store_true", help="Only lorarx JSON, no MeshCore parse")
    p.add_argument("--tcp-out", type=int, metavar="PORT")
    p.add_argument("--tcp-bind", default="0.0.0.0")
    p.add_argument(
        "--channel-key",
        action="append",
        default=[],
        metavar="HASH:HEX",
        help="Decrypt key for GRP_TXT/GRP_DATA, e.g. 1A:adc9db724d479a90aba3f32932b5b51d",
    )
    p.add_argument(
        "--channels-file",
        default=None,
        help=f"Channel keys file (default: {_CHANNELS_FILE.name} if present)",
    )
    p.add_argument(
        "--packet-gap",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Blank line between packets on console (default: on)",
    )
    p.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="Append packets to a pretty-printed JSON array file",
    )
    p.add_argument(
        "--pretty-console",
        action="store_true",
        help="Indented JSON on console (default: one line per packet)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.cr == 0:
        args.cr = None
    if args.net == 0:
        args.net = None
    if args.raw_json:
        args.parse = False

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        set_channel_keys(load_channel_keys(args))
    except (ValueError, OSError) as exc:
        logger.error("Channel keys: %s", exc)
        return 1

    lorarx_path = Path(args.lorarx)
    if not lorarx_path.is_file():
        logger.error(
            "lorarx not found at %s — run invoke_build.cmd first (VS2019 x64 prompt)",
            args.lorarx,
        )
        return 1

    stop = threading.Event()

    def on_signal(_s, _f):
        logger.info("Stopping...")
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_signal)

    return run(args, stop)


if __name__ == "__main__":
    raise SystemExit(main())
