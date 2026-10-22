package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type user struct {
	ID       int64  `json:"id"`
	Language string `json:"language_code"`
	Username string `json:"username"`
}
type message struct {
	ID   int `json:"message_id"`
	Chat struct {
		ID int64 `json:"id"`
	} `json:"chat"`
	From user   `json:"from"`
	Text string `json:"text"`
}
type callback struct {
	ID      string   `json:"id"`
	From    user     `json:"from"`
	Message *message `json:"message"`
	Data    string   `json:"data"`
}
type update struct {
	ID       int64     `json:"update_id"`
	Message  *message  `json:"message"`
	Callback *callback `json:"callback_query"`
}
type button struct {
	Text string `json:"text"`
	Data string `json:"callback_data"`
}
type markup struct {
	Rows [][]button `json:"inline_keyboard"`
}
type outgoing struct {
	ChatID    int64   `json:"chat_id"`
	MessageID int     `json:"message_id,omitempty"`
	Text      string  `json:"text"`
	ParseMode string  `json:"parse_mode,omitempty"`
	Markup    *markup `json:"reply_markup,omitempty"`
}

type telegramError struct {
	Code        int
	RetryAfter  int
	Description string
}

func (e *telegramError) Error() string {
	return fmt.Sprintf("Telegram API %d: %s", e.Code, e.Description)
}

type telegram struct {
	base     string
	token    string
	username string
	client   *http.Client
}

func (t *telegram) call(ctx context.Context, method string, params any, result any) error {
	body, err := json.Marshal(params)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(t.base, "/")+"/bot"+t.token+"/"+method, bytes.NewReader(body))
	if err != nil {
		return errors.New("invalid Telegram API URL")
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := t.client.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		// http.Client errors contain the full URL, including BOT_TOKEN.
		return errors.New("Telegram " + method + " transport failed")
	}
	defer resp.Body.Close()
	var envelope struct {
		OK          bool            `json:"ok"`
		Result      json.RawMessage `json:"result"`
		Code        int             `json:"error_code"`
		Description string          `json:"description"`
		Parameters  struct {
			RetryAfter int `json:"retry_after"`
		} `json:"parameters"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 8<<20)).Decode(&envelope); err != nil {
		return fmt.Errorf("telegram %s: invalid response (HTTP %d)", method, resp.StatusCode)
	}
	if !envelope.OK || resp.StatusCode != http.StatusOK {
		if envelope.Code == 0 {
			envelope.Code = resp.StatusCode
		}
		return &telegramError{envelope.Code, envelope.Parameters.RetryAfter, strings.ReplaceAll(envelope.Description, t.token, "[redacted]")}
	}
	if result != nil {
		return json.Unmarshal(envelope.Result, result)
	}
	return nil
}

func (t *telegram) send(ctx context.Context, out outgoing) error {
	return t.call(ctx, "sendMessage", out, nil)
}
func (t *telegram) edit(ctx context.Context, out outgoing) error {
	if out.Markup == nil {
		out.Markup = &markup{Rows: [][]button{}}
	}
	err := t.call(ctx, "editMessageText", out, nil)
	var apiError *telegramError
	if errors.As(err, &apiError) && apiError.Code == 400 && strings.Contains(apiError.Description, "message is not modified") {
		return nil
	}
	return err
}

func (t *telegram) initialize(ctx context.Context) error {
	var me user
	if err := t.call(ctx, "getMe", struct{}{}, &me); err != nil {
		return err
	}
	t.username = me.Username
	if err := t.call(ctx, "deleteWebhook", map[string]any{"drop_pending_updates": false}, nil); err != nil {
		return err
	}
	commands := []map[string]string{
		{"command": "start", "description": "Open searches and add a new search"},
		{"command": "stop", "description": "Stop and delete all searches"},
		{"command": "lang", "description": "Set interface language (en / ru)"},
	}
	return t.call(ctx, "setMyCommands", map[string]any{"commands": commands}, nil)
}

func waitContext(ctx context.Context, duration time.Duration) bool {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}
