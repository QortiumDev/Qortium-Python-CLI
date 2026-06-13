from __future__ import annotations

import base64
import hashlib

from qortium_cli.constants import (
    B58_ALPHABET_BYTES,
    B58_ALPHABET_SET,
    KDF_THREADS,
    STATIC_BCRYPT_SALT,
    STATIC_SALT,
)


def b58encode(raw: bytes) -> str:
    if not raw:
        return "1"

    n = int.from_bytes(raw, "big")
    out = bytearray()
    while n > 0:
        n, r = divmod(n, 58)
        out.append(B58_ALPHABET_BYTES[r])

    pad = 0
    for byte in raw:
        if byte == 0:
            pad += 1
        else:
            break

    return (B58_ALPHABET_BYTES[0:1] * pad + out[::-1]).decode("ascii")


def b58decode(value: str) -> bytes:
    text = (value or "").strip()
    if not text:
        return b""

    n = 0
    for ch in text:
        if ch not in B58_ALPHABET_SET:
            raise ValueError("Invalid Base58 string")
        n = n * 58 + B58_ALPHABET_BYTES.index(ord(ch).to_bytes(1, "big"))

    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""

    pad = 0
    for ch in text:
        if ch == "1":
            pad += 1
        else:
            break

    return b"\x00" * pad + raw


def is_base58(value: str) -> bool:
    return bool(value) and all(char in B58_ALPHABET_SET for char in value)


def to_base58_pubkey(pub_from_config: str) -> str:
    pubkey = (pub_from_config or "").strip()
    if not pubkey:
        raise ValueError("PUBLIC_KEY is empty")

    if is_base58(pubkey):
        return pubkey

    try:
        raw = base64.b64decode(pubkey, validate=False)
        if raw:
            return b58encode(raw)
    except Exception:
        pass

    try:
        fixed = pubkey.replace("-", "+").replace("_", "/")
        fixed += "=" * ((4 - len(fixed) % 4) % 4)
        raw = base64.b64decode(fixed, validate=False)
        if raw:
            return b58encode(raw)
    except Exception:
        pass

    raise ValueError("PUBLIC_KEY is neither Base58 nor decodable Base64")


def qortal_hub_kdf(value: str) -> bytes:
    import bcrypt

    text = str(value or "")
    if not text:
        raise ValueError("KDF input is empty.")

    parts = []
    for i in range(KDF_THREADS):
        msg = (STATIC_SALT + text + str(i)).encode("utf-8")
        sha = hashlib.sha512(msg).digest()
        b64_72 = base64.b64encode(sha).decode("ascii")[:72]
        pw = (b64_72.encode("utf-8") + b"\x00")[:72]
        parts.append(bcrypt.hashpw(pw, STATIC_BCRYPT_SALT).decode("utf-8"))

    final_input = (STATIC_SALT + "".join(parts)).encode("utf-8")
    return hashlib.sha512(final_input).digest()


def derive_private_key_from_seed_phrase(seed_phrase: str) -> str:
    phrase = (seed_phrase or "").strip()
    if not phrase:
        raise ValueError("Seed phrase is empty.")

    master_seed = qortal_hub_kdf(phrase)

    idx = (0).to_bytes(4, "big")
    inp = idx + master_seed + idx
    s1 = hashlib.sha512(inp).digest()
    s2 = hashlib.sha512(s1 + inp).digest()
    seed32 = s2[:32]
    return b58encode(seed32)

