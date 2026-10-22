package main

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestTimetableHTTPContractAndSoldOutWizard(t *testing.T) {
	var authCalls, scheduleCalls, availabilityCalls atomic.Int32
	s := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/connect/token":
			authCalls.Add(1)
			id, key, ok := r.BasicAuth()
			if r.Method != http.MethodPost || !ok || id != timetableClientID || key != "public-test-key" || r.Header.Get("Content-Type") != "application/x-www-form-urlencoded" {
				t.Error("invalid anonymous authentication request")
			}
			if err := r.ParseForm(); err != nil || r.Form.Get("grant_type") != "client_credentials" {
				t.Error("invalid grant type", err)
			}
			fmt.Fprint(w, `{"access_token":"guest-fixture","expires_in":315360000}`)
		case "/v1/GeorgianRailway/stations/timetable":
			scheduleCalls.Add(1)
			q := r.URL.Query()
			if r.Method != http.MethodGet || q.Get("Date") != "2026-10-24" || q.Get("FromStation") != "56014" || q.Get("ToStation") != "57151" || len(q) != 3 || r.Header.Get("Authorization") != "Bearer guest-fixture" {
				t.Error("invalid timetable request")
			}
			data, err := os.ReadFile("testdata/tre_timetable.json")
			if err != nil {
				t.Error(err)
			}
			w.Write(data)
		case "/Availability/available-rides":
			availabilityCalls.Add(1)
			fmt.Fprint(w, `{"departureAvailableRides":[]}`)
		default:
			t.Error("unexpected request", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer s.Close()
	a := &timetableAPI{base: s.URL, key: "public-test-key", client: s.Client()}
	c := testConfig()
	c.Date = "2026-10-24"
	availability := &railwayAPI{base: s.URL, key: "availability-key", client: s.Client()}
	if rides, err := availability.search(context.Background(), c); err != nil || len(rides) != 0 {
		t.Fatal("fixture must reproduce a sold-out route", rides, err)
	}
	rides, err := a.schedule(context.Background(), c)
	departures := make(map[scalar]string)
	for _, r := range rides {
		departures[r.Number] = formatTime(r.Start)
	}
	if err != nil || len(rides) != 2 || departures["802"] != "08:05" || departures["804"] != "17:10" {
		t.Fatal("timetable lost sold-out trains or used an obsolete capture", rides, err)
	}
	h := newHarness(t)
	h.b.timetable = a
	for _, data := range []string{"search:add", "wiz_date:tomorrow", "wiz_from:56014", "wiz_to:57151"} {
		h.handle(t, cb(1, 1, data))
	}
	choice := departure{time: "08:05", number: "802"}
	keyboard := requestKeyboard(t, h.last())
	if !keyboardHas(keyboard, choice.callback()) || !keyboardHas(keyboard, (departure{time: "17:10", number: "804"}).callback()) || !keyboardHas(keyboard, "wiz_time:any") {
		t.Fatal("sold-out trains missing from wizard", keyboard)
	}
	h.handle(t, cb(1, 1, "wiz_time:reload"))
	if authCalls.Load() != 1 || scheduleCalls.Load() != 3 || availabilityCalls.Load() != 1 {
		t.Fatal("wizard used availability or failed to reuse guest access", authCalls.Load(), scheduleCalls.Load(), availabilityCalls.Load())
	}
	h.handle(t, cb(1, 1, choice.callback()))
	h.handle(t, cb(1, 1, "wiz_class:II"))
	chat, err := h.b.store.load(1)
	if err != nil || len(chat.Searches) != 1 || chat.Searches[0].RideNumber != "802" || chat.Searches[0].DepartureTime != "08:05" {
		t.Fatal("sold-out departure was not saved", chat, err)
	}
}

func TestTimetableRejectsInvalidResponsesWithoutLeakingTokens(t *testing.T) {
	for _, body := range []string{"null", "{}", "{", `{"ok":true}`, `{"ok":true,"stationTable":null}`, `{"ok":false,"stationTable":[],"description":"guest-sensitive-response"}`} {
		t.Run(body, func(t *testing.T) {
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				fmt.Fprint(w, body)
			}))
			defer s.Close()
			a := &timetableAPI{base: s.URL, client: s.Client(), token: "guest-sensitive-response", expires: time.Now().Add(time.Hour)}
			if _, err := a.schedule(context.Background(), testConfig()); err == nil || strings.Contains(err.Error(), "guest-sensitive-response") {
				t.Fatal("accepted malformed response or exposed credentials", err)
			}
		})
	}
	for _, body := range []string{"null", "{}", "{", `{"access_token":"secret","expires_in":0}`, `{"expires_in":3600}`} {
		t.Run("auth/"+body, func(t *testing.T) {
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, body) }))
			defer s.Close()
			a := &timetableAPI{base: s.URL, key: "secret", client: s.Client()}
			if _, err := a.schedule(context.Background(), testConfig()); err == nil || strings.Contains(err.Error(), "secret") {
				t.Fatal("accepted invalid guest access or exposed credentials", err)
			}
		})
	}
}

