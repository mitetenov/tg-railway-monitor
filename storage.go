package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

type config struct {
	FromCode string `json:"from_station_code,omitempty"`
	ToCode   string `json:"to_station_code,omitempty"`
	From     string `json:"from_station,omitempty"`
	To       string `json:"to_station,omitempty"`
	Date     string `json:"date,omitempty"`
	Class    string `json:"seat_class,omitempty"`
	Language string `json:"language,omitempty"`
}

func (c config) complete() bool {
	_, validClass := classFilters[c.Class]
	return numericCode(c.FromCode) && numericCode(c.ToCode) && c.FromCode != c.ToCode && validDate(c.Date) && (c.Class == "Any" || validClass)
}

func numericCode(code string) bool {
	if code == "" {
		return false
	}
	for _, r := range code {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func (c config) legacyRouteKey() string     { return c.FromCode + ">" + c.ToCode + "@" + c.Date }
func (c config) routeKey() string           { return c.legacyRouteKey() + "#" + c.Class }
func (c config) expired(now time.Time) bool { return c.Date < now.In(georgiaZone).Format("2006-01-02") }

type seatState struct {
	Seats int         `json:"seats"`
	Price json.Number `json:"price"`
}
type snapshot struct {
	Key   string                          `json:"key"`
	Rides map[string]map[string]seatState `json:"rides"`
}

type storage struct {
	dir string
	mu  sync.Mutex
}

func (s *storage) path(id int64, state bool) string {
	suffix := ".json"
	if state {
		suffix = ".state.json"
	}
	return filepath.Join(s.dir, strconv.FormatInt(id, 10)+suffix)
}

func (s *storage) preflight() error {
	if err := os.MkdirAll(s.dir, 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(s.dir, ".write-probe-*")
	if err != nil {
		return fmt.Errorf("configuration storage %s is not writable by uid %d: %w (existing Docker volumes must be owned by uid 1000)", s.dir, os.Getuid(), err)
	}
	name := f.Name()
	err = f.Close()
	return errors.Join(err, os.Remove(name))
}

func readJSON(path string, dst any) error {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	data = bytes.TrimSpace(data)
	if len(data) == 0 || data[0] != '{' {
		return errors.New("storage root value must be a JSON object")
	}
	return json.Unmarshal(data, dst)
}

// atomicJSON keeps the previous file intact if a write is interrupted.
func atomicJSON(path string, value any) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".pending-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(data); err != nil {
		f.Close()
		return err
	}
	if err = f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Rename(f.Name(), path)
}

func (s *storage) load(id int64) (config, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var c config
	err := readJSON(s.path(id, false), &c)
	return c, err
}

func (s *storage) update(id int64, edit func(*config)) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	var c config
	if err := readJSON(s.path(id, false), &c); err != nil {
		return err
	}
	edit(&c)
	return atomicJSON(s.path(id, false), c)
}

func (s *storage) delete(id int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, state := range []bool{false, true} {
		if err := os.Remove(s.path(id, state)); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
	}
	return nil
}

// clearMonitor preserves the interface language when stopping or expiring a route.
func (s *storage) clearMonitor(id int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	var c config
	if err := readJSON(s.path(id, false), &c); err != nil {
		c = config{}
	}
	if c.Language != "" {
		if err := atomicJSON(s.path(id, false), config{Language: c.Language}); err != nil {
			return err
		}
	} else if err := os.Remove(s.path(id, false)); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if err := os.Remove(s.path(id, true)); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

func (s *storage) ids() ([]int64, error) {
	entries, err := os.ReadDir(s.dir)
	if err != nil {
		return nil, err
	}
	var ids []int64
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		id, err := strconv.ParseInt(strings.TrimSuffix(e.Name(), ".json"), 10, 64)
		if err == nil {
			ids = append(ids, id)
		}
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	return ids, nil
}

func (s *storage) loadState(id int64, key string) snapshot {
	var state snapshot
	legacyKey, _, _ := strings.Cut(key, "#")
	if err := readJSON(s.path(id, true), &state); err != nil || (state.Key != key && state.Key != legacyKey) || state.Rides == nil {
		return snapshot{Key: key, Rides: make(map[string]map[string]seatState)}
	}
	state.Key = key
	return state
}

func (s *storage) saveState(id int64, state snapshot) error {
	return atomicJSON(s.path(id, true), state)
}
