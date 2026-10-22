package main

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"log/slog"
	"sort"
	"strconv"
	"strings"
	"time"
	_ "time/tzdata"
)

type wizard struct {
	step              string
	draft             config
	departures        []departure
	departureError    bool
	departureFallback bool
}

type departure struct {
	time   string
	number string
}

func (d departure) callback() string {
	sum := sha256.Sum256([]byte(d.time + "\x00" + d.number))
	return fmt.Sprintf("wiz_time:%x", sum[:8])
}

var georgiaZone = func() *time.Location {
	zone, err := time.LoadLocation("Asia/Tbilisi")
	if err != nil {
		return time.FixedZone("Asia/Tbilisi", 4*60*60)
	}
	return zone
}()

type bot struct {
	tg        *telegram
	store     *storage
	poller    *poller
	timetable timetableSource
	locale    *catalog
	stations  []station
	index     map[string]station
	wizards   map[[2]int64]*wizard
	languages map[int64]string
	now       func() time.Time
	zone      *time.Location
}

func newBot(tg *telegram, store *storage, p *poller, timetable timetableSource, locale *catalog) *bot {
	return &bot{tg: tg, store: store, poller: p, timetable: timetable, locale: locale, index: make(map[string]station), wizards: make(map[[2]int64]*wizard), languages: make(map[int64]string), now: time.Now, zone: georgiaZone}
}

func (b *bot) loadStations(ctx context.Context, api *railwayAPI) {
	stations, err := api.stations(ctx)
	if err != nil || len(stations) == 0 {
		stations = b.locale.fallback
		slog.Warn("Using offline station dictionary")
	}
	b.stations = nil
	b.index = make(map[string]station)
	for _, s := range stations {
		if _, err := strconv.ParseUint(string(s.Code), 10, 32); err != nil {
			continue
		}
		if _, duplicate := b.index[string(s.Code)]; duplicate {
			continue
		}
		b.stations = append(b.stations, s)
		b.index[string(s.Code)] = s
	}
	if len(b.stations) == 0 {
		for _, s := range b.locale.fallback {
			b.stations = append(b.stations, s)
			b.index[string(s.Code)] = s
		}
	}
}

func (b *bot) keyboard(lang, kind string) *markup {
	t := func(key string) string { return b.locale.text(lang, key) }
	cancel := []button{{t("button.cancel"), "cancel"}}
	switch kind {
	case "date":
		return &markup{[][]button{
			{{t("wizard.date_today_btn"), "wiz_date:today"}, {t("wizard.date_tomorrow_btn"), "wiz_date:tomorrow"}},
			{{t("wizard.date_custom_btn"), "wiz_date:custom"}}, cancel,
		}}
	case "class":
		return &markup{[][]button{
			{{t("wizard.class_any_btn"), "wiz_class:Any"}, {t("wizard.class_business_btn"), "wiz_class:Business"}},
			{{t("wizard.class_i_btn"), "wiz_class:I"}, {t("wizard.class_ii_btn"), "wiz_class:II"}}, cancel,
		}}
	case "lang":
		return &markup{[][]button{{{t("lang.en_btn"), "lang_set:en"}, {t("lang.ru_btn"), "lang_set:ru"}}}}
	default:
		return b.quickStationKeyboard(lang, kind, "")
	}
}

func (b *bot) quickStationKeyboard(lang, action, excludedCode string) *markup {
	var quick []button
	for _, code := range []string{"56014", "57151"} {
		if s, ok := b.index[code]; ok && code != excludedCode {
			quick = append(quick, button{b.locale.stationName(code, lang, s.Name), action + ":" + code})
		}
	}
	rows := [][]button{}
	if len(quick) > 0 {
		rows = append(rows, quick)
	}
	rows = append(rows, []button{{b.locale.text(lang, "wizard.station_all_btn"), action + ":all"}}, []button{{b.locale.text(lang, "button.cancel"), "cancel"}})
	return &markup{Rows: rows}
}

