# Smart Basket GTA

Compares everyday grocery basket totals across Greater Toronto Area supermarkets.
Weekly GitHub Action scrapes public pages -> merges -> commits JSON -> GitHub Pages serves the app.

## What is verified and what is not
| Store | Status |
|---|---|
| No Frills, Real Canadian Superstore | Page structure and tile text verified; parsers tested on real captured text |
| Loblaws | Same platform (PC Express); not separately checked |
| Walmart Canada | Category pages verified server-rendered; search is NOT used (robots.txt disallows it) |
| Metro, Food Basics | **Unverified scaffold** (sites blocked research fetches). May return nothing |
| Sobeys, FreshCo, Safeway | **Unverified scaffold, no search URLs configured yet.** Does nothing until you confirm URLs |

I could not run a live browser scrape in the build environment, so the first
GitHub Actions run is the real test. Expect to tune selectors after reading its log.

## Files
- `common.py` parsing, unit-price maths, robots.txt check, block detection
- `staples.py` search terms; `loblaw_scraper.py`, `walmart_scraper.py`, `metro_scraper.py`, `sobeys_scraper.py`
- `merge_datasets.py` -> `smart_basket_dataset.json` + `smart_basket_status.json`
- `smart_basket_app.html` the app
- `test_parsers.py` (17 Python tests), `test_basket_logic.js` (13 app tests)
- `github_workflows_scrape.yml` -> must be saved as `.github/workflows/scrape.yml`
- `LEGAL_AND_MONETIZATION.md` read before charging money or promoting this

## Setup (new repo, web UI only)
1. github.com -> New repository (e.g. `smartbasket-canada`), Public, add a README.
2. **Add file -> Upload files**: drag in every file from this folder EXCEPT `github_workflows_scrape.yml`. Commit.
3. **Add file -> Create new file**. In the name box type `.github/workflows/scrape.yml`, paste the contents of `github_workflows_scrape.yml`, commit.
4. **Settings -> Actions -> General -> Workflow permissions**: choose "Read and write permissions", Save.
5. **Actions** tab -> "Weekly price scrape" -> **Run workflow**. Open the run and read each step's log (first run takes up to ~1.5 h).
6. **Settings -> Pages**: Source "Deploy from a branch", branch `main`, folder `/ (root)`. Your app: `https://<username>.github.io/<repo>/smart_basket_app.html`.
7. If a store shows 0 products or `blocked: true` in `smart_basket_status.json`, that is expected for some stores. Do not add proxies or evasion; see the legal notes.

## Run tests locally (no network needed)
    python -m unittest test_parsers -v
    node test_basket_logic.js
