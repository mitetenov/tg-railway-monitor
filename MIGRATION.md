# Go migration validation — 2026-10-22

Migrated from Python baseline `4442a00`; integrated all monitoring reliability changes from current main `d971895` (PR #39). Local validation preceded PR creation; no deployment.

## Compatibility

- `/start` wizard, `/stop`, `/lang`, EN/RU and Georgian travel-date semantics.
- Original callback names, per-chat JSON configuration and seat snapshot formats.
- Automatic restoration after restart; non-root UID/GID 1000:1000 and `/app/data`.
- Grouped notifications, class filters, train times, prices, tre.ge purchase links.

Intentional fixes: unfinished wizard drafts do not change an active route;
language selection works during setup; failed delivery does not advance the
snapshot; tickets reappearing after an empty result are announced again.
Language retention on stop, expiry after the Georgian travel day, class-specific snapshot keys and legacy snapshot migration preserve the newer main behavior. Storage writes are atomic. Corrupt state can be rebuilt; unreadable configs are
logged and skipped during restoration. Unwritable storage fails startup clearly.

## Image measurements

Rebuilt baseline and Go images on the same local Docker engine. Sizes use
`docker image inspect .Size` and decimal MB (1 MB = 1,000,000 bytes).

| Image | Architecture | Bytes | MB | Filesystem layers |
|---|---|---:|---:|---:|
| Python baseline | ARM64 | 118380087 | 118.38 | 10 |
| Go scratch | ARM64 | 10063020 | 10.06 | 4 |
| Go scratch | AMD64 | 10893157 | 10.89 | 4 |

Same-architecture reduction: **91.50%**. AMD64 Python size was not
measured. Go images contain no Python interpreter, compiler, shell, source tree,
local secrets or test fixtures. CA roots are present, while locales, station
names and timezone data are embedded in the binary.

A version-only rebuild (`VERSION=9.9.9`) reused the compiled binary and the first
three runtime layer digests. Only the final version-file layer changed; the
native `--version` returned `9.9.9`. Manifest/runtime files precede source in the
build, Go compilation uses a BuildKit cache mount, and `.dockerignore` allowlists
only required inputs. Release builds cross-compile natively for AMD64/ARM64.

## Checks completed

- `go test -race -count=1 -timeout=60s ./...`: **205 tests/subtests passed**,
  including **160 exact notification comparisons** against the Python baseline;
  statement coverage 79.2%.
- `go vet`, `gofmt`, `git diff --check`, GitHub Actions `actionlint`: passed.
- ARM64 and AMD64 images: built and ran offline `--check`; version checked.
- Real ARM64 container against local Telegram/tre.ge HTTP fixtures: startup,
  long polling, complete wizard, grouped notification and snapshot persistence.
- Existing volume initialized by Python image: read/write compatibility as UID
  1000, restored monitoring after restart, no duplicate notification.
- Read-only root filesystem, dropped capabilities, CA root bundle and writable
  data/tmp ownership verified. SIGTERM completed cleanly in about 0.08 seconds.
- Compose configuration validated without loading/interpolating secret values.

Live Telegram/tre.ge behavior was not tested; test endpoints used dummy
credentials. GitHub CI has been updated but has not run remotely. Deployment
and rollback instructions are in `DEPLOY.md`.
