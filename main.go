package main

import (
	"bufio"
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
)

var version = "dev"

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// loadDotEnv supports the simple KEY=value files used by this project. Actual
// environment variables, including explicitly empty ones, always take precedence.
func loadDotEnv(path string) error {
	f, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimPrefix(line, "export ")
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			return errors.New("invalid .env assignment")
		}
		key = strings.TrimSpace(key)
		value = strings.TrimSpace(value)
		if strings.HasPrefix(value, "\"") {
			// Strip trailing comments after the closing quote, respecting escapes.
			end := 1
			for end < len(value) {
				if value[end] == '\\' {
					end += 2
					continue
				}
				if value[end] == '"' {
					break
				}
				end++
			}
			if end >= len(value) {
				return errors.New("unterminated .env quote")
			}
			value, err = strconv.Unquote(value[:end+1])
			if err != nil {
				return errors.New("invalid .env quoted value")
			}
		} else if strings.HasPrefix(value, "'") {
			end := strings.Index(value[1:], "'")
			if end < 0 {
				return errors.New("unterminated .env quote")
			}
			value = value[1 : end+1]
		} else {
			if i := strings.Index(value, " #"); i >= 0 {
				value = strings.TrimSpace(value[:i])
			}
		}
		if _, exists := os.LookupEnv(key); !exists {
			if err := os.Setenv(key, value); err != nil {
				return err
			}
		}
	}
	return scanner.Err()
}

func run() error {
	showVersion := flag.Bool("version", false, "Print version and exit")
	check := flag.Bool("check", false, "Check embedded resources and data directory without network access")
	flag.Parse()
	if *showVersion {
		if data, err := os.ReadFile("version.txt"); err == nil {
			version = strings.TrimSpace(string(data))
		}
		fmt.Println(version)
		return nil
	}
	if err := loadDotEnv(".env"); err != nil {
		return err
	}
	store := &storage{dir: env("DATA_DIR", "data")}
	if err := store.preflight(); err != nil {
		return err
	}
	locale, err := newCatalog()
	if err != nil {
		return err
	}
	if *check {
		fmt.Println("Storage and embedded resources OK")
		return nil
	}
	token := os.Getenv("BOT_TOKEN")
	if token == "" {
		return errors.New("BOT_TOKEN not set in environment or .env file")
	}
	if source := strings.ToLower(strings.TrimSpace(env("TICKET_SOURCE", "trege"))); source != "trege" {
		return fmt.Errorf("unknown TICKET_SOURCE %q; supported: trege", source)
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.MaxIdleConnsPerHost = 16
	defer transport.CloseIdleConnections()
	api := &railwayAPI{base: env("TRE_API_BASE", defaultRailwayBase), key: env("TRE_API_KEY", defaultRailwayKey), client: &http.Client{Transport: transport, Timeout: 15 * time.Second}}
	tg := &telegram{base: env("TELEGRAM_API_BASE", "https://api.telegram.org"), token: token, client: &http.Client{Transport: transport, Timeout: 40 * time.Second}}
	if err := tg.initialize(ctx); err != nil {
		return err
	}
	p := newPoller(ctx, store, api, tg, locale)
	defer p.close()
	b := newBot(tg, store, p, locale)
	b.loadStations(ctx, api)
	restored, err := p.restore()
	if err != nil {
		return err
	}
	slog.Info("Ticket monitor started", "version", version, "restored_chats", restored, "stations", len(b.stations))
	return b.run(ctx)
}

func main() {
	if err := run(); err != nil {
		slog.Error("Ticket monitor stopped", "error", err)
		os.Exit(1)
	}
}
