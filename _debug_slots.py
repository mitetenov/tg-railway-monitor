#!/usr/bin/env python3
"""Check Updater class slots and inheritance."""
from telegram.ext._updater import Updater

print("Has __slots__:", hasattr(Updater, '__slots__'))
if hasattr(Updater, '__slots__'):
    print("__slots__:", Updater.__slots__)
print("Has __dict__:", hasattr(Updater, '__dict__'))
print("MRO:", [c.__name__ for c in Updater.__mro__])

# Check parent classes for slots
for cls in Updater.__mro__:
    if hasattr(cls, '__slots__'):
        print(f"{cls.__name__}.__slots__: {cls.__slots__}")

# Check .pyc freshness
import telegram.ext._updater as mod
print("Module file:", mod.__file__)
import os
print("File mtime:", os.path.getmtime(mod.__file__))
