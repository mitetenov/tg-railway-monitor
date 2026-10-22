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
	if err := s.update(id, func(dst *config) { *dst = c }); err != nil {
		t.Fatal(err)
	}
}

func TestPythonStorageCompatibility(t *testing.T) {
	s := testStore(t)
	data := `{"from_station":"Tbilisi","to_station":"Batumi","from_station_code":"56014","to_station_code":"57151","date":"2026-12-30","seat_class":"Business","language":"ru"}`
	if err := os.WriteFile(s.path(-100123, false), []byte(data), 0600); err != nil {
		t.Fatal(err)
	}
	c, err := s.load(-100123)
	if err != nil || !c.complete() || c.Class != "Business" {
		t.Fatalf("%+v %v", c, err)
	}
	state := `{"key":"56014>57151@2026-12-30","rides":{"812":{"5":{"seats":3,"price":126}}}}`
	if err := os.WriteFile(s.path(-100123, true), []byte(state), 0600); err != nil {
		t.Fatal(err)
	}
	if got := s.loadState(-100123, c.routeKey()); got.Rides["812"]["5"].Seats != 3 {
		t.Fatalf("%+v", got)
	}
	if got := s.loadState(-100123, "different"); len(got.Rides) != 0 {
		t.Fatalf("stale state: %+v", got)
	}
	if err := s.saveState(-100123, s.loadState(-100123, c.routeKey())); err != nil {
		t.Fatal(err)
	}
	ids, err := s.ids()
	if err != nil || len(ids) != 1 || ids[0] != -100123 {
		t.Fatalf("%v %v", ids, err)
	}
	if err := s.delete(-100123); err != nil {
		t.Fatal(err)
	}
	for _, state := range []bool{false, true} {
		if _, err := os.Stat(s.path(-100123, state)); !os.IsNotExist(err) {
			t.Fatal("file survived delete", err)
		}
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
	if err := s.update(1, func(c *config) { c.Language = "en" }); err == nil {
		t.Fatal("overwrote corrupt config")
	}
	if err := os.WriteFile(s.path(1, true), []byte("{"), 0600); err != nil {
		t.Fatal(err)
	}
	if state := s.loadState(1, "key"); len(state.Rides) != 0 {
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
			if err := s.update(1, func(c *config) { c.Language = "en" }); err != nil {
				t.Error(err)
			}
			if _, err := s.load(1); err != nil {
				t.Error(err)
			}
		})
	}
	wg.Wait()
	c, err := s.load(1)
	if err != nil || c.Language != "en" || c.FromCode != "56014" {
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
