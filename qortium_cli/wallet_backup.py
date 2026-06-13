from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from typing import Any, Dict

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from qortium_cli.constants import KDF_THREADS
from qortium_cli.crypto import b58decode, b58encode, qortal_hub_kdf

QORTIUM_PRIVATE_KEY_WALLET_VERSION = 3
PRIVATE_KEY_BYTES = 32


def qortal_address_from_private_seed(seed: bytes) -> str:
    if len(seed) != 32:
        raise ValueError("Qortal private seed must be exactly 32 bytes.")

    public_key = (
        Ed25519PrivateKey.from_private_bytes(seed)
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
    )
    public_key_hash = hashlib.sha256(public_key).digest()
    account_hash = hashlib.new("ripemd160", public_key_hash).digest()
    address_without_checksum = bytes([58]) + account_hash
    checksum = hashlib.sha256(hashlib.sha256(address_without_checksum).digest()).digest()[:4]
    return b58encode(address_without_checksum + checksum)


def decode_private_key_input(private_key: str) -> bytes:
    try:
        decoded = b58decode(str(private_key or "").strip())
    except ValueError as exc:
        raise ValueError("PRIVATE_KEY must be a valid Base58 private key.") from exc

    # Qortium Home accepts a 64-byte Ed25519 secret key and uses its 32-byte seed.
    if len(decoded) == PRIVATE_KEY_BYTES * 2:
        return decoded[:PRIVATE_KEY_BYTES]
    if len(decoded) != PRIVATE_KEY_BYTES:
        raise ValueError("PRIVATE_KEY must decode to exactly 32 or 64 bytes.")
    return decoded


def generate_wallet_backup_from_private_key(
    private_key: str,
    address: str,
    password: str,
    *,
    salt: bytes | None = None,
    iv: bytes | None = None,
) -> Dict[str, Any]:
    private_seed = decode_private_key_input(private_key)

    wallet_address = str(address or "").strip()
    if not wallet_address:
        raise ValueError("Wallet address is empty.")
    derived_address = qortal_address_from_private_seed(private_seed)
    if derived_address != wallet_address:
        raise ValueError(
            "Private key does not match the configured wallet address."
        )

    wallet_password = str(password or "")
    if not wallet_password:
        raise ValueError("Wallet backup password cannot be empty.")

    salt_bytes = os.urandom(32) if salt is None else bytes(salt)
    iv_bytes = os.urandom(16) if iv is None else bytes(iv)
    if len(salt_bytes) != 32:
        raise ValueError("Wallet backup salt must be exactly 32 bytes.")
    if len(iv_bytes) != 16:
        raise ValueError("Wallet backup IV must be exactly 16 bytes.")

    key = qortal_hub_kdf(wallet_password)
    encryption_key = key[:32]
    mac_key = key[32:63]

    encryptor = Cipher(
        algorithms.AES(encryption_key),
        modes.CBC(iv_bytes),
    ).encryptor()
    encrypted_seed = encryptor.update(private_seed) + encryptor.finalize()
    mac = hmac.new(mac_key, encrypted_seed, hashlib.sha512).digest()

    return {
        "address0": wallet_address,
        "encryptedSeed": b58encode(encrypted_seed),
        "salt": b58encode(salt_bytes),
        "iv": b58encode(iv_bytes),
        "version": QORTIUM_PRIVATE_KEY_WALLET_VERSION,
        "mac": b58encode(mac),
        "kdfThreads": KDF_THREADS,
    }


def write_wallet_backup(path: Path, backup: Dict[str, Any]) -> Path:
    output_path = path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(backup, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def sanitize_wallet_backup_name(value: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "").strip())
    return sanitized or "wallet"


def default_wallet_backup_path(
    address: str,
    *,
    wallet_name: str = "wallet",
) -> Path:
    filename = f"{sanitize_wallet_backup_name(wallet_name)}_{address}.json"
    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        return downloads / filename
    return Path.cwd() / filename
