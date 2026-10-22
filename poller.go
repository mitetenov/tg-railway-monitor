package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"strings"
	"sync"
	"time"
)

type ticketSource interface {
	search(context.Context, config) ([]ride, error)
}
type messageSender interface {
	send(context.Context, outgoing) error
}
type pollTask struct {
	cancel context.CancelFunc
	done   chan struct{}
}

type taskKey struct {
	chatID   int64
	searchID string
}

var errMonitorExpired = errors.New("monitoring date has passed")
var errMonitorInactive = errors.New("search is paused or deleted")

type poller struct {
	ctx      context.Context
	store    *storage
	api      ticketSource
	sender   messageSender
	locale   *catalog
	interval time.Duration
	now      func() time.Time
	mu       sync.Mutex
	tasks    map[taskKey]pollTask
}

func newPoller(ctx context.Context, store *storage, api ticketSource, sender messageSender, locale *catalog) *poller {
	return &poller{ctx: ctx, store: store, api: api, sender: sender, locale: locale, interval: 60 * time.Second, now: time.Now, tasks: make(map[taskKey]pollTask)}
}

func (p *poller) stopLocked(key taskKey) {
	if task, ok := p.tasks[key]; ok {
		task.cancel()
		<-task.done
		delete(p.tasks, key)
	}
}
func (p *poller) stop(id int64, searchID string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.stopLocked(taskKey{id, searchID})
}

func (p *poller) stopChat(id int64) {
	p.mu.Lock()
	defer p.mu.Unlock()
	for key := range p.tasks {
		if key.chatID == id {
			p.stopLocked(key)
		}
	}
}

func (p *poller) start(id int64, searchID string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.startLocked(taskKey{id, searchID})
}

func (p *poller) startLocked(key taskKey) {
	p.stopLocked(key)
	ctx, cancel := context.WithCancel(p.ctx)
	task := pollTask{cancel: cancel, done: make(chan struct{})}
	p.tasks[key] = task
	go func() {
		defer func() {
			// Signal before taking the registry lock: stop waits while holding it.
			close(task.done)
			p.mu.Lock()
			defer p.mu.Unlock()
			if current, ok := p.tasks[key]; ok && current.done == task.done {
				delete(p.tasks, key)
			}
		}()
		for ctx.Err() == nil {
			err := p.check(ctx, key.chatID, key.searchID)
			if errors.Is(err, errMonitorExpired) || errors.Is(err, errMonitorInactive) {
				return
			}
			if err != nil && ctx.Err() == nil {
				slog.Warn("Ticket check failed; will retry", "chat_id", key.chatID, "search_id", key.searchID, "error", err)
			}
			if !waitContext(ctx, p.interval) {
				return
			}
		}
	}()
}

// setPaused waits for in-flight delivery before changing the persisted status.
// Keeping the snapshot suppresses unchanged tickets when the search resumes.
func (p *poller) setPaused(id int64, searchID string, paused bool) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	key := taskKey{id, searchID}
	p.stopLocked(key)
	if err := p.store.setPaused(id, searchID, paused); err != nil {
		p.restartLocked(key)
		return err
	}
	if !paused {
		p.startLocked(key)
	}
	return nil
}

func (p *poller) remove(id int64, searchID string) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	key := taskKey{id, searchID}
	p.stopLocked(key)
	if err := p.store.removeSearch(id, searchID); err != nil {
		p.restartLocked(key)
		return err
	}
	return nil
}

func (p *poller) restartLocked(key taskKey) {
	c, err := p.store.load(key.chatID)
	entry, exists := c.find(key.searchID)
	if err == nil && exists && !entry.Paused {
		p.startLocked(key)
	}
}

func (p *poller) close() {
	p.mu.Lock()
	defer p.mu.Unlock()
	for id := range p.tasks {
		p.stopLocked(id)
	}
}

func (p *poller) restore() (int, error) {
	ids, err := p.store.ids()
	if err != nil {
		return 0, err
	}
	count := 0
	for _, id := range ids {
		c, err := p.store.load(id)
		if err != nil {
			slog.Warn("Skipping unreadable configuration", "chat_id", id, "error", err)
			continue
		}
		for _, entry := range c.Searches {
			if entry.expired(p.now()) {
				if err := p.store.removeSearch(id, entry.ID); err != nil {
					slog.Warn("Cannot clear expired search", "chat_id", id, "search_id", entry.ID, "error", err)
				}
				continue
			}
			if !entry.Paused {
				p.start(id, entry.ID)
				count++
			}
		}
	}
	return count, nil
}

