"""Permite `python -m param_manager.front`, além do console script."""

from __future__ import annotations

import sys

from param_manager.front.launcher import main

if __name__ == '__main__':
    sys.exit(main())
