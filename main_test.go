package main

import (
	"flag"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"sync/atomic"
	"testing"
)

// Run startup in a child process to isolate flags, signals and environment.
// Accepted sources must reach Telegram initialization; unknown ones must fail
// before making a request. The fixture rejects initialization to end startup.
func TestStartupTicketSource(t *testing.T) {
	if os.Getenv("TICKET_MONITOR_STARTUP_TEST") == "1" {
		flag.CommandLine = flag.NewFlagSet("ticket-monitor", flag.ContinueOnError)
		os.Args = os.Args[:1]
		if err := run(); err != nil {
			fmt.Println(err)
			return
		}
		t.Fatal("startup unexpectedly succeeded")
	}

	for _, source := range []string{"", "trege", "tre.ge", " TREGE ", " TRE.GE ", "unknown", "https://tre.ge"} {
		t.Run(source, func(t *testing.T) {
			var requests atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				if r.URL.Path != "/bot123:dummy/getMe" {
					t.Error("unexpected startup request", r.URL.Path)
				}
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(http.StatusUnauthorized)
				fmt.Fprint(w, `{"ok":false,"error_code":401,"description":"startup fixture"}`)
			}))
			defer server.Close()
			dir := t.TempDir()
			child := exec.Command(os.Args[0], "-test.run=^TestStartupTicketSource$")
			child.Dir = dir
			child.Env = []string{
				"TICKET_MONITOR_STARTUP_TEST=1", "BOT_TOKEN=123:dummy",
				"DATA_DIR=" + dir, "TICKET_SOURCE=" + source,
				"TELEGRAM_API_BASE=" + server.URL, "TRE_API_BASE=" + server.URL,
			}
			output, err := child.CombinedOutput()
			if err != nil {
				t.Fatalf("startup child failed: %v\n%s", err, output)
			}
			wantError, wantRequests := "Telegram API 401: startup fixture", int32(1)
			if source == "unknown" || source == "https://tre.ge" {
				wantError, wantRequests = "unknown TICKET_SOURCE", 0
			}
			if !strings.Contains(string(output), wantError) || requests.Load() != wantRequests {
				t.Fatalf("startup: %s; requests: %d; want %q and %d requests", output, requests.Load(), wantError, wantRequests)
			}
		})
	}
}
