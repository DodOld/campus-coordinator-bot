package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"
)

type scheduleResult struct {
	Message string `json:"message,omitempty"`
	Error   string `json:"error,omitempty"`
}

func main() {
	jsonMode := flag.Bool("json", false, "write JSON result")
	dateText := flag.String("date", "", "target date in YYYY-MM-DD")
	flag.Parse()
	if !*jsonMode {
		fmt.Fprintln(os.Stderr, "only --json mode is supported")
		os.Exit(2)
	}

	targetDate, err := parseTargetDate(*dateText)
	if err != nil {
		writeResult(scheduleResult{Error: "invalid_date"}, 2)
		return
	}
	icsPath, cleanup, err := getIcsSchedule()
	if err != nil {
		writeResult(scheduleResult{Error: "schedule_unavailable"}, 1)
		return
	}
	defer cleanup()
	message, err := parseIcs(icsPath, targetDate)
	if err != nil {
		writeResult(scheduleResult{Error: "schedule_unavailable"}, 1)
		return
	}
	writeResult(scheduleResult{Message: message}, 0)
}

func parseTargetDate(value string) (time.Time, error) {
	if value == "" {
		now := time.Now().In(tomskLocation)
		return time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, tomskLocation), nil
	}
	parsed, err := time.ParseInLocation("2006-01-02", value, tomskLocation)
	if err != nil {
		return time.Time{}, err
	}
	return parsed, nil
}

func writeResult(result scheduleResult, exitCode int) {
	encoded, _ := json.Marshal(result)
	fmt.Println(string(encoded))
	if exitCode != 0 {
		os.Exit(exitCode)
	}
}
