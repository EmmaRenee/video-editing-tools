#!/usr/bin/env python3
"""Compatibility wrapper for the V1 footage rater."""

from __future__ import annotations

import sys

from videoedit.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["rate", *sys.argv[1:]]))
