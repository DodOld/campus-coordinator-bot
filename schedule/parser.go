package main

import(
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	ics "github.com/arran4/golang-ical"
)

type Lesson struct {
	Start 	 time.Time
	End 	 time.Time
	Summary  string
	Location string
	Teacher	 string
}

type TimeGroup struct {
	TimeRange string
	Lessons   []Lesson
}

type PairSlot struct {
	TimeRange	string
	StartMin	int
	EndMin		int
}

var tpuSlots = []PairSlot{
	{TimeRange: "08:30-10:05", StartMin: 8*60 + 30, EndMin: 10*60 + 5},
	{TimeRange: "10:25-12:00", StartMin: 10*60 + 25, EndMin: 12*60 + 0},
	{TimeRange: "12:40-14:15", StartMin: 12*60 + 40, EndMin: 14*60 + 15},
	{TimeRange: "14:35-16:10", StartMin: 14*60 + 35, EndMin: 16*60 + 10},
	{TimeRange: "16:30-18:05", StartMin: 16*60 + 30, EndMin: 18*60 + 5},
	{TimeRange: "18:25-20:00", StartMin: 18*60 + 25, EndMin: 20*60 + 0},
	{TimeRange: "20:20-21:55", StartMin: 20*60 + 20, EndMin: 21*60 + 55},
}

func timeToMinutes(t time.Time) int {
	return t.Hour()*60 + t.Minute()
}

func extractTeacher(desc string) string {
	descClean := strings.ReplaceAll(desc, "\\n", "\n")
	descClean = strings.ReplaceAll(descClean, "\\,", ",")
	lines := strings.Split(descClean, "\n")

	var cleanedLines []string
	for _, l := range lines {
		l = strings.TrimSpace(l)
		if l != "" {
			cleanedLines = append(cleanedLines, l)
		}
	}

	if len(cleanedLines) >= 3 {
		return cleanedLines[2]
	}
	return ""
}

func ParseIcs(filename string) (string, string, error) {
	file, err := os.Open(filename)
	if err != nil {
		return "", "", fmt.Errorf("failed to open ICS file: %w", err)
	}
	defer file.Close()

	cal, err := ics.ParseCalendar(file)
	if err != nil {
		return "", "", fmt.Errorf("failed to parse ICS calendar: %w", err)
	}

	locationTomsk := time.FixedZone("UTC+7", 7*60*60)
	nowInTomsk := time.Now().In(locationTomsk)
	todayStr := nowInTomsk.Format("02.01.2006")

	var todayLessons []Lesson

	for _, event := range cal.Events() {
		startAt, err := event.GetStartAt()
		if err != nil {
			continue
		}

		startInTomsk := startAt.In(locationTomsk)

		if startInTomsk.Format("02.01.2006") != todayStr {
			continue
		}

		endAt, err := event.GetEndAt()
		if err != nil {
			endAt = startAt
		}
		endInTomsk := endAt.In(locationTomsk)

		summary := ""
		if s := event.GetProperty(ics.ComponentPropertySummary); s != nil {
			summary = s.Value
		}

		location := ""
		if l := event.GetProperty(ics.ComponentPropertyLocation); l != nil {
			location = l.Value
		}

		description := ""
		if d := event.GetProperty(ics.ComponentPropertyDescription); d != nil {
			description = d.Value
		}

		summary = strings.ReplaceAll(summary, "\\,", ",")
		location = strings.ReplaceAll(location, "\\,", ",")

		teacher := extractTeacher(description)
		todayLessons = append(todayLessons, Lesson{
			Start:		startInTomsk,
			End: 		endInTomsk,
			Summary: 	summary,
			Location:	location,
			Teacher:	teacher,
		})
	}

	if len(todayLessons) == 0 {
		return "today is rest day", "", nil
	}

	sort.Slice(todayLessons, func(i, j int) bool {
		return todayLessons[i].Start.Before(todayLessons[j].Start)
	})

	firstLessonTime := todayLessons[0].Start.Format("15:04")

	var timeGroups []TimeGroup
	groupMap := make(map[string]int)

	for _, l := range todayLessons {
		tr := fmt.Sprintf("%s-%s", l.Start.Format("15:04"), l.End.Format("15:04"))
		if idx, exists := groupMap[tr]; exists {
			timeGroups[idx].Lessons = append(timeGroups[idx].Lessons, l)
		} else {
			newGroup := TimeGroup{
				TimeRange: tr,
				Lessons: []Lesson{l},
			}
			timeGroups = append(timeGroups, newGroup)
			groupMap[tr] = len(timeGroups) - 1
		}
	}

	var finalTimeGroups []TimeGroup
	for i := 0; i < len(timeGroups); i++ {
		finalTimeGroups = append(finalTimeGroups, timeGroups[i])

		if i < len(timeGroups) - 1 {
			currEnd := timeToMinutes(timeGroups[i].Lessons[0].End)
			nextStart := timeToMinutes(timeGroups[i+1].Lessons[0].Start)

			if nextStart - currEnd > 60 {
				var insertAnySlot bool
				for _, slot := range tpuSlots {
					if slot.StartMin >= currEnd && slot.EndMin <= nextStart {
						finalTimeGroups = append(finalTimeGroups, TimeGroup{
							TimeRange: slot.TimeRange,
							Lessons: []Lesson{
								{Summary: ""},
							},
						})
						insertAnySlot = true
					}
				}

				if !insertAnySlot {
					gapRange := fmt.Sprintf("%s-%s",
						timeGroups[i].Lessons[0].End.Format("15:04"),
						timeGroups[i+1].Lessons[0].Start.Format("15:04"),
				)
				finalTimeGroups = append(finalTimeGroups, TimeGroup{
					TimeRange: gapRange,
					Lessons: []Lesson{
						{Summary: ""},
					},
				})
				}
			}
		}
	}

	var msgBuilder strings.Builder
	for _, g := range finalTimeGroups {
		msgBuilder.WriteString(fmt.Sprintf("%s\n", g.TimeRange))
		for _, l := range g.Lessons {
			msgBuilder.WriteString(fmt.Sprintf("\t\t%s\n", l.Summary))
			if l.Teacher != "" {
				msgBuilder.WriteString(fmt.Sprintf("\t\t\t%s\n", l.Teacher))
			}
			if l.Location != "" {
				msgBuilder.WriteString(fmt.Sprintf("\t\t\t\t%s\n", l.Location))
			}
		}
		msgBuilder.WriteString("\n")
	}

	return strings.TrimSpace(msgBuilder.String()), firstLessonTime, nil
}
