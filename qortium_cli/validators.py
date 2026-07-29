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


def normalize_api_key(value: str) -> str:
    """Return a header-safe API key or raise without revealing its contents."""

    api_key = str(value or "").strip()
    if not api_key:
        raise ValueError("API key is empty.")

    if any(ord(char) < 33 or ord(char) > 126 for char in api_key):
        raise ValueError(
            "The stored API key contains an invalid control or non-ASCII character. "
            "Open Settings > Connection & account > Change API key and paste it again."
        )
    return api_key


def looks_like_qortal_address(address: str) -> bool:
    if not isinstance(address, str):
        return False
    addr = address.strip()
    if not addr.startswith("Q"):
        return False
    if len(addr) < 20 or len(addr) > 60:
        return False
    return all(char in B58_ALPHABET_SET for char in addr)
