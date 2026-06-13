from colorama import Fore, Style

APP_VERSION = "0.3.0"
APP_TITLE = f"Qortium CLI {APP_VERSION}"
SETUP_TITLE = "Qortium Setup"

DEFAULT_BASE_URL = "http://127.0.0.1:24891"
DEFAULT_TIMEOUT_SECONDS = 120
ASSET_ID_QORT = 0
NONCE_COMPUTE_TIMEOUT_SECONDS = 180
NONCE_COMPUTE_PATHS = (
    "/transactions/mempow/compute",
    "/transactions/compute/mempow",
    "/chat/compute",
    "/arbitrary/compute",
    "/addresses/publicize/compute",
)
NONCE_ERROR_MARKERS = ("nonce", "pow", "proof", "mempow")

PLACEHOLDER_VALUES = {"", "x", "changeme", "your_value_here"}

QDN_SERVICES = (
    "AUTO_UPDATE",
    "AUTO_UPDATE_BINARY",
    "ARBITRARY_DATA",
    "QCHAT_ATTACHMENT",
    "QCHAT_ATTACHMENT_PRIVATE",
    "ATTACHMENT",
    "ATTACHMENT_PRIVATE",
    "FILE",
    "FILE_PRIVATE",
    "FILES",
    "CHAIN_DATA",
    "WEBSITE",
    "GIT_REPOSITORY",
    "IMAGE",
    "IMAGE_PRIVATE",
    "THUMBNAIL",
    "QCHAT_IMAGE",
    "VIDEO",
    "VIDEO_PRIVATE",
    "AUDIO",
    "AUDIO_PRIVATE",
    "QCHAT_AUDIO",
    "QCHAT_VOICE",
    "VOICE",
    "VOICE_PRIVATE",
    "PODCAST",
    "BLOG",
    "BLOG_POST",
    "BLOG_COMMENT",
    "DOCUMENT",
    "DOCUMENT_PRIVATE",
    "LIST",
    "PLAYLIST",
    "APP",
    "METADATA",
    "JSON",
    "GIF_REPOSITORY",
    "STORE",
    "PRODUCT",
    "OFFER",
    "COUPON",
    "CODE",
    "PLUGIN",
    "EXTENSION",
    "GAME",
    "ITEM",
    "NFT",
    "DATABASE",
    "SNAPSHOT",
    "COMMENT",
    "CHAIN_COMMENT",
    "MAIL",
    "MAIL_PRIVATE",
    "MESSAGE",
    "MESSAGE_PRIVATE",
)

B58_ALPHABET_BYTES = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
B58_ALPHABET_SET = set(B58_ALPHABET_BYTES.decode("ascii"))

# Seed -> private key derivation constants (matches Hub/UI flow)
STATIC_SALT = "4ghkVQExoneGqZqHTMMhhFfxXsVg2A75QeS1HCM5KAih"
STATIC_BCRYPT_SALT = b"$2a$11$IxVE941tXVUD4cW0TNVm.O"
KDF_THREADS = 16

QORTIUM_ASCII = """
                                     d8,
                              d8P   `8P
                           d888888P
.d88b,.88P d8888b   88bd88b  ?88'    88b?88   d8P  88bd8b,d88b
88P  `88P'd8P' ?88  88P'  `  88P     88Pd88   88   88P'`?8P'?8b
?8b  d88  88b  d88 d88       88b    d88 ?8(  d88  d88  d88  88P
`?888888  `?8888P'd88'       `?8b  d88' `?88P'?8bd88' d88'  88b
    `?88
      88b
      ?8P
"""

RESET = Style.RESET_ALL
BOLD = Style.BRIGHT
DIM = Style.DIM

C_CORE = "\x1b[38;2;178;124;255m"
C_ACCENT = "\x1b[38;2;220;176;255m"
C_TEXT = Fore.WHITE
C_KEY = Fore.LIGHTYELLOW_EX + BOLD
C_GOOD = Fore.LIGHTGREEN_EX + BOLD
C_WARN = Fore.LIGHTYELLOW_EX + BOLD
C_BAD = Fore.LIGHTRED_EX + BOLD

# Deterministic per-address chat colors.
CHAT_USER_COLORS = [
    "\x1b[38;2;255;122;122m",  # red
    "\x1b[38;2;255;166;77m",   # orange
    "\x1b[38;2;255;214;102m",  # amber
    "\x1b[38;2;150;226;119m",  # lime
    "\x1b[38;2;88;220;176m",   # mint
    "\x1b[38;2;96;212;255m",   # cyan
    "\x1b[38;2;104;170;255m",  # blue
    "\x1b[38;2;138;132;255m",  # indigo
    "\x1b[38;2;184;126;255m",  # violet
    "\x1b[38;2;236;136;255m",  # magenta
    "\x1b[38;2;255;146;206m",  # pink
    "\x1b[38;2;182;192;208m",  # silver
]

# Top-to-bottom gradient for logo lines.
LOGO_GRADIENT = [
    "\x1b[38;2;232;208;255m" + BOLD,
    "\x1b[38;2;214;176;255m" + BOLD,
    "\x1b[38;2;196;144;255m" + BOLD,
    "\x1b[38;2;174;112;247m" + BOLD,
    "\x1b[38;2;148;88;229m" + BOLD,
    "\x1b[38;2;120;72;204m" + BOLD,
    "\x1b[38;2;90;60;176m" + BOLD,
]