func (b *bot) stationKeyboard(lang, action string, page int, excludedCode string) *markup {
	var stations []station
	for _, s := range b.stations {
		if s.Code != "56014" && s.Code != "57151" && string(s.Code) != excludedCode {
			stations = append(stations, s)
		}
	}
	pages := max(1, (len(stations)+7)/8)
	page = max(0, min(page, pages-1))
	rows := [][]button{}
	for _, s := range stations[min(page*8, len(stations)):min((page+1)*8, len(stations))] {
		rows = append(rows, []button{{b.locale.stationName(string(s.Code), lang, s.Name), action + ":" + string(s.Code)}})
	}
	var nav []button
	if page > 0 {
		nav = append(nav, button{b.locale.text(lang, "button.prev"), fmt.Sprintf("page:%s:%d", action, page-1)})
	}
	nav = append(nav, button{fmt.Sprintf("%d/%d", page+1, pages), "noop"})
	if page < pages-1 {
		nav = append(nav, button{b.locale.text(lang, "button.next"), fmt.Sprintf("page:%s:%d", action, page+1)})
	}
	return &markup{append(rows, nav, []button{{b.locale.text(lang, "button.cancel"), "cancel"}})}
}

// loadDepartures reads the timetable independently of ticket availability, so
// sold-out trains remain selectable.
func (b *bot) loadDepartures(ctx context.Context, w *wizard) {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	c := w.draft
	c.Class = "Any"
	rides, err := b.timetable.schedule(ctx, c)
	w.departures = nil
	w.departureError = err != nil
	w.departureFallback = false
	if err != nil {
		slog.Warn("Cannot load departure choices", "error", err)
		rides = nil
	}
	// tre.ge's published timetable omits some intermediate station pairs.
	// Preserve the available departures for those routes and label the limited
	// list, instead of silently removing previously selectable trains.
	if len(rides) == 0 {
		available, availabilityErr := b.poller.api.search(ctx, c)
		if availabilityErr != nil {
			w.departureError = true
			slog.Warn("Cannot load fallback departure choices", "error", availabilityErr)
		} else if len(available) > 0 {
			rides = available
			w.departureError = false
			w.departureFallback = true
		}
	}
	seen := make(map[departure]bool)
	for _, r := range rides {
		choice := departure{time: formatTime(r.Start), number: string(r.Number)}
		if r.Number == "" || !validTime(choice.time) || seen[choice] {
			continue
		}
		seen[choice] = true
		w.departures = append(w.departures, choice)
	}
	sort.Slice(w.departures, func(i, j int) bool {
		a, b := w.departures[i], w.departures[j]
		if a.time == b.time {
			return a.number < b.number
		}
		return a.time < b.time
	})
}

func (b *bot) departureChoices(lang string, w *wizard, page int) (string, *markup) {
	t := func(key string, args ...any) string { return b.locale.text(lang, key, args...) }
	text := t("wizard.select_time")
	if w.departureFallback {
		text += "\n\n" + t("wizard.time_partial")
	} else if w.departureError {
		text += "\n\n" + t("wizard.time_unavailable")
	} else if len(w.departures) == 0 {
		text += "\n\n" + t("wizard.time_empty")
	}
	rows := [][]button{{{t("wizard.time_any_btn"), "wiz_time:any"}}}
	pages := max(1, (len(w.departures)+7)/8)
	page = max(0, min(page, pages-1))
	for i := page * 8; i < min((page+1)*8, len(w.departures)); i++ {
		d := w.departures[i]
		rows = append(rows, []button{{t("wizard.time_ride_btn", "time", d.time, "number", d.number), d.callback()}})
	}
	if pages > 1 {
		var nav []button
		if page > 0 {
			nav = append(nav, button{t("button.prev"), fmt.Sprintf("page:wiz_time:%d", page-1)})
		}
		nav = append(nav, button{fmt.Sprintf("%d/%d", page+1, pages), "noop"})
		if page+1 < pages {
			nav = append(nav, button{t("button.next"), fmt.Sprintf("page:wiz_time:%d", page+1)})
		}
		rows = append(rows, nav)
	}
	if w.departureError || len(w.departures) == 0 {
		rows = append(rows, []button{{t("wizard.time_reload_btn"), "wiz_time:reload"}})
	}
	rows = append(rows, []button{{t("button.cancel"), "cancel"}})
	return text, &markup{Rows: rows}
}

func (b *bot) respond(ctx context.Context, id int64, messageID int, text string, keyboard *markup) error {
	out := outgoing{ChatID: id, MessageID: messageID, Text: text, ParseMode: "Markdown", Markup: keyboard}
	if messageID != 0 {
		return b.tg.edit(ctx, out)
	}
	return b.tg.send(ctx, out)
}

func (b *bot) className(lang, class string) string {
	if class == "Any" {
		return b.locale.text(lang, "searches.class_any")
	}
	return class
}

