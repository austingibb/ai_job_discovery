"""Preset search URLs the live canary runs against.

Every preset is chosen to reliably return results (broad "software" / "software
engineer" across the USA, plus a NYC software-engineer search that always has
listings). That property is what makes the canary's core assumption valid:

    A healthy page that yields ZERO jobs always means breakage, never a
    legitimately empty search.

The presets intentionally span DIFFERENT searchState param shapes (a bare
country-level search vs a locality search with radius, date, YoE, and role-type
filters). That diversity is what lets the cross-preset check discriminate:

  - All presets fail (regardless of shape)  -> the site markup / results API
    changed -> systemic scraper drift -> escalate.
  - Only presets sharing one URL/param shape fail while differently-shaped
    presets stay healthy with jobs -> that URL/param format drifted, not the
    scraper -> CANARY_MAINTENANCE (low priority, fix the preset URL).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    name: str
    plugin: str
    url: str


# hiring.cafe is the priority site. Both presets are broad enough that a healthy
# page must return jobs.
HIRING_CAFE_PRESETS: list[Preset] = [
    Preset(
        name="hiring_cafe_software_usa",
        plugin="hiring_cafe",
        url=(
            "https://hiring.cafe/?searchState=%7B%22locations%22%3A%5B%7B%22formatted_address%22%3A%22United%20States%22%2C%22types%22%3A%5B%22country%22%5D%2C%22geometry%22%3A%7B%22location%22%3A%7B%22lat%22%3A39.7391%2C%22lon%22%3A-104.9866%7D%7D%2C%22id%22%3A%22user_country%22%2C%22address_components%22%3A%5B%7B%22long_name%22%3A%22United%20States%22%2C%22short_name%22%3A%22US%22%2C%22types%22%3A%5B%22country%22%5D%7D%5D%2C%22options%22%3A%7B%22flexible_regions%22%3A%5B%22anywhere_in_continent%22%2C%22anywhere_in_world%22%5D%7D%7D%5D%2C%22searchQuery%22%3A%22software%22%7D"
        ),
    ),
    Preset(
        name="hiring_cafe_software_engineer_usa",
        plugin="hiring_cafe",
        url=(
            "https://hiring.cafe/?searchState=%7B%22locations%22%3A%5B%7B%22formatted_address%22%3A%22United%20States%22%2C%22types%22%3A%5B%22country%22%5D%2C%22geometry%22%3A%7B%22location%22%3A%7B%22lat%22%3A39.7391%2C%22lon%22%3A-104.9866%7D%7D%2C%22id%22%3A%22user_country%22%2C%22address_components%22%3A%5B%7B%22long_name%22%3A%22United%20States%22%2C%22short_name%22%3A%22US%22%2C%22types%22%3A%5B%22country%22%5D%7D%5D%2C%22options%22%3A%7B%22flexible_regions%22%3A%5B%22anywhere_in_continent%22%2C%22anywhere_in_world%22%5D%7D%7D%5D%2C%22searchQuery%22%3A%22software%20engineer%22%7D"
        ),
    ),
    # Different param shape on purpose: a locality (NYC) search with radius, date,
    # YoE, and role-type filters. NYC software-engineer searches reliably return
    # listings, and the distinct shape gives the cross-check a way to tell a
    # URL/param-format drift apart from a site/API change.
    Preset(
        name="hiring_cafe_software_engineer_nyc",
        plugin="hiring_cafe",
        url=(
            "https://hiring.cafe/?searchState=%7B%22locations%22%3A%5B%7B%22id%22%3A%228Bk1yZQBoEtHp_8UuN0b%22%2C%22types%22%3A%5B%22locality%22%5D%2C%22address_components%22%3A%5B%7B%22long_name%22%3A%22New+York+City%22%2C%22short_name%22%3A%22New+York+City%22%2C%22types%22%3A%5B%22locality%22%5D%7D%2C%7B%22long_name%22%3A%22New+York%22%2C%22short_name%22%3A%22NY%22%2C%22types%22%3A%5B%22administrative_area_level_1%22%5D%7D%2C%7B%22long_name%22%3A%22United+States%22%2C%22short_name%22%3A%22US%22%2C%22types%22%3A%5B%22country%22%5D%7D%5D%2C%22geometry%22%3A%7B%22location%22%3A%7B%22lat%22%3A40.71427%2C%22lon%22%3A-74.00597%7D%7D%2C%22formatted_address%22%3A%22New+York+City%2C+NY%2C+US%22%2C%22population%22%3A8804190%2C%22workplace_types%22%3A%5B%5D%2C%22options%22%3A%7B%22radius%22%3A50%2C%22radius_unit%22%3A%22miles%22%2C%22ignore_radius%22%3Afalse%7D%7D%5D%2C%22searchQuery%22%3A%22software+engineer%22%2C%22dateFetchedPastNDays%22%3A14%2C%22roleYoeRange%22%3A%5B0%2C4%5D%2C%22roleTypes%22%3A%5B%22Individual+Contributor%22%5D%7D"
        ),
    ),
]

DEFAULT_PRESETS = HIRING_CAFE_PRESETS
