from qortium_cli.constants import B58_ALPHABET_SET, PLACEHOLDER_VALUES


def normalize_node_url(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("URL cannot be empty.")
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise ValueError("URL must start with http:// or https://")
    return cleaned.rstrip("/")


def is_placeholder(value: str) -> bool:
    return (value or "").strip().lower() in PLACEHOLDER_VALUES


def looks_like_qortal_address(address: str) -> bool:
    if not isinstance(address, str):
        return False
    addr = address.strip()
    if not addr.startswith("Q"):
        return False
    if len(addr) < 20 or len(addr) > 60:
        return False
    return all(char in B58_ALPHABET_SET for char in addr)

