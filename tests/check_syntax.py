#!/usr/bin/env python3
"""Syntax check for all project Python source files (excludes tests)."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
modules = sorted(
    f.name for f in ROOT.iterdir()
    if f.suffix == ".py" and not f.name.startswith("test_") and f.name != "check_syntax.py"
)

all_ok = True
for mod in modules:
    try:
        path = ROOT / mod
        ast.parse(path.read_text())
        print(f"  OK  {mod}")
    except SyntaxError as e:
        print(f"  FAIL  {mod}: {e}")
        all_ok = False

sys.exit(0 if all_ok else 1)
