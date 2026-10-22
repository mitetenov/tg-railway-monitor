package main

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
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
	FromCode      string `json:"from_station_code,omitempty"`
	ToCode        string `json:"to_station_code,omitempty"`
	From          string `json:"from_station,omitempty"`
	To            string `json:"to_station,omitempty"`
	Date          string `json:"date,omitempty"`
	Class         string `json:"seat_class,omitempty"`
	DepartureTime string `json:"departure_time,omitempty"`
	RideNumber    string `json:"ride_number,omitempty"`
	Language      string `json:"language,omitempty"`
}

type search struct {
	ID     string `json:"id"`
	Paused bool   `json:"paused,omitempty"`
	config
}

type chatConfig struct {
	Language string   `json:"language,omitempty"`
	Searches []search `json:"searches"`
}

func (c chatConfig) find(id string) (search, bool) {
	for _, s := range c.Searches {
		if s.ID == id {
			return s, true
		}
	}
	return search{}, false
}

var errSearchNotFound = errors.New("search not found")

func validSearchID(id string) bool {
	if id == "legacy" {
		return true
	}
	_, err := hex.DecodeString(id)
	return len(id) == 16 && err == nil
}

// readChat migrates a single-route config in memory. The next write saves the
// search list atomically; the legacy search keeps its original snapshot path.
func readChat(path string) (chatConfig, error) {
	var doc struct {
		config
		Searches *[]search `json:"searches"`
	}
	if err := readJSON(path, &doc); err != nil {
		return chatConfig{}, err
	}
	c := chatConfig{Language: doc.Language, Searches: []search{}}
	if doc.Searches == nil {
		if doc.config.complete() {
			doc.config.Language = ""
			c.Searches = append(c.Searches, search{ID: "legacy", config: doc.config})
		}
	} else {
		c.Searches = *doc.Searches
	}
	seen := make(map[string]bool)
	for i := range c.Searches {
		s := &c.Searches[i]
		if !validSearchID(s.ID) || seen[s.ID] || !s.complete() {
			return chatConfig{}, errors.New("invalid or duplicate saved search")
		}
		seen[s.ID] = true
		s.Language = "" // The interface language belongs to the chat.
	}
	return c, nil
}

func (c config) complete() bool {
	_, validClass := classFilters[c.Class]
	validDeparture := (c.DepartureTime == "" || validTime(c.DepartureTime)) && (c.RideNumber == "" || c.DepartureTime != "")
	return numericCode(c.FromCode) && numericCode(c.ToCode) && c.FromCode != c.ToCode && validDate(c.Date) && (c.Class == "Any" || validClass) && validDeparture
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

func (c config) legacyRouteKey() string { return c.FromCode + ">" + c.ToCode + "@" + c.Date }
func (c config) routeKey() string {
	key := c.legacyRouteKey() + "#" + c.Class
	if c.DepartureTime != "" {
		key += "#" + c.DepartureTime
	}
	if c.RideNumber != "" {
		key += "#" + c.RideNumber
	}
	return key
}
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

func (s *storage) statePath(id int64, searchID string) string {
	if searchID == "legacy" {
		return s.path(id, true)
	}
	return filepath.Join(s.dir, strconv.FormatInt(id, 10)+"."+searchID+".state.json")
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

func (s *storage) load(id int64) (chatConfig, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return readChat(s.path(id, false))
}

func (s *storage) update(id int64, edit func(*chatConfig) error) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, err := readChat(s.path(id, false))
	if err != nil {
		return err
	}
	if err := edit(&c); err != nil {
		return err
	}
	return atomicJSON(s.path(id, false), c)
}

func (s *storage) addSearch(id int64, c config) (string, error) {
	if !c.complete() {
		return "", errors.New("incomplete search configuration")
	}
	var random [8]byte
	if _, err := rand.Read(random[:]); err != nil {
		return "", err
	}
	searchID := hex.EncodeToString(random[:])
	c.Language = ""
	err := s.update(id, func(chat *chatConfig) error {
		if _, exists := chat.find(searchID); exists {
			return errors.New("duplicate search ID")
		}
		chat.Searches = append(chat.Searches, search{ID: searchID, config: c})
		return nil
	})
	return searchID, err
}

func (s *storage) setPaused(id int64, searchID string, paused bool) error {
	return s.update(id, func(c *chatConfig) error {
		for i := range c.Searches {
			if c.Searches[i].ID == searchID {
				c.Searches[i].Paused = paused
				return nil
			}
		}
		return errSearchNotFound
	})
}

// removeSearch commits removal before discarding its disposable snapshot.
// Callers must cancel and join the worker first, unless called by that worker.
func (s *storage) removeSearch(id int64, searchID string) error {
	if !validSearchID(searchID) {
		return errSearchNotFound
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	c, err := readChat(s.path(id, false))
	if err != nil {
		return err
	}
	for i, entry := range c.Searches {
		if entry.ID == searchID {
			c.Searches = append(c.Searches[:i], c.Searches[i+1:]...)
			if err := atomicJSON(s.path(id, false), c); err != nil {
				return err
			}
			break
		}
	}
	if err := os.Remove(s.statePath(id, searchID)); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

// clearMonitor preserves the interface language when stopping or expiring a route.
func (s *storage) clearMonitor(id int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	c, _ := readChat(s.path(id, false))
	if c.Language != "" {
		if err := atomicJSON(s.path(id, false), chatConfig{Language: c.Language, Searches: []search{}}); err != nil {
			return err
		}
	} else if err := os.Remove(s.path(id, false)); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	paths, err := filepath.Glob(filepath.Join(s.dir, strconv.FormatInt(id, 10)+".*.state.json"))
	if err != nil {
		return err
	}
	for _, path := range append(paths, s.path(id, true)) {
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return err
		}
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

func (s *storage) loadState(id int64, searchID, key string) snapshot {
	s.mu.Lock()
	defer s.mu.Unlock()
	var state snapshot
	legacyKey, _, _ := strings.Cut(key, "#")
	allowLegacy := strings.Count(key, "#") == 1
	if !validSearchID(searchID) {
		return snapshot{Key: key, Rides: make(map[string]map[string]seatState)}
	}
	if err := readJSON(s.statePath(id, searchID), &state); err != nil || (state.Key != key && !(allowLegacy && state.Key == legacyKey)) || state.Rides == nil {
		return snapshot{Key: key, Rides: make(map[string]map[string]seatState)}
	}
	state.Key = key
	return state
}

func (s *storage) saveState(id int64, searchID string, state snapshot) error {
	if !validSearchID(searchID) {
		return errSearchNotFound
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	return atomicJSON(s.statePath(id, searchID), state)
}
