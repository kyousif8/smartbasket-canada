"""
Smart Basket Canada - Sobeys / FreshCo / Safeway scraper  ***UNVERIFIED SCAFFOLD***

sobeys.com/en/groceries/ returned 404 during research and the grocery sites
for these banners could not be fetched, so the URLs and page structure below
are PLACEHOLDERS you must confirm in a normal browser before relying on them:
  1. Open the banner's online-grocery site, search "butter".
  2. Copy the results URL, replace the term with {term}, put it in BANNERS.
  3. If the page is a JavaScript app, tiles may need a different selector.

It fails safe: robots.txt checked per URL, bot-check pages stop the run,
no products => status 'no_products' and exit 0.
Set ENABLE_UNVERIFIED=0 to skip it entirely.
"""

import os
import urllib.parse

from playwright.sync_api import sync_playwright

from common import (allowed_by_robots, launch_context, looks_blocked,
                    parse_generic_tile, polite_sleep, save_json, write_status)
from staples import STAPLES

OUTPUT_FILE = "sobeys_products.json"

# PLACEHOLDERS - confirm before trusting. Leave "search" empty to skip a banner.
BANNERS = [
    {"key": "sobeys", "base": "https://www.sobeys.com", "search": ""},
    {"key": "freshco", "base": "https://www.freshco.com", "search": ""},
    {"key": "safeway", "base": "https://www.safeway.ca", "search": ""},
]

EXTRACT_JS = r"""
() => {
  const out = [], seen = new Set();
  const priceRe = /\$\s*\d[\d,]*\.\d\d/;
  const tiles = document.querySelectorAll(
    '[data-product-id], [class*="product-card"], [class*="product-tile"], [class*="ProductCard"]');
  for (const t of tiles) {
    const a = t.querySelector('a[href]');
    if (!a || !priceRe.test(t.innerText || '')) continue;
    const href = a.getAttribute('href');
    if (seen.has(href)) continue;
    seen.add(href);
    const title = t.querySelector('[class*="title"], [class*="name"], h3, h2');
    out.push({href, name: title ? title.innerText : '', tileText: t.innerText});
  }
  return out;
}
"""


def main():
    active = [b for b in BANNERS if b["search"]]
    if os.environ.get("ENABLE_UNVERIFIED", "1") == "0" or not active:
        print("Sobeys scaffold: nothing to do (no confirmed search URLs yet).")
        save_json(OUTPUT_FILE, [])
        write_status("sobeys", [], note="unverified scaffold; no search URLs configured")
        return
    terms = STAPLES[: int(os.environ.get("MAX_TERMS", 25))]
    all_products, errors, blocked_flag = [], [], False
    with sync_playwright() as p:
        browser, context = launch_context(p, "STORAGE_STATE_SOBEYS")
        page = context.new_page()
        for banner in active:
            print(f"== {banner['key']} (unverified) ==")
            for term in terms:
                url = banner["base"] + banner["search"].format(
                    term=urllib.parse.quote(term))
                if not allowed_by_robots(url):
                    continue
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(3000)
                    if looks_blocked(page.inner_text("body")):
                        blocked_flag = True
                        errors.append(f"{banner['key']}: bot-check page; stopped")
                        break
                    for r in page.evaluate(EXTRACT_JS):
                        rec = parse_generic_tile(r["tileText"], r["href"],
                                                 banner["key"], banner["base"],
                                                 name_hint=r["name"], category=term)
                        if rec:
                            all_products.append(rec)
                    save_json(OUTPUT_FILE, all_products)
                except Exception as e:
                    errors.append(f"{banner['key']}/{term}: {e}")
                polite_sleep()
        browser.close()
    uniq = {r["url"]: r for r in all_products}
    all_products = list(uniq.values())
    save_json(OUTPUT_FILE, all_products)
    write_status("sobeys", all_products, blocked=blocked_flag, errors=errors,
                 note="unverified scaffold")
    print(f"Done. {len(all_products)} products -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