func (b *bot) departureName(lang string, c config) string {
	if c.DepartureTime == "" {
		return b.locale.text(lang, "searches.time_any")
	}
	if c.RideNumber == "" {
		return c.DepartureTime
	}
	return b.locale.text(lang, "wizard.time_ride_btn", "time", c.DepartureTime, "number", c.RideNumber)
}

func (b *bot) showHome(ctx context.Context, id int64, messageID int, lang string, page int) error {
	c, err := b.store.load(id)
	if err != nil {
		return err
	}
	// Paused searches have no worker to expire them, so also prune on navigation.
	for _, entry := range c.Searches {
		if entry.expired(b.now()) {
			if err := b.poller.remove(id, entry.ID); err != nil {
				return err
			}
		}
	}
	c, err = b.store.load(id)
	if err != nil {
		return err
	}
	t := func(key string, args ...any) string { return b.locale.text(lang, key, args...) }
	active := 0
	for _, entry := range c.Searches {
		if !entry.Paused {
			active++
		}
	}
	text := t("start.welcome") + "\n\n" + t("searches.title") + "\n"
	if active == 0 {
		text += t("searches.empty")
	} else {
		text += t("searches.active_count", "count", active)
	}
	if len(c.Searches) > 0 {
		text += "\n\n" + t("searches.select")
	}
	const pageSize = 8
	pages := max(1, (len(c.Searches)+pageSize-1)/pageSize)
	page = max(0, min(page, pages-1))
	rows := [][]button{}
	for _, entry := range c.Searches[min(page*pageSize, len(c.Searches)):min((page+1)*pageSize, len(c.Searches))] {
		status := "🟢"
		if entry.Paused {
			status = "⏸"
		}
		label := fmt.Sprintf("%s %s → %s · %s · %s", status, b.locale.stationName(entry.FromCode, lang, entry.From), b.locale.stationName(entry.ToCode, lang, entry.To), entry.Date, b.className(lang, entry.Class))
		if entry.DepartureTime != "" {
			label += " · " + b.departureName(lang, entry.config)
		}
		rows = append(rows, []button{{label, "search:view:" + entry.ID}})
	}
	if pages > 1 {
		var nav []button
		if page > 0 {
			nav = append(nav, button{t("button.prev"), fmt.Sprintf("search:page:%d", page-1)})
		}
		nav = append(nav, button{fmt.Sprintf("%d/%d", page+1, pages), "noop"})
		if page+1 < pages {
			nav = append(nav, button{t("button.next"), fmt.Sprintf("search:page:%d", page+1)})
		}
		rows = append(rows, nav)
	}
	rows = append(rows, []button{{t("searches.add"), "search:add"}})
	return b.respond(ctx, id, messageID, text, &markup{Rows: rows})
}

func (b *bot) showSearch(ctx context.Context, id int64, messageID int, lang, searchID string, confirmDelete bool) error {
	c, err := b.store.load(id)
	if err != nil {
		return err
	}
	entry, exists := c.find(searchID)
	if !exists {
		return b.showHome(ctx, id, messageID, lang, 0)
	}
	if entry.expired(b.now()) {
		if err := b.poller.remove(id, searchID); err != nil {
			return err
		}
		return b.showHome(ctx, id, messageID, lang, 0)
	}
	t := func(key string, args ...any) string { return b.locale.text(lang, key, args...) }
	text := t("searches.details", "from_name", markdown(b.locale.stationName(entry.FromCode, lang, entry.From)), "to_name", markdown(b.locale.stationName(entry.ToCode, lang, entry.To)), "date", entry.Date, "class_name", b.className(lang, entry.Class))
	text += "\n" + t("searches.departure", "time", markdown(b.departureName(lang, entry.config)))
	status, action, label := "searches.active", "pause", "searches.pause"
	if entry.Paused {
		status, action, label = "searches.paused", "resume", "searches.resume"
	}
	text += "\n\n" + t(status)
	rows := [][]button{
		{{t(label), "search:" + action + ":" + searchID}},
		{{t("searches.delete"), "search:delete:" + searchID}},
		{{t("searches.back"), "search:home"}},
	}
	if confirmDelete {
		text += "\n\n" + t("searches.delete_confirm")
		rows = [][]button{
			{{t("searches.delete_yes"), "search:remove:" + searchID}},
			{{t("searches.delete_no"), "search:view:" + searchID}},
		}
	}
	return b.respond(ctx, id, messageID, text, &markup{Rows: rows})
}

