"""Qortium Home-compatible deterministic foreign-wallet derivation."""

from __future__ import annotations

import hashlib
import hmac
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import ec

from qortium_cli.crypto import b58encode
from qortium_cli.wallet_backup import decode_private_key_input


SECP256K1_ORDER = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
)
STANDARD_XPUB_VERSION = 0x0488B21E
DOGE_XPUB_VERSION = 0x02FACAFD


@dataclass(frozen=True)
class ForeignWalletSpec:
    coin: str
    display_name: str
    address_prefix: bytes
    indicator: bytes = b""
    xpub_version: int = STANDARD_XPUB_VERSION


@dataclass(frozen=True)
class ForeignWallet:
    """Public wallet material safe to send to Core for read-only lookups."""

    coin: str
    address: str
    xpub58: str


FOREIGN_WALLET_SPECS: dict[str, ForeignWalletSpec] = {
    "BTC": ForeignWalletSpec("BTC", "Bitcoin", b"\x00"),
    "LTC": ForeignWalletSpec("LTC", "Litecoin", b"\x30", b"LTC"),
    "DOGE": ForeignWalletSpec(
        "DOGE",
        "Dogecoin",
        b"\x1e",
        b"DOGE",
        DOGE_XPUB_VERSION,
    ),
    "DGB": ForeignWalletSpec("DGB", "DigiByte", b"\x1e", b"DGB"),
    "RVN": ForeignWalletSpec("RVN", "Ravencoin", b"\x3c", b"RVN"),
    "DASH": ForeignWalletSpec("DASH", "Dash", b"\x4c", b"DASH"),
    "NMC": ForeignWalletSpec("NMC", "Namecoin", b"\x34", b"NMC"),
    "FIRO": ForeignWalletSpec("FIRO", "Firo", b"\x52", b"FIRO"),
}

SUPPORTED_FOREIGN_WALLET_CODES = tuple(FOREIGN_WALLET_SPECS)


@dataclass(frozen=True)
class _WalletNode:
    private_key: int
    chain_code: bytes


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _public_key(private_key: int) -> bytes:
    public_numbers = (
        ec.derive_private_key(private_key, ec.SECP256K1())
        .public_key()
        .public_numbers()
    )
    prefix = b"\x02" if public_numbers.y % 2 == 0 else b"\x03"
    return prefix + public_numbers.x.to_bytes(32, "big")


def _base58check(payload: bytes) -> str:
    checksum = _sha256(_sha256(payload))[:4]
    return b58encode(payload + checksum)


def _root_node(address_seed: bytes, indicator: bytes) -> _WalletNode:
    reversed_seed = address_seed[::-1]
    reverse_seed_hash = _sha256(reversed_seed + indicator)
    seed_hash = _sha512(reversed_seed + reverse_seed_hash)
    private_key = int.from_bytes(seed_hash[:32], "big")
    private_key = (private_key % (SECP256K1_ORDER - 1)) + 1
    return _WalletNode(
        private_key=private_key,
        chain_code=_sha256(seed_hash[32:]),
    )


def _child_node(parent: _WalletNode, child_index: int) -> _WalletNode:
    data = _public_key(parent.private_key) + struct.pack(">I", child_index)
    digest = hmac.new(parent.chain_code, data, hashlib.sha512).digest()
    private_key = (
        int.from_bytes(digest[:32], "big") + parent.private_key
    ) % SECP256K1_ORDER
    if private_key == 0:
        raise ValueError("Invalid secp256k1 child key.")
    return _WalletNode(private_key=private_key, chain_code=digest[32:])


def _serialize_xpub(node: _WalletNode, version: int) -> str:
    payload = (
        struct.pack(">I", version)
        + b"\x00"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + node.chain_code
        + _public_key(node.private_key)
    )
    return _base58check(payload)


def derive_foreign_wallet(private_key: str, coin: str) -> ForeignWallet:
    """Derive the same address and root xpub as Qortium Home.

    Qortium Home first derives the selected account seed and then derives
    each foreign wallet from that 32-byte value. The CLI already stores the
    selected address-0 private seed, so no master seed or wallet password is
    needed here.
    """

    code = str(coin or "").strip().upper()
    try:
        spec = FOREIGN_WALLET_SPECS[code]
    except KeyError as exc:
        raise ValueError(f"Unsupported Qortium foreign wallet: {code or 'empty'}") from exc

    address_seed = decode_private_key_input(private_key)
    root = _root_node(address_seed, spec.indicator)
    receive = _child_node(root, 0)
    first_address = _child_node(receive, 0)
    public_key_hash = hashlib.new(
        "ripemd160",
        _sha256(_public_key(first_address.private_key)),
    ).digest()

    return ForeignWallet(
        coin=code,
        address=_base58check(spec.address_prefix + public_key_hash),
        xpub58=_serialize_xpub(root, spec.xpub_version),
    )
