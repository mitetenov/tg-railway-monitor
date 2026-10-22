package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

type fakeAPI struct {
	mu    sync.Mutex
	rides []ride
	err   error
	calls int
}

func (a *fakeAPI) search(ctx context.Context, c config) ([]ride, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.calls++
	return a.rides, a.err
}

type fakeSender struct {
	mu       sync.Mutex
	messages []outgoing
	fail     bool
}

func (s *fakeSender) send(ctx context.Context, out outgoing) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.fail {
		return errors.New("delivery failed")
	}
	s.messages = append(s.messages, out)
	return nil
}
func testPoller(t *testing.T) (*poller, *fakeAPI, *fakeSender) {
	t.Helper()
	cat, err := newCatalog()
	if err != nil {
		t.Fatal(err)
	}
	a := &fakeAPI{}
	sender := &fakeSender{}
	p := newPoller(context.Background(), testStore(t), a, sender, cat)
	p.now = func() time.Time { return time.Date(2026, 10, 22, 0, 0, 0, 0, time.UTC) }
	t.Cleanup(p.close)
	return p, a, sender
}
func sampleRide(seats int) ride {
	return ride{Number: "812", Start: "2026-12-30T00:30:00Z", End: "2026-12-30T05:42:00Z", Duration: "05:12:00", Classes: []seatClass{{2, seats, "36"}, {1, 15, "76"}, {5, 3, "126"}}}
}

func TestPollerAvailabilitySequenceAndRestart(t *testing.T) {
	p, a, s := testPoller(t)
	c := testConfig()
	c.Class = "II"
	saveConfig(t, p.store, 1, c)
	for _, test := range []struct {
		seats  int
		notify bool
	}{{3, true}, {3, false}, {2, false}, {0, false}, {1, true}, {7, true}} {
		a.rides = []ride{sampleRide(test.seats)}
		before := len(s.messages)
		if err := p.check(context.Background(), 1, "legacy"); err != nil {
			t.Fatal(err)
		}
		if (len(s.messages) > before) != test.notify {
			t.Fatalf("%+v: %d messages", test, len(s.messages)-before)
		}
	}
	// A fresh poller loads the Python-compatible on-disk snapshot.
	p2 := newPoller(context.Background(), p.store, a, s, p.locale)
	if err := p2.check(context.Background(), 1, "legacy"); err != nil {
		t.Fatal(err)
	}
	if len(s.messages) != 3 {
		t.Fatal("restart re-announced tickets", len(s.messages))
	}
	// An authoritative empty result removes stale rides, then reappearance notifies.
	a.rides = nil
	if err := p.check(context.Background(), 1, "legacy"); err != nil {
		t.Fatal(err)
	}
	a.rides = []ride{sampleRide(7)}
	if err := p.check(context.Background(), 1, "legacy"); err != nil {
		t.Fatal(err)
	}
	if len(s.messages) != 4 {
		t.Fatal("reappearing ride not announced")
	}
}

func TestPollerRetryDeliveryAndAPIFailure(t *testing.T) {
	p, a, s := testPoller(t)
	saveConfig(t, p.store, 1, testConfig())
	a.rides = []ride{sampleRide(1)}
	s.fail = true
	if err := p.check(context.Background(), 1, "legacy"); err == nil {
		t.Fatal("expected delivery error")
	}
	if state := p.store.loadState(1, "legacy", testConfig().routeKey()); len(state.Rides) != 0 {
		t.Fatal("failed notification committed state")
	}
	s.fail = false
	if err := p.check(context.Background(), 1, "legacy"); err != nil {
		t.Fatal(err)
	}
	a.err = errors.New("upstream unavailable")
	before, _ := os.ReadFile(p.store.path(1, true))
	if err := p.check(context.Background(), 1, "legacy"); err == nil {
		t.Fatal("expected API error")
	}
	after, _ := os.ReadFile(p.store.path(1, true))
	if string(before) != string(after) {
		t.Fatal("API failure reset baseline")
	}
	a.err = nil
	if err := p.check(context.Background(), 1, "legacy"); err != nil {
		t.Fatal(err)
	}
	if len(s.messages) != 1 {
		t.Fatal(len(s.messages))
	}
}

func TestPollerGroupedClassesAndRouteReset(t *testing.T) {
	p, _, _ := testPoller(t)
	for _, lang := range []string{"en", "ru"} {
		for _, class := range []string{"Any", "I", "II", "Business"} {
			t.Run(lang+"/"+class, func(t *testing.T) {
				c := testConfig()
				c.Language = lang
				c.Class = class
				other := sampleRide(7)
				other.Number = "814"
				state, text := p.notification(c, []ride{sampleRide(4), other}, snapshot{})
				if !strings.Contains(text, "#812") || !strings.Contains(text, "#814") || strings.Count(text, "https://tre.ge/en/search") != 2 {
					t.Fatal(text)
				}
				if class != "Any" && len(state.Rides["812"]) != 1 {
					t.Fatal(state)
				}
				if _, again := p.notification(c, []ride{sampleRide(4), other}, state); again != "" {
					t.Fatal("duplicate notification")
				}
				c.Date = "2026-12-31"
				if _, again := p.notification(c, []ride{sampleRide(4)}, state); again == "" {
					t.Fatal("route change reused snapshot")
				}
			})
		}
	}
}