func (b *bot) setLanguage(id int64, code string) (string, error) {
	code = strings.ToLower(strings.Split(code, "-")[0])
	if code != "ru" && code != "en" {
		return "", errors.New("unsupported language")
	}
	if err := b.store.update(id, func(c *chatConfig) error { c.Language = code; return nil }); err != nil {
		return "", err
	}
	b.languages[id] = code
	return code, nil
}

func (b *bot) handle(ctx context.Context, u update) error {
	m := u.Message
	actor := user{}
	if m != nil {
		actor = m.From
	}
	if u.Callback != nil {
		m = u.Callback.Message
		actor = u.Callback.From
		if err := b.tg.call(ctx, "answerCallbackQuery", map[string]string{"callback_query_id": u.Callback.ID}, nil); err != nil {
			slog.Warn("Cannot acknowledge callback", "error", err)
		}
	}
	if m == nil {
		return nil
	}
	id := m.Chat.ID
	key := [2]int64{id, actor.ID}
	c, loadErr := b.store.load(id)
	lang := b.languages[id]
	if lang == "" {
		if c.Language != "" {
			lang = language(c.Language)
		} else {
			lang = language(actor.Language)
		}
	}
	b.languages[id] = lang
	t := func(k string, args ...any) string { return b.locale.text(lang, k, args...) }
	send := func(text string, k *markup) error {
		return b.tg.send(ctx, outgoing{ChatID: id, Text: text, ParseMode: "Markdown", Markup: k})
	}
	edit := func(text string, k *markup) error {
		return b.tg.edit(ctx, outgoing{ChatID: id, MessageID: m.ID, Text: text, ParseMode: "Markdown", Markup: k})
	}
	if u.Callback == nil {
		args := strings.Fields(m.Text)
		command := ""
		if len(args) > 0 && strings.HasPrefix(args[0], "/") {
			command = args[0]
			if name, mention, ok := strings.Cut(command, "@"); ok {
				if !strings.EqualFold(mention, b.tg.username) {
					return nil
				}
				command = name
			}
		}
		if command == "/stop" {
			b.poller.stopChat(id)
			if err := b.store.clearMonitor(id); err != nil {
				return err
			}
			for k := range b.wizards {
				if k[0] == id {
					delete(b.wizards, k)
				}
			}
			if err := send(t("stop.stopped"), nil); err != nil {
				return err
			}
			return b.showHome(ctx, id, 0, lang, 0)
		}
		if loadErr != nil {
			return loadErr
		}
		if c.Language == "" {
			if err := b.store.update(id, func(c *chatConfig) error { c.Language = lang; return nil }); err != nil {
				return err
			}
		}
		switch command {
		case "/start":
			delete(b.wizards, key)
			return b.showHome(ctx, id, 0, lang, 0)
		case "/lang":
			if len(args) != 2 {
				return send(t("lang.select"), b.keyboard(lang, "lang"))
			}
			code := strings.ToLower(strings.Split(args[1], "-")[0])
			if code != "en" && code != "ru" {
				return b.tg.send(ctx, outgoing{ChatID: id, Text: fmt.Sprintf("❌ Unsupported language '%s'.\nSupported: en, ru", args[1])})
			}
			newLang, err := b.setLanguage(id, args[1])
			if err != nil {
				return err
			}
			name := "English"
			if newLang == "ru" {
				name = "Русский"
			}
			return send(b.locale.text(newLang, "lang.set_success", "language", name), nil)
		}
		w := b.wizards[key]
		if command == "" && w != nil && w.step == "custom" {
			date := strings.TrimSpace(m.Text)
			if !validDate(date) {
				return send(t("wizard.date_invalid"), nil)
			}
			if date < b.now().In(b.zone).Format("2006-01-02") {
				return send(t("wizard.date_past"), nil)
			}
			w.draft.Date = date
			w.step = "from"
			if err := send(t("wizard.date_set", "date", date), nil); err != nil {
				return err
			}
			return send(t("wizard.select_departure"), b.keyboard(lang, "wiz_from"))
		}
		if m.Text != "" {
			return send(t("fallback.unrecognised"), nil)
		}
		return nil
	}
	if loadErr != nil {
		return loadErr
	}
	data := u.Callback.Data
	if data == "search:home" {
		delete(b.wizards, key)
		return b.showHome(ctx, id, m.ID, lang, 0)
	}
	if data == "search:add" {
		if c.Language == "" {
			if _, err := b.setLanguage(id, lang); err != nil {
				return err
			}
		}
		b.wizards[key] = &wizard{step: "date"}
		return edit(t("wizard.date_select"), b.keyboard(lang, "date"))
	}
	if strings.HasPrefix(data, "search:page:") {
		page, err := strconv.Atoi(strings.TrimPrefix(data, "search:page:"))
		if err != nil {
			return nil
		}
		return b.showHome(ctx, id, m.ID, lang, page)
	}
	if strings.HasPrefix(data, "search:") {
		parts := strings.Split(data, ":")
		if len(parts) != 3 || !validSearchID(parts[2]) {
			return nil
		}
		action, searchID := parts[1], parts[2]
		switch action {
		case "view", "delete":
			delete(b.wizards, key)
			return b.showSearch(ctx, id, m.ID, lang, searchID, action == "delete")
		case "pause", "resume":
			entry, exists := c.find(searchID)
			if !exists || entry.expired(b.now()) {
				return b.showHome(ctx, id, m.ID, lang, 0)
			}
			if entry.Paused != (action == "pause") {
				if err := b.poller.setPaused(id, searchID, action == "pause"); err != nil && !errors.Is(err, errSearchNotFound) {
					return err
				}
			}
			return b.showSearch(ctx, id, m.ID, lang, searchID, false)
		case "remove":
			if err := b.poller.remove(id, searchID); err != nil {
				return err
			}
			return b.showHome(ctx, id, m.ID, lang, 0)
		}
		return nil
	}
	if strings.HasPrefix(data, "lang_set:") {
		code := strings.TrimPrefix(data, "lang_set:")
		if code != "en" && code != "ru" {
			return nil
		}
		newLang, err := b.setLanguage(id, code)
		if err != nil {
			return err
		}
		name := "English"
		if newLang == "ru" {
			name = "Русский"
		}
		if w := b.wizards[key]; w != nil && w.step == "time" {
			text, keyboard := b.departureChoices(newLang, w, 0)
			return edit(b.locale.text(newLang, "lang.set_success", "language", name)+"\n\n"+text, keyboard)
		}
		return edit(b.locale.text(newLang, "lang.set_success", "language", name), nil)
	}
	w := b.wizards[key]
	if w == nil {
		return nil
	}
	if data == "cancel" {
		delete(b.wizards, key)
		return b.showHome(ctx, id, m.ID, lang, 0)
	}
	if data == "noop" {
		return nil
	}
	if w.step == "date" && strings.HasPrefix(data, "wiz_date:") {
		choice := strings.TrimPrefix(data, "wiz_date:")
		if choice == "custom" {
			w.step = "custom"
			return edit(t("wizard.date_custom_prompt"), &markup{Rows: [][]button{{{t("button.cancel"), "cancel"}}}})
		}
		if choice != "today" && choice != "tomorrow" {
			return nil
		}
		date := b.now().In(b.zone)
		if choice == "tomorrow" {
			date = date.AddDate(0, 0, 1)
		}
		w.draft.Date = date.Format("2006-01-02")
		w.step = "from"
		if err := edit(t("wizard.date_"+choice+"_set", "date", w.draft.Date), nil); err != nil {
			return err
		}
		return send(t("wizard.select_departure"), b.keyboard(lang, "wiz_from"))
	}
	if w.step == "from" || w.step == "to" {
		action := "wiz_" + w.step
		prompt := "wizard.select_departure"
		excludedCode := ""
		if w.step == "to" {
			prompt = "wizard.select_arrival"
			excludedCode = w.draft.FromCode
		}
		if strings.HasPrefix(data, "page:"+action+":") {
			page, err := strconv.Atoi(strings.TrimPrefix(data, "page:"+action+":"))
			if err != nil {
				return nil
			}
			return b.tg.call(ctx, "editMessageReplyMarkup", map[string]any{"chat_id": id, "message_id": m.ID, "reply_markup": b.stationKeyboard(lang, action, page, excludedCode)}, nil)
		}
		if !strings.HasPrefix(data, action+":") {
			return nil
		}
		code := strings.TrimPrefix(data, action+":")
		if code == "all" {
			return edit(t(prompt), b.stationKeyboard(lang, action, 0, excludedCode))
		}
		s, ok := b.index[code]
		if !ok {
			return edit(t("wizard.station_not_found"), b.quickStationKeyboard(lang, action, excludedCode))
		}
		if w.step == "from" {
			w.draft.FromCode = code
			w.draft.From = s.Name
			w.step = "to"
			return edit(t("wizard.from_selected", "station_name", markdown(b.locale.stationName(code, lang, s.Name))), b.quickStationKeyboard(lang, "wiz_to", code))
		}
		if w.draft.FromCode == code {
			return edit(t("wizard.station_same"), b.quickStationKeyboard(lang, "wiz_to", excludedCode))
		}
		w.draft.ToCode = code
		w.draft.To = s.Name
		w.step = "time"
		if err := edit(t("wizard.route_saved", "from_name", markdown(b.locale.stationName(w.draft.FromCode, lang, w.draft.From)), "to_name", markdown(b.locale.stationName(code, lang, s.Name))), nil); err != nil {
			return err
		}
		b.loadDepartures(ctx, w)
		text, keyboard := b.departureChoices(lang, w, 0)
		return send(text, keyboard)
	}
	if w.step == "time" {
		if strings.HasPrefix(data, "page:wiz_time:") {
			page, err := strconv.Atoi(strings.TrimPrefix(data, "page:wiz_time:"))
			if err != nil {
				return nil
			}
			text, keyboard := b.departureChoices(lang, w, page)
			return edit(text, keyboard)
		}
		if !strings.HasPrefix(data, "wiz_time:") {
			return nil
		}
		choice := strings.TrimPrefix(data, "wiz_time:")
		if choice == "reload" {
			b.loadDepartures(ctx, w)
			text, keyboard := b.departureChoices(lang, w, 0)
			return edit(text, keyboard)
		}
		if choice == "any" {
			w.draft.DepartureTime, w.draft.RideNumber = "", ""
		} else {
			selected := false
			for _, d := range w.departures {
				if d.callback() == data {
					w.draft.DepartureTime, w.draft.RideNumber = d.time, d.number
					selected = true
					break
				}
			}
			if !selected {
				return nil
			}
		}
		w.step = "class"
		return edit(t("wizard.time_set", "time", markdown(b.departureName(lang, w.draft)))+"\n\n"+t("wizard.select_class"), b.keyboard(lang, "class"))
	}
	if w.step == "class" && strings.HasPrefix(data, "wiz_class:") {
		class := strings.TrimPrefix(data, "wiz_class:")
		if _, ok := classFilters[class]; !ok && class != "Any" {
			return nil
		}
		w.draft.Class = class
		if !w.draft.complete() {
			return errors.New("incomplete wizard configuration")
		}
		if w.draft.expired(b.now()) {
			w.step = "date"
			return edit(t("wizard.date_past"), b.keyboard(lang, "date"))
		}
		searchID, err := b.store.addSearch(id, w.draft)
		if err != nil {
			return err
		}
		delete(b.wizards, key)
		b.poller.start(id, searchID)
		if err := edit(t("wizard.class_set", "class_name", class), nil); err != nil {
			return err
		}
		return b.showHome(ctx, id, 0, lang, 0)
	}
	return nil
}

