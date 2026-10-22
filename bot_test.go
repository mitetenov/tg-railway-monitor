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
	for _, u := range []update{msg(-1001, 7, "/start"), cb(-1001, 7, "search:add"), cb(-1001, 7, "wiz_date:tomorrow"), cb(-1001, 7, "wiz_from:56014"), cb(-1001, 7, "wiz_to:57151"), cb(-1001, 7, "wiz_class:Business")} {
		h.handle(t, u)
	}
	c, err := h.b.store.load(-1001)
	if err != nil || len(c.Searches) != 1 || c.Searches[0].Date != "2026-10-24" || c.Searches[0].Class != "Business" || c.Language != "ru" {
		t.Fatalf("%+v %v", c, err)
	}
	if !strings.Contains(h.last().Body["text"].(string), "Активных поисков: 1") {
		t.Fatal(h.last())
	}
	if len(h.b.wizards) != 0 {
		t.Fatal("wizard not cleared")
	}
	h.handle(t, msg(-1001, 7, "/start"))
	h.handle(t, cb(-1001, 7, "search:add"))
	h.handle(t, msg(-1001, 7, "/stop"))
	c, _ = h.b.store.load(-1001)
	if len(c.Searches) != 0 || len(h.b.wizards) != 0 {
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
	if len(c.Searches) != 0 {
		t.Fatal("stale callback reactivated monitoring")
	}
}

func TestWizardDatesValidationAndCancellation(t *testing.T) {
	h := newHarness(t)
	h.handle(t, msg(1, 1, "/start"))
	h.handle(t, cb(1, 1, "search:add"))
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
	h.handle(t, cb(1, 1, "search:add"))
	h.handle(t, cb(1, 1, "wiz_date:today"))
	if got := h.b.wizards[[2]int64{1, 1}].draft.Date; got != "2026-10-23" {
		t.Fatal(got)
	}
}

func TestReconfigurationIsAtomicAndGroupWizardsAreIsolated(t *testing.T) {
	h := newHarness(t)
	old := testConfig()
	saveConfig(t, h.b.store, 1, old)
	for _, u := range []update{msg(1, 1, "/start"), cb(1, 1, "search:add"), cb(1, 1, "wiz_date:today"), cb(1, 1, "wiz_from:57151"), cb(1, 1, "wiz_to:56014")} {
		h.handle(t, u)
	}
	c, _ := h.b.store.load(1)
	if len(c.Searches) != 1 || c.Searches[0].routeKey() != old.routeKey() {
		t.Fatal("unfinished wizard changed active route", c)
	}
	h.handle(t, cb(1, 1, "cancel"))
	c, _ = h.b.store.load(1)
	if len(c.Searches) != 1 || c.Searches[0].routeKey() != old.routeKey() {
		t.Fatal("cancel changed route")
	}
	h.handle(t, msg(1, 1, "/start"))
	h.handle(t, cb(1, 1, "search:add"))
	h.handle(t, msg(1, 2, "/start"))
	h.handle(t, cb(1, 2, "search:add"))
	h.handle(t, msg(2, 1, "/start"))
	h.handle(t, cb(2, 1, "search:add"))
	h.handle(t, cb(1, 1, "wiz_date:today"))
	if h.b.wizards[[2]int64{1, 2}].step != "date" || h.b.wizards[[2]int64{2, 1}].step != "date" {
		t.Fatal("cross-user state leaked")
	}
}

