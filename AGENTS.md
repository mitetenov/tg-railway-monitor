# AGENTS.md — tg-ticket-monitor

Instructions for coding agents. Keep this file current when the codebase changes.

## Project

Telegram bot monitoring Georgian Railway (tre.ge) tickets. Go 1.27.3, standard
library only, no external modules. Remote: `mitetenov/tg-railway-monitor`.
Version: `version.txt`. Docker image: `mitetenov/tg-ticket-monitor`.

## Build, test, run

```sh
go test -race -count=1 ./...
go vet ./...
go build -trimpath -o ticket-monitor .
cp .env.example .env  # set BOT_TOKEN
./ticket-monitor
./ticket-monitor --check    # resource/storage check, no network or token
./ticket-monitor --version
```

Tests use local HTTP/TLS fixtures and temporary storage; no real Telegram token,
production data, or live railway service is needed. `testdata/python_notifications.json`
contains 160 notification cases captured from committed Python HEAD `4442a00`.

## Architecture

| File | Purpose |
|---|---|
| `main.go` | Environment, HTTP clients, signal handling, startup |
| `bot.go` | Sequential Telegram update loop and per-chat/per-user wizard |
| `telegram.go` | Telegram Bot API HTTP client, JSON models, safe errors |
| `railway.go` | tre.ge station/search client, purchase URLs, class filters |
| `poller.go` | One cancellable goroutine per chat, availability diff and delivery |
| `storage.go` | Atomic per-chat JSON config and snapshot files |
| `i18n.go` | Embedded translations and station dictionary |
| `stations.json` | Single source of station names/codes/popularity/slugs |
| `locales/{en,ru}/messages.json` | User-facing translations |
| `*_test.go`, `testdata/` | Behavioral tests and Python parity fixtures |

Only `/start`, `/stop`, `/lang` are registered commands. Do not restore removed
`/setroute`, `/setdate`, `/setclass`, `/status` commands. Wizard steps: date,
custom date, departure, arrival, class. Old callback strings remain supported.
Travel dates always use **Asia/Tbilisi**, regardless of user/host timezone.

Wizard drafts remain in memory until class selection; cancellation preserves the
previous active route. Language buttons work during any wizard step. `/stop`
cancels the worker, waits for it to exit, clears monitor fields/state while preserving language, and clears drafts.

## Persistence and polling

- Config: `data/{chat_id}.json`. Keys are compatible with the Python version:
  `from_station_code`, `to_station_code`, `from_station`, `to_station`, `date`,
  `seat_class` (`Any`, `I`, `II`, `Business`), `language` (`en`, `ru`).
- Snapshot: `data/{chat_id}.state.json`: `key` is `from>to@date#class`; legacy keys without the class are migrated; `rides` maps
  ride numbers to class IDs, each containing `seats` and `price`.
- JSON writes use a private temporary file, fsync, and atomic rename.
- Complete configurations resume automatically on startup. Past travel dates expire at Georgian midnight, preserving the interface language and clearing monitor state. Snapshots suppress
  duplicate notifications after restart. Corrupt configs are logged/skipped;
  corrupt state is disposable. Storage preflight fails startup on unwritable data.
- Check immediately, then 60 seconds after each completed check. Reuse HTTP clients.
- Notify on newly available seats or an increase, grouped across all available
  rides in the selected class. Decreases only update state. A successful empty
  result resets stale rides; API errors preserve state. Commit state after send
  succeeds so failed notifications retry. Multi-message delivery is at-least-once.
- No legacy standalone/threading monitor or Python compatibility patches remain.

## Docker

```sh
docker build --build-arg VERSION=$(cat version.txt) -t tg-ticket-monitor:local .
docker run --rm --network none tg-ticket-monitor:local --version
docker compose build
docker compose up -d
```

Multi-stage native build with cross-compilation for amd64/arm64. `scratch` runtime
contains the static binary, CA certificates, embedded locales/timezone database,
and writable `/app/data` and `/tmp`. **Keep UID/GID 1000:1000**: existing volumes
belong to this UID. Changing it requires an explicit ownership migration.
`.dockerignore` is an allowlist: secrets, runtime data, worktrees, docs and tests
are excluded. Manifest and runtime assets precede source; compiler cache uses a
BuildKit cache mount. Version metadata is last. Avoid `--no-cache` in normal builds.

## Environment and conventions

`BOT_TOKEN` required; `.env` is loaded without overriding environment variables.
`DATA_DIR` defaults to `data` locally and `/app/data` in Docker. `TICKET_SOURCE`
only accepts `trege`. Optional test/provider overrides: `TRE_API_BASE`,
`TRE_API_KEY`, `TELEGRAM_API_BASE`. Never log token-bearing request URLs.

Use `gofmt`, idiomatic Go comments on exported symbols, contextual errors and
`slog`. Synchronize shared worker/storage state and test concurrent lifecycle
changes with the race detector. Avoid holding storage locks across network I/O.
Station fallback excludes unserved Kutaisi city `57530`; API results may re-enable
it. Time strings from railway responses are displayed as returned (no conversion).

## Git

Push to `origin`; branches `feat/...`, `fix/...`, `refactor/...`; PRs target
`main` only. Rebase/merge main before a PR; squash-merge only when requested.
Preserve unrelated dirty files and untracked `docs/`. Never add a coauthor trailer.