func markdown(s string) string {
	return strings.NewReplacer("_", "\\_", "*", "\\*", "`", "\\`", "[", "\\[").Replace(s)
}

func (b *bot) run(ctx context.Context) error {
	offset := int64(0)
	backoff := time.Second
	for ctx.Err() == nil {
		var updates []update
		err := b.tg.call(ctx, "getUpdates", map[string]any{"offset": offset, "timeout": 30, "allowed_updates": []string{"message", "callback_query"}}, &updates)
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			var te *telegramError
			if errors.As(err, &te) && (te.Code == 401 || te.Code == 409) {
				return err
			}
			delay := backoff
			if te != nil && te.RetryAfter > 0 {
				delay = time.Duration(te.RetryAfter) * time.Second
			}
			slog.Warn("Telegram polling failed; retrying", "error", err, "delay", delay)
			if !waitContext(ctx, delay) {
				return nil
			}
			backoff = min(backoff*2, 30*time.Second)
			continue
		}
		backoff = time.Second
		for _, u := range updates {
			if ctx.Err() != nil {
				return nil
			}
			if u.ID < offset {
				continue
			}
			if err := b.handle(ctx, u); err != nil {
				slog.Error("Cannot process update", "update_id", u.ID, "error", err)
				m := u.Message
				if u.Callback != nil {
					m = u.Callback.Message
				}
				if m != nil && ctx.Err() == nil {
					lang := b.languages[m.Chat.ID]
					if err := b.tg.send(ctx, outgoing{ChatID: m.Chat.ID, Text: b.locale.text(lang, "error.retry")}); err != nil {
						slog.Warn("Cannot send error response", "error", err)
					}
				}
			}
			offset = u.ID + 1
		}
	}
	return nil
}
