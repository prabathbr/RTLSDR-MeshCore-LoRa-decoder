"""MeshCore group channel crypto (OE5DXL mcd.py / MeshCore GRP_TXT)."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


def channel_hash_for_key(key: bytes) -> int:
    return hashlib.sha256(key).digest()[0]


def parse_channel_key_spec(spec: str) -> tuple[int, bytes]:
    """Parse '1A:hexkey' or bare 32-hex-char key (hash derived from key)."""
    spec = spec.strip()
    if not spec or spec.startswith("#"):
        raise ValueError("empty channel key spec")
    if ":" in spec:
        hash_part, key_part = spec.split(":", 1)
        key = bytes.fromhex(key_part.strip())
        ch_hash = int(hash_part.strip(), 16)
    else:
        key = bytes.fromhex(spec)
        ch_hash = channel_hash_for_key(key)
    if len(key) != 16:
        raise ValueError(f"channel key must be 16 bytes, got {len(key)}")
    if channel_hash_for_key(key) != ch_hash:
        raise ValueError(
            f"channel hash {ch_hash:02X} does not match key (expected "
            f"{channel_hash_for_key(key):02X})"
        )
    return ch_hash, key


def load_channel_keys_file(path: str | Path) -> dict[int, bytes]:
    keys: dict[int, bytes] = {}
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        ch_hash, key = parse_channel_key_spec(line)
        keys[ch_hash] = key
    return keys


def merge_channel_keys(*maps: dict[int, bytes]) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    for m in maps:
        out.update(m)
    return out


def _aes_ecb_decrypt(key: bytes, data: bytes) -> bytes:
    if not _HAS_CRYPTO:
        raise RuntimeError("cryptography package required for channel decrypt")
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    out = b""
    offset = 0
    while offset + 16 <= len(data):
        out += decryptor.update(data[offset : offset + 16])
        offset += 16
    remainder = data[offset:]
    if remainder:
        padded = (remainder + bytes(16))[:16]
        out += decryptor.update(padded)[: len(remainder)]
    return out + decryptor.finalize()


def decrypt_group_ciphertext(mac_and_cipher: bytes, key: bytes) -> Optional[bytes]:
    """Verify 2-byte HMAC-SHA256 MAC and AES-128-ECB decrypt (mcd.py compatible)."""
    if len(key) != 16 or len(mac_and_cipher) < 3:
        return None
    mac = mac_and_cipher[:2]
    ciphertext = mac_and_cipher[2:]
    calc = hmac.new(key, ciphertext, hashlib.sha256).digest()[:2]
    if calc != mac:
        return None
    if not ciphertext:
        return b""
    return _aes_ecb_decrypt(key, ciphertext)


def parse_group_plaintext(plaintext: bytes) -> dict[str, object]:
    if len(plaintext) < 5:
        return {"plaintext_hex": plaintext.hex()}
    ts = (
        plaintext[0]
        | (plaintext[1] << 8)
        | (plaintext[2] << 16)
        | (plaintext[3] << 24)
    )
    flags = plaintext[4]
    text_bytes = plaintext[5:].split(b"\x00", 1)[0]
    text = text_bytes.decode("utf-8", errors="replace")
    sender, sep, message = text.partition(": ")
    result: dict[str, object] = {
        "timestamp": ts,
        "flags": flags,
        "text": text,
    }
    if sep:
        result["sender"] = sender
        result["message"] = message
    return result