func TestPollerLifecycleAndRestore(t *testing.T) {
	p, a, _ := testPoller(t)
	p.interval = 2 * time.Millisecond
	a.err = errors.New("temporary")
	saveConfig(t, p.store, -1001, testConfig())
	saveConfig(t, p.store, 2, config{Language: "ru"})
	if err := os.WriteFile(p.store.path(3, false), []byte("bad"), 0600); err != nil {
		t.Fatal(err)
	}
	n, err := p.restore()
	if err != nil || n != 1 {
		t.Fatal(n, err)
	}
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		a.mu.Lock()
		calls := a.calls
		a.mu.Unlock()
		if calls >= 2 {
			break
		}
		time.Sleep(time.Millisecond)
	}
	p.stop(-1001, "legacy")
	a.mu.Lock()
	calls := a.calls
	a.mu.Unlock()
	if calls < 2 {
		t.Fatal("loop died on API error")
	}
	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Go(func() { p.start(-1001, "legacy"); p.stop(-1001, "legacy") })
	}
	wg.Wait()
	p.mu.Lock()
	count := len(p.tasks)
	p.mu.Unlock()
	if count != 0 {
		t.Fatal("task leaked")
	}
	if _, err := os.Stat(p.store.path(-1001, false)); err != nil {
		t.Fatal("stop deleted config", err)
	}
}

func TestSplitLargeNotification(t *testing.T) {
	text := "header"
	for i := 0; i < 80; i++ {
		text += fmt.Sprintf("\n\n🚆 Рейс #%d\n🔗 [Купить](https://tre.ge/en/search?leavingPlace=56014)\nII Class: 3 мест · 36 GEL", i)
	}
	chunks := splitNotification(text)
	if len(chunks) < 2 {
		t.Fatal("did not split")
	}
	for _, chunk := range chunks {
		if len([]rune(chunk)) > 4096 {
			t.Fatal("Telegram limit exceeded")
		}
	}
	if strings.Join(chunks, "\n\n") != text {
		t.Fatal("lost text")
	}
}

func TestPythonNotificationParity(t *testing.T) {
	data, err := os.ReadFile("testdata/python_notifications.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name     string   `json:"name"`
		Config   config   `json:"config"`
		Previous snapshot `json:"previous"`
		Rides    []ride   `json:"rides"`
		Want     string   `json:"want"`
	}
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) < 100 {
		t.Fatal("not enough parity cases", len(cases))
	}
	p, _, _ := testPoller(t)
	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			_, got := p.notification(c.Config, c.Rides, c.Previous)
			if got != c.Want {
				t.Fatalf("Go:\n%s\nPython:\n%s", got, c.Want)
			}
		})
	}
}

func TestReliabilityClassSnapshotAndLegacyMigration(t *testing.T) {
	p, a, s := testPoller(t)
	c := testConfig()
	saveConfig(t, p.store, 1, c)
	a.rides = []ride{sampleRide(4)}
	old := snapshot{Key: c.legacyRouteKey(), Rides: map[string]map[string]seatState{"812": {"1": {15, "76"}, "2": {4, "36"}, "5": {3, "126"}}}}
	if err := p.store.saveState(1, "legacy", old); err != nil {
		t.Fatal(err)
	}
	if err := p.check(context.Background(), 1, "legacy"); err != nil {
		t.Fatal(err)
	}
	if len(s.messages) != 0 {
		t.Fatal("legacy state re-announced tickets")
	}
	stored := p.store.loadState(1, "legacy", c.routeKey())
	if stored.Key != c.routeKey() {
		t.Fatal(stored)
	}
	c.Class = "I"
	saveConfig(t, p.store, 1, c)
	if err := p.check(context.Background(), 1, "legacy"); err != nil {
		t.Fatal(err)
	}
	if len(s.messages) != 1 {
		t.Fatal("class change reused unrelated snapshot")
	}
	if p.store.loadState(1, "legacy", c.routeKey()).Key != "56014>57151@2026-12-30#I" {
		t.Fatal("missing class identity")
	}
}

