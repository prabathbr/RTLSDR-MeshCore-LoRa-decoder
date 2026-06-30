"""MeshCore application-layer packet parsing (from OE5DXL mcd.py / loraprotocols.c)."""

from __future__ import annotations

import base64
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from meshcore_crypto import decrypt_group_ciphertext, parse_group_plaintext

_channel_keys: dict[int, bytes] = {}

PACKET_TYPES = {
    0: "REQ",
    1: "RESPONSE",
    2: "TXT_MSG",
    3: "ACK",
    4: "ADVERT",
    5: "GRP_TXT",
    6: "GRP_DATA",
    7: "ANON_REQ",
    8: "PATH",
    9: "TRACE",
    10: "MULTIPART",
    11: "CONTROL",
    15: "RAW_CUSTOM",
}

ROUTE_TYPES = {
    0: "TRANSPORT_FLOOD",
    1: "FLOOD",
    2: "DIRECT",
    3: "TRANSPORT_DIRECT",
}

NODE_TYPES = {
    1: "ChatNode",
    2: "Repeater",
    3: "RoomServer",
    4: "Sensor",
}


def set_channel_keys(keys: dict[int, bytes]) -> None:
    global _channel_keys
    _channel_keys = dict(keys)


def get_channel_keys() -> dict[int, bytes]:
    return dict(_channel_keys)


def _route_name(flags: int) -> str:
    return ROUTE_TYPES.get(flags & 3, f"ROUTE_{flags & 3}")


def _packet_type(flags: int) -> str:
    return PACKET_TYPES.get((flags >> 2) & 15, "UNDEF")


def _read_u32_le(data: bytes, offset: int) -> int:
    return (
        data[offset]
        | (data[offset + 1] << 8)
        | (data[offset + 2] << 16)
        | (data[offset + 3] << 24)
    )


