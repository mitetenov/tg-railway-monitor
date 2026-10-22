package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"testing"
)

func testStore(t *testing.T) *storage {
	t.Helper()
	s := &storage{dir: t.TempDir()}
	if err := s.preflight(); err != nil {
		t.Fatal(err)
	}
	return s
}
func testConfig() config {
	return config{FromCode: "56014", ToCode: "57151", From: "Tbilisi", To: "Batumi", Date: "2026-12-30", Class: "Any", Language: "ru"}
}
func saveConfig(t *testing.T, s *storage, id int64, c config) {
	t.Helper()
	if err := s.update(id, func(dst *chatConfig) error {
		dst.Language = c.Language
		dst.Searches = []search{}
		if c.complete() {
			c.Language = ""
			dst.Searches = []search{{ID: "legacy", config: c}}
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
}

func TestPythonStorageCompatibility(t *testing.T) {
	s := testStore(t)
	data := `{"from_station":"Tbilisi","to_station":"Batumi","from_station_code":"56014","to_station_code":"57151","date":"2026-12-30","seat_class":"Business","language":"ru"}`
	if err := os.WriteFile(s.path(-100123, false), []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
	chat, err := s.load(-100123)
	if err != nil || len(chat.Searches) != 1 || chat.Searches[0].Class != "Business" {
		t.Fatalf("%+v %v", chat, err)
	}
	c := chat.Searches[0].config
	state := `{"key":"56014>57151@2026-12-30","rides":{"812":{"5":{"seats":3,"price":126}}}}`
	if err := os.WriteFile(s.path(-100123, true), []byte(state), 0600); err != nil {
		t.Fatal(err)
	}
	if got := s.loadState(-100123, "legacy", c.routeKey()); got.Rides["812"]["5"].Seats != 3 {
		t.Fatalf("%+v", got)
	}
	if got := s.loadState(-100123, "legacy", "different"); len(got.Rides) != 0 {
		t.Fatalf("stale state: %+v", got)
	}
	if err := s.saveState(-100123, "legacy", s.loadState(-100123, "legacy", c.routeKey())); err != nil {
		t.Fatal(err)
	}
	ids, err := s.ids()
	if err != nil || len(ids) != 1 || ids[0] != -100123 {
		t.Fatalf("%v %v", ids, err)
	}
	if err := s.clearMonitor(-100123); err != nil {
		t.Fatal(err)
	}
	if chat, err := s.load(-100123); err != nil || len(chat.Searches) != 0 || chat.Language != "ru" {
		t.Fatal("stop lost language or kept searches", chat, err)
	}
	if _, err := os.Stat(s.path(-100123, true)); !os.IsNotExist(err) {
		t.Fatal("snapshot survived stop", err)
	}
}

func TestDeparturePersistenceAndValidation(t *testing.T) {
	s := testStore(t)
	c := testConfig()
	c.DepartureTime, c.RideNumber = "08:15", "812"
	id, err := s.addSearch(1, c)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.setPaused(1, id, true); err != nil {
		t.Fatal(err)
	}
	chat, err := (&storage{dir: s.dir}).load(1)
	if err != nil || len(chat.Searches) != 1 || chat.Searches[0].DepartureTime != "08:15" || chat.Searches[0].RideNumber != "812" || !chat.Searches[0].Paused {
		t.Fatal("departure was lost across persistence or pause", chat, err)
	}
	for _, value := range []string{"8:15", "24:00", "12:60", "08:15:00", "bad", " 08:15"} {
		c.DepartureTime = value
		if _, err := s.addSearch(1, c); err == nil {
			t.Fatal("invalid departure time accepted", value)
		}
	}
	c.DepartureTime = ""
	if c.complete() {
		t.Fatal("train without a departure time accepted")
	}
	c.RideNumber = ""
	if !c.complete() {
		t.Fatal("existing unrestricted config rejected")
	}
}

func TestStorageCorruptionAndAtomicWrites(t *testing.T) {
	s := testStore(t)
	if err := os.WriteFile(s.path(1, false), []byte("{"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.load(1); err == nil {
		t.Fatal("corruption silently ignored")
	}
	if err := s.update(1, func(c *chatConfig) error { c.Language = "en"; return nil }); err == nil {
		t.Fatal("overwrote corrupt config")
	}
	if err := os.WriteFile(s.path(1, true), []byte("{"), 0600); err != nil {
		t.Fatal(err)
	}
	if state := s.loadState(1, "legacy", "key"); len(state.Rides) != 0 {
		t.Fatal("corrupt state not discarded")
	}
	saveConfig(t, s, 2, testConfig())
	before, _ := os.ReadFile(s.path(2, false))
	if err := atomicJSON(s.path(2, false), make(chan int)); err == nil {
		t.Fatal("invalid value accepted")
	}
	after, _ := os.ReadFile(s.path(2, false))
	if string(before) != string(after) {
		t.Fatal("failed write changed file")
	}
	entries, _ := filepath.Glob(filepath.Join(s.dir, ".pending-*"))
	if len(entries) != 0 {
		t.Fatal(entries)
	}
	if mode, _ := os.Stat(s.path(2, false)); mode.Mode().Perm() != 0600 {
		t.Fatal("config is not private", mode.Mode())
	}
}

func TestStorageConcurrentLanguageAndRouteUpdates(t *testing.T) {
	s := testStore(t)
	saveConfig(t, s, 1, testConfig())
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Go(func() {
			if err := s.update(1, func(c *chatConfig) error { c.Language = "en"; return nil }); err != nil {
				t.Error(err)
			}
			if _, err := s.load(1); err != nil {
				t.Error(err)
			}
		})
	}
	wg.Wait()
	c, err := s.load(1)
	if err != nil || c.Language != "en" || len(c.Searches) != 1 || c.Searches[0].FromCode != "56014" {
		t.Fatalf("%+v %v", c, err)
	}
}

func TestStorageReadOnlyAndCompleteValidation(t *testing.T) {
	s := testStore(t)
	file := filepath.Join(s.dir, "file")
	if err := os.WriteFile(file, nil, 0600); err != nil {
		t.Fatal(err)
	}
	if err := (&storage{dir: filepath.Join(file, "data")}).preflight(); err == nil {
		t.Fatal("invalid data path accepted")
	}
	for _, mutate := range []func(*config){func(c *config) { c.Class = "III" }, func(c *config) { c.Date = "2026-02-30" }, func(c *config) { c.ToCode = c.FromCode }, func(c *config) { c.FromCode = "" }} {
		c := testConfig()
		mutate(&c)
		if c.complete() {
			t.Fatalf("invalid config accepted: %+v", c)
		}
	}
	c := testConfig()
	c.ToCode = "not-a-code"
	if c.complete() {
		t.Fatal("non-numeric station accepted")
	}
	for _, data := range []string{"null", "[]", "42", `"config"`} {
		if err := os.WriteFile(s.path(9, false), []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := s.load(9); err == nil {
			t.Fatal("non-object config accepted", data)
		}
	}
	c = config{}
	if err := json.Unmarshal([]byte(`{"language":"en"}`), &c); err != nil || c.complete() {
		t.Fatal(err, c)
	}
}

func addTestSearch(t *testing.T, s *storage, id int64, c config) string {
	t.Helper()
	searchID, err := s.addSearch(id, c)
	if err != nil {
		t.Fatal(err)
	}
	return searchID
}

func TestSearchMigrationPersistsIDsPauseAndIndependentSnapshots(t *testing.T) {
	s := testStore(t)
	c := testConfig()
	// Start from an actual pre-feature file and its existing notification history.
	if err := atomicJSON(s.path(-42, false), c); err != nil {
		t.Fatal(err)
	}
	baseline := snapshot{Key: c.legacyRouteKey(), Rides: map[string]map[string]seatState{"812": {"2": {3, "36"}}}}
	if err := s.saveState(-42, "legacy", baseline); err != nil {
		t.Fatal(err)
	}
	first := addTestSearch(t, s, -42, c)
	second := addTestSearch(t, s, -42, c)
	if first == second || first == "legacy" {
		t.Fatal("search IDs reused", first, second)
	}
	if err := s.setPaused(-42, first, true); err != nil {
		t.Fatal(err)
	}
	if err := s.update(-42, func(c *chatConfig) error { c.Language = "en"; return nil }); err != nil {
		t.Fatal(err)
	}
	reopened := &storage{dir: s.dir}
	chat, err := reopened.load(-42)
	if err != nil || len(chat.Searches) != 3 || chat.Language != "en" {
		t.Fatal(chat, err)
	}
	if chat.Searches[0].ID != "legacy" || chat.Searches[1].ID != first || !chat.Searches[1].Paused || chat.Searches[2].Paused {
		t.Fatal("IDs or pause status changed after restart", chat)
	}
	if state := reopened.loadState(-42, "legacy", c.routeKey()); state.Rides["812"]["2"].Seats != 3 {
		t.Fatal("migration lost old baseline", state)
	}
	if state := reopened.loadState(-42, first, c.routeKey()); len(state.Rides) != 0 {
		t.Fatal("new search reused another search's baseline", state)
	}
	if err := reopened.saveState(-42, first, baseline); err != nil {
		t.Fatal(err)
	}
	if err := reopened.removeSearch(-42, first); err != nil {
		t.Fatal(err)
	}
	chat, err = reopened.load(-42)
	if err != nil || len(chat.Searches) != 2 || chat.Searches[1].ID != second || chat.Language != "en" {
		t.Fatal("deletion affected another search", chat, err)
	}
	if _, err := os.Stat(s.statePath(-42, first)); !os.IsNotExist(err) {
		t.Fatal("deleted search retained snapshot", err)
	}
	if state := reopened.loadState(-42, "legacy", c.routeKey()); len(state.Rides) != 1 {
		t.Fatal("deletion removed old search's baseline")
	}
	ids, err := s.ids()
	if err != nil || len(ids) != 1 || ids[0] != -42 {
		t.Fatal("snapshot treated as a chat", ids, err)
	}
	if err := s.clearMonitor(-42); err != nil {
		t.Fatal(err)
	}
	paths, _ := filepath.Glob(filepath.Join(s.dir, "*.state.json"))
	if len(paths) != 0 {
		t.Fatal("stop retained snapshots", paths)
	}
}

func TestConcurrentSearchCreationDoesNotLoseLanguageOrSearches(t *testing.T) {
	s := testStore(t)
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		wg.Go(func() {
			id, err := s.addSearch(1, testConfig())
			if err != nil {
				t.Error(err)
				return
			}
			if err := s.setPaused(1, id, true); err != nil {
				t.Error(err)
			}
			if err := s.update(1, func(c *chatConfig) error { c.Language = "ru"; return nil }); err != nil {
				t.Error(err)
			}
		})
	}
	wg.Wait()
	c, err := s.load(1)
	if err != nil || len(c.Searches) != 12 || c.Language != "ru" {
		t.Fatal("concurrent update lost data", c, err)
	}
	for _, entry := range c.Searches {
		if !entry.Paused {
			t.Fatal("concurrent update lost pause", entry)
		}
	}
}

func TestInvalidSearchIDsAndDuplicatesCannotTouchStorage(t *testing.T) {
	s := testStore(t)
	for _, id := range []string{"../1", "", "../../other", "0123456789abcdef/", "not-a-search"} {
		if err := s.removeSearch(1, id); err == nil {
			t.Fatal("invalid deletion ID accepted", id)
		}
		if err := s.saveState(1, id, snapshot{}); err == nil {
			t.Fatal("invalid snapshot ID accepted", id)
		}
	}
	for _, entries := range [][]search{
		{{ID: "../1", config: testConfig()}},
		{{ID: "legacy", config: testConfig()}, {ID: "legacy", config: testConfig()}},
		{{ID: "legacy"}},
	} {
		if err := atomicJSON(s.path(1, false), chatConfig{Searches: entries}); err != nil {
			t.Fatal(err)
		}
		if _, err := s.load(1); err == nil {
			t.Fatal("invalid saved searches accepted", entries)
		}
	}
}
