package main

import (
	"embed"
	"encoding/json"
	"fmt"
	"strings"
)

//go:embed locales/*/messages.json stations.json
var resources embed.FS

type stationData struct {
	Code     string `json:"code"`
	EN       string `json:"en"`
	RU       string `json:"ru"`
	KA       string `json:"ka"`
	Slug     string `json:"slug"`
	Popular  bool   `json:"popular"`
	Unserved bool   `json:"unserved,omitempty"`
}

type catalog struct {
	texts    map[string]map[string]string
	names    map[string]stationData
	fallback []station
}

func newCatalog() (*catalog, error) {
	c := &catalog{texts: make(map[string]map[string]string), names: make(map[string]stationData)}
	for _, lang := range []string{"en", "ru"} {
		data, err := resources.ReadFile("locales/" + lang + "/messages.json")
		if err != nil {
			return nil, err
		}
		var sections map[string]map[string]string
		if err := json.Unmarshal(data, &sections); err != nil {
			return nil, err
		}
		c.texts[lang] = make(map[string]string)
		for section, entries := range sections {
			for key, value := range entries {
				c.texts[lang][section+"."+key] = value
			}
		}
	}
	data, err := resources.ReadFile("stations.json")
	if err != nil {
		return nil, err
	}
	var stations []stationData
	if err := json.Unmarshal(data, &stations); err != nil {
		return nil, err
	}
	for _, s := range stations {
		c.names[s.Code] = s
		if !s.Unserved {
			c.fallback = append(c.fallback, station{scalar(s.Code), s.EN, s.Popular})
		}
	}
	return c, nil
}

func language(code string) string {
	code = strings.ToLower(strings.Split(code, "-")[0])
	if code == "ru" {
		return "ru"
	}
	return "en"
}

func (c *catalog) text(lang, key string, args ...any) string {
	value := c.texts[language(lang)][key]
	if value == "" {
		value = c.texts["en"][key]
	}
	if value == "" {
		return "?" + key + "?"
	}
	for i := 0; i+1 < len(args); i += 2 {
		value = strings.ReplaceAll(value, "{"+fmt.Sprint(args[i])+"}", fmt.Sprint(args[i+1]))
	}
	return value
}

func (c *catalog) stationName(code, lang, fallback string) string {
	if s, ok := c.names[code]; ok {
		if lang == "ru" {
			return s.RU
		}
		if lang == "ka" {
			return s.KA
		}
		return s.EN
	}
	if fallback != "" {
		return fallback
	}
	return code
}
