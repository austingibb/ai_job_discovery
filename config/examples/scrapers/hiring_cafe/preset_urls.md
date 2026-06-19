# Hiring Cafe preset search URLs

When `search_filter_url` is set in `config/scrapers/hiring_cafe/config.json`, the
scraper navigates straight to that URL and skips the interactive "set filters then
press Enter" prompt. The URL encodes all of the search filters in its `searchState`
query parameter, so you can capture any search by setting up filters on hiring.cafe
in the browser and copying the resulting address bar URL.

To capture your own preset:

1. Open https://hiring.cafe/ in a browser.
2. Set the location, search query, and any other filters you want.
3. Copy the full URL from the address bar.
4. Paste it as the `search_filter_url` value in the scraper config.

## Presets below

These two are deliberately broad ("software" across all of the United States) so they
return thousands of results. That property is what makes them useful as canary targets:
zero jobs from a healthy page means something broke, never a legitimately empty search.

### Broad: software, all of USA (no extra narrowing)

```
https://hiring.cafe/?searchState=%7B%22locations%22%3A%5B%7B%22formatted_address%22%3A%22United%20States%22%2C%22types%22%3A%5B%22country%22%5D%2C%22geometry%22%3A%7B%22location%22%3A%7B%22lat%22%3A39.7391%2C%22lon%22%3A-104.9866%7D%7D%2C%22id%22%3A%22user_country%22%2C%22address_components%22%3A%5B%7B%22long_name%22%3A%22United%20States%22%2C%22short_name%22%3A%22US%22%2C%22types%22%3A%5B%22country%22%5D%7D%5D%2C%22options%22%3A%7B%22flexible_regions%22%3A%5B%22anywhere_in_continent%22%2C%22anywhere_in_world%22%5D%7D%7D%5D%2C%22searchQuery%22%3A%22software%22%7D
```

Decoded `searchState`:

```json
{
  "locations": [
    {
      "formatted_address": "United States",
      "types": ["country"],
      "geometry": {"location": {"lat": 39.7391, "lon": -104.9866}},
      "id": "user_country",
      "address_components": [
        {"long_name": "United States", "short_name": "US", "types": ["country"]}
      ],
      "options": {"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]}
    }
  ],
  "searchQuery": "software"
}
```

### Preferred daily: software engineer, all of USA, IC, 0 to 4 YoE, last 2 days

This narrower search is the one used as the live default in the personal scraper config.

```
https://hiring.cafe/?searchState=%7B%22locations%22%3A%5B%7B%22formatted_address%22%3A%22United+States%22%2C%22types%22%3A%5B%22country%22%5D%2C%22geometry%22%3A%7B%22location%22%3A%7B%22lat%22%3A39.7391%2C%22lon%22%3A-104.9866%7D%7D%2C%22id%22%3A%22user_country%22%2C%22address_components%22%3A%5B%7B%22long_name%22%3A%22United+States%22%2C%22short_name%22%3A%22US%22%2C%22types%22%3A%5B%22country%22%5D%7D%5D%2C%22options%22%3A%7B%22flexible_regions%22%3A%5B%22anywhere_in_continent%22%2C%22anywhere_in_world%22%5D%7D%7D%5D%2C%22searchQuery%22%3A%22software+engineer%22%2C%22dateFetchedPastNDays%22%3A2%2C%22roleYoeRange%22%3A%5B0%2C4%5D%2C%22roleTypes%22%3A%5B%22Individual+Contributor%22%5D%7D
```
