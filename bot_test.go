package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

type telegramRequest struct {
	Method string
	Body   map[string]any
}
type botHarness struct {
	b        *bot
	mu       sync.Mutex
	requests []telegramRequest
}

func newHarness(t *testing.T) *botHarness {
	t.Helper()
	h := &botHarness{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		method := strings.TrimPrefix(r.URL.Path, "/bot123:dummy/")
		h.mu.Lock()
		h.requests = append(h.requests, telegramRequest{method, body})
		h.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		if method == "getMe" {
			fmt.Fprint(w, `{"ok":true,"result":{"id":123,"username":"rail_test_bot"}}`)
		} else {
			fmt.Fprint(w, `{"ok":true,"result":true}`)
		}
	}))
	t.Cleanup(server.Close)
	p, _, _ := testPoller(t)
	tg := &telegram{base: server.URL, token: "123:dummy", username: "rail_test_bot", client: server.Client()}
	h.b = newBot(tg, p.store, p, p.locale)
	h.b.stations = p.locale.fallback
	for _, s := range h.b.stations {
		h.b.index[string(s.Code)] = s
	}
	h.b.now = func() time.Time { return time.Date(2026, 10, 22, 21, 30, 0, 0, time.UTC) }
	return h
}

func msg(chat, actor int64, text string) update {
	m := &message{ID: 42, From: user{ID: actor, Language: "ru-RU"}, Text: text}
	m.Chat.ID = chat
	return update{Message: m}
}
func cb(chat, actor int64, data string) update {
	u := msg(chat, actor, "")
	return update{Callback: &callback{ID: "callback", From: u.Message.From, Message: u.Message, Data: data}}
}
func (h *botHarness) handle(t *testing.T, u update) {
	t.Helper()
	if err := h.b.handle(context.Background(), u); err != nil {
		t.Fatal(err)
	}
}
func (h *botHarness) last() telegramRequest {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.requests[len(h.requests)-1]
}

func TestBotCompleteWizardAndStop(t *testing.T) {
	h := newHarness(t)
	for _, u := range []update{msg(-1001, 7, "/start"), cb(-1001, 7, "wiz_date:tomorrow"), cb(-1001, 7, "wiz_from:56014"), cb(-1001, 7, "wiz_to:57151"), cb(-1001, 7, "wiz_class:Business")} {
		h.handle(t, u)
	}
	c, err := h.b.store.load(-1001)
	if err != nil || !c.complete() || c.Date != "2026-10-24" || c.Class != "Business" || c.Language != "ru" {
		t.Fatalf("%+v %v", c, err)
	}
	if !strings.Contains(h.last().Body["text"].(string), "Мониторинг запущен") {
		t.Fatal(h.last())
	}
	if len(h.b.wizards) != 0 {
		t.Fatal("wizard not cleared")
	}
	h.handle(t, msg(-1001, 7, "/start"))
	h.handle(t, msg(-1001, 7, "/stop"))
	c, _ = h.b.store.load(-1001)
	if c.complete() || len(h.b.wizards) != 0 {
		t.Fatal("stop retained configuration or wizard")
	}
	if c.Language != "ru" {
		t.Fatal("stop lost stored language", c)
	}
	h.b.languages = make(map[int64]string)
	u := msg(-1001, 7, "/lang")
	u.Message.From.Language = "en"
	h.handle(t, u)
	if h.last().Body["text"] != "🌐 *Выберите язык интерфейса:*" {
		t.Fatal("stored language did not survive restart")
	}
	h.handle(t, cb(-1001, 7, "wiz_class:I"))
	c, _ = h.b.store.load(-1001)
	if c.complete() {
		t.Fatal("stale callback reactivated monitoring")
	}
}

