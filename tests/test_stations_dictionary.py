"""Invariants for the station dictionary.

The dictionary had drifted from the upstream API: three entries with no
code at all, six wrong isPopular flags and a wrong Georgian letter. These
tests pin the properties that made those defects harmful, without
requiring network access.

The live cross-check against the API is marked `network` and skipped by
default; run it with `pytest -m network` when refreshing the table.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import stations
from stations import (
    FALLBACK_STATIONS,
    STATION_NAMES,
    STATION_NAMES_KA,
    STATION_NAMES_RU,
    _STATION_DATA,
)

API_URL = (
    "https://gateway.tkt.ge/integrations/api/GeorgianRailway"
    "/Dictionaries/civil-stations"
    "?api_key=7d8d34d1-e9af-4897-9f0f-5c36c179be77"
)

# Present in the popular-routes endpoint but not in civil-stations, and
# currently unserved. Excluded from the live comparison on purpose.
NOT_IN_CIVIL_STATIONS = set(stations.UNSERVED_STATION_CODES)


class TestStructuralInvariants:

    def test_every_station_has_a_code(self):
        """A blank code makes bot._station_index collapse entries together.

        Three codeless rows used to share the key "", so selecting any of
        them stored an empty station code in the chat config.
        """
        codeless = [row[1] for row in _STATION_DATA if not row[0]]
        assert codeless == [], f"stations without a code: {codeless}"

    def test_codes_are_unique(self):
        codes = [row[0] for row in _STATION_DATA]
        assert len(codes) == len(set(codes))

    def test_index_keeps_every_station(self):
        """Building a code-keyed index must not lose any entry."""
        index = {s["code"]: s for s in FALLBACK_STATIONS}
        assert len(index) == len(FALLBACK_STATIONS)

    def test_codes_are_numeric(self):
        for code, name, *_ in _STATION_DATA:
            assert code.isdigit(), f"{name} has a non-numeric code {code!r}"

    def test_names_are_unique(self):
        """Duplicate names would make the slug reverse-mapping ambiguous."""
        names = [row[1] for row in _STATION_DATA]
        assert len(names) == len(set(names))


class TestUnservedStations:
    """Unbookable stations stay resolvable but must not be selectable."""

    def test_unserved_stations_are_not_offered(self):
        offered = {s["code"] for s in FALLBACK_STATIONS}
        assert not (offered & stations.UNSERVED_STATION_CODES), (
            "an unbookable station reached the selection keyboard"
        )

    def test_unserved_stations_still_resolve_by_code(self):
        """Existing chat configs may still reference the code."""
        for code in stations.UNSERVED_STATION_CODES:
            assert int(code) in STATION_NAMES
            assert int(code) in STATION_NAMES_RU
            assert int(code) in STATION_NAMES_KA

    def test_unserved_stations_are_not_popular(self):
        """Popular puts a station on the first keyboard page."""
        for code, _, _, popular, _ in _STATION_DATA:
            if code in stations.UNSERVED_STATION_CODES:
                assert not popular, f"{code} is unbookable but flagged popular"

    def test_kutaisi_airport_is_the_served_one(self):
        """57450 is the bookable Kutaisi station and must stay offered."""
        offered = {s["code"] for s in FALLBACK_STATIONS}
        assert "57450" in offered
        assert STATION_NAMES[57450] == "Kutaisi Airport"


class TestLocalisationCoverage:

    def test_russian_names_cover_every_station(self):
        missing = set(STATION_NAMES) - set(STATION_NAMES_RU)
        assert not missing, f"no Russian name for: {sorted(missing)}"

    def test_russian_names_have_no_extras(self):
        extra = set(STATION_NAMES_RU) - set(STATION_NAMES)
        assert not extra, f"Russian names for unknown codes: {sorted(extra)}"

    def test_georgian_names_cover_every_station(self):
        assert set(STATION_NAMES_KA) == set(STATION_NAMES)

    def test_georgian_names_are_georgian_script(self):
        """Catches transliteration slips like the API's own "წifa"."""
        for code, name in STATION_NAMES_KA.items():
            letters = [c for c in name if c.isalpha()]
            assert letters, f"{name!r} has no letters"
            assert all("Ⴀ" <= c <= "ჿ" for c in letters), (
                f"{code} ({STATION_NAMES[code]}): {name!r} mixes scripts"
            )

    def test_russian_names_are_cyrillic(self):
        for code, name in STATION_NAMES_RU.items():
            letters = [c for c in name if c.isalpha()]
            assert all("Ѐ" <= c <= "ӿ" for c in letters), (
                f"{code}: {name!r} mixes scripts"
            )

    def test_kareli_georgian_name(self):
        """Regression: was ყარელი; the API returns ქარელი."""
        assert STATION_NAMES_KA[57880] == "ქარელი"


@pytest.mark.network
class TestAgainstLiveApi:
    """Cross-check the table against the upstream dictionary.

    Skipped unless explicitly selected — CI must not depend on a third
    party being reachable.
    """

    @staticmethod
    def _fetch():
        import json
        import urllib.request

        with urllib.request.urlopen(API_URL, timeout=30) as resp:
            return {str(s["code"]): s for s in json.loads(resp.read().decode())}

    def test_codes_match(self):
        live = self._fetch()
        mine = {row[0] for row in _STATION_DATA} - NOT_IN_CIVIL_STATIONS
        assert mine == set(live), (
            f"missing: {sorted(set(live) - mine)}; "
            f"unexpected: {sorted(mine - set(live))}"
        )

    def test_is_popular_matches(self):
        live = self._fetch()
        wrong = [
            (code, name, popular, live[code]["isPopular"])
            for code, name, _, popular, _ in _STATION_DATA
            if code in live and live[code]["isPopular"] != popular
        ]
        assert not wrong, f"isPopular drifted: {wrong}"
