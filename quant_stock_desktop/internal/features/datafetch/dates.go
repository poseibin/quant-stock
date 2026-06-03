package datafetch

import (
	"fmt"
	"time"
)

// shiftDateImpl 把 yyyymmdd 偏移 delta 天后返回。
func shiftDateImpl(s string, delta int) (string, error) {
	t, err := time.Parse("20060102", s)
	if err != nil {
		return "", fmt.Errorf("invalid date %q: %w", s, err)
	}
	return t.AddDate(0, 0, delta).Format("20060102"), nil
}