func TestExpiredMonitorsPreserveLanguageAndLeaveRegistry(t *testing.T) {
	p, a, _ := testPoller(t)
	p.now = func() time.Time { return time.Date(2026, 10, 22, 21, 0, 0, 0, time.UTC) }
	c := testConfig()
	c.Date = "2026-10-22" // Already October 23 in Georgia.
	saveConfig(t, p.store, 1, c)
	if err := p.store.saveState(1, "legacy", snapshot{Key: c.routeKey(), Rides: map[string]map[string]seatState{}}); err != nil {
		t.Fatal(err)
	}
	p.start(1, "legacy")
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		p.mu.Lock()
		count := len(p.tasks)
		p.mu.Unlock()
		if count == 0 {
			break
		}
		time.Sleep(time.Millisecond)
	}
	p.mu.Lock()
	count := len(p.tasks)
	p.mu.Unlock()
	if count != 0 {
		t.Fatal("expired worker retained in registry")
	}
	got, err := p.store.load(1)
	if err != nil || (got.Language != "ru" || len(got.Searches) != 0) {
		t.Fatal(got, err)
	}
	if _, err := os.Stat(p.store.path(1, true)); !os.IsNotExist(err) {
		t.Fatal("expired snapshot retained", err)
	}
	a.mu.Lock()
	calls := a.calls
	a.mu.Unlock()
	if calls != 0 {
		t.Fatal("expired route queried API")
	}
	// Restoration clears expired entries; today's route remains active.
	saveConfig(t, p.store, 2, c)
	c.Date = "2026-10-23"
	saveConfig(t, p.store, 3, c)
	n, err := p.restore()
	if err != nil || n != 1 {
		t.Fatal(n, err)
	}
	p.stop(3, "legacy")
	got, _ = p.store.load(2)
	if got.Language != "ru" || len(got.Searches) != 0 {
		t.Fatal(got)
	}
}

type blockingAPI struct {
	started chan config
}

func (a *blockingAPI) search(ctx context.Context, c config) ([]ride, error) {
	select {
	case a.started <- c:
	case <-ctx.Done():
	}
	<-ctx.Done()
	// Even a provider returning success after cancellation must not send or save.
	return []ride{sampleRide(9)}, nil
}

type blockingSender struct {
	started chan struct{}
}

func (s *blockingSender) send(ctx context.Context, out outgoing) error {
	close(s.started)
	<-ctx.Done()
	return ctx.Err()
}

func TestPauseCancelsDeliveryWithoutCommittingSnapshot(t *testing.T) {
	p, a, _ := testPoller(t)
	a.rides = []ride{sampleRide(4)}
	sender := &blockingSender{started: make(chan struct{})}
	p.sender = sender
	id := addTestSearch(t, p.store, 1, testConfig())
	p.start(1, id)
	select {
	case <-sender.started:
	case <-time.After(time.Second):
		t.Fatal("notification did not start")
	}
	if err := p.setPaused(1, id, true); err != nil {
		t.Fatal(err)
	}
	if state := p.store.loadState(1, id, testConfig().routeKey()); len(state.Rides) != 0 {
		t.Fatal("canceled delivery committed baseline")
	}
	chat, err := p.store.load(1)
	if err != nil || len(chat.Searches) != 1 || !chat.Searches[0].Paused {
		t.Fatal("delivery cancellation lost paused search", chat, err)
	}
}

func awaitSearch(t *testing.T, started <-chan config) config {
	t.Helper()
	select {
	case c := <-started:
		return c
	case <-time.After(time.Second):
		t.Fatal("search did not start")
		return config{}
	}
}

func TestParallelSearchesPauseAndDeleteIndependently(t *testing.T) {
	p, _, sender := testPoller(t)
	a := &blockingAPI{started: make(chan config, 2)}
	p.api = a
	c := testConfig()
	c.Class = "II"
	first := addTestSearch(t, p.store, 1, c)
	c.Class = "I"
	second := addTestSearch(t, p.store, 1, c)
	p.start(1, first)
	p.start(1, second)
	seen := map[string]bool{awaitSearch(t, a.started).Class: true}
	seen[awaitSearch(t, a.started).Class] = true
	if len(seen) != 2 {
		t.Fatal("searches did not run simultaneously", seen)
	}
	if err := p.setPaused(1, first, true); err != nil {
		t.Fatal(err)
	}
	p.mu.Lock()
	_, secondRunning := p.tasks[taskKey{1, second}]
	count := len(p.tasks)
	p.mu.Unlock()
	if count != 1 || !secondRunning {
		t.Fatal("pause affected another worker", count)
	}
	chat, err := p.store.load(1)
	if err != nil || len(chat.Searches) != 2 || !chat.Searches[0].Paused || chat.Searches[1].Paused {
		t.Fatal("pause lost configuration", chat, err)
	}
	if err := p.remove(1, second); err != nil {
		t.Fatal(err)
	}
	chat, err = p.store.load(1)
	if err != nil || len(chat.Searches) != 1 || chat.Searches[0].ID != first {
		t.Fatal("delete affected paused search", chat, err)
	}
	for _, id := range []string{first, second} {
		if _, err := os.Stat(p.store.statePath(1, id)); !os.IsNotExist(err) {
			t.Fatal("canceled request wrote a snapshot", err)
		}
	}
	if len(sender.messages) != 0 {
		t.Fatal("canceled request sent a notification")
	}
	// Concurrent lifecycle changes must never leak a worker or resurrect deletion.
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Go(func() {
			if err := p.setPaused(1, first, false); err != nil && !errors.Is(err, errSearchNotFound) {
				t.Error(err)
			}
			if err := p.setPaused(1, first, true); err != nil && !errors.Is(err, errSearchNotFound) {
				t.Error(err)
			}
		})
	}
	wg.Go(func() {
		if err := p.remove(1, first); err != nil {
			t.Error(err)
		}
	})
	wg.Wait()
	p.mu.Lock()
	count = len(p.tasks)
	p.mu.Unlock()
	chat, err = p.store.load(1)
	if err != nil || len(chat.Searches) != 0 || count != 0 {
		t.Fatal("concurrent lifecycle resurrected search", chat, count, err)
	}
}

