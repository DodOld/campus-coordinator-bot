package main

import (
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	ics "github.com/arran4/golang-ical"
)

var tomskLocation = time.FixedZone("Asia/Tomsk", 7*60*60)

type lesson struct {
	start    time.Time
	end      time.Time
	summary  string
	location string
	teacher  string
}

func parseIcs(filename string, targetDate time.Time) (string, error) {
	file, err := os.Open(filename)
	if err != nil {
		return "", err
	}
	defer file.Close()
	calendar, err := ics.ParseCalendar(file)
	if err != nil {
		return "", err
	}
	target := targetDate.In(tomskLocation).Format("2006-01-02")
	lessons := make([]lesson, 0)
	for _, event := range calendar.Events() {
		start, err := event.GetStartAt()
		if err != nil || start.In(tomskLocation).Format("2006-01-02") != target {
			continue
		}
		end, err := event.GetEndAt()
		if err != nil {
			end = start
		}
		lessons = append(lessons, lesson{
			start: start.In(tomskLocation), end: end.In(tomskLocation),
			summary:  propertyValue(event, ics.ComponentPropertySummary),
			location: propertyValue(event, ics.ComponentPropertyLocation),
			teacher:  extractTeacher(propertyValue(event, ics.ComponentPropertyDescription)),
		})
	}
	if len(lessons) == 0 {
		return "Занятий нет.", nil
	}
	sort.Slice(lessons, func(i, j int) bool { return lessons[i].start.Before(lessons[j].start) })
	var result strings.Builder
	for _, entry := range lessons {
		fmt.Fprintf(&result, "%s–%s\n%s\n", entry.start.Format("15:04"), entry.end.Format("15:04"), entry.summary)
		if entry.teacher != "" {
			fmt.Fprintf(&result, "%s\n", entry.teacher)
		}
		if entry.location != "" {
			fmt.Fprintf(&result, "%s\n", entry.location)
		}
		result.WriteString("\n")
	}
	return strings.TrimSpace(result.String()), nil
}

func propertyValue(event *ics.VEvent, property ics.ComponentProperty) string {
	if value := event.GetProperty(property); value != nil {
		return strings.ReplaceAll(value.Value, "\\,", ",")
	}
	return ""
}

func extractTeacher(description string) string {
	lines := strings.Split(strings.ReplaceAll(description, "\\n", "\n"), "\n")
	if len(lines) >= 3 {
		return strings.TrimSpace(lines[2])
	}
	return ""
}