func TestWizardDatesValidationAndCancellation(t *testing.T) {
	h := newHarness(t)
	h.handle(t, msg(1, 1, "/start"))
	h.handle(t, cb(1, 1, "wiz_date:custom"))
	for input, key := range map[string]string{"2026-02-30": "date_invalid", "2026-10-22": "date_past", "2026-1-02": "date_invalid", "oops": "date_invalid"} {
		h.handle(t, msg(1, 1, input))
		if h.last().Body["text"] != h.b.locale.text("ru", "wizard."+key) {
			t.Fatal(input, h.last())
		}
	}
	h.handle(t, msg(1, 1, "2026-10-23"))
	if h.b.wizards[[2]int64{1, 1}].step != "from" {
		t.Fatal("today in Tbilisi was rejected")
	}
	h.handle(t, cb(1, 1, "cancel"))
	if len(h.b.wizards) != 0 {
		t.Fatal("not canceled")
	}
	// Today must use Georgia's date even though UTC still says October 22.
	h.handle(t, msg(1, 1, "/start"))
	h.handle(t, cb(1, 1, "wiz_date:today"))
	if got := h.b.wizards[[2]int64{1, 1}].draft.Date; got != "2026-10-23" {
		t.Fatal(got)
	}
}

func TestReconfigurationIsAtomicAndGroupWizardsAreIsolated(t *testing.T) {
	h := newHarness(t)
	old := testConfig()
	saveConfig(t, h.b.store, 1, old)
	for _, u := range []update{msg(1, 1, "/start"), cb(1, 1, "wiz_date:today"), cb(1, 1, "wiz_from:57151"), cb(1, 1, "wiz_to:56014")} {
		h.handle(t, u)
	}
	c, _ := h.b.store.load(1)
	if c != old {
		t.Fatal("unfinished wizard changed active route", c)
	}
	h.handle(t, cb(1, 1, "cancel"))
	c, _ = h.b.store.load(1)
	if c != old {
		t.Fatal("cancel changed route")
	}
	h.handle(t, msg(1, 1, "/start"))
	h.handle(t, msg(1, 2, "/start"))
	h.handle(t, msg(2, 1, "/start"))
	h.handle(t, cb(1, 1, "wiz_date:today"))
	if h.b.wizards[[2]int64{1, 2}].step != "date" || h.b.wizards[[2]int64{2, 1}].step != "date" {
		t.Fatal("cross-user state leaked")
	}
}

func TestWizardStationsAndStaleCallbacks(t *testing.T) {
	h := newHarness(t)
	h.handle(t, msg(1, 1, "/start"))
	h.handle(t, cb(1, 1, "wiz_class:Any"))
	if h.b.wizards[[2]int64{1, 1}].step != "date" {
		t.Fatal("out-of-order class accepted")
	}
	h.handle(t, cb(1, 1, "wiz_date:today"))
	h.handle(t, cb(1, 1, "wiz_from:all"))
	for _, page := range []string{"-1", "999", "oops", "1"} {
		h.handle(t, cb(1, 1, "page:wiz_from:"+page))
	}
	h.handle(t, cb(1, 1, "wiz_from:00000"))
	if !strings.Contains(h.last().Body["text"].(string), "не найдена") {
		t.Fatal(h.last())
	}
	h.handle(t, cb(1, 1, "wiz_from:56014"))
	h.handle(t, cb(1, 1, "wiz_to:56014"))
	if h.b.wizards[[2]int64{1, 1}].step != "to" {
		t.Fatal("same station accepted")
	}
	h.handle(t, cb(1, 1, "wiz_to:57151"))
	h.handle(t, cb(1, 1, "wiz_class:III"))
	if h.b.wizards[[2]int64{1, 1}].step != "class" {
		t.Fatal("invalid class accepted")
	}
	for _, page := range []int{-100, 0, 1, 999} {
		keyboard := h.b.stationKeyboard("ru", "wiz_from", page)
		for _, row := range keyboard.Rows {
			for _, b := range row {
				if b.Data == "wiz_from:57530" {
					t.Fatal("unserved station offered")
				}
			}
		}
	}
}

