# Railway API contract

The bot uses the public Georgian Railway integration consumed by tre.ge.
Implementation: `railway.go`; HTTP/TLS fixtures: `railway_test.go`.

Base URL: `https://gateway.tkt.ge/integrations/api/GeorgianRailway`.
`TRE_API_BASE` and `TRE_API_KEY` override the default base and public client key.
Every request includes the `api_key` query parameter. Requests have a 15-second
context deadline and share a reusable HTTP transport. Errors do not log URLs or
response bodies. Non-200, malformed JSON, null, and missing availability arrays
are errors, preserving the previous availability baseline.

## Stations

`GET /Dictionaries/civil-stations?api_key=...`

Response: array of objects with `code`, `stationName`, `isPopular`.
String and numeric codes are accepted. The bot skips blank/invalid codes and
duplicates. If the dictionary is unavailable or contains no usable stations,
`stations.json` supplies the offline list. Station display names come from the
embedded EN/RU/KA dictionary, with the API name as a fallback.

The offline list excludes Kutaisi city (`57530`), which was unserved when the
Python dictionary was recorded. If the API includes it again, it becomes
selectable automatically. Kutaisi Airport is `57450`.

Sample: `sample_stations.json`.

## Ticket availability

`GET /Availability/available-rides`

| Query parameter | Value |
|---|---|
| `passengersNumbers` | `1` |
| `departureDateFrom` | Selected date + `T00:00:00.000Z` |
| `startStationCode` | Departure code |
| `endStationCode` | Arrival code |
| `returnWay` | `false` |
| `disability` | `false` |
| `api_key` | Public integration key |

The response must contain a non-null `departureAvailableRides` array; an empty
array is a successful no-availability result. Each ride supplies `rideNumber`,
`rideStartDate`, `rideEndDate`, `rideDuration`, `availableSeatsClasses`.
Each class supplies `seatClassId`, `availableNumberOfSeats`, `moneyAmount`.

| Class ID | Stored filter | Notification label |
|---|---|---|
| `1` | `I` | I Class |
| `2` | `II` | II Class |
| `5` | `Business` | Business |

`Any` includes all classes. Prices preserve the JSON number representation;
missing/null prices render as zero. Missing/null seat counts are zero. Ride
numbers accept strings or numbers. Unknown ride fields are ignored. Rides
without a ride number are skipped. Times display the upstream HH:MM as returned;
the bot does not convert train times between zones.

Sample: `sample_rides.json`. Notifications compare successful results with the
persisted route/date snapshot. Errors do not clear it; absent rides/classes in
a successful response do. Notifications contain all currently available rides
matching the filter when any seats appear or increase.

## Timetable (independent of availability)

The wizard uses `https://api.tre.ge/v1/GeorgianRailway/stations/timetable`,
the independent timetable consumed by the tre.ge website. The daily
`available-rides` response can be empty when tickets sell out and cannot be the
primary source of departure choices.

Authenticate lazily with `POST /connect/token`, form-encoded
`grant_type=client_credentials`, using the website's public `RailwayWeb` client.
Cache the returned bearer token only in memory, with expiry and one retry after
HTTP 401. Tokens, credentials, URLs, and response bodies are excluded from errors.
`TRE_TIMETABLE_BASE` and `TRE_TIMETABLE_KEY` override this service independently
of the availability API. Authentication and the timetable request share a
15-second deadline and the existing reusable HTTP client.

Request query: `Date=YYYY-MM-DD`, `FromStation=<code>`, `ToStation=<code>`.
Use a date without a timezone: the service interprets an offset-bearing midnight
as the previous UTC date. Require `ok=true` and a non-null `stationTable` array;
an empty array is a successful empty schedule. Rows use `trainNumber`,
`leavingDate`, `enteringDate`, `fromStationNumber`, `toStationNumber`, and
`requestDate`. Check the returned route and departure date, and use the most
recent capture per train to avoid obsolete times from historical duplicates.

Live verification on 2026-10-22: Tbilisi to Batumi for 2026-10-23 and 2026-10-24
returned no available rides but the timetable supplied trains 802 at 08:05 and
804 at 17:10. For 2026-10-30 both sources agreed on train numbers and the raw
displayed times (the availability response adds `Z`, without changing HH:MM).

Choices contain the upstream `HH:MM` and train number, sorted by time then
number. "Any time" is always available after an empty timetable or provider error.
The published timetable does not cover every intermediate station pair: live
verification found Kutaisi Airport → Batumi absent even with available tickets.
If the timetable is empty or unavailable, fall back to the existing availability
endpoint and explicitly label a nonempty list as limited to trains with tickets.
Both lookups share a 15-second wizard deadline.
Selected departures persist as `departure_time` and `ride_number`; notifications
include only rides matching both values. The availability request still covers the
whole day. Existing searches without these fields include all departures and
retain their notification history. Filtered snapshot keys include the departure
time and number and do not reuse an unrestricted or legacy baseline.

## Purchase URL

```text
https://tre.ge/en/search?leavingPlace=56014&enteringPlace=57151&leaveDate=30.12.2026&passengerCount=1&wcuCount=0&depVT=railway
```

The search uses numeric station codes and the selected date formatted as
`DD.MM.YYYY`. No purchase, reservation, seat-map request, or payment is made.
Calendar/popular-route sample files are retained as reference data; those
endpoints are not needed by the bot and have no runtime client methods.
