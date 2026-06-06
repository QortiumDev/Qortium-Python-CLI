from __future__ import annotations

import traceback

from qortium_cli.app import run
from qortium_cli.ui import error, warn
from qortium_cli.utils import pretty_exception


def main() -> None:
    try:
        run()
    except KeyboardInterrupt:
        warn("\nCancelled.")
    except Exception as exc:
        error("ERROR: " + pretty_exception(exc))
        traceback.print_exc()
        try:
            input("\nAn error occurred. Press Enter to exit...")
        except Exception:
            pass
