package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"
)

const (
	scheduleBaseURL = "https://ro-rasp.tpu.ru"
	// Temporary source configured for group 0B62. Arbitrary group selection
	// requires a documented mapping from a public group ID to this calendar ID.
	scheduleCalendarID = "XMU0te"
	exportClassID      = "ZnJvbnRlbmRcY3J1ZFxleHBvcnRcR3JvdXBFeHBvcnRDcnVk"
)

func getIcsSchedule() (string, func(), error) {
	jar, err := cookiejar.New(nil)
	if err != nil {
		return "", nil, err
	}
	client := &http.Client{Jar: jar, Timeout: 45 * time.Second}
	sourceURL := fmt.Sprintf("%s/app/modal/source.html?class=%s&kalendar=%s", scheduleBaseURL, exportClassID, scheduleCalendarID)
	request, err := http.NewRequest(http.MethodGet, sourceURL, nil)
	if err != nil {
		return "", nil, err
	}
	request.Header.Set("Accept", "application/json, text/javascript, */*; q=0.01")
	request.Header.Set("X-Requested-With", "XMLHttpRequest")
	response, err := client.Do(request)
	if err != nil {
		return "", nil, err
	}
	body, readErr := io.ReadAll(response.Body)
	response.Body.Close()
	if readErr != nil || response.StatusCode != http.StatusOK {
		return "", nil, fmt.Errorf("source request failed")
	}
	var modalResponse struct {
		HTML string `json:"html"`
	}
	if json.Unmarshal(body, &modalResponse) == nil && modalResponse.HTML != "" {
		body = []byte(modalResponse.HTML)
	}
	document, err := goquery.NewDocumentFromReader(bytes.NewReader(body))
	if err != nil {
		return "", nil, err
	}
	csrfToken, exists := document.Find("input[name='_csrf']").Attr("value")
	if !exists || csrfToken == "" {
		return "", nil, fmt.Errorf("csrf token missing")
	}
	values := url.Values{
		"_csrf":                       {csrfToken},
		"GroupExportForm[kalendar]":   {scheduleCalendarID},
		"GroupExportForm[variant_id]": {"3"},
		"GroupExportForm[agree]":      {"1"},
	}
	updateURL := fmt.Sprintf("%s/app/modal/update.html?class=%s&kalendar=%s", scheduleBaseURL, exportClassID, scheduleCalendarID)
	post, err := http.NewRequest(http.MethodPost, updateURL, strings.NewReader(values.Encode()))
	if err != nil {
		return "", nil, err
	}
	post.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	post.Header.Set("Referer", sourceURL)
	post.Header.Set("X-Requested-With", "XMLHttpRequest")
	updated, err := client.Do(post)
	if err != nil {
		return "", nil, err
	}
	defer updated.Body.Close()
	if updated.StatusCode != http.StatusOK {
		return "", nil, fmt.Errorf("calendar update failed")
	}
	var payload struct {
		URL string `json:"url"`
	}
	if err := json.NewDecoder(updated.Body).Decode(&payload); err != nil || payload.URL == "" {
		return "", nil, fmt.Errorf("calendar URL missing")
	}
	downloadURL, err := url.Parse(scheduleBaseURL + payload.URL)
	if err != nil || downloadURL.Host != "ro-rasp.tpu.ru" {
		return "", nil, fmt.Errorf("unsafe calendar URL")
	}
	icsResponse, err := client.Get(downloadURL.String())
	if err != nil {
		return "", nil, err
	}
	defer icsResponse.Body.Close()
	if icsResponse.StatusCode != http.StatusOK {
		return "", nil, fmt.Errorf("calendar download failed")
	}
	file, err := os.CreateTemp("", "schedule-*.ics")
	if err != nil {
		return "", nil, err
	}
	path := file.Name()
	if _, err := io.Copy(file, icsResponse.Body); err != nil {
		file.Close()
		os.Remove(path)
		return "", nil, err
	}
	if err := file.Close(); err != nil {
		os.Remove(path)
		return "", nil, err
	}
	return path, func() { _ = os.Remove(path) }, nil
}
