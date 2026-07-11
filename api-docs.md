# tre.ge Georgian Railway API — Endpoint Reference

Base URL: `https://gateway.tre.ge/integrations/api/GeorgianRailway`
API Key: `7d8d34d1-e9af-4897-9f0f-5c36c179be77` (public key, embedded in Next.js client-side JS)

All endpoints require `api_key` as a query parameter. All requests are `GET`. Responses are JSON. All endpoints are **public** (no authentication beyond the hard-coded key).

## Codebase Architecture

The API client code uses a **factory + abstract base class** pattern for extensibility:

### TicketApi ABC (`_api_base.py`)

`TicketApi` is an abstract base class defining 5 methods that every ticket provider must implement:

| Method                       | Purpose                                         |
|------------------------------|-------------------------------------------------|
| `get_stations(session)`      | Fetch list of railway stations                  |
| `search_trips(session, from, to, date)` | Search available rides on a route    |
| `get_availability_calendar(session, from, to)` | Multi-day availability calendar |
| `get_seats(session, ride_id)` | Per-ride seat maps (stub — raises NotImplementedError) |
| `get_prices(session, ride_id)` | Standalone pricing (stub — raises NotImplementedError) |

### TreGeApi (`api_tre.py`)

`TreGeApi(TicketApi)` is the concrete implementation for the tre.ge backend. It:

- Implements the 3 core REST endpoints (stations, rides, calendar)
- Raises `NotImplementedError` for `get_seats()`/`get_prices()` (no public endpoints for these)
- Provides `build_purchase_url(from_code, to_code, date)` — generates a tre.ge purchase link
- Includes station slug mapping helpers (`station_to_slug`, `slug_to_station`)

### Factory (`api.py`)

`api.py` provides the factory layer and backward-compat aliases:

- `get_ticket_api(source=None)` — factory function; resolves `source` from the `TICKET_SOURCE` environment variable (default `"trege"`), instantiates the matching `TicketApi` class, and caches the result as a module-level singleton.
- `init_ticket_api(source=None)` — explicit startup initializer (called from `bot.post_init`).
- **Backward-compatible module-level aliases** — `get_stations()`, `get_available_rides()`, `get_availability_calendar()` delegate to the cached singleton so existing callers (`poller.py`, `bot.py`) work unchanged.

### How components connect

```
poller.py / bot.py
      │
      ▼ call backward-compat alias
api.py (get_stations / get_available_rides / ...)
      │
      ▼ delegate to cached singleton
TreGeApi (api_tre.py)  ←── implements TicketApi (_api_base.py)
      │
      ▼ HTTP via aiohttp
tre.ge REST API
```

### Constants

Defined in `_api_base.py` and shared across all implementations:

```python
API_BASE = "https://gateway.tre.ge/integrations/api/GeorgianRailway"
API_KEY  = "7d8d34d1-e9af-4897-9f0f-5c36c179be77"
```

---

## 1. Stations Dictionary

Fetches the full list of Georgian Railway stations.

**Endpoint:** `GET /Dictionaries/civil-stations`

**Parameters:**

| Param    | Type   | Required | Description                    |
|----------|--------|----------|--------------------------------|
| api_key  | string | yes      | Public API key                 |

**Example URL:**
```
https://gateway.tre.ge/integrations/api/GeorgianRailway/Dictionaries/civil-stations?api_key=7d8d34d1-e9af-4897-9f0f-5c36c179be77
```

**Response format:** Array of station objects.

```json
[
  {
    "code": 56014,
    "stationName": "Tbilisi (tbilisi-samg)",
    "isPopular": true
  },
  {
    "code": 57151,
    "stationName": "Batumi (batumi ( samg))",
    "isPopular": true
  }
]
```

| Field        | Type    | Description                          |
|--------------|---------|--------------------------------------|
| code         | int     | Numeric station code                 |
| stationName  | string  | Station name (Latin transliteration) |
| isPopular    | bool    | Whether it's a popular station       |

**Known stations (17 codes found in codebase):**

|| Code   | Name                     | Notes                         |
||--------|--------------------------|-------------------------------|
|| 56014  | Tbilisi                  |                               |
|| 57151  | Batumi                   |                               |
|| 57530  | Kutaisi                  | city center; found via popular-routes, not in civil-stations dict |
|| 57450  | Kutaisi Airport          |                               |
| 57290  | Zugdidi                  |
| 57120  | Kobuleti                 |
| 57100  | Ozurgeti                 |
| 57190  | Senaki                   |
| 57000  | Samtredia                |
| 57070  | Ureki                    |
| 57210  | Poti                     |
| 57900  | Gori                     |
| 57720  | Khashuri                 |
| 57600  | Zestafoni                |
| 57510  | Rioni                    |
| 57030  | Nigoiti                  |
| 56040  | Mtskheta                 |
| 56080  | Kaspi                    |

