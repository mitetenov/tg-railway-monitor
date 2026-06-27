#!/usr/bin/env bash
# ─── bump_version.sh — SemVer auto-increment ──────────────────────────
#
# Reads the current version from version.txt (located one directory up
# from this script), increments the requested segment, and writes the
# new version back.
#
# Usage:
#   ./scripts/bump_version.sh         # increment patch (default)
#   ./scripts/bump_version.sh patch   # increment patch (explicit)
#   ./scripts/bump_version.sh minor   # increment minor, reset patch to 0
#   ./scripts/bump_version.sh major   # increment major, reset minor+patch to 0
#   ./scripts/bump_version.sh show    # print current version and exit
#   ./scripts/bump_version.sh -n      # dry-run: print new version, don't write
#
set -euo pipefail

# ── Locate version.txt relative to THIS script, not CWD ───────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION_FILE="${SCRIPT_DIR}/../version.txt"

# Normalise path (remove /../)
VERSION_FILE="$(cd "$(dirname "$VERSION_FILE")" && pwd)/$(basename "$VERSION_FILE")"

# ── Parse arguments ──────────────────────────────────────────────────
DRY_RUN=false
SEGMENT="patch"

for arg in "$@"; do
    case "$arg" in
        -n|--dry-run|--dryrun)
            DRY_RUN=true
            ;;
        patch|minor|major|show)
            SEGMENT="$arg"
            ;;
        *)
            echo "Usage: $0 [patch|minor|major|show] [-n]"
            echo "  patch  — increment patch (default)"
            echo "  minor  — increment minor, reset patch to 0"
            echo "  major  — increment major, reset minor+patch to 0"
            echo "  show   — print current version and exit"
            echo "  -n     — dry-run, don't write file"
            exit 2
            ;;
    esac
done

# ── Read current version ─────────────────────────────────────────────
if [ ! -f "$VERSION_FILE" ]; then
    echo "ERROR: version file not found: $VERSION_FILE" >&2
    exit 1
fi

CURRENT="$(cat "$VERSION_FILE" | tr -d '[:space:]')"

# Validate semver: must match major.minor.patch
if ! echo "$CURRENT" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "ERROR: version.txt does not contain a valid SemVer string (major.minor.patch)." >&2
    echo "  got: '$CURRENT'" >&2
    exit 1
fi

# ── Show & exit ──────────────────────────────────────────────────────
if [ "$SEGMENT" = "show" ]; then
    echo "$CURRENT"
    exit 0
fi

# ── Parse components ─────────────────────────────────────────────────
# Use 10# prefix so numbers with leading zero (e.g. 08, 09) parse correctly
MAJOR="$(( 10#$(echo "$CURRENT" | cut -d. -f1) ))"
MINOR="$(( 10#$(echo "$CURRENT" | cut -d. -f2) ))"
PATCH="$(( 10#$(echo "$CURRENT" | cut -d. -f3) ))"

# ── Increment ────────────────────────────────────────────────────────
case "$SEGMENT" in
    major)
        MAJOR=$(( MAJOR + 1 ))
        MINOR=0
        PATCH=0
        ;;
    minor)
        MINOR=$(( MINOR + 1 ))
        PATCH=0
        ;;
    patch)
        PATCH=$(( PATCH + 1 ))
        ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"

# ── Preview ──────────────────────────────────────────────────────────
echo "${CURRENT} → ${NEW_VERSION}  ($(dirname "$VERSION_FILE")/version.txt)"

if [ "$DRY_RUN" = true ]; then
    echo "(dry-run — file not modified)"
    exit 0
fi

# ── Write ─────────────────────────────────────────────────────────────
echo "$NEW_VERSION" > "$VERSION_FILE"
echo "✓ version.txt updated"
