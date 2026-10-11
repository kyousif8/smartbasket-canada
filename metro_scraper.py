"""
Smart Basket Canada - Metro / Food Basics scraper  ***UNVERIFIED SCAFFOLD***

metro.ca and foodbasics.ca blocked automated fetches while this project was
being researched, so the page structure here is NOT confirmed. It is written
defensively and fails safe:
  * robots.txt is checked per URL
  * a bot-check / access-denied page stops the scraper (no workaround)
  * if no products can be parsed it records status 'no_products' and exits 0
If it returns nothing, that is expected - the rest of the app keeps working.
Review each site's terms of use before relying on this.

Set ENABLE_UNVERIFIED=0 to skip it entirely.
"""

import os
import urllib.parse

from playwright.sync_api import sync_playwright

from common import (allowed_by_robots, launch_context, looks_blocked,
                    parse_generic_tile, polite_sleep, save_json, write_status)
from staples import STAPLES

OUTPUT_FILE = "metro_products.json"

BANNERS = [
    {"key": "metro", "base": "https://www.metro.ca",
     "search": "/en/online-grocery/search?filter={term}"},
    {"key": "food_basics", "base": "https://www.foodbasics.ca",
     "search": "/search?filter={term}"},
]

# Guess: Metro-platform tiles are links to /en/online-grocery/aisles/... or
# /product/... pages. We grab every link that sits in a container with a price.
EXTRACT_JS = r"""
() => {
  const out = [], seen = new Set();
  const priceRe = /\$\s*\d[\d,]*\.\d\d/;
  const tiles = document.querySelectorAll(
    '[data-product-id], .tile-product, .default-product-tile, li.product-tile, [class*="product-tile"]');
  for (const t of tiles) {
    const a = t.querySelector('a[href]');
    if (!a || !priceRe.test(t.innerText || '')) continue;
    const href = a.getAttribute('href');
    if (seen.has(href)) continue;
    seen.add(href);
    const title = t.querySelector('[class*="title"], h3, h2');
    out.push({href, name: title ? title.innerText : '', tileText: t.innerText});
  }
  return out;
}
"""


def main():
    if os.environ.get("ENABLE_UNVERIFIED", "1") == "0":
        print("Metro scaffold disabled (ENABLE_UNVERIFIED=0)")
        write_status("metro", [], note="disabled")
        save_json(OUTPUT_FILE, [])
        return
    terms = STAPLES[: int(os.environ.get("MAX_TERMS", 25))]
    all_products, errors, blocked_flag = [], [], False
    with sync_playwright() as p:
        browser, context = launch_context(p, "STORAGE_STATE_METRO")
        page = context.new_page()
        for banner in BANNERS:
            print(f"== {banner['key']} (unverified) ==")
            for term in terms:
                url = banner["base"] + banner["search"].format(
                    term=urllib.parse.quote(term))
                if not allowed_by_robots(url):
                    print(f"  [robots] skipping {url}")
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
    write_status("metro", all_products, blocked=blocked_flag, errors=errors,
                 note="unverified scaffold" + ("" if all_products else "; no_products"))
    print(f"Done. {len(all_products)} products -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
