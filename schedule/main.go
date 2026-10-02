package main

import (
	"fmt"
	"os"
	"log"
	"encoding/json"
)

type ScheduleResult struct {
	Message		string `json:"message"`
	FirstLesson string `json:"first_lesson,omitempty"`
	Error		string `json:"error,omitempty"`
}

func main() {
	jsonMode := false
	for _, arg := range os.Args[1:] {
		if arg == "--json" {
			jsonMode = true
		}
	}

	if jsonMode {
		runJSONMode()
		return
	}

	log.Println("script successful running")

	icsFile, err := GetIcsSchedule()
	if err != nil {
		log.Fatalf("error in downloading ics schedule: %v", err)
	}
	log.Printf("successful downloaded file: %s", icsFile)

	_, _, err = ParseIcs(icsFile)
	if err != nil {
		log.Fatalf("error parsing ics schedule: %v", err)
	}
}

func runJSONMode() {
	result := ScheduleResult{}

	icsFile, err := GetIcsSchedule()
	if err != nil {
		result.Error = fmt.Sprintf("download error: %v", err)
		b, _ := json.Marshal(result)
		fmt.Println(string(b))
		os.Exit(1)
	}

	msg, firstLesson, err := ParseIcs(icsFile)
	if err != nil {
		result.Error = fmt.Sprintf("parse error: %v", err)
		b, _ := json.Marshal(result)
		fmt.Println(string(b))
		os.Exit(1)
	}

	result.Message = msg
	result.FirstLesson = firstLesson
	b, _ := json.Marshal(result)
	fmt.Println(string(b))
}