// notification compares authoritative successful results. Missing rides/classes
// reset the baseline, so tickets reappearing after a sell-out are announced.
func (p *poller) notification(c config, rides []ride, previous snapshot) (snapshot, string) {
	next := snapshot{Key: c.routeKey(), Rides: make(map[string]map[string]seatState)}
	if previous.Key != next.Key && !(c.DepartureTime == "" && previous.Key == c.legacyRouteKey()) {
		previous.Rides = nil
	}
	changed := false
	var blocks []string
	lang := language(c.Language)
	for _, r := range rides {
		if r.Number == "" || (c.DepartureTime != "" && formatTime(r.Start) != c.DepartureTime) || (c.RideNumber != "" && string(r.Number) != c.RideNumber) {
			continue
		}
		classes := make(map[string]seatState)
		var lines []string
		for _, cl := range r.Classes {
			if _, known := classNames[cl.ID]; !known {
				continue
			}
			if c.Class != "Any" && classFilters[c.Class] != cl.ID {
				continue
			}
			key := strconv.Itoa(cl.ID)
			price := cl.Price
			if price == "" {
				price = "0"
			}
			classes[key] = seatState{cl.Seats, price}
			if cl.Seats <= 0 {
				continue
			}
			old, known := previous.Rides[string(r.Number)][key]
			if !known || cl.Seats > old.Seats {
				changed = true
			}
			name := classNames[cl.ID]
			if name == "" {
				name = fmt.Sprintf("Class %d", cl.ID)
			}
			lines = append(lines, p.locale.text(lang, "poller.class_info", "class_name", name, "seats", cl.Seats, "price", price))
		}
		next.Rides[string(r.Number)] = classes
		if len(lines) == 0 {
			continue
		}
		duration := r.Duration
		if duration == "" {
			duration = "?"
		}
		header := p.locale.text(lang, "poller.ride", "ride_num", r.Number, "departure", formatTime(r.Start), "arrival", formatTime(r.End), "duration", duration)
		link := p.locale.text(lang, "poller.purchase_link", "url", purchaseURL(c))
		blocks = append(blocks, header+"\n"+link+"\n"+strings.Join(lines, "\n"))
	}
	if !changed {
		return next, ""
	}
	header := p.locale.text(lang, "poller.route_header", "from_name", markdown(p.locale.stationName(c.FromCode, lang, c.From)), "to_name", markdown(p.locale.stationName(c.ToCode, lang, c.To)))
	return next, header + "\n" + p.locale.text(lang, "poller.date", "date", c.Date) + "\n\n" + strings.Join(blocks, "\n\n")
}

func (p *poller) check(ctx context.Context, id int64, searchID string) error {
	chat, err := p.store.load(id)
	if err != nil {
		return err
	}
	entry, exists := chat.find(searchID)
	if !exists || entry.Paused {
		return errMonitorInactive
	}
	c := entry.config
	c.Language = chat.Language
	if c.expired(p.now()) {
		if err := p.store.removeSearch(id, searchID); err != nil {
			return err
		}
		return errMonitorExpired
	}
	rides, err := p.api.search(ctx, c)
	if err != nil {
		return err
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	// A request may straddle Georgian midnight.
	if c.expired(p.now()) {
		if err := p.store.removeSearch(id, searchID); err != nil {
			return err
		}
		return errMonitorExpired
	}
	state, text := p.notification(c, rides, p.store.loadState(id, searchID, c.routeKey()))
	if text != "" {
		// Commit the snapshot only after delivery. A failed send is retried
		// on the next check, rather than silently losing the notification.
		for _, chunk := range splitNotification(text) {
			if err := p.sender.send(ctx, outgoing{ChatID: id, Text: chunk, ParseMode: "Markdown", Markup: &markup{Rows: [][]button{{{p.locale.text(c.Language, "searches.open"), "search:view:" + searchID}}}}}); err != nil {
				return err
			}
		}
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if err := p.store.saveState(id, searchID, state); err != nil {
		slog.Warn("Cannot persist ticket snapshot", "chat_id", id, "search_id", searchID, "error", err)
	}
	return nil
}

// Split between complete ride blocks to keep Markdown links intact and stay
// below Telegram's 4096-character limit, including for large route results.
func splitNotification(text string) []string {
	var result []string
	current := ""
	for _, block := range strings.Split(text, "\n\n") {
		if current != "" && len([]rune(current))+len([]rune(block))+2 > 4000 {
			result = append(result, current)
			current = ""
		}
		if current != "" {
			current += "\n\n"
		}
		current += block
	}
	if current != "" {
		result = append(result, current)
	}
	return result
}