func TestIndependentBaselinesSurvivePauseResumeAndRestart(t *testing.T) {
	p, a, sender := testPoller(t)
	c := testConfig()
	// Identical searches still have independent delivery histories.
	first := addTestSearch(t, p.store, 1, c)
	second := addTestSearch(t, p.store, 1, c)
	if err := p.store.update(1, func(c *chatConfig) error { c.Language = "ru"; return nil }); err != nil {
		t.Fatal(err)
	}
	a.rides = []ride{sampleRide(4)}
	for _, searchID := range []string{first, second, first, second} {
		if err := p.check(context.Background(), 1, searchID); err != nil {
			t.Fatal(err)
		}
	}
	if len(sender.messages) != 2 {
		t.Fatal("searches shared baseline or reannounced seats", len(sender.messages))
	}
	for i, id := range []string{first, second} {
		if sender.messages[i].Markup.Rows[0][0].Data != "search:view:"+id {
			t.Fatal("notification linked to wrong search")
		}
	}
	if err := p.setPaused(1, first, true); err != nil {
		t.Fatal(err)
	}
	if err := p.check(context.Background(), 1, first); !errors.Is(err, errMonitorInactive) {
		t.Fatal("paused search polled", err)
	}
	// Restart: resume only active searches, preserving both snapshot files.
	p2 := newPoller(context.Background(), p.store, a, sender, p.locale)
	p2.now = p.now
	t.Cleanup(p2.close)
	n, err := p2.restore()
	if err != nil || n != 1 {
		t.Fatal("paused search resumed at startup", n, err)
	}
	p2.stopChat(1)
	if err := p2.setPaused(1, first, false); err != nil {
		t.Fatal(err)
	}
	// Stop and manually run one completed check to avoid relying on timing.
	p2.stop(1, first)
	if err := p2.check(context.Background(), 1, first); err != nil {
		t.Fatal(err)
	}
	if len(sender.messages) != 2 {
		t.Fatal("resume or restart reannounced unchanged tickets")
	}
	a.rides = []ride{sampleRide(8)}
	if err := p2.check(context.Background(), 1, first); err != nil {
		t.Fatal(err)
	}
	if len(sender.messages) != 3 {
		t.Fatal("increase after pause not delivered")
	}
	if err := p2.remove(1, first); err != nil {
		t.Fatal(err)
	}
	if state := p.store.loadState(1, second, c.routeKey()); state.Rides["812"]["2"].Seats != 4 {
		t.Fatal("deletion changed another baseline", state)
	}
}

func TestRestoreExpiresOnlyPastSearchesIncludingPaused(t *testing.T) {
	p, _, _ := testPoller(t)
	c := testConfig()
	live := addTestSearch(t, p.store, 1, c)
	paused := addTestSearch(t, p.store, 1, c)
	c.Date = "2026-10-21"
	expired := addTestSearch(t, p.store, 1, c)
	if err := p.store.setPaused(1, paused, true); err != nil {
		t.Fatal(err)
	}
	if err := p.store.setPaused(1, expired, true); err != nil {
		t.Fatal(err)
	}
	n, err := p.restore()
	if err != nil || n != 1 {
		t.Fatal(n, err)
	}
	p.stopChat(1)
	chat, err := p.store.load(1)
	if err != nil || len(chat.Searches) != 2 || chat.Searches[0].ID != live || chat.Searches[1].ID != paused || !chat.Searches[1].Paused {
		t.Fatal("expiration affected current searches", chat, err)
	}
}
