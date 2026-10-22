package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

const defaultTimetableBase = "https://api.tre.ge"

// These public client credentials are shipped by the tre.ge website. They grant
// anonymous access; no Telegram token or personal railway account is involved.
const timetableClientID = "RailwayWeb"
const defaultTimetableKey = "D265F2#sd58E"

type timetableSource interface {
	schedule(context.Context, config) ([]ride, error)
}

type timetableAPI struct {
	base    string
	key     string
	client  *http.Client
	mu      sync.Mutex
	token   string
	expires time.Time
}

// request never includes response bodies, credentials, or request URLs in errors.
func (a *timetableAPI) request(req *http.Request, dst any) (int, error) {
	resp, err := a.client.Do(req)
	if err != nil {
		if req.Context().Err() != nil {
			return 0, req.Context().Err()
		}
		return 0, errors.New("timetable API request failed")
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return resp.StatusCode, fmt.Errorf("timetable API: HTTP %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return resp.StatusCode, errors.New("cannot read timetable API response")
	}
	if err := json.Unmarshal(data, dst); err != nil {
		return resp.StatusCode, errors.New("invalid timetable API response")
	}
	return resp.StatusCode, nil
}

func (a *timetableAPI) accessToken(ctx context.Context) (string, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.token != "" && time.Now().Before(a.expires) {
		return a.token, nil
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(a.base, "/")+"/connect/token", strings.NewReader("grant_type=client_credentials"))
	if err != nil {
		return "", errors.New("invalid timetable API URL")
	}
	req.SetBasicAuth(timetableClientID, a.key)
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	var response struct {
		Token   string `json:"access_token"`
		Expires int64  `json:"expires_in"`
	}
	if _, err := a.request(req, &response); err != nil {
		return "", fmt.Errorf("timetable authentication: %w", err)
	}
	if response.Token == "" || response.Expires <= 0 {
		return "", errors.New("timetable authentication returned no valid token")
	}
	// Refresh at least daily even when the public service issues a long-lived
	// token. Keep it only in memory, and renew early or on an explicit HTTP 401.
	a.token = response.Token
	a.expires = time.Now().Add(time.Duration(min(response.Expires, 86400))*time.Second - time.Second)
	return a.token, nil
}

func (a *timetableAPI) invalidateToken(token string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.token == token {
		a.token = ""
	}
}

func (a *timetableAPI) schedule(ctx context.Context, c config) ([]ride, error) {
	if !validDate(c.Date) || !numericCode(c.FromCode) || !numericCode(c.ToCode) || c.FromCode == c.ToCode {
		return nil, errors.New("invalid timetable route or date")
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	query := url.Values{"Date": {c.Date}, "FromStation": {c.FromCode}, "ToStation": {c.ToCode}}
	var response struct {
		OK   bool `json:"ok"`
		Rows *[]struct {
			From      scalar `json:"fromStationNumber"`
			To        scalar `json:"toStationNumber"`
			Number    scalar `json:"trainNumber"`
			Start     string `json:"leavingDate"`
			End       string `json:"enteringDate"`
			Requested string `json:"requestDate"`
		} `json:"stationTable"`
	}
	for attempt := 0; attempt < 2; attempt++ {
		token, err := a.accessToken(ctx)
		if err != nil {
			return nil, err
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(a.base, "/")+"/v1/GeorgianRailway/stations/timetable?"+query.Encode(), nil)
		if err != nil {
			return nil, errors.New("invalid timetable API URL")
		}
		req.Header.Set("Authorization", "Bearer "+token)
		status, err := a.request(req, &response)
		if status == http.StatusUnauthorized {
			a.invalidateToken(token)
			if attempt == 0 {
				continue
			}
		}
		if err != nil {
			return nil, err
		}
		break
	}
	if !response.OK || response.Rows == nil {
		return nil, errors.New("timetable API returned no valid stationTable")
	}
	// The API returns historical captures of the same departure. Use the most
	// recent capture per train, rather than offering obsolete departure times.
	latest := make(map[scalar]string)
	var rides []ride
	indices := make(map[scalar]int)
	for _, row := range *response.Rows {
		date, _, _ := strings.Cut(row.Start, "T")
		if string(row.From) != c.FromCode || string(row.To) != c.ToCode || date != c.Date || row.Number == "" || !validTime(formatTime(row.Start)) {
			continue
		}
		r := ride{Number: row.Number, Start: row.Start, End: row.End}
		if i, exists := indices[row.Number]; exists {
			if row.Requested > latest[row.Number] {
				rides[i] = r
				latest[row.Number] = row.Requested
			}
			continue
		}
		indices[row.Number] = len(rides)
		latest[row.Number] = row.Requested
		rides = append(rides, r)
	}
	return rides, nil
}
