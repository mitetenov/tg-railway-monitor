package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

func TestRailwayHTTPContract(t *testing.T) {
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		if q.Get("api_key") != "test-key" {
			t.Error("missing API key")
		}
		file := "sample_stations.json"
		if strings.HasSuffix(r.URL.Path, "available-rides") {
			file = "sample_rides.json"
			for k, v := range map[string]string{"startStationCode": "56014", "endStationCode": "57151", "departureDateFrom": "2026-12-30T00:00:00.000Z", "passengersNumbers": "1", "returnWay": "false", "disability": "false"} {
				if q.Get(k) != v {
					t.Errorf("%s = %q", k, q.Get(k))
				}
			}
		}
		data, err := os.ReadFile(file)
		if err != nil {
			t.Error(err)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write(data)
	}))
	defer server.Close()
	a := &railwayAPI{base: server.URL, key: "test-key", client: server.Client()}
	stations, err := a.stations(context.Background())
	if err != nil || len(stations) != 36 {
		t.Fatalf("%d %v", len(stations), err)
	}
	rides, err := a.search(context.Background(), testConfig())
	if err != nil || len(rides) != 1 || rides[0].Number != "812" || rides[0].Classes[0].Seats != 1 {
		t.Fatalf("%+v %v", rides, err)
	}
	// Selection is applied locally; keep the provider request for the whole day.
	c := testConfig()
	c.DepartureTime, c.RideNumber = "00:30", "812"
	if _, err := a.search(context.Background(), c); err != nil {
		t.Fatal(err)
	}
}

func TestRailwayErrorsDoNotLookLikeEmptyAvailability(t *testing.T) {
	for _, body := range []string{"null", "[1]", "{", "{}", `{"departureAvailableRides":null}`, `{"departureAvailableRides":[{"availableSeatsClasses":[{"availableNumberOfSeats":"oops"}]}]}`} {
		t.Run(body, func(t *testing.T) {
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, body) }))
			defer s.Close()
			a := &railwayAPI{base: s.URL, client: s.Client()}
			if _, err := a.search(context.Background(), testConfig()); err == nil {
				t.Fatal("accepted invalid response")
			}
		})
	}
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(503) }))
	defer s.Close()
	a := &railwayAPI{base: s.URL, client: s.Client()}
	if _, err := a.search(context.Background(), testConfig()); err == nil {
		t.Fatal("accepted 503")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := a.search(ctx, testConfig()); err == nil {
		t.Fatal("ignored cancellation")
	}
}

func TestPurchaseTimeAndScalar(t *testing.T) {
	want := "https://tre.ge/en/search?leavingPlace=56014&enteringPlace=57151&leaveDate=30.12.2026&passengerCount=1&wcuCount=0&depVT=railway"
	if got := purchaseURL(testConfig()); got != want {
		t.Fatal(got)
	}
	for input, want := range map[string]string{"": "??:??", "2026-06-27T00:30:00Z": "00:30", "2026-06-27T12:30:00.123+04:00": "12:30", "2026-06-27T12:30:00-04:00": "12:30", "12:45": "12:45", "bogus": "bogus"} {
		if got := formatTime(input); got != want {
			t.Errorf("%q: %s", input, got)
		}
	}
	for _, input := range []string{`812`, `"812"`} {
		var id scalar
		if err := json.Unmarshal([]byte(input), &id); err != nil || id != "812" {
			t.Fatal(id, err)
		}
	}
	if !waitContext(context.Background(), time.Millisecond) {
		t.Fatal("wait failed")
	}
}

func TestStationCatalogAndLocales(t *testing.T) {
	c, err := newCatalog()
	if err != nil {
		t.Fatal(err)
	}
	if len(c.names) != 37 || len(c.fallback) != 36 {
		t.Fatal(len(c.names), len(c.fallback))
	}
	for _, s := range c.fallback {
		if s.Code == "57530" || s.Code == "" {
			t.Fatal(s)
		}
	}
	for key := range c.texts["en"] {
		if c.texts["ru"][key] == "" {
			t.Fatal("missing Russian key", key)
		}
	}
	for _, s := range c.names {
		if s.RU == "" || s.EN == "" || s.KA == "" {
			t.Fatal(s)
		}
	}
	if c.stationName("56014", "ru", "") != "Тбилиси" || c.stationName("123", "en", "Unknown") != "Unknown" {
		t.Fatal("translation")
	}
	for input, want := range map[string]string{"ru-RU": "ru", "en-US": "en", "ka": "en", "": "en", "RU": "ru"} {
		if got := language(input); got != want {
			t.Error(input, got)
		}
	}
}
