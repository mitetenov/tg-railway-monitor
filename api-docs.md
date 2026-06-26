# tkt.ge Georgian Railway API — Endpoint Reference

Base URL: `https://gateway.tkt.ge/integrations/api/GeorgianRailway`
API Key: `7d8d34d1-e9af-4897-9f0f-5c36c179be77` (public key, embedded in Next.js client-side JS)

All endpoints require `api_key` as a query parameter. All requests are `GET`. Responses are JSON. All endpoints are **public** (no authentication beyond the hard-coded key).

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
https://gateway.tkt.ge/integrations/api/GeorgianRailway/Dictionaries/civil-stations?api_key=7d8d34d1-e9af-4897-9f0f-5c36c179be77
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

| Code   | Name                     |
|--------|--------------------------|
| 56014  | Tbilisi                  |
| 57151  | Batumi                   |
| 57450  | Kutaisi Airport          |
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
- `api.py:27` — `get_stations()` async wrapper
- `api_explorer.py:51` — `get_stations()` sync wrapper
- `bot.py:67` — `load_stations()` startup cache

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
https://gateway.tkt.ge/integrations/api/GeorgianRailway/Availability/availability-time-table?day=Tomorrow&directionType=FromTbilisi&api_key=7d8d34d1-e9af-4897-9f0f-5c36c179be77
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
    "mobileImage": "https://static.tkt.ge/Railway/Popular/batumi.jpg"
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

**Used by:** `api_explorer.py:129` — `get_popular_routes()` (exploratory tool only, not used in production monitor/bot).

**Source files:**
- `api_explorer.py:129` — `get_popular_routes()`

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
https://gateway.tkt.ge/integrations/api/GeorgianRailway/Availability/availability-calendar?fromStationCode=56014&toStationCode=57151&api_key=7d8d34d1-e9af-4897-9f0f-5c36c179be77
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

**Used by:** `api_explorer.py:66` — `get_availability_calendar()` (exploratory tool only, not used in production monitor/bot).

**Source files:**
- `api.py:58` — `get_availability_calendar()` async wrapper
- `api_explorer.py:66` — `get_availability_calendar()` sync wrapper

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
https://gateway.tkt.ge/integrations/api/GeorgianRailway/Availability/available-rides?passengersNumbers=1&departureDateFrom=2026-06-27T00:00:00.000Z&startStationCode=56014&endStationCode=57151&returnWay=false&disability=false&api_key=7d8d34d1-e9af-4897-9f0f-5c36c179be77
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
        {"label": "კონდენციონერი", "iconUrl": "https://static.tkt.ge/.../snowflake.svg", "type": 2}
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

**Used by:** This is the core endpoint used for monitoring.
- `api.py:31` — `get_available_rides()` async wrapper (used by `poller.py` and `bot.py`)
- `ticket_monitor.py:381` — `_fetch_rides()` using `urllib` (standalone monitor, no dependencies)
- `api_explorer.py:90` — `get_available_rides()` sync wrapper (exploratory)
- `poller.py:31` — `_check_and_notify()` calls the async wrapper

**Source files:**
- `api.py:31` — async wrapper via aiohttp
- `ticket_monitor.py:381` — sync wrapper via urllib (zero-dependency monitor)
- `poller.py:46` — async call via aiohttp (Telegram bot poller)
- `api_explorer.py:90` — sync wrapper via curl subprocess

---

## Usage Summary by Component

| Component         | Endpoint(s) Used               | Library     |
|-------------------|--------------------------------|-------------|
| `api.py`          | Stations, Calendar, Rides      | aiohttp     |
| `ticket_monitor.py` | Rides only                   | urllib      |
| `poller.py`       | Rides only                     | aiohttp     |
| `bot.py`          | Stations (cached at startup)   | aiohttp     |
| `api_explorer.py` | Stations, Popular Routes, Calendar, Rides | curl via subprocess |

## API Quirks & Notes

1. **Station name inconsistency:** The dictionary endpoint (`/Dictionaries/civil-stations`) returns station names in **Latin transliteration** (e.g., `"Batumi (batumi ( samg))"`), while the availability endpoints return names in **Georgian script** (e.g., `"ბათუმი"`). The codebase uses a hardcoded `STATION_NAMES` dict as the canonical mapping.

2. **Typo in API:** The calendar endpoint returns fields named `toDestionation` and `fromDestionation` — "Destination" is misspelled (missing letter 'a'). This is the actual API response, not a codebase typo.

3. **Date timezone inconsistency:** `available-rides` uses `Z` (UTC) suffix on dates. `availability-calendar` sometimes omits timezone entirely. Georgia is UTC+4.

4. **API key is public:** The key `7d8d34d1-e9af-4897-9f0f-5c36c179be77` is hard-coded in the Next.js frontend source. It's not a secret — treat as a public client-side key.

5. **Timeout configuration:** The async wrapper (`api.py`) uses a 15-second timeout. The sync wrapper (`ticket_monitor.py`) uses 30 seconds.

6. **Backend base URL:** All requests go through `gateway.tkt.ge` (not directly to a railway API). The path prefix is `/integrations/api/GeorgianRailway`.