func TestLanguageCanChangeInsideWizardAndSurvivesRestart(t *testing.T) {
	h := newHarness(t)
	h.handle(t, msg(1, 1, "/start"))
	h.handle(t, cb(1, 1, "lang_set:en"))
	h.handle(t, cb(1, 1, "wiz_date:today"))
	if h.last().Body["text"] != "🚉 *Select departure station:*" {
		t.Fatal(h.last())
	}
	h.handle(t, msg(1, 1, "/lang ru-RU"))
	c, _ := h.b.store.load(1)
	if c.Language != "ru" {
		t.Fatal(c)
	}
	h.b.languages = make(map[int64]string)
	h.handle(t, msg(1, 1, "/lang"))
	if h.last().Body["text"] != "🌐 *Выберите язык интерфейса:*" {
		t.Fatal(h.last())
	}
	h.handle(t, msg(1, 1, "/lang xx"))
	if !strings.Contains(h.last().Body["text"].(string), "Unsupported language") {
		t.Fatal(h.last())
	}
	h.handle(t, cb(1, 1, "lang_set:xx"))
	c, _ = h.b.store.load(1)
	if c.Language != "ru" {
		t.Fatal(c)
	}
}

func TestOtherBotCommandsAndCorruptConfigRecovery(t *testing.T) {
	h := newHarness(t)
	h.handle(t, msg(1, 1, "/start@another_bot"))
	if len(h.b.wizards) != 0 {
		t.Fatal("handled another bot's command")
	}
	h.handle(t, msg(1, 1, "/start@rail_test_bot"))
	if len(h.b.wizards) != 1 {
		t.Fatal("did not handle own mention")
	}
	h.handle(t, msg(1, 1, "/unknown"))
	if !strings.Contains(h.last().Body["text"].(string), "не понимаю") {
		t.Fatal(h.last())
	}
	if err := os.WriteFile(h.b.store.path(1, false), []byte("bad"), 0600); err != nil {
		t.Fatal(err)
	}
	h.handle(t, msg(1, 1, "/stop"))
	if _, err := os.Stat(h.b.store.path(1, false)); !os.IsNotExist(err) {
		t.Fatal(err)
	}
}

func TestTelegramInitializationAndErrors(t *testing.T) {
	h := newHarness(t)
	if err := h.b.tg.initialize(context.Background()); err != nil {
		t.Fatal(err)
	}
	h.mu.Lock()
	requests := append([]telegramRequest(nil), h.requests...)
	h.mu.Unlock()
	if len(requests) != 3 || requests[0].Method != "getMe" || requests[1].Method != "deleteWebhook" || requests[2].Method != "setMyCommands" {
		t.Fatal(requests)
	}
	commands := requests[2].Body["commands"].([]any)
	if len(commands) != 3 {
		t.Fatal(commands)
	}
	for _, code := range []int{401, 409, 429, 500} {
		t.Run(fmt.Sprint(code), func(t *testing.T) {
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(code)
				fmt.Fprintf(w, `{"ok":false,"error_code":%d,"description":"123:dummy","parameters":{"retry_after":2}}`, code)
			}))
			defer s.Close()
			tg := &telegram{base: s.URL, token: "123:dummy", client: s.Client()}
			err := tg.send(context.Background(), outgoing{ChatID: 1, Text: "test"})
			var apiError *telegramError
			if !errors.As(err, &apiError) || apiError.Code != code || apiError.RetryAfter != 2 || strings.Contains(err.Error(), tg.token) {
				t.Fatal(err)
			}
			if code == 401 || code == 409 {
				h.b.tg = tg
				if err := h.b.run(context.Background()); err == nil {
					t.Fatal("fatal error retried indefinitely")
				}
			}
		})
	}
}