func TestTimetableEmptyResponseAndRouteDateFiltering(t *testing.T) {
	for _, rows := range []string{
		`[]`,
		`[{"fromStationNumber":57151,"toStationNumber":56014,"trainNumber":803,"leavingDate":"2026-12-30T08:00:00"},
		{"fromStationNumber":56014,"toStationNumber":57151,"trainNumber":802,"leavingDate":"2026-12-29T08:00:00"},
		{"fromStationNumber":56014,"toStationNumber":57151,"leavingDate":"2026-12-30T08:00:00"},
		{"fromStationNumber":56014,"toStationNumber":57151,"trainNumber":804,"leavingDate":"2026-12-30T25:00:00"}]`,
	} {
		s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprintf(w, `{"ok":true,"stationTable":%s}`, rows) }))
		a := &timetableAPI{base: s.URL, client: s.Client(), token: "guest", expires: time.Now().Add(time.Hour)}
		if rides, err := a.schedule(context.Background(), testConfig()); err != nil || len(rides) != 0 {
			t.Fatal("unrelated date, route, or malformed departure accepted", rides, err)
		}
		s.Close()
	}
}

func TestTimetableRenewsUnauthorizedTokenAndBoundsRetries(t *testing.T) {
	for _, alwaysReject := range []bool{false, true} {
		t.Run(fmt.Sprint(alwaysReject), func(t *testing.T) {
			var authCalls, scheduleCalls atomic.Int32
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/connect/token" {
					n := authCalls.Add(1)
					fmt.Fprintf(w, `{"access_token":"guest-%d","expires_in":3600}`, n)
					return
				}
				scheduleCalls.Add(1)
				if alwaysReject || r.Header.Get("Authorization") == "Bearer guest-1" {
					w.WriteHeader(http.StatusUnauthorized)
					return
				}
				fmt.Fprint(w, `{"ok":true,"stationTable":[]}`)
			}))
			defer s.Close()
			a := &timetableAPI{base: s.URL, key: "public-test-key", client: s.Client()}
			_, err := a.schedule(context.Background(), testConfig())
			if (err != nil) != alwaysReject || authCalls.Load() != 2 || scheduleCalls.Load() != 2 {
				t.Fatal("incorrect authorization retry", err, authCalls.Load(), scheduleCalls.Load())
			}
		})
	}
}

func TestTimetableConcurrentGuestAccessAndCancellation(t *testing.T) {
	var authCalls atomic.Int32
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/connect/token" {
			authCalls.Add(1)
			fmt.Fprint(w, `{"access_token":"guest","expires_in":3600}`)
			return
		}
		fmt.Fprint(w, `{"ok":true,"stationTable":[]}`)
	}))
	defer s.Close()
	a := &timetableAPI{base: s.URL, client: s.Client()}
	var wg sync.WaitGroup
	for i := 0; i < 5; i++ {
		wg.Go(func() {
			if _, err := a.schedule(context.Background(), testConfig()); err != nil {
				t.Error(err)
			}
		})
	}
	wg.Wait()
	if authCalls.Load() != 1 {
		t.Fatal("parallel timetable requests did not reuse anonymous access", authCalls.Load())
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := a.schedule(ctx, testConfig()); err == nil {
		t.Fatal("ignored cancellation")
	}
}