def _parse_meshcore_path(
    payload: bytes, pos: int, is_trace: bool
) -> tuple[list[str], int]:
    """Parse MeshCore path header (loraprotocols.c / decodemeshcore)."""
    if pos >= len(payload):
        return [], pos
    pl_byte = payload[pos]
    pos += 1
    path2 = 2 if (pl_byte // 64) & 1 else 1
    hop_bytes = (pl_byte & 0x3F) * path2
    path: list[str] = []
    consumed = 0
    while consumed < hop_bytes and pos < len(payload):
        if is_trace:
            # TRACE payloads embed per-hop SNR after path bytes; keep bytes only.
            path.append(f"{payload[pos]:02X}")
            pos += 1
            consumed += 1
            if pos + 8 < len(payload):
                pos += 8
            continue
        if path2 == 2:
            if pos + 1 >= len(payload):
                break
            path.append(f"{payload[pos]:02X}")
            path.append(f"{payload[pos + 1]:02X}")
            pos += 2
            consumed += 2
        else:
            path.append(f"{payload[pos]:02X}")
            pos += 1
            consumed += 1
    return path, pos


def decode_payload(payload: bytes) -> dict[str, Any]:
    """Parse raw MeshCore frame bytes (after LoRa decode)."""
    if not payload:
        return {"error": "empty payload"}

    flags = payload[0]
    out: dict[str, Any] = {
        "route": _route_name(flags),
        "type": _packet_type(flags),
    }

    pos = 1
    if flags & 3 in (0, 3) and len(payload) > 4:
        out["transport"] = f"{_read_u32_le(payload, 1):08X}"
        pos = 5

    ptype = (flags >> 2) & 15
    is_trace = ptype == 9
    if pos < len(payload) and not is_trace:
        path, pos = _parse_meshcore_path(payload, pos, is_trace=False)
        if path and ptype != 9:
            out["path"] = path
    elif pos < len(payload) and is_trace:
        path, pos = _parse_meshcore_path(payload, pos, is_trace=True)
        if path:
            out["path"] = path

    body = payload[pos:]
    out["body_hex"] = body.hex()

    if ptype == 4:
        out.update(_decode_advert(body))
    elif ptype in (5, 6):
        out.update(_decode_group_text(body, ptype == 6, _channel_keys))
    elif ptype == 2 and body:
        out.update(_decode_text_msg(body))

    return out


def _decode_advert(body: bytes) -> dict[str, Any]:
    if len(body) < 109:
        return {"advert_error": "too short"}
    pubkey = body[:32]
    ts = _read_u32_le(body, 32)
    app = body[100]
    result: dict[str, Any] = {
        "pubkey_prefix": pubkey[:4].hex(),
        "timestamp": ts,
        "node_type": NODE_TYPES.get(app & 15, f"type_{app & 15}"),
    }
    p = 101
    if (app >> 4) & 1 and len(body) >= 109:
        lat = _read_u32_le(body, 101) * 1e-6
        lon = _read_u32_le(body, 105) * 1e-6
        result["lat"] = lat
        result["lon"] = lon
        p += 8
    if (app >> 7) & 1 and p < len(body):
        name = body[p:].split(b"\x00", 1)[0]
        try:
            result["name"] = name.decode("utf-8", errors="replace")
        except Exception:
            result["name"] = name.hex()
    return result


def _decode_group_text(
    body: bytes, is_data: bool, channel_keys: dict[int, bytes]
) -> dict[str, Any]:
    if not body:
        return {}
    ch_hash = body[0]
    result: dict[str, Any] = {
        "channel_hash": f"{ch_hash:02X}",
        "encrypted": True,
        "is_data": is_data,
        "ciphertext_hex": body[3:].hex() if len(body) > 3 else "",
        "mac_hex": body[1:3].hex() if len(body) > 2 else "",
    }
    key = channel_keys.get(ch_hash)
    if key is None:
        return result
    plaintext = decrypt_group_ciphertext(body[1:], key)
    if plaintext is None:
        result["decrypt_error"] = "mac_failed"
        return result
    result["encrypted"] = False
    result.update(parse_group_plaintext(plaintext))
    return result


def _decode_text_msg(body: bytes) -> dict[str, Any]:
    if len(body) < 5:
        return {}
    ts = _read_u32_le(body, 0)
    text = body[5:].split(b"\x00", 1)[0]
    try:
        decoded = text.decode("utf-8", errors="replace")
    except Exception:
        decoded = text.hex()
    return {"timestamp": ts, "text": decoded}


def payload_bytes_from_lorarx(obj: dict[str, Any]) -> Optional[bytes]:
    raw = obj.get("payload")
    if not raw:
        return None
    if isinstance(raw, str):
        return base64.b64decode(raw)
    return bytes(raw)


def _crc_label(crc: Any) -> str:
    if crc == 1:
        return "ok"
    if crc == 0:
        return "fail"
    return "none"


def extract_phy_raw(obj: dict[str, Any]) -> dict[str, Any]:
    """LoRa PHY layer from lorarx (chirp demod) — no decoded payload bytes."""
    keys = (
        "net",
        "crc",
        "invers",
        "bw",
        "sf",
        "cr",
        "preamb",
        "duration",
        "level",
        "afc",
        "dre",
        "eye",
        "eyemin",
        "nfloor",
        "pknfloor",
        "snr",
        "snrmin",
        "fec",
        "firlen",
        "notches",
        "chirps",
        "rxmhz",
        "ver",
        "phy_hex",
        "phy_hex_len",
        "phy_sync_hex",
        "phy_header_hex",
        "phy_lora_crc_hex",
        "mode",
        "freq",
        "region",
    )
    phy: dict[str, Any] = {k: obj[k] for k in keys if k in obj}
    net = obj.get("net")
    if net is not None:
        phy["sync_word_dec"] = int(net)
        phy["sync_word_hex"] = f"{int(net) & 0xFF:02X}"
        phy["meshcore_sync"] = int(net) == 18
    crc = obj.get("crc")
    phy["lora_crc"] = crc
    phy["lora_crc_label"] = _crc_label(crc)
    phy["lora_crc_ok"] = crc == 1
    parts = []
    if "sf" in phy:
        parts.append(f"sf{phy['sf']}")
    if "bw" in phy:
        parts.append(f"bw{phy['bw']:.0f}")
    if "cr" in phy:
        parts.append(f"cr4/{phy['cr']}")
    if net is not None:
        parts.append(f"net0x{int(net) & 0xFF:02X}")
    parts.append(f"crc={phy['lora_crc_label']}")
    if "snr" in phy:
        parts.append(f"snr{phy['snr']:.1f}dB")
    if "afc" in phy:
        parts.append(f"afc{phy['afc']}Hz")
    if "preamb" in phy:
        parts.append(f"preamb{phy['preamb']}")
    phy["summary"] = " ".join(parts)
    return phy


def extract_lora_payload(obj: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Bytes recovered after LoRa PHY decode (MeshCore frame input to app parser)."""
    payload = payload_bytes_from_lorarx(obj)
    if payload is None:
        return None
    out: dict[str, Any] = {
        "len": len(payload),
        "hex": payload.hex(),
    }
    if isinstance(obj.get("payload"), str):
        out["b64"] = obj["payload"]
    return out


def extract_lora_raw(obj: dict[str, Any]) -> dict[str, Any]:
    """PHY + lora payload (legacy combined view)."""
    phy = extract_phy_raw(obj)
    lp = extract_lora_payload(obj)
    if lp:
        phy["payload_len"] = lp["len"]
        phy["payload_hex"] = lp["hex"]
        if "b64" in lp:
            phy["payload_b64"] = lp["b64"]
    return phy


def analyze_lora(phy: dict[str, Any]) -> dict[str, Any]:
    sync = bool(phy.get("meshcore_sync"))
    crc_ok = bool(phy.get("lora_crc_ok"))
    return {
        "meshcore_sync": sync,
        "lora_crc_ok": crc_ok,
        "likely_meshcore": sync and crc_ok,
        "note": (
            "valid MeshCore LoRa frame"
            if sync and crc_ok
            else (
                "MeshCore sync (0x12) but LoRa CRC failed — tuning or false sync"
                if sync and not crc_ok
                else (
                    f"sync word 0x{phy.get('sync_word_hex', '??')} is not MeshCore (0x12)"
                    if not sync
                    else "unknown"
                )
            )
        ),
    }


def build_packet_output(obj: dict[str, Any], parse_meshcore: bool) -> dict[str, Any]:
    """Compact decode record (no duplicate phy/lorarx/payload fields)."""
    return build_clean_packet_output(
        obj,
        parse_meshcore=parse_meshcore,
        freq_hz=obj.get("freq"),
        region=obj.get("region"),
    )


def build_clean_packet_output(
    obj: dict[str, Any],
    *,
    parse_meshcore: bool,
    freq_hz: Optional[int] = None,
    region: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Single canonical JSON object per captured packet."""
    lora_payload = extract_lora_payload(obj)
    if lora_payload is None:
        return {"error": "no payload", "freq_hz": freq_hz or obj.get("freq")}

    net = obj.get("net")
    crc_ok = obj.get("crc") in (1, True)
    sync_hex = obj.get("phy_sync_hex")
    if sync_hex is None and net is not None:
        sync_hex = f"{int(net) & 0xFF:02X}"

    phy: dict[str, Any] = {"crc_ok": crc_ok}
    if sync_hex is not None:
        phy["sync_hex"] = sync_hex
    for src, dst in (
        ("phy_hex", "hex"),
        ("phy_header_hex", "header_hex"),
        ("phy_lora_crc_hex", "lora_crc_hex"),
        ("sf", "sf"),
        ("bw", "bw"),
        ("cr", "cr"),
        ("snr", "snr_db"),
        ("afc", "afc_hz"),
        ("preamb", "preamb"),
        ("duration", "duration_ms"),
        ("level", "level_db"),
        ("invers", "inverted"),
    ):
        if src in obj:
            phy[dst] = obj[src]

    out: dict[str, Any] = {
        "ts": timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "freq_hz": freq_hz if freq_hz is not None else obj.get("freq"),
        "phy": phy,
        "packet": {
            "len": lora_payload["len"],
            "hex": lora_payload["hex"],
        },
    }
    reg = region or obj.get("region")
    if reg:
        out["region"] = reg

    if parse_meshcore and crc_ok and net in (18, 0x12):
        payload = payload_bytes_from_lorarx(obj)
        if payload:
            out["meshcore"] = decode_payload(payload)
    return out


class JsonCaptureFile:
    """Append packets to a pretty-printed JSON array file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._records = data
            except (json.JSONDecodeError, OSError):
                self._records = []

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._records, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    def __len__(self) -> int:
        return len(self._records)


def decode_lorarx_json(obj: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Enrich a lorarx JSON object (legacy wrapper around build_packet_output)."""
    if obj.get("crc") not in (1, True):
        return None
    net = obj.get("net")
    if net is not None and net not in (18, 0x12):
        return None
    if not obj.get("payload"):
        return None
    return build_packet_output(obj, parse_meshcore=True)
