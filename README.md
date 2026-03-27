# AI Job Discovery

> **Warning:** The LinkedIn scraper plugin operates via browser automation on a Chrome instance where you are logged into LinkedIn. This means the scraper has full access to your authenticated LinkedIn session. Review the source code in `plugins/linkedin/` to verify what it does — there is nothing nefarious, but you should satisfy yourself of that before running it. The same applies to any browser-based scorer (e.g., `scorers/claude_browser/`), which operates on your authenticated claude.ai session.
>
> Browser automation is used because LinkedIn does not expose job search through its API for basic apps created in the LinkedIn developer portal, and Claude Pro chat subscriptions do not include API access. If you have API access for either service, a non-browser plugin/scorer could replace these.

Plugin-based job discovery pipeline that scrapes job boards via Playwright, scores listings against user-defined criteria using LLM integration, and generates ranked reports based on job fit.

## How It Works

1. **Scrape** — A job board plugin (currently LinkedIn) uses Playwright to collect job listings via browser automation
2. **Prefilter** — Listings are filtered by company name and title keywords before any LLM calls
3. **Score** — An AI scorer evaluates each remaining listing against your profile, background, and fit criteria, returning a 0-100 score with reasoning
4. **Report** — Results are ranked by score and written to a Markdown report

## Project Structure

```
ai_job_discovery/
├── main.py                  # Entry point — orchestrates the pipeline
├── config.py                # Loads user configuration from config/
├── models.py                # Core data models and plugin/scorer protocols
├── config/
│   ├── examples/            # Example configs (tracked in git)
│   │   ├── background.md
│   │   ├── fit_criteria.md
│   │   ├── rules.md
│   │   ├── prefilter.json
│   │   └── scorers/
│   │       └── claude_browser.json
│   ├── background.md        # Your professional background
│   ├── fit_criteria.md      # Scoring criteria (0-100 scale)
│   ├── rules.md             # Hard filter rules
│   ├── prefilter.json       # Company/title keyword exclusions
│   └── scorers/             # Personal scorer configs (API keys, project URLs)
│       └── claude_browser.json
├── plugins/
│   ├── linkedin/            # LinkedIn scraper plugin
│   │   ├── linkedin.py
│   │   └── config.json      # CDP URL, pagination settings
│   └── mock/                # Mock plugin for testing
│       └── mock.py
└── scorers/
    ├── prompt.py            # Builds scoring prompts from profile + jobs
    ├── parser.py            # Parses structured LLM responses
    ├── claude_browser/      # Scores via browser automation on claude.ai
    │   ├── claude_browser.py
    │   └── config.json      # CDP URL, default URL, batch size
    └── mock/                # Mock scorer for testing
        └── mock.py
```

## Installation

```bash
# Clone the repo
git clone https://github.com/austingibbons/ai_job_discovery.git
cd ai_job_discovery

# Create a virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

All personal configuration lives in the `config/` directory, which is gitignored. Example configs are provided in `config/examples/` as a starting point.

### 1. Copy the examples

```bash
cp config/examples/background.md config/background.md
cp config/examples/fit_criteria.md config/fit_criteria.md
cp config/examples/rules.md config/rules.md
cp config/examples/prefilter.json config/prefilter.json
mkdir -p config/scorers
cp config/examples/scorers/claude_browser.json config/scorers/claude_browser.json
```

### 2. Edit the config files

| File | Purpose |
|------|---------|
| `config/background.md` | Your work history, skills, education, and the types of roles you're targeting |
| `config/rules.md` | Hard filters — jobs matching any rule are excluded entirely (e.g., skip roles requiring 6+ YOE) |
| `config/fit_criteria.md` | Scoring guide — tells the LLM how to evaluate fit on a 0-100 scale |
| `config/prefilter.json` | Lists of companies and title keywords to exclude before scoring |
| `config/scorers/claude_browser.json` | Claude project URL for the browser scorer (optional — falls back to `claude.ai/new`) |

## Browser Setup

Some plugins and scorers (e.g., the LinkedIn scraper and Claude browser scorer) use Playwright to automate a real browser session. If you're using any browser-based plugin or scorer, you'll need to start a Chrome instance with remote debugging enabled before running the pipeline:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/ChromeDebug"
```

A separate user data directory (`ChromeDebug`) is required to avoid conflicts with your normal Chrome session.

Once the browser is running, log into any sites required by the plugins and scorers you're using. For example, the LinkedIn plugin requires an active linkedin.com session, and the Claude browser scorer requires a claude.ai session.

This step is not needed if you're only using API-based plugins and scorers.

**Note:** Browser-based plugins rely on specific DOM selectors to interact with each site. If a site updates its markup, these selectors may break and need to be updated in the plugin or scorer source code.

## Usage

```bash
python main.py
```

The pipeline gathers job listings using the configured scraper plugin, scores them against your profile using the configured AI scorer, and writes a ranked report to `output/report.md`.

The defaults are LinkedIn for scraping and Claude browser automation for scoring (browser automation is used because Claude Pro does not include API access). Both can be swapped for API-based or other implementations — see [Extending](#extending) below.

To write the report to a different file:

```bash
python main.py --output output/results.md
```

## Extending

The pipeline is built on two protocols defined in `models.py`:

**JobBoardPlugin** — Any class with a `scrape()` method returning `list[JobListing]`:
```python
class MyPlugin:
    def scrape(self) -> list[JobListing]: ...
```

**AIScorer** — Any class with a `score()` method returning `list[ScoringResult]`:
```python
class MyScorer:
    def score(self, profile: UserProfile, jobs: list[JobListing]) -> list[ScoringResult]: ...
```

Mock implementations of both are included in `plugins/mock/` and `scorers/mock/` for testing without a browser or LLM.

## Testing with Mocks

To test the pipeline without browser automation or LLM calls, swap in the mock plugin and scorer in `main.py`:

```python
from plugins.mock.mock import MockPlugin
from scorers.mock.mock import MockScorer

plugin = MockPlugin()
scorer = MockScorer()
```

This uses hardcoded job listings and scoring responses to verify the pipeline end to end.
