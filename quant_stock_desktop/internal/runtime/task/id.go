package task

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"strings"
	"time"
)

func NewID() string {
	buffer := make([]byte, 4)
	_, _ = rand.Read(buffer)
	return fmt.Sprintf("task_%s_%s", time.Now().Format("20060102_150405"), hex.EncodeToString(buffer))
}

func NewRunID(req CreateRequest) string {
	start := valueString(req.Params["start_date"], "start")
	end := valueString(req.Params["end_date"], "end")
	strategies := strategyTag(firstNonNil(req.Params["strategies_filter"], req.Params["strategies"]))
	prefix := "tm"
	if req.TaskType == TypeStrategyEvaluation {
		prefix = "se"
	} else if req.TaskType == TypePortfolioOptimization {
		prefix = "po"
	} else if req.TaskType == TypeWalkForwardEvaluation {
		prefix = "wf"
	} else if req.TaskType == TypeParameterExperiment {
		prefix = "px"
	} else if req.TaskType == TypeFactorResearch {
		prefix = "fr"
	}
	return fmt.Sprintf("%s_%s_%s_%s_%s", prefix, strategies, start, end, time.Now().Format("150405"))
}

func firstNonNil(values ...any) any {
	for _, value := range values {
		if value != nil {
			return value
		}
	}
	return nil
}

func valueString(value any, fallback string) string {
	if text, ok := value.(string); ok && text != "" {
		return text
	}
	return fallback
}

func strategyTag(value any) string {
	items, ok := value.([]any)
	if !ok || len(items) == 0 {
		return "all"
	}
	if len(items) == 1 {
		if text, ok := items[0].(string); ok && text != "" {
			return sanitize(text)
		}
	}
	return fmt.Sprintf("multi%d", len(items))
}

func sanitize(value string) string {
	value = strings.TrimSpace(value)
	value = strings.ReplaceAll(value, " ", "_")
	value = strings.ReplaceAll(value, "/", "_")
	return value
}
