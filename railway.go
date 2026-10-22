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
	"time"
)

const defaultRailwayBase = "https://gateway.tkt.ge/integrations/api/GeorgianRailway"

// Public client key shipped by the tre.ge website; operators may override it.
const defaultRailwayKey = "7d8d34d1-e9af-4897-9f0f-5c36c179be77"

var classNames = map[int]string{1: "I Class", 2: "II Class", 5: "Business"}
var classFilters = map[string]int{"I": 1, "II": 2, "Business": 5}

// scalar accepts the numeric and string identifiers returned by the API.
type scalar string

func (s *scalar) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		*s = ""
		return nil
	}
	var text string
	if len(data) > 0 && data[0] == '"' {
		if err := json.Unmarshal(data, &text); err != nil {
			return err
		}
	} else {
		var n json.Number
		if err := json.Unmarshal(data, &n); err != nil {
			return err
		}
		text = n.String()
	}
	*s = scalar(text)
	return nil
}

type station struct {
	Code    scalar `json:"code"`
	Name    string `json:"stationName"`
	Popular bool   `json:"isPopular"`
}
type seatClass struct {
	ID    int         `json:"seatClassId"`
	Seats int         `json:"availableNumberOfSeats"`
	Price json.Number `json:"moneyAmount"`
}
type ride struct {
	Number   scalar      `json:"rideNumber"`
	Start    string      `json:"rideStartDate"`
	End      string      `json:"rideEndDate"`
	Duration string      `json:"rideDuration"`
	Classes  []seatClass `json:"availableSeatsClasses"`
}
type railwayAPI struct {
	base   string
	key    string
	client *http.Client
}

func (a *railwayAPI) get(ctx context.Context, path string, query url.Values, dst any) error {
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	query.Set("api_key", a.key)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(a.base, "/")+path+"?"+query.Encode(), nil)
	if err != nil {
		return errors.New("invalid railway API URL")
	}
	resp, err := a.client.Do(req)
	if err != nil {
		return errors.New("railway API request failed")
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("railway API: HTTP %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if err != nil {
		return err
	}
	if string(data) == "null" {
		return errors.New("railway API returned null")
	}
	return json.Unmarshal(data, dst)
}

func (a *railwayAPI) stations(ctx context.Context) ([]station, error) {
	var stations []station
	err := a.get(ctx, "/Dictionaries/civil-stations", url.Values{}, &stations)
	return stations, err
}

func (a *railwayAPI) search(ctx context.Context, c config) ([]ride, error) {
	var response struct {
		Rides *[]ride `json:"departureAvailableRides"`
	}
	err := a.get(ctx, "/Availability/available-rides", url.Values{
		"passengersNumbers": {"1"}, "departureDateFrom": {c.Date + "T00:00:00.000Z"},
		"startStationCode": {c.FromCode}, "endStationCode": {c.ToCode},
		"returnWay": {"false"}, "disability": {"false"},
	}, &response)
	if err != nil {
		return nil, err
	}
	if response.Rides == nil {
		return nil, errors.New("railway API response has no departureAvailableRides array")
	}
	return *response.Rides, nil
}

func purchaseURL(c config) string {
	date, err := time.Parse("2006-01-02", c.Date)
	if err != nil {
		return ""
	}
	return "https://tre.ge/en/search?leavingPlace=" + url.QueryEscape(c.FromCode) + "&enteringPlace=" + url.QueryEscape(c.ToCode) + "&leaveDate=" + date.Format("02.01.2006") + "&passengerCount=1&wcuCount=0&depVT=railway"
}

func formatTime(value string) string {
	if value == "" {
		return "??:??"
	}
	if _, after, ok := strings.Cut(value, "T"); ok && len(after) >= 5 {
		return after[:5]
	}
	return value
}

func validDate(value string) bool {
	_, err := time.Parse("2006-01-02", value)
	return len(value) == 10 && err == nil
}
