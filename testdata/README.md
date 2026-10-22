# Python notification fixtures

`python_notifications.json` contains 160 outputs captured from the original
`poller._check_and_notify` at committed baseline `4442a00` (before the Go rewrite).
Inputs vary EN/RU, Any/I/II/Business filters, two rides, class availability,
previous seat counts, and changed route keys. Generation used Python Random
seed 42, 20 cases per language/filter pair. HTTP, storage and Telegram sends
were substituted locally; no external service or user data was accessed.

`TestPythonNotificationParity` feeds each input/snapshot to the Go notifier and
compares its output text exactly. The newer main reliability behavior from PR #39 is also preserved, including language retention on stop, monitor expiry in Georgia, class-specific state keys and migration of legacy snapshots. Separate behavioral tests cover intentional
fixes: retry after delivery failure, empty results and missing classes resetting
state, atomic wizard configuration, and language selection within the wizard.

## Independent timetable fixture

`tre_timetable.json` contains only the fields used from the public tre.ge
timetable response fetched on 2026-10-22 for Tbilisi → Batumi on 2026-10-24.
The availability endpoint returned no rides for that date, but the timetable
listed trains 802 at 08:05 and 804 at 17:10. An older capture with a changed time
and a duplicate row were added to exercise historical-capture selection.
No tokens, user data, reservations, or booking requests are included.

`TestTimetableHTTPContractAndSoldOutWizard` serves this fixture over local TLS,
with an empty availability response, and verifies that both trains can still
be selected in the wizard and that the selection is saved.
