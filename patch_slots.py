"""
Patch the installed python-telegram-bot package for Python 3.13 compatibility.

PTB v20.8 has a known issue: the `Updater` class defines `__slots__` but assigns
`self.__polling_cleanup_cb` in `__init__` without including it in the slots tuple.
Python 3.13 enforces `__slots__` more strictly, causing AttributeError on init.

This script adds the missing slot name so the library works on Python 3.13.
Run after `pip install -r requirements.txt` or after any venv rebuild.
"""

import os
import shutil


def patch_updater_slots(site_packages: str) -> bool:
    """Patch the Updater.__slots__ tuple in the installed telegram package."""
    updater_path = os.path.join(site_packages, "telegram", "ext", "_updater.py")
    if not os.path.isfile(updater_path):
        print(f"❌ Not found: {updater_path}")
        return False

    with open(updater_path) as f:
        content = f.read()

    marker = '"__polling_cleanup_cb"'
    if marker in content:
        print(f"✅ Already patched — {marker} found in {updater_path}")
        return True

    old = (
        '    __slots__ = (\n'
        '        "__lock",\n'
        '        "__polling_task",\n'
        '        "_httpd",\n'
        '        "_initialized",\n'
        '        "_last_update_id",\n'
        '        "_running",\n'
        '        "bot",\n'
        '        "update_queue",\n'
        '    )'
    )
    new = (
        '    __slots__ = (\n'
        '        "__lock",\n'
        '        "__polling_task",\n'
        '        "__polling_cleanup_cb",\n'
        '        "_httpd",\n'
        '        "_initialized",\n'
        '        "_last_update_id",\n'
        '        "_running",\n'
        '        "bot",\n'
        '        "update_queue",\n'
        '    )'
    )

    if old not in content:
        print(f"❌ Could not find __slots__ tuple in {updater_path} — unexpected format")
        return False

    content = content.replace(old, new)

    # Backup original
    backup = updater_path + ".bak"
    if not os.path.exists(backup):
        shutil.copy2(updater_path, backup)
        print(f"📦 Backup saved: {backup}")

    with open(updater_path, "w") as f:
        f.write(content)

    print(f"✅ Patched {updater_path}")
    return True


def find_site_packages(venv_dir: str) -> str | None:
    """Find the site-packages directory inside a venv."""
    for lib in ["lib"]:
        py_dir = os.path.join(venv_dir, lib)
        if not os.path.isdir(py_dir):
            continue
        for entry in os.listdir(py_dir):
            if entry.startswith("python"):
                sp = os.path.join(py_dir, entry, "site-packages")
                if os.path.isdir(sp):
                    return sp
    return None


def main() -> None:
    # Try auto-detect from script location (project root with .venv/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.join(script_dir, ".venv")

    if os.path.isdir(venv_dir):
        sp = find_site_packages(venv_dir)
        if sp:
            print(f"📁 Found venv site-packages: {sp}")
            if patch_updater_slots(sp):
                print("\n✅ Patch applied successfully.")
                return
            print("\n❌ Patch failed.")
            return

    # Fallback: let the user provide the path
    print("❌ Could not auto-detect virtualenv site-packages.")
    print("   Usage: python3 patch_slots.py")
    print("   Or manually patch: find site-packages/telegram/ext/_updater.py")
    print("   and add '__polling_cleanup_cb' to the __slots__ tuple.")
    print(f"   Searched: {venv_dir}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
