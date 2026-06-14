#!/usr/bin/env python3
import os
import sys

sys.dont_write_bytecode = True

# Ensure the project root is on sys.path when double-clicked from Explorer.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from qortium_cli.entrypoint import main

if __name__ == "__main__":
    main()
