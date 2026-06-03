package datafetch

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"
)

type TushareError struct {
	Msg  string
	Hard bool
}

func (e *TushareError) Error() string { return e.Msg }

func IsHardLimit(err error) bool {
	var te *TushareError
	if errors.As(err, &te) {
		return te.Hard
	}
	return false
}

type TushareRow = []any

type TushareResponse struct {
	Fields  []string     `json:"fields"`
	Items   []TushareRow `json:"items"`
	HasMore bool         `json:"has_more"`
}

type tushareEnvelope struct {
	RequestID string           `json:"request_id"`
	Code      int              `json:"code"`
	Msg       string           `json:"msg"`
	Data      *TushareResponse `json:"data"`
}

type TushareClient struct {
	token    string
	endpoint string
	httpc    *http.Client

	mu       sync.Mutex
	lastCall map[string]time.Time
	history  []time.Time
}

func NewTushareClient(token string) *TushareClient {
	return &TushareClient{
		token:    strings.TrimSpace(token),
		endpoint: tushareDefaultEndpoint,
		httpc:    &http.Client{Timeout: 60 * time.Second},
		lastCall: make(map[string]time.Time),
	}
}

func (c *TushareClient) throttle(api string) {
	c.mu.Lock()
	defer c.mu.Unlock()

	now := time.Now()
	cutoff := now.Add(-tushareWindow)
	pruned := c.history[:0]
	for _, t := range c.history {
		if t.After(cutoff) {
			pruned = append(pruned, t)
		}
	}
	c.history = pruned

	if len(c.history) >= tushareCallsPerMinute {
		wait := tushareWindow - now.Sub(c.history[0]) + 500*time.Millisecond
		if wait > 0 {
			c.mu.Unlock()
			time.Sleep(wait)
			c.mu.Lock()
			now = time.Now()
		}
	}

	interval, ok := tushareApiInterval[api]
	if !ok {
		interval = tushareDefaultInterval
	}
	if last, ok := c.lastCall[api]; ok {
		gap := now.Sub(last)
		if gap < interval {
			wait := interval - gap
			c.mu.Unlock()
			time.Sleep(wait)
			c.mu.Lock()
			now = time.Now()
		}
	}

	c.lastCall[api] = now
	c.history = append(c.history, now)
}

func (c *TushareClient) Call(ctx context.Context, api string, params map[string]any, fields string) (*TushareResponse, error) {
	if c.token == "" {
		return nil, errors.New("tushare token is empty")
	}
	c.throttle(api)

	body := map[string]any{
		"api_name": api,
		"token":    c.token,
		"params":   params,
		"fields":   fields,
	}
	payload, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}

	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint, bytes.NewReader(payload))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")

		resp, err := c.httpc.Do(req)
		if err != nil {
			lastErr = err
			time.Sleep(time.Duration(2<<attempt) * time.Second)
			continue
		}
		data, err := io.ReadAll(resp.Body)
		_ = resp.Body.Close()
		if err != nil {
			lastErr = err
			time.Sleep(time.Duration(2<<attempt) * time.Second)
			continue
		}
		if resp.StatusCode >= 500 {
			lastErr = fmt.Errorf("tushare http %d: %s", resp.StatusCode, string(data))
			time.Sleep(time.Duration(2<<attempt) * time.Second)
			continue
		}
		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("tushare http %d: %s", resp.StatusCode, string(data))
		}

		var env tushareEnvelope
		if err := json.Unmarshal(data, &env); err != nil {
			return nil, fmt.Errorf("tushare decode: %w", err)
		}
		if env.Code != 0 {
			if isRateLimitMessage(env.Msg) {
				return nil, &TushareError{Msg: env.Msg, Hard: true}
			}
			return nil, &TushareError{Msg: env.Msg}
		}
		if env.Data == nil {
			return &TushareResponse{}, nil
		}
		return env.Data, nil
	}
	return nil, lastErr
}

func isRateLimitMessage(msg string) bool {
	if msg == "" {
		return false
	}
	keywords := []string{"每分钟", "每小时", "每秒", "频次", "访问限制", "频率超限", "limit", "too many", "rate"}
	lower := strings.ToLower(msg)
	for _, kw := range keywords {
		if strings.Contains(msg, kw) || strings.Contains(lower, kw) {
			return true
		}
	}
	return false
}
