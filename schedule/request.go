package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"
)

type UpdateResponse struct {
	URL			string	`json:"url"`
	Error		bool	`json:"error"`
	Response	string	`json:"response"`
}

var customClient *http.Client

func init() {
	jar, err := cookiejar.New(nil)
	if err != nil {
		log.Fatalf("error creating cookie jar: %v", err)
	}

	customClient = &http.Client{
		Jar: jar,
		Transport: &http.Transport{
			DialContext: (&net.Dialer{
				Resolver: &net.Resolver{
					PreferGo: true,
					Dial: func(ctx context.Context, network, addres string) (net.Conn, error) {
						d := net.Dialer{Timeout: time.Second * 5}
						return d.DialContext(ctx, "udp", "8.8.8.8:53")
					},
				},
			}).DialContext,
		},
		Timeout: 45 * time.Second,
	}
}

func GetIcsSchedule() (string, error) {
	baseURL := "https://ro-rasp.tpu.ru"
	classParam := "ZnJvbnRlbmRcY3J1ZFxleHBvcnRcR3JvdXBFeHBvcnRDcnVk"
	kalendarParam := "XMU0te"

	sourceURL := fmt.Sprintf("%s/app/modal/source.html?class=%s&kalendar=%s", baseURL, classParam, kalendarParam)
	req, err := http.NewRequest("GET", sourceURL, nil)
	if err != nil {
		return "", fmt.Errorf("failed to create source request: %w", err)
	}

	req.Header.Set("User-Agent", "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0")
	req.Header.Set("X-Requested-With", "XMLHttpRequest")
	req.Header.Set("Accept", "application/json, text/javascript, */*; q=0.01")
	req.Header.Set("Referer", baseURL+"/")

	resp, err := customClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("failed to fetch modal source: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("bad status code from source: %d", resp.StatusCode)
	}

	bodyBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}

	var modalResp struct {
		HTML string `json:"html"`
	}

	var csrfToken string
	if json.Unmarshal(bodyBytes, &modalResp) == nil && modalResp.HTML != "" {
		doc, err := goquery.NewDocumentFromReader(strings.NewReader(modalResp.HTML))
		if err == nil {
			csrfToken, _ = doc.Find("input[name='_csrf']").Attr("value")
		}
	} else {
		doc, err := goquery.NewDocumentFromReader(strings.NewReader(string(bodyBytes)))
		if err == nil {
			csrfToken, _ = doc.Find("input[name='_csrf']").Attr("value")
		}
	}

	if csrfToken == "" {
		return "", fmt.Errorf("CSRF token not found in response")
	}

	updateURL := fmt.Sprintf("%s/app/modal/update.html?class=%s&kalendar=%s", baseURL, classParam, kalendarParam)
	formData := url.Values{
		"_csrf":					 {csrfToken},
		"GroupExportForm[kalendar]": {kalendarParam},
		"GroupExportForm[variant_id]": {"3"},
		"GroupExportForm[agree]": {"1"},
	}

	postReq, err := http.NewRequest("POST", updateURL, strings.NewReader(formData.Encode()))
	if err != nil {
		return "", fmt.Errorf("failed to create update request: %w", err)
	}

	postReq.Header.Set("User-Agent", "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0")
	postReq.Header.Set("X-Requested-With", "XMLHttpRequest")
	postReq.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	postReq.Header.Set("Referer", sourceURL)

	postResp, err := customClient.Do(postReq)
	if err != nil {
		return "", fmt.Errorf("failed to send update POST: %w", err)
	}
	defer postResp.Body.Close()

	var updateRes UpdateResponse
	if err := json.NewDecoder(postResp.Body).Decode(&updateRes); err != nil {
		return "", fmt.Errorf("failed to decode update response JSON: %w", err)
	}

	if updateRes.URL == "" {
		return "", fmt.Errorf("empty download URL returned from server")
	}

	icsDownloadURL := baseURL + updateRes.URL
	log.Printf("downloading schedule from: %s", icsDownloadURL)

	icsResp, err := customClient.Get(icsDownloadURL)
	if err != nil {
		return "", fmt.Errorf("failed to download ICS file: %w", err)
	}
	defer icsResp.Body.Close()

	if icsResp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("bad status code on ICS download: %d", icsResp.StatusCode)
	}

	icsFilename := "schedule.ics"
	out, err := os.Create(icsFilename)
	if err != nil {
		return "", err
	}
	defer out.Close()

	if _, err = io.Copy(out, icsResp.Body); err != nil {
		return "", err
	}

	return icsFilename, nil
}
