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
| `bot.go` | Search list/cards, sequential Telegram update loop and per-chat/per-user wizard |
| `telegram.go` | Telegram Bot API HTTP client, JSON models, safe errors |
| `railway.go` | tre.ge station/search client, purchase URLs, class filters |
| `timetable.go` | Independent tre.ge timetable client and anonymous access cache |
| `poller.go` | One cancellable goroutine per search, availability diff and delivery |
| `storage.go` | Atomic per-chat search lists and per-search snapshot files |
| `i18n.go` | Embedded translations and station dictionary |
| `stations.json` | Single source of station names/codes/popularity/slugs |
| `locales/{en,ru}/messages.json` | User-facing translations |
| `*_test.go`, `testdata/` | Behavioral tests and Python parity fixtures |

Only `/start`, `/stop`, `/lang` are registered commands. Do not restore removed
`/setroute`, `/setdate`, `/setclass`, `/status` commands. Wizard steps: date,
custom date, departure, arrival, departure time/train, class. `/start` opens the search list; the inline
add button starts the wizard. Search cards offer pause/resume and confirmed
deletion. Lists use eight searches per page and include paused searches.
Old wizard callback strings remain supported.
Travel dates always use **Asia/Tbilisi**, regardless of user/host timezone.
After selecting a route, offer time/train choices from the independent tre.ge
timetable, regardless of ticket availability, sorted by departure time and
paginated eight per page. If the timetable is empty or unavailable, fall back to
`available-rides` and label a nonempty fallback list as limited to available
tickets; the published timetable omits some intermediate station pairs.
Request `Date=YYYY-MM-DD`, with exact from/to station filters; a timezone offset
can make the timetable API select the previous date. Validate the returned route
and departure date. Historical captures may repeat a train: use the most recent
`requestDate` per train. Guest access uses the public web client credentials;
cache tokens in memory only, refresh on expiry/401, and never log credentials.
Always offer "Any time". Offer refresh only when loading failed or the departure
list is empty; hide it after a successful nonempty load, including fallback lists.
Empty/error responses must not block setup.
Validate train choices against the current draft; refreshing must not change what
an old choice button selects. Time strings are compared as returned, with no
timezone conversion.
Exclude the selected departure station from both quick arrival choices and every
page of the arrival station list, including error recovery. Keep the same-station
callback validation to reject stale or forged buttons.

Wizard drafts remain in memory until class selection; completing the wizard
adds a new search without replacing existing ones. Cancellation returns to the
list. Language buttons work during any wizard step. `/stop` cancels all workers
in the chat, waits for them to exit, deletes all searches/snapshots while
preserving language, and clears all drafts for that chat.

## Persistence and polling

- Config: `data/{chat_id}.json` contains chat-level `language` (`en`, `ru`) and
  `searches`. Each search has a stable random 16-hex-character `id`, `paused`,
  `from_station_code`, `to_station_code`, `from_station`, `to_station`, `date`,
  and `seat_class` (`Any`, `I`, `II`, `Business`). Optional `departure_time`
  (`HH:MM`) and `ride_number` identify the selected departure; missing fields
  mean any time/train. Legacy single-route configs
  become one search with ID `legacy`; the next mutation writes the new format.
- Snapshot: `data/{chat_id}.{search_id}.state.json`; the migrated `legacy` search
  retains `data/{chat_id}.state.json` to preserve its notification baseline.
  `key` is `from>to@date#class`, with `#HH:MM#ride_number` appended for a
  selected departure. Legacy keys without the class are migrated only for
  unrestricted searches; `rides` maps
  ride numbers to class IDs, each containing `seats` and `price`.
- JSON writes use a private temporary file, fsync, and atomic rename.
- Active searches resume automatically on startup. Paused searches stay paused
  across restarts and keep snapshots; resuming checks immediately without
  reannouncing unchanged seats. Pause/delete cancel and join only that worker.
  Past travel dates expire at Georgian midnight, preserving the interface
  language and other searches. Paused searches expire on startup or navigation.
  Snapshots suppress
  duplicate notifications after restart. Corrupt configs are logged/skipped;
  corrupt state is disposable. Storage preflight fails startup on unwritable data.
- Check immediately, then 60 seconds after each completed check. Reuse HTTP clients.
- Notify on newly available seats or an increase, grouped across all available
  rides in the selected class and departure time/train. Decreases only update state. A successful empty
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

GitHub Actions validates modules, formatting, vet, golangci-lint v2.15.0,
unit tests, race tests and the production binary on `ubuntu-26.04`.
The required `test` job name stays unchanged. `setup-go` caches via `go.mod`;
this standard-library-only module intentionally has no `go.sum`.
Every PR, main push and manual validation builds both Docker platforms
on native `ubuntu-26.04` / `ubuntu-26.04-arm` runners without credentials.
Only main pushes log in and publish the same built image IDs. Digest artifacts
retain one day; manifests keep the existing `latest` and version tags. Publication
is serialized and never cancelled mid-push. Actions use exact release SHA pins;
weekly Dependabot covers Go modules, Actions and Docker, grouping minor/patch
updates. See `CI_AUDIT.md` for historical baseline measurements.

## Environment and conventions

`BOT_TOKEN` required; `.env` is loaded without overriding environment variables.
`DATA_DIR` defaults to `data` locally and `/app/data` in Docker. `TICKET_SOURCE`
accepts `trege` (default) and its alias `tre.ge`, ignoring case and surrounding
whitespace. Optional test/provider overrides: `TRE_API_BASE`,
`TRE_API_KEY`, `TRE_TIMETABLE_BASE`, `TRE_TIMETABLE_KEY`, `TELEGRAM_API_BASE`.
Never log token-bearing request URLs.

Use `gofmt`, idiomatic Go comments on exported symbols, contextual errors and
`slog`. Synchronize shared worker/storage state and test concurrent lifecycle
changes with the race detector. Avoid holding storage locks across network I/O.
Station fallback excludes unserved Kutaisi city `57530`; API results may re-enable
it. Time strings from railway responses are displayed as returned (no conversion).

## Git

Push to `origin`; branches `feat/...`, `fix/...`, `refactor/...`; PRs target
`main` only. Rebase/merge main before a PR; squash-merge only when requested.
Preserve unrelated dirty files and untracked `docs/`. Never add a coauthor trailer.
Keep `.worktrees/` out of the Git index; local checkouts must not become gitlinks
without `.gitmodules`, which breaks checkout credential cleanup in CI.

Integration tests that start subprocesses and Docker runtime smoke checks were
removed by request. Isolated domain, in-process HTTP fake and filesystem tests remain.

Integration tests that start subprocesses and Docker runtime smoke checks were
removed by request. Isolated domain, in-process HTTP fake and filesystem tests remain.
