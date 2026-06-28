#!/usr/bin/env python3
"""
tkt.ge Railway API Explorer
Queries Georgian Railway availability via the public tkt.ge API.
"""
import json
import sys
from datetime import datetime, timedelta, timezone

from _api_base import API_BASE, API_KEY
from stations import STATION_NAMES

def fetch_json(url, label=""):
    """Fetch JSON from a URL (uses curl via subprocess for compatibility)."""
    import subprocess
    import shlex
    cmd = f"curl -s {shlex.quote(url)}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"  ERROR fetching {label}: {result.stderr}")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"  ERROR parsing {label}: {e}")
        print(f"  Raw: {result.stdout[:200]}")
        return None


def get_stations():
    """Fetch the dictionary of railway stations."""
    url = f"{API_BASE}/Dictionaries/civil-stations?api_key={API_KEY}"
    data = fetch_json(url, "stations")
    if data is None:
        return None
    print(f"\n  Stations: {len(data)} total")
    for s in data:
        name = s["stationName"]
        code = s["code"]
        pop = "★" if s.get("isPopular") else " "
        print(f"    [{code}] {pop} {name}")
    return data


def get_availability_calendar(from_code, to_code):
    """Get daily ticket availability for a route."""
    url = f"{API_BASE}/Availability/availability-calendar?fromStationCode={from_code}&toStationCode={to_code}&api_key={API_KEY}"
    data = fetch_json(url, "calendar")
    if data is None:
        return None
    
    print(f"\n  Calendar (to destination):")
    for entry in data.get("toDestionation", []):
        d = entry["date"][:10]
        a = entry["available"]
        marker = " ✓" if a > 0 else ""
        print(f"    {d}: {a} tickets{marker}")
    
    print(f"\n  Calendar (from destination / return):")
    for entry in data.get("fromDestionation", []):
        d = entry["date"][:10]
        a = entry["available"]
        marker = " ✓" if a > 0 else ""
        print(f"    {d}: {a} tickets{marker}")
    
    return data


def get_available_rides(from_code, to_code, date_str, passengers=1):
    """Get actual train rides for a specific date and route."""
    url = (
        f"{API_BASE}/Availability/available-rides"
        f"?passengersNumbers={passengers}"
        f"&departureDateFrom={date_str}T00:00:00.000Z"
        f"&startStationCode={from_code}"
        f"&endStationCode={to_code}"
        f"&returnWay=false"
        f"&disability=false"
        f"&api_key={API_KEY}"
    )
    data = fetch_json(url, "rides")
    if data is None:
        return None
    
    print(f"  Any departure trip available: {data.get('isAnyDepartureTripAvailable')}")
    print(f"  Any returning trip available: {data.get('isAnyReturningTripAvailable')}")
    
    rides = data.get("departureAvailableRides", [])
    print(f"  Departure rides: {len(rides)}")
    
    for ride in rides:
        print(f"\n  --- Ride #{ride.get('rideNumber')} ---")
        print(f"      From: {ride.get('rideStationFromName')} ({ride.get('stationFromName')})")
        print(f"      To:   {ride.get('rideStationToName')} ({ride.get('stationToName')})")
        print(f"      Departure: {ride.get('rideStartDate')}")
        print(f"      Arrival:   {ride.get('rideEndDate')}")
        print(f"      Duration: {ride.get('rideDuration')}")
        print(f"      Train type: {ride.get('trainType')} (2=double-decker?)")
        print(f"      Floors: {ride.get('floorCount')}")
        print(f"      Has seat map: {ride.get('hasMap')}")
        
        for cls in ride.get("availableSeatsClasses", []):
            print(f"      {cls.get('seatClassName')}: {cls.get('availableNumberOfSeats')} seats @ {cls.get('moneyAmount')} GEL")
    
    return data


def get_popular_routes(day="Tomorrow", direction="FromTbilisi"):
    """Get popular routes summary."""
    url = f"{API_BASE}/Availability/availability-time-table?day={day}&directionType={direction}&api_key={API_KEY}"
    data = fetch_json(url, "popular routes")
    if data is None:
        return None
    
    routes_from = "Tbilisi" if direction == "FromTbilisi" else "Regions"
    print(f"\n  Popular routes ({day}) - {routes_from}:")
    for r in data:
        print(f"    {r['fromStationName']} → {r['toStationName']}: {r['availableCount']} avail, {r['ridesNumber']} rides, from {r['priceFrom']} GEL, {r['duration']}")
    
    return data


def main():
    print("=" * 60)
    print("tkt.ge Railway API Explorer")
    print("=" * 60)
    
    # Default: Tbilisi → Batumi, tomorrow
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    date_str = tomorrow.strftime("%Y-%m-%d")
    
    from_code = "56014"  # Tbilisi
    to_code = "57151"    # Batumi
    
    print(f"\nRoute: Tbilisi → Batumi")
    print(f"Date:  {date_str}")
    print(f"Station codes: {from_code} → {to_code}")
    
    # 1. Popular routes
    print("\n--- 1. Popular Routes (From Tbilisi, Tomorrow) ---")
    get_popular_routes("Tomorrow", "FromTbilisi")
    
    print("\n--- 1b. Popular Routes (To Tbilisi, Tomorrow) ---")
    get_popular_routes("Tomorrow", "ToTbilisi")
    
    # 2. Stations
    print("\n--- 2. Stations Dictionary ---")
    get_stations()
    
    # 3. Calendar
    print(f"\n--- 3. Availability Calendar (Tbilisi→Batumi) ---")
    calendar = get_availability_calendar(from_code, to_code)
    
    # 4. Rides
    print(f"\n--- 4. Available Rides (Tbilisi→Batumi, {date_str}) ---")
    rides = get_available_rides(from_code, to_code, date_str)
    
    # Summary
    print("\n" + "=" * 60)
    print("API ENDPOINT SUMMARY")
    print("=" * 60)
    print(f"""
Base:    {API_BASE}
API Key: {API_KEY}

1. Stations Dictionary
   GET /Dictionaries/civil-stations?api_key={API_KEY}
   Returns 36 stations with code, name, isPopular

2. Popular Routes (aggregate)
   GET /Availability/availability-time-table?day=Today&directionType=FromTbilisi&api_key={API_KEY}
   GET /Availability/availability-time-table?day=Tomorrow&directionType=ToTbilisi&api_key={API_KEY}
   directionType: FromTbilisi | ToTbilisi

3. Availability Calendar (daily ticket counts)
   GET /Availability/availability-calendar?fromStationCode=56014&toStationCode=57151&api_key={API_KEY}
   Returns ~30 days of toDestionation/fromDestionation availability

4. Available Rides (actual departures)
   GET /Availability/available-rides
     ?passengersNumbers=1
     &departureDateFrom=2026-06-27T00:00:00.000Z
     &startStationCode=56014
     &endStationCode=57151
     &returnWay=false
     &disability=false
     &api_key={API_KEY}

QUIRKS:
- Date tz: +04:00 (Georgia) or Z. availability-calendar sometimes omits tz
- "toDestionation" and "fromDestionation" have typo (missing 'a')
- Station names in Georgian in availability, transliterated in stations dict
- API key is public (embedded in Next.js client)
""")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
