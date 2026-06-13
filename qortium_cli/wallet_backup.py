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
QORTIUM_WALLET_VERSION = 2
PRIVATE_KEY_BYTES = 32
MASTER_SEED_BYTES = 64


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


def derive_address_seed(master_seed: bytes, address_index: int = 0) -> bytes:
    if len(master_seed) != MASTER_SEED_BYTES:
        raise ValueError("Qortium Home master seed must be exactly 64 bytes.")
    if address_index < 0:
        raise ValueError("Wallet address index must be >= 0.")

    nonce = int(address_index).to_bytes(4, "big", signed=False)
    nonce_seed = nonce + master_seed + nonce
    first_hash = hashlib.sha512(nonce_seed).digest()
    return hashlib.sha512(first_hash + nonce_seed).digest()[:PRIVATE_KEY_BYTES]


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


def _require_wallet_string(wallet: Dict[str, Any], key: str) -> str:
    value = wallet.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Wallet file must include non-empty {key}.")
    return value.strip()


def _require_wallet_version(wallet: Dict[str, Any]) -> int:
    try:
        version = int(wallet.get("version"))
    except (TypeError, ValueError):
        raise ValueError("Wallet file must include numeric version.") from None

    if version not in {QORTIUM_WALLET_VERSION, QORTIUM_PRIVATE_KEY_WALLET_VERSION}:
        raise ValueError(f"Unsupported Qortium Home wallet version: {version}.")
    return version


def decrypt_wallet_payload(wallet: Dict[str, Any], password: str) -> bytes:
    wallet_password = str(password or "")
    if not wallet_password:
        raise ValueError("Wallet password is required.")

    _require_wallet_version(wallet)
    try:
        kdf_threads = int(wallet.get("kdfThreads"))
    except (TypeError, ValueError):
        raise ValueError("Wallet file must include numeric kdfThreads.") from None
    if kdf_threads != KDF_THREADS:
        raise ValueError(f"Unsupported wallet kdfThreads value: {kdf_threads}.")

    try:
        encrypted_seed = b58decode(_require_wallet_string(wallet, "encryptedSeed"))
        salt = b58decode(_require_wallet_string(wallet, "salt"))
        iv = b58decode(_require_wallet_string(wallet, "iv"))
        stored_mac = b58decode(_require_wallet_string(wallet, "mac"))
    except ValueError as exc:
        raise ValueError("Wallet file contains invalid Base58 data.") from exc

    if len(salt) != 32:
        raise ValueError("Wallet salt must decode to exactly 32 bytes.")
    if len(iv) != 16:
        raise ValueError("Wallet IV must decode to exactly 16 bytes.")
    if len(encrypted_seed) == 0 or len(encrypted_seed) % 16 != 0:
        raise ValueError("Wallet encryptedSeed length is invalid.")

    key = qortal_hub_kdf(wallet_password)
    encryption_key = key[:32]
    mac_key = key[32:63]
    computed_mac = hmac.new(mac_key, encrypted_seed, hashlib.sha512).digest()
    if not hmac.compare_digest(computed_mac, stored_mac):
        raise ValueError("Incorrect wallet password.")

    try:
        decryptor = Cipher(
            algorithms.AES(encryption_key),
            modes.CBC(iv),
        ).decryptor()
        return decryptor.update(encrypted_seed) + decryptor.finalize()
    except Exception as exc:
        raise ValueError("Unable to unlock wallet.") from exc


def private_key_from_wallet(wallet: Dict[str, Any], password: str) -> str:
    version = _require_wallet_version(wallet)
    address = _require_wallet_string(wallet, "address0")
    payload = decrypt_wallet_payload(wallet, password)

    if version == QORTIUM_PRIVATE_KEY_WALLET_VERSION:
        if len(payload) != PRIVATE_KEY_BYTES:
            raise ValueError("Version 3 wallet payload must be exactly 32 bytes.")
        private_seed = payload
    else:
        if len(payload) != MASTER_SEED_BYTES:
            raise ValueError("Version 2 wallet payload must be exactly 64 bytes.")
        private_seed = derive_address_seed(payload, 0)

    derived_address = qortal_address_from_private_seed(private_seed)
    if derived_address != address:
        raise ValueError("Wallet password unlocked data, but address0 did not match.")
    return b58encode(private_seed)


def private_key_from_wallet_file(path: Path, password: str) -> str:
    wallet_path = path.expanduser().resolve()
    try:
        wallet = json.loads(wallet_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Wallet file not found: {wallet_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Wallet file must be valid JSON.") from exc

    if not isinstance(wallet, dict):
        raise ValueError("Wallet file must contain a JSON object.")
    return private_key_from_wallet(wallet, password)


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