The API returns ~36 stations total. Station names use Latin transliteration in the dictionary, but Georgian script in the availability endpoints (see quirk below).

**Used by:** `bot.py` — populates station selection keyboard on bot startup. Falls back to a hardcoded list if the API call fails.

**Source files:**
- `api.py:101` — `get_stations()` async alias (delegates to ``TreGeApi.get_stations()``)
- `api_tre.py:166` — `TreGeApi.get_stations()` (actual implementation)
|- `api_explorer.py:30` — `get_stations()` sync wrapper
|- `bot.py:57` — `load_stations()` startup cache

---

## 2. Popular Routes Summary

Returns aggregate availability data for popular routes in a given direction.

**Endpoint:** `GET /Availability/availability-time-table`

**Parameters:**

| Param          | Type   | Required | Description                                      |
|----------------|--------|----------|--------------------------------------------------|
| day            | string | yes      | `"Today"` or `"Tomorrow"`                        |
| directionType  | string | yes      | `"FromTbilisi"` or `"ToTbilisi"`                 |
| api_key        | string | yes      | Public API key                                   |

**Example URL:**
```
https://gateway.tre.ge/integrations/api/GeorgianRailway/Availability/availability-time-table?day=Tomorrow&directionType=FromTbilisi&api_key=7d8d34d1-e9af-4897-9f0f-5c36c179be77
```

**Response format:** Array of route summary objects.

```json
[
  {
    "fromStationNumber": 56014,
    "fromStationName": "თბილისი",
    "toStationNumber": 57151,
    "toStationName": "ბათუმი",
    "availableCount": 23,
    "isAnyTripAvailable": false,
    "ridesNumber": 1,
    "priceFrom": 35,
    "duration": "02:20:00",
    "mobileImage": "https://static.tre.ge/Railway/Popular/batumi.jpg"
  }
]
```

| Field                | Type   | Description                              |
|----------------------|--------|------------------------------------------|
| fromStationNumber    | int    | Departure station code                   |
| fromStationName      | string | Departure station name (Georgian script) |
| toStationNumber      | int    | Arrival station code                     |
| toStationName        | string | Arrival station name (Georgian script)   |
| availableCount       | int    | Total available tickets across all rides |
| isAnyTripAvailable   | bool   | Whether any trip has availability        |
| ridesNumber          | int    | Number of rides on this route            |
| priceFrom            | float  | Minimum ticket price (GEL)               |
| duration             | string | Approximate duration (constant per route, not ride-specific) |
| mobileImage          | string | Banner image URL for the destination     |

**Note:** `duration` is a fixed approximate value per route, not the actual ride duration from the timetable.

**Used by:** `api_explorer.py:108` — `get_popular_routes()` (exploratory tool only, not used in production monitor/bot).

**Source files:**
|- `api_explorer.py:108` — `get_popular_routes()`

---

## 3. Availability Calendar

Returns daily ticket availability counts for a route over a ~30-day window.

**Endpoint:** `GET /Availability/availability-calendar`

**Parameters:**

| Param            | Type   | Required | Description              |
|------------------|--------|----------|--------------------------|
| fromStationCode  | string | yes      | Departure station code   |
| toStationCode    | string | yes      | Arrival station code     |
| api_key          | string | yes      | Public API key           |

**Example URL:**
```
https://gateway.tre.ge/integrations/api/GeorgianRailway/Availability/availability-calendar?fromStationCode=56014&toStationCode=57151&api_key=7d8d34d1-e9af-4897-9f0f-5c36c179be77
```

**Response format:** Object with two arrays.

```json
{
  "toDestionation": [
    {
      "date": "2026-06-27T00:00:00",
      "available": 1
    },
    {
      "date": "2026-06-28T00:00:00",
      "available": 5
    }
  ],
  "fromDestionation": [
    {
      "date": "2026-06-27T00:00:00",
      "available": 0
    }
  ]
}
```

| Field              | Type   | Description                              |
|--------------------|--------|------------------------------------------|
| toDestionation     | array  | Tickets going **to** the destination     |
| fromDestionation   | array  | Tickets coming **from** the destination (return direction) |
| .date              | string | ISO date (may omit timezone)             |
| .available         | int    | Number of available tickets on that date |

**Quirks:**
- Field names have a typo: "Destionation" instead of "Destination" (missing 'a'). This is the actual API response.
- `date` values may omit timezone information (unlike `available-rides` which uses `Z` suffix).

**Used by:** `api_explorer.py:45` — `get_availability_calendar()` (exploratory tool only, not used in production monitor/bot).

