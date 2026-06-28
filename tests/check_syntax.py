#!/usr/bin/env python3
"""Quick syntax check for all bot modules."""
import ast
import sys

modules = ["api.py", "config_manager.py", "poller.py", "bot.py"]
all_ok = True
for mod in modules:
    try:
        with open(mod) as f:
            ast.parse(f.read())
        print(f"  ✓ {mod}")
    except SyntaxError as e:
        print(f"  ✗ {mod}: {e}")
        all_ok = False

sys.exit(0 if all_ok else 1)
