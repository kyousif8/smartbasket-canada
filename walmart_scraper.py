"""
Smart Basket Canada - Walmart Canada scraper (category pages only).

Walmart.ca /en/cp/, /en/browse/ and /en/shop/ pages are server-rendered.
/en/search is DISALLOWED by Walmart's robots.txt and is deliberately NOT used.
Every URL is also checked against robots.txt in code.

Walmart may show a "Robot or human?" check to automated browsers. If it does,
this scraper stops and records blocked=true. It does not try to bypass it.

Prices can depend on the store Walmart assigns by default. To pin a GTA store,
save a Playwright storage_state after choosing the store yourself and set the
env var STORAGE_STATE_WALMART.

Add more categories by copying URLs from walmart.ca grocery navigation.
"""

import os

from playwright.sync_api import sync_playwright

from common import (allowed_by_robots, launch_context, looks_blocked,
                    parse_generic_tile, polite_sleep, save_json, write_status)

OUTPUT_FILE = "walmart_products.json"
BASE = "https://www.walmart.ca"
STORE = "walmart_canada"

# Verified category paths (from walmart.ca grocery navigation).
CATEGORIES = {
    "yogurt": "/en/browse/grocery/dairy-eggs/yogurt/10019_6000194327369_6000194327390",
    "lactose-free milk": "/en/browse/grocery/dairy-eggs/dairy-milk/lactose-free-milk/10019_6000194327369_6000194327399_6000203372449",
    "almond milk": "/en/browse/grocery/dairy-eggs/non-dairy-milk-alternatives/almond-nuts-beverages/10019_6000194327369_6000206536130_6000194349397",
    "coffee creamer": "/en/browse/grocery/dairy-eggs/cream-creamers/coffee-creamers-enhancers/10019_6000194327369_6000194349396_6000203373014",
    "heavy cream": "/en/browse/grocery/dairy-eggs/cream-creamers/heavy-cream-whipping-cream/10019_6000194327369_6000194349396_6000206536243",
    "cereal": "/en/browse/grocery/pantry-food/cereal-breakfast/family-kids-cereals/10019_6000194326346_6000194328506_6000194328527",
    "flour": "/en/browse/grocery/pantry-food/baking-ingredients-supplies/flour-meals/10019_6000194326346_6000194328505_6000194329529",
    "baking": "/en/cp/grocery/pantry-food/baking-ingredients-supplies/6000194328505",
    "chips": "/en/cp/grocery/snacks-candy/chips/6000194329540",
    "chocolate": "/en/browse/grocery/snacks-candy/chocolate/10019_6000194328523_6000194329539",
    "coffee": "/en/browse/grocery/drinks/coffee/10019_6000194326336_6000194327380",
    "kombucha": "/en/browse/grocery/drinks/kombucha-wellness-drinks/10019_6000194326336_6000205760085",
    "grocery (top level)": "/en/cp/grocery/10019",
}

EXTRACT_JS = r"""
() => {
  const out = [], seen = new Set();
  const priceRe = /\$\s*\d[\d,]*\.\d\d/;
  for (const a of document.querySelectorAll('a[href*="/ip/"]')) {
    const href = a.getAttribute('href');
    if (!href || seen.has(href)) continue;
    let node = a, tile = a;
    for (let i = 0; i < 8 && node.parentElement; i++) {
      node = node.parentElement;
      const hrefs = new Set([...node.querySelectorAll('a[href*="/ip/"]')]
        .map(l => l.getAttribute('href')));
      if (hrefs.size > 1) break;
      tile = node;
      if (priceRe.test(node.innerText || '')) break;
    }
    const titleEl = tile.querySelector('[data-automation-id="product-title"]');
    seen.add(href);
    out.push({href,
              name: (titleEl && titleEl.innerText) || a.getAttribute('aria-label') || a.innerText || '',
              tileText: tile.innerText || ''});
  }
  return out;
}
"""


def scrape_category(page, label, path):
    url = BASE + path
    if not allowed_by_robots(url):
        print(f"  [robots] skipping disallowed URL {url}")
        return [], False, ""
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_selector('a[href*="/ip/"]', timeout=15000)
    except Exception:
        pass
    body = page.inner_text("body")
    if looks_blocked(body):
        return [], True, "bot-check page"
    products = []
    rows = page.evaluate(EXTRACT_JS)
    for r in rows:
        rec = parse_generic_tile(r["tileText"], r["href"], STORE, BASE,
                                 name_hint=r["name"], category=label)
        if rec:
            products.append(rec)
    diag = ""
    if not products:  # record what the page actually was, to diagnose later
        snippet = " ".join(body.split())[:200]
        diag = f"0 products ({len(rows)} product links); title={page.title()!r}; body starts: {snippet!r}"
    return products, False, diag


def main():
    all_products, errors, blocked_flag = [], [], False
    empty_streak = 0
    with sync_playwright() as p:
        browser, context = launch_context(p, "STORAGE_STATE_WALMART")
        page = context.new_page()
        for label, path in CATEGORIES.items():
            try:
                products, blocked, diag = scrape_category(page, label, path)
            except Exception as e:
                errors.append(f"{label}: {e}")
                print(f"  !! {label}: {e}")
                continue
            if blocked:
                blocked_flag = True
                errors.append("bot-check page; stopped")
                print("  Walmart served a bot-check page; stopping")
                break
            print(f"  {label}: {len(products)} products")
            if diag:
                print(f"     {diag}")
                errors.append(f"{label}: {diag}")
            empty_streak = 0 if products else empty_streak + 1
            if empty_streak >= 3:
                # Three category pages in a row with nothing to read: most likely the
                # site is not serving product tiles to this runner. Stop, don't evade.
                blocked_flag = True
                errors.append("no products rendered 3 times in a row; stopped")
                print("  no products rendered 3 times in a row; stopping")
                break
            all_products.extend(products)
            save_json(OUTPUT_FILE, all_products)
            polite_sleep()
        browser.close()
    # de-dupe by URL
    uniq = {r["url"]: r for r in all_products}
    all_products = list(uniq.values())
    save_json(OUTPUT_FILE, all_products)
    write_status("walmart", all_products, blocked=blocked_flag, errors=errors)
    print(f"Done. {len(all_products)} products -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