**Source files:**
- `api.py:119` — `get_availability_calendar()` async alias (delegates to ``TreGeApi.get_availability_calendar()``)
- `api_tre.py:199` — `TreGeApi.get_availability_calendar()` (actual implementation)
|- `api_explorer.py:45` — `get_availability_calendar()` sync wrapper

---

## 4. Available Rides (Main Endpoint)

Returns actual train rides with seat classes, availability counts, and pricing for a specific route and date. This is the **primary endpoint** used by the ticket monitor.

**Endpoint:** `GET /Availability/available-rides`

**Parameters:**

| Param              | Type   | Required | Default    | Description                                   |
|--------------------|--------|----------|------------|-----------------------------------------------|
| passengersNumbers  | int    | yes      | —          | Number of passengers                          |
| departureDateFrom  | string | yes      | —          | ISO datetime (`YYYY-MM-DDThh:mm:ss.sssZ`)     |
| startStationCode   | string | yes      | —          | Departure station code                        |
| endStationCode     | string | yes      | —          | Arrival station code                          |
| returnWay          | bool   | yes      | `false`    | Whether this is a return trip                 |
| disability         | bool   | yes      | `false`    | Whether to filter for disability-accessible seats |
| api_key            | string | yes      | —          | Public API key                                |

**Example URL:**
```
https://gateway.tre.ge/integrations/api/GeorgianRailway/Availability/available-rides?passengersNumbers=1&departureDateFrom=2026-06-27T00:00:00.000Z&startStationCode=56014&endStationCode=57151&returnWay=false&disability=false&api_key=7d8d34d1-e9af-4897-9f0f-5c36c179be77
```

**Response format:** Object with ride arrays.

```json
{
  "isAnyDepartureTripAvailable": true,
  "isAnyReturningTripAvailable": false,
  "departureAvailableRides": [
    {
      "id": 20873,
      "guid": "7b4f1dec-9167-4bae-a897-4e97815adca3",
      "rideNumber": 812,
      "availableCount": 19,
      "rideStartDate": "2026-06-27T00:30:00Z",
      "rideEndDate": "2026-06-27T05:42:00Z",
      "rideDuration": "05:12:00",
      "trainType": 2,
      "stationFromNumber": 56014,
      "stationToNumber": 57151,
      "stationFromName": "თბილისი",
      "stationToName": "ბათუმი",
      "rideStationFromName": "თბილისი",
      "rideStationToName": "ბათუმი",
      "floorCount": 2,
      "hasMap": true,
      "additionalFields": [
        {"label": "#812", "iconUrl": null, "type": 0},
        {"label": "კონდენციონერი", "iconUrl": "https://static.tre.ge/.../snowflake.svg", "type": 2}
      ],
      "availableSeatsClasses": [
        {
          "seatClassId": 2,
          "availableNumberOfSeats": 1,
          "moneyAmount": 36,
          "seatClassName": "II კლასი"
        },
        {
          "seatClassId": 1,
          "availableNumberOfSeats": 15,
          "moneyAmount": 76,
          "seatClassName": "I კლასი"
        },
        {
          "seatClassId": 5,
          "availableNumberOfSeats": 3,
          "moneyAmount": 126,
          "seatClassName": "ბიზ. კლასი"
        }
      ],
      "availableSeatsGroups": []
    }
  ],
  "returningAvailableRides": []
}
```

**Top-level fields:**

| Field                       | Type    | Description                                   |
|-----------------------------|---------|-----------------------------------------------|
| isAnyDepartureTripAvailable | bool    | Whether any departure trips have tickets      |
| isAnyReturningTripAvailable | bool    | Whether any return trips have tickets         |
| departureAvailableRides     | array   | List of departure rides                      |
| returningAvailableRides     | array   | List of return rides                         |

**Ride object fields:**

| Field                  | Type   | Description                                   |
|------------------------|--------|-----------------------------------------------|
| id                     | int    | Internal ride ID                              |
| guid                   | string | Unique ride GUID                              |
| rideNumber             | int    | Train/ride number (e.g. 812) — used for display |
| availableCount         | int    | Total available seats across all classes      |
| rideStartDate          | string | ISO datetime of departure (`Z` suffix)        |
| rideEndDate            | string | ISO datetime of arrival (`Z` suffix)          |
| rideDuration           | string | Duration as `HH:MM:SS`                        |
| trainType              | int    | Train type (2 = double-decker?)               |
| stationFromNumber      | int    | Departure station code                        |
| stationToNumber        | int    | Arrival station code                          |
| stationFromName        | string | Departure station name (Georgian)             |
| stationToName          | string | Arrival station name (Georgian)               |
| rideStationFromName    | string | Same as stationFromName                       |
| rideStationToName      | string | Same as stationToName                         |
| floorCount             | int    | Number of floors/decks on the train           |
| hasMap                 | bool   | Whether a seat map is available               |
| additionalFields       | array  | UI metadata: icons for amenities (AC, coffee, charging, WC) |
| availableSeatsClasses  | array  | List of seat classes with availability/pricing |
| availableSeatsGroups   | array  | (Empty in observed responses)                 |