func TestWizardStationsAndStaleCallbacks(t *testing.T) {
	h := newHarness(t)
	h.handle(t, msg(1, 1, "/start"))
	h.handle(t, cb(1, 1, "search:add"))
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
	h.handle(t, cb(1, 1, "search:add"))
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
	if len(h.b.wizards) != 0 || !strings.Contains(h.last().Body["text"].(string), "Мои поиски") {
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
	saveConfig(t, h.b.store, 1, testConfig())
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
	c, _ := h.b.store.load(1)
	if len(c.Searches) != 1 {
		t.Fatal("duplicate update executed /stop")
	}
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

func requestKeyboard(t *testing.T, request telegramRequest) *markup {
	t.Helper()
	data, err := json.Marshal(request.Body["reply_markup"])
	if err != nil {
		t.Fatal(err)
	}
	var keyboard markup
	if err := json.Unmarshal(data, &keyboard); err != nil {
		t.Fatal(err)
	}
	return &keyboard
}

func keyboardHas(keyboard *markup, data string) bool {
	for _, row := range keyboard.Rows {
		for _, button := range row {
			if button.Data == data {
				return true
			}
		}
	}
	return false
}

func TestHomeShowsEmptySearchListAndAddButton(t *testing.T) {
	for _, lang := range []string{"ru", "en"} {
		t.Run(lang, func(t *testing.T) {
			h := newHarness(t)
			u := msg(1, 1, "/start")
			u.Message.From.Language = lang
			h.handle(t, u)
			if !strings.Contains(h.last().Body["text"].(string), h.b.locale.text(lang, "searches.empty")) || !keyboardHas(requestKeyboard(t, h.last()), "search:add") {
				t.Fatal("home lacks empty state or add button", h.last())
			}
			if len(h.b.wizards) != 0 {
				t.Fatal("opening home started a wizard")
			}
			h.handle(t, cb(1, 1, "search:add"))
			if h.b.wizards[[2]int64{1, 1}].step != "date" {
				t.Fatal("add did not start wizard")
			}
			h.handle(t, cb(1, 1, "cancel"))
			if len(h.b.wizards) != 0 || !keyboardHas(requestKeyboard(t, h.last()), "search:add") {
				t.Fatal("cancel did not return home")
			}
		})
	}
}

func TestBotMultipleSearchesPauseResumeDeleteAndStaleButtons(t *testing.T) {
	h := newHarness(t)
	h.handle(t, msg(1, 1, "/start"))
	for _, class := range []string{"II", "Business"} {
		for _, data := range []string{"search:add", "wiz_date:tomorrow", "wiz_from:56014", "wiz_to:57151", "wiz_class:" + class} {
			h.handle(t, cb(1, 1, data))
		}
	}
	chat, err := h.b.store.load(1)
	if err != nil || len(chat.Searches) != 2 || chat.Searches[0].Class != "II" || chat.Searches[1].Class != "Business" {
		t.Fatal("second wizard replaced first search", chat, err)
	}
	first, second := chat.Searches[0].ID, chat.Searches[1].ID
	keyboard := requestKeyboard(t, h.last())
	if !keyboardHas(keyboard, "search:view:"+first) || !keyboardHas(keyboard, "search:view:"+second) || !keyboardHas(keyboard, "search:add") {
		t.Fatal("home omitted a search", keyboard)
	}
	h.handle(t, cb(1, 1, "search:view:"+first))
	if !keyboardHas(requestKeyboard(t, h.last()), "search:pause:"+first) || !strings.Contains(h.last().Body["text"].(string), "Класс: II") {
		t.Fatal("search card omitted details or pause")
	}
	h.handle(t, cb(1, 1, "search:pause:"+first))
	if !keyboardHas(requestKeyboard(t, h.last()), "search:resume:"+first) {
		t.Fatal("paused card lacks resume")
	}
	chat, _ = h.b.store.load(1)
	if !chat.Searches[0].Paused || chat.Searches[1].Paused {
		t.Fatal("pause affected another search", chat)
	}
	h.handle(t, cb(1, 1, "search:home"))
	if !strings.Contains(h.last().Body["text"].(string), "Активных поисков: 1") {
		t.Fatal("home counted paused search as active")
	}
	h.handle(t, cb(1, 1, "search:resume:"+first))
	chat, _ = h.b.store.load(1)
	if chat.Searches[0].Paused {
		t.Fatal("resume did not persist")
	}
	// A search ID from a different chat grants no access to its settings.
	for _, action := range []string{"view", "pause", "resume", "remove"} {
		h.handle(t, cb(2, 1, "search:"+action+":"+first))
	}
	chat, _ = h.b.store.load(1)
	if len(chat.Searches) != 2 || chat.Searches[0].Paused {
		t.Fatal("another chat modified search", chat)
	}
	h.handle(t, cb(1, 1, "search:delete:"+first))
	chat, _ = h.b.store.load(1)
	if len(chat.Searches) != 2 || !keyboardHas(requestKeyboard(t, h.last()), "search:remove:"+first) {
		t.Fatal("delete was not confirmed in the card")
	}
	h.handle(t, cb(1, 1, "search:view:"+first))
	h.handle(t, cb(1, 1, "search:delete:"+first))
	h.handle(t, cb(1, 1, "search:remove:"+first))
	chat, _ = h.b.store.load(1)
	if len(chat.Searches) != 1 || chat.Searches[0].ID != second {
		t.Fatal("delete removed wrong search", chat)
	}
	for _, action := range []string{"resume", "pause", "view", "remove"} {
		h.handle(t, cb(1, 1, "search:"+action+":"+first))
	}
	chat, _ = h.b.store.load(1)
	if len(chat.Searches) != 1 || chat.Searches[0].ID != second {
		t.Fatal("stale buttons resurrected deleted search", chat)
	}
	h.handle(t, cb(1, 1, "search:pause:"+second))
	h.handle(t, cb(1, 1, "search:home"))
	if !strings.Contains(h.last().Body["text"].(string), "не запущено ни одного поиска") || !keyboardHas(requestKeyboard(t, h.last()), "search:view:"+second) {
		t.Fatal("paused-only home lost empty state or search")
	}
	h.handle(t, msg(1, 1, "/stop"))
	chat, _ = h.b.store.load(1)
	if len(chat.Searches) != 0 || chat.Language != "ru" || !keyboardHas(requestKeyboard(t, h.last()), "search:add") {
		t.Fatal("stop did not clear searches and return home", chat)
	}
}

func TestSearchListPaginationAndExpiry(t *testing.T) {
	h := newHarness(t)
	var ids []string
	for i := 0; i < 10; i++ {
		ids = append(ids, addTestSearch(t, h.b.store, 1, testConfig()))
	}
	h.handle(t, msg(1, 1, "/start"))
	keyboard := requestKeyboard(t, h.last())
	if !keyboardHas(keyboard, "search:view:"+ids[0]) || keyboardHas(keyboard, "search:view:"+ids[8]) || !keyboardHas(keyboard, "search:page:1") {
		t.Fatal("incorrect first search page", keyboard)
	}
	h.handle(t, cb(1, 1, "search:page:999"))
	keyboard = requestKeyboard(t, h.last())
	if !keyboardHas(keyboard, "search:view:"+ids[9]) || !keyboardHas(keyboard, "search:page:0") || !keyboardHas(keyboard, "search:add") {
		t.Fatal("incorrect last search page", keyboard)
	}
	c := testConfig()
	c.Date = "2026-10-22" // Already October 23 in Georgia.
	expired := addTestSearch(t, h.b.store, 1, c)
	if err := h.b.store.setPaused(1, expired, true); err != nil {
		t.Fatal(err)
	}
	h.handle(t, cb(1, 1, "search:view:"+expired))
	chat, err := h.b.store.load(1)
	if err != nil || len(chat.Searches) != 10 {
		t.Fatal("opening expired card affected current searches", chat, err)
	}
	if _, exists := chat.find(expired); exists {
		t.Fatal("expired paused search retained")
	}
}

func TestWizardCrossingMidnightDoesNotCreatePastSearch(t *testing.T) {
	h := newHarness(t)
	for _, data := range []string{"search:add", "wiz_date:today", "wiz_from:56014", "wiz_to:57151"} {
		h.handle(t, cb(1, 1, data))
	}
	h.b.now = func() time.Time { return time.Date(2026, 10, 24, 0, 0, 0, 0, georgiaZone) }
	h.handle(t, cb(1, 1, "wiz_class:Any"))
	chat, err := h.b.store.load(1)
	if err != nil || len(chat.Searches) != 0 || h.b.wizards[[2]int64{1, 1}].step != "date" {
		t.Fatal("wizard created expired search", chat, err)
	}
	if !strings.Contains(h.last().Body["text"].(string), "Дата в прошлом") {
		t.Fatal("wizard did not explain date expiry")
	}
}