func TestTelegramTransportRedactsTokenAndCancellation(t *testing.T) {
	release := make(chan struct{})
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-release }))
	tg := &telegram{base: s.URL, token: "secret:token", client: s.Client()}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Millisecond)
	err := tg.send(ctx, outgoing{})
	cancel()
	close(release)
	s.Close()
	if err == nil || strings.Contains(err.Error(), tg.token) {
		t.Fatal(err)
	}
	err = tg.send(context.Background(), outgoing{})
	if err == nil || strings.Contains(err.Error(), tg.token) {
		t.Fatal(err)
	}
}

func TestDotEnvPrecedenceAndQuotes(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env")
	t.Setenv("TG_TEST_EXISTING", "environment")
	for _, key := range []string{"TG_TEST_DOUBLE", "TG_TEST_SINGLE", "TG_TEST_PLAIN"} {
		t.Setenv(key, "")
		os.Unsetenv(key)
	}
	if err := os.WriteFile(path, []byte("# comment\nTG_TEST_EXISTING=file\nexport TG_TEST_DOUBLE=\"hello world\" # comment\nTG_TEST_SINGLE='value#hash'\nTG_TEST_PLAIN=value # comment\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := loadDotEnv(path); err != nil {
		t.Fatal(err)
	}
	for key, want := range map[string]string{"TG_TEST_EXISTING": "environment", "TG_TEST_DOUBLE": "hello world", "TG_TEST_SINGLE": "value#hash", "TG_TEST_PLAIN": "value"} {
		if got := os.Getenv(key); got != want {
			t.Fatal(key, got)
		}
	}
}

func TestLongPollingOffsetsAndDuplicateUpdates(t *testing.T) {
	h := newHarness(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var offsets []int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "getUpdates") {
			fmt.Fprint(w, `{"ok":true,"result":true}`)
			return
		}
		var body struct {
			Offset  int64    `json:"offset"`
			Timeout int      `json:"timeout"`
			Allowed []string `json:"allowed_updates"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		offsets = append(offsets, body.Offset)
		if body.Timeout != 30 || len(body.Allowed) != 2 {
			t.Error("long polling contract", body)
		}
		switch len(offsets) {
		case 1:
			u := msg(1, 1, "/start")
			u.ID = 10
			json.NewEncoder(w).Encode(map[string]any{"ok": true, "result": []update{u}})
		case 2:
			stale := msg(1, 1, "/stop")
			stale.ID = 10
			u := msg(1, 1, "/lang en")
			u.ID = 11
			json.NewEncoder(w).Encode(map[string]any{"ok": true, "result": []update{stale, u}})
		default:
			cancel()
			fmt.Fprint(w, `{"ok":true,"result":[]}`)
		}
	}))
	defer server.Close()
	h.b.tg.base = server.URL
	h.b.tg.client = server.Client()
	if err := h.b.run(ctx); err != nil {
		t.Fatal(err)
	}
	// Shutdown the server before reading request-owned state.
	server.Close()
	if fmt.Sprint(offsets) != "[0 11 12]" {
		t.Fatal(offsets)
	}
	if len(h.b.wizards) != 1 {
		t.Fatal("duplicate update executed /stop")
	}
	c, _ := h.b.store.load(1)
	if c.Language != "en" {
		t.Fatal(c)
	}
}

func TestStationFallbackAndAPIReenablesStation(t *testing.T) {
	h := newHarness(t)
	for _, body := range []string{"null", `[{"code":"57530","stationName":"Kutaisi"},{"code":"","stationName":"bad"},{"code":"57530","stationName":"duplicate"}]`} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, body) }))
		h.b.loadStations(context.Background(), &railwayAPI{base: server.URL, client: server.Client()})
		server.Close()
		if body == "null" {
			if len(h.b.stations) != 36 {
				t.Fatal("fallback not loaded")
			}
		} else {
			if len(h.b.stations) != 1 || h.b.stations[0].Code != "57530" {
				t.Fatal(h.b.stations)
			}
			if _, old := h.b.index["56014"]; old {
				t.Fatal("station reload left stale entry")
			}
		}
	}
}