**Seat class object fields:**

| Field                  | Type    | Description                         |
|------------------------|---------|-------------------------------------|
| seatClassId            | int     | Class ID: `1` = I Class, `2` = II Class, `5` = Business |
| availableNumberOfSeats | int     | Available seats in this class       |
| moneyAmount            | float   | Price per seat (GEL)                |
| seatClassName          | string  | Class name in Georgian script       |

**Seat class mapping** (from codebase constants):

| ID | Class    | Emoji |
|----|----------|-------|
| 1  | I Class  | 💺   |
| 2  | II Class | 🪑   |
| 5  | Business | ⭐   |


### Python API method: `search_trips()`

The primary Python entry point for this endpoint is `TreGeApi.search_trips()` (`api_tre.py:171`):

```python
async def search_trips(
    self,
    session: aiohttp.ClientSession,
    from_code: str,
    to_code: str,
    date_str: str,
    passengers: int = 1,
) -> Optional[dict]:
```

For backward compatibility, `api.get_available_rides()` (`api.py:107`) is a module-level alias that delegates to `TreGeApi.search_trips()` via the cached API singleton. Existing callers (`poller.py`, `bot.py`) use this alias and continue to work unchanged.
**Used by:** This is the core endpoint used for monitoring.
- `api.py:107` — `get_available_rides()` backward-compat alias (delegates to ``TreGeApi.search_trips()``)
- `api_tre.py:171` — `TreGeApi.search_trips()` (actual implementation for tre.ge)
- `ticket_monitor.py:381` — `_fetch_rides()` using `urllib` (standalone monitor, no dependencies)
|- `api_explorer.py:69` — `get_available_rides()` sync wrapper (exploratory)
|- `poller.py:55` — `_check_and_notify()` calls the async alias

**Source files:**
- `api.py:107` — `get_available_rides()` alias wrapping ``search_trips()``
- `api_tre.py:171` — `TreGeApi.search_trips()` (primary implementation)
- `ticket_monitor.py:381` — sync wrapper via urllib (zero-dependency monitor)
- `poller.py:55` — async call via aiohttp (Telegram bot poller)
|- `api_explorer.py:69` — sync wrapper via curl subprocess

---

## Usage Summary by Component

| Component         | Endpoint(s) Used               | Library     |
|-------------------|--------------------------------|-------------|
| `api_tre.py`      | Stations, Rides, Calendar      | aiohttp     |
| `api.py`          | Factory + backward-compat layer | aiohttp    |
| `_api_base.py`    | Constants + TicketApi ABC       | aiohttp     |
| `ticket_monitor.py` | Rides only                   | urllib      |
| `poller.py`       | Rides only                     | aiohttp     |
| `bot.py`          | Stations (cached at startup)   | aiohttp     |
| `api_explorer.py` | Stations, Popular Routes, Calendar, Rides | curl via subprocess |

## API Quirks & Notes

1. **Station name inconsistency:** The dictionary endpoint (`/Dictionaries/civil-stations`) returns station names in **Latin transliteration** (e.g., `"Batumi (batumi ( samg))"`), while the availability endpoints return names in **Georgian script** (e.g., `"ბათუმი"`). The codebase uses `stations.py` as the single source of truth for station data with multi-language names.

2. **Typo in API:** The calendar endpoint returns fields named `toDestionation` and `fromDestionation` — "Destination" is misspelled (missing letter 'a'). This is the actual API response, not a codebase typo.

3. **Date timezone inconsistency:** `available-rides` uses `Z` (UTC) suffix on dates. `availability-calendar` sometimes omits timezone entirely. Georgia is UTC+4.

4. **API key is public:** The key `7d8d34d1-e9af-4897-9f0f-5c36c179be77` is hard-coded in the Next.js frontend source. It's not a secret — treat as a public client-side key.

5. **Timeout configuration:** `TreGeApi.fetch_json()` (`api_tre.py:118`) uses a 15-second aiohttp timeout. The standalone `ticket_monitor.py` uses a 30-second timeout for urllib requests.

6. **Backend base URL:** All requests go through `gateway.tre.ge` (not directly to a railway API). The path prefix is `/integrations/api/GeorgianRailway`.
