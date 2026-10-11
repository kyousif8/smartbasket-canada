"""
Smart Basket Canada - Loblaw banners scraper (No Frills, Real Canadian
Superstore, Loblaws) - all run on the same PC Express platform.

Structure verified against live pages (server-rendered search results, product
links like /en/<slug>/p/<id>, tile text such as
'Lactantia Salted Butter 454 g, $1.76/100g' + '$7.99', 'sale: $5.00 ,
formerly: $6.29', 'sale: $1.74 MIN 2 , formerly: $2.49').

Uses site search pages for staple terms (robots.txt is checked per URL).
Prices depend on the store the site assigns by default. To pin a GTA store,
log in / choose a store once in a local browser, save the session with
Playwright (context.storage_state(path=...)), and point the env var
STORAGE_STATE_LOBLAW at that file.

Usage:
    pip install playwright && python -m playwright install chromium
    python loblaw_scraper.py
Env:
    BANNERS=no_frills,real_canadian_superstore   (optional filter)
    MAX_TERMS=10                                 (optional, for quick tests)
"""

import os
import urllib.parse

from playwright.sync_api import sync_playwright

from common import (allowed_by_robots, launch_context, looks_blocked,
                    parse_pcx_tile, polite_sleep, save_json, write_status)
from staples import STAPLES

OUTPUT_FILE = "loblaw_products.json"

BANNERS = [
    {"key": "no_frills", "base": "https://www.nofrills.ca"},
    {"key": "real_canadian_superstore", "base": "https://www.realcanadiansuperstore.ca"},
    {"key": "loblaws", "base": "https://www.loblaws.ca"},
]

# Collect each product tile: its link, link text, and the smallest ancestor
# that contains exactly one product and a (non unit-price) price.
EXTRACT_JS = r"""
() => {
  const out = [], seen = new Set();
  const priceRe = /\$\s*\d[\d,]*\.\d\d(?!\d)(?!\s*\/)/;
  for (const a of document.querySelectorAll('a[href*="/p/"]')) {
    const href = a.getAttribute('href');
    if (!href || seen.has(href)) continue;
    let node = a, tile = a;
    for (let i = 0; i < 8 && node.parentElement; i++) {
      node = node.parentElement;
      const hrefs = new Set([...node.querySelectorAll('a[href*="/p/"]')]
        .map(l => l.getAttribute('href')));
      if (hrefs.size > 1) break;
      tile = node;
      if (priceRe.test(node.innerText || '')) break;
    }
    seen.add(href);
    out.push({href, linkText: a.innerText || a.getAttribute('aria-label') || '',
              tileText: tile.innerText || ''});
  }
  return out;
}
"""


def scrape_term(page, banner, term):
    url = f"{banner['base']}/en/search?search-bar={urllib.parse.quote(term)}"
    if not allowed_by_robots(url):
        print(f"  [robots] skipping disallowed URL {url}")
        return [], False
    last = None
    for attempt in (1, 2):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector('a[href*="/p/"]', timeout=15000)
            except Exception:
                pass
            break
        except Exception as e:
            last = e
            polite_sleep(3)
    else:
        raise last
    body = page.inner_text("body")
    if looks_blocked(body):
        return [], True
    rows = page.evaluate(EXTRACT_JS)
    products = []
    for r in rows:
        rec = parse_pcx_tile(r["linkText"], r["tileText"], r["href"],
                             banner["key"], banner["base"], category=term)
        if rec:
            products.append(rec)
    return products, False


def main():
    wanted = os.environ.get("BANNERS")
    banners = [b for b in BANNERS if not wanted or b["key"] in wanted.split(",")]
    terms = STAPLES[: int(os.environ.get("MAX_TERMS", len(STAPLES)))]
    all_products, errors, any_blocked = [], [], False

    with sync_playwright() as p:
        browser, context = launch_context(p, "STORAGE_STATE_LOBLAW")
        page = context.new_page()
        for banner in banners:
            print(f"== {banner['key']} ==")
            for term in terms:
                try:
                    products, blocked = scrape_term(page, banner, term)
                except Exception as e:
                    errors.append(f"{banner['key']}/{term}: {e}")
                    print(f"  !! {term}: {e}")
                    continue
                if blocked:
                    any_blocked = True
                    errors.append(f"{banner['key']}: bot-check page; stopped")
                    print("  site served a bot-check page; stopping this banner")
                    break
                print(f"  {term}: {len(products)} products")
                all_products.extend(products)
                save_json(OUTPUT_FILE, all_products)  # incremental save
                polite_sleep()
        browser.close()

    save_json(OUTPUT_FILE, all_products)
    write_status("loblaw", all_products, blocked=any_blocked, errors=errors)
    print(f"Done. {len(all_products)} products -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
