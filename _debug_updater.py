#!/usr/bin/env python3
"""Quick check: telegram-bot Updater class and Python version."""
import inspect
from telegram.ext._updater import Updater
import telegram
import sys

print("Python:", sys.version)
print("python-telegram-bot:", telegram.__version__)
print()
print("Updater.__init__ source:")
src = inspect.getsource(Updater.__init__)
print(src[:1500])
