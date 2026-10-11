"""
Smart Basket Canada - shared helpers
====================================
Parsing, unit-price maths, robots.txt checks, block detection and JSON saving
used by every scraper.

COMPLIANCE GUARDRAILS (deliberate, please keep them):
  * robots.txt is checked before every URL; explicitly disallowed URLs are skipped.
  * Requests are slow (several seconds apart) and low volume.
  * If a site shows a bot-check / access-denied page, the scraper STOPS for that
    store. It never tries to get around the block (no proxies, no CAPTCHA tricks).
  * Only name, price, size, unit price and product URL are collected. No images,
    no descriptions, no personal data.
"""

import json
import os
import random
import re
import time
import urllib.parse
import urllib.robotparser
from datetime import datetime, timezone

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# --------------------------------------------------------------------------
# Unit price maths
# --------------------------------------------------------------------------
# Matches "$1.76/100g", "55¢/100g", "$0.33/1ea", "$2.10/1kg", "$4.50/100 ml"
UNIT_RE = re.compile(
    r"(?:\$\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*¢)\s*/\s*(\d+(?:\.\d+)?)?\s*"
    r"(kg|g|ml|l|ea|each|lb)\b",
    re.IGNORECASE,
)
SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|ml|l|ea)\b", re.IGNORECASE)
MULTI_SIZE_RE = re.compile(
    r"(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\b", re.IGNORECASE
)
PRICE_RE = re.compile(r"\$\s*(\d[\d,]*\.\d\d)(?!\d)(?!\s*/)")

GRAMS_PER_LB = 453.592


def normalize_unit_price(amount, qty, unit):
    """Return (price, basis) where basis is '100g', '100ml' or 'ea'."""
    unit = unit.lower()
    qty = float(qty) if qty else 1.0
    if qty == 0:
        return None, None
    if unit == "g":
        return round(amount / qty * 100, 2), "100g"
    if unit == "kg":
        return round(amount / (qty * 1000) * 100, 2), "100g"
    if unit == "lb":
        return round(amount / (qty * GRAMS_PER_LB) * 100, 2), "100g"
    if unit == "ml":
        return round(amount / qty * 100, 2), "100ml"
    if unit == "l":
        return round(amount / (qty * 1000) * 100, 2), "100ml"
    if unit in ("ea", "each"):
        return round(amount / qty, 2), "ea"
    return None, None


def parse_displayed_unit_price(text):
    """Find the unit price the site itself displays, normalised."""
    m = UNIT_RE.search(text or "")
    if not m:
        return None, None
    dollars, cents, qty, unit = m.groups()
    amount = float(dollars) if dollars is not None else float(cents) / 100.0
    return normalize_unit_price(amount, qty, unit)


def parse_size(name):
    """Return (quantity, unit) in grams / ml / ea parsed from a product name."""
    if not name:
        return None, None
    m = MULTI_SIZE_RE.search(name)
    if m:
        n, q, u = m.groups()
        total = int(n) * float(q)
        u = u.lower()
        if u == "kg":
            return total * 1000, "g"
        if u == "l":
            return total * 1000, "ml"
        return total, u
    matches = SIZE_RE.findall(name)
    if not matches:
        return None, None
    q, u = matches[-1]
    q = float(q)
    u = u.lower()
    if u == "kg":
        return q * 1000, "g"
    if u == "l":
        return q * 1000, "ml"
    return q, u


def compute_unit_price(price, name):
    """Fallback: price / size from the product name -> (value, basis)."""
    qty, unit = parse_size(name)
    if not qty or price is None:
        return None, None
    if unit == "g":
        return round(price / qty * 100, 2), "100g"
    if unit == "ml":
        return round(price / qty * 100, 2), "100ml"
    if unit == "ea":
        return round(price / qty, 2), "ea"
    return None, None


# --------------------------------------------------------------------------
# Tile parsing
# --------------------------------------------------------------------------
NOISE_LINE_RE = re.compile(
    r"(current price|^was\b|^now\b|avg price|sale:|formerly:|sponsored|add to|"
    r"^add$|out of 5|reviews?|pickup|delivery|shipping|in stock|^\$|¢|^min \d)",
    re.IGNORECASE,
)


def _clean(text):
    return " ".join((text or "").split())


def pick_name(tile_text):
    """Pick the most name-like line from raw tile text (fallback only)."""
    best = ""
    for line in (tile_text or "").splitlines():
        line = line.strip()
        if not line or NOISE_LINE_RE.search(line):
            continue
        if len(line) > len(best):
            best = line
    return best


def _record(store, name, price, regular, on_sale, deal_price, deal_min_qty,
            unit_price, unit_basis, url, category, extra=None):
    rec = {
        "store": store,
        "name": name,
        "price_cad": price,
        "regular_price": regular,
        "on_sale": bool(on_sale),
        "deal_price": deal_price,
        "deal_min_qty": deal_min_qty,
        "unit_price": unit_price,
        "unit_basis": unit_basis,
        "url": url,
        "category": category,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        rec.update(extra)
    return rec


def parse_pcx_tile(link_text, tile_text, href, store, base_url, category=""):
    """
    Parse one PC Express (Loblaw banners) product tile.

    link_text example:
        'Prepared in Canada Lactantia Salted Butter 454 g, $1.76/100g'
    tile_text examples (whitespace-collapsed):
        '... 454 g, $1.76/100g $7.99'
        'sale: $5.00 , formerly: $6.29 Sponsored ... 200 g, $2.50/100g'
        'sale: $1.74 MIN 2 , formerly: $2.49 ... 226 g, $1.10/100g'

    Multi-buy ("MIN 2") offers: the displayed unit price is based on the
    REGULAR price, so price_cad stores the regular single-unit price and the
    multi-buy price goes into deal_price / deal_min_qty. Rankings stay honest.
    """
    link_text = _clean(link_text)
    tile_text = _clean(tile_text)
    if not tile_text and link_text:
        tile_text = link_text

    name_src = re.sub(r"^Sponsored\s*", "", link_text, flags=re.IGNORECASE)
    if not name_src:
        name_src = re.sub(r"^Sponsored\s*", "", pick_name(tile_text),
                          flags=re.IGNORECASE)

    unit_price, unit_basis = parse_displayed_unit_price(name_src)
    if unit_price is None:
        unit_price, unit_basis = parse_displayed_unit_price(tile_text)

    um = UNIT_RE.search(name_src)
    name = name_src[:um.start()] if um else name_src
    name = name.strip(" ,")
    if not name:
        return None

    sale = re.search(
        r"sale:\s*\$\s*(\d[\d,]*\.\d\d)(?:\s*MIN\s*(\d+))?", tile_text,
        re.IGNORECASE)
    formerly = re.search(r"formerly:\s*\$\s*(\d[\d,]*\.\d\d)", tile_text,
                         re.IGNORECASE)

    price = regular = deal_price = deal_min = None
    on_sale = False
    if sale:
        sale_price = float(sale.group(1).replace(",", ""))
        regular = float(formerly.group(1).replace(",", "")) if formerly else None
        if sale.group(2):  # multi-buy
            deal_price, deal_min = sale_price, int(sale.group(2))
            price = regular if regular is not None else sale_price
        else:
            price, on_sale = sale_price, True
    else:
        m = PRICE_RE.search(tile_text)
        if m:
            price = float(m.group(1).replace(",", ""))
    if price is None:
        return None

    if unit_price is None:
        unit_price, unit_basis = compute_unit_price(price, name)

    url = href if href.startswith("http") else base_url + href
    return _record(store, name, price, regular, on_sale, deal_price, deal_min,
                   unit_price, unit_basis, url, category)


def parse_generic_tile(tile_text, href, store, base_url, name_hint=None,
                       category=""):
    """
    Parse a Walmart.ca-style tile (also used by the scaffold scrapers).

    Handles:  'current price $2.47' / 'Now $3.97 ... Was $4.48' /
              'avg price $x' (weight-sold produce) and '55¢/100g' unit prices.
    """
    text = _clean(tile_text)
    if not text:
        return None

    was = re.search(r"\bWas\s*\$\s*(\d[\d,]*\.\d\d)", text, re.IGNORECASE)
    cur = (
        re.search(r"current price\s*\$\s*(\d[\d,]*\.\d\d)", text, re.IGNORECASE)
        or re.search(r"\bNow\s*\$\s*(\d[\d,]*\.\d\d)", text, re.IGNORECASE)
        or re.search(r"avg price\s*\$\s*(\d[\d,]*\.\d\d)", text, re.IGNORECASE)
    )
    avg = bool(re.search(r"avg price", text, re.IGNORECASE))
    if cur:
        price = float(cur.group(1).replace(",", ""))
    else:
        # first plain price that is not a Was-price and not a unit price
        price = None
        for m in PRICE_RE.finditer(text):
            if was and text[max(0, m.start() - 5):m.start()].lower().endswith("was"):
                continue
            price = float(m.group(1).replace(",", ""))
            break
    if price is None:
        return None

    regular = float(was.group(1).replace(",", "")) if was else None
    on_sale = regular is not None and regular > price

    name = _clean(name_hint) if name_hint else ""
    if not name:
        name = _clean(pick_name(tile_text))
    if not name:
        return None

    unit_price, unit_basis = parse_displayed_unit_price(text)
    if unit_price is None:
        unit_price, unit_basis = compute_unit_price(price, name)

    url = href if href.startswith("http") else base_url + href
    return _record(store, name, price, regular, on_sale, None, None,
                   unit_price, unit_basis, url, category,
                   extra={"price_is_avg": True} if avg else None)


# --------------------------------------------------------------------------
# robots.txt / politeness / block detection
# --------------------------------------------------------------------------
_robots_cache = {}


def allowed_by_robots(url):
    """True unless robots.txt explicitly disallows this URL for everyone."""
    parts = urllib.parse.urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    rp = _robots_cache.get(root)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(root + "/robots.txt")
        try:
            rp.read()
        except Exception as e:  # unreachable robots.txt: warn, don't guess
            print(f"  [robots] could not read {root}/robots.txt ({e}); "
                  "proceeding cautiously")
            rp = False
        _robots_cache[root] = rp
    if rp is False:
        return True
    return rp.can_fetch("*", url)


BLOCK_MARKERS = (
    "access denied", "unusual traffic", "captcha", "verify you are human",
    "robot or human", "are you a robot", "request blocked", "pardon our interruption",
)


def looks_blocked(page_text):
    t = (page_text or "").lower()
    return any(m in t for m in BLOCK_MARKERS)


def polite_sleep(base=4.0):
    time.sleep(base + random.uniform(0, 2.0))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def write_status(name, products, blocked=False, errors=None, note=""):
    """Small status file so the app and merge step can report honestly."""
    stores = {}
    for p in products:
        stores[p["store"]] = stores.get(p["store"], 0) + 1
    save_json(f"status_{name}.json", {
        "scraper": name,
        "finished_at": utc_now(),
        "products": len(products),
        "per_store": stores,
        "blocked": bool(blocked),
        "errors": (errors or [])[:20],
        "note": note,
    })


def launch_context(p, storage_state_env=None):
    """
    Headless Chromium (required on GitHub Actions - no display there).
    Optional: set an env var to the path of a Playwright storage_state JSON to
    reuse a session in which YOU picked a Toronto-area store. Nothing else is
    changed about the browser identity.
    """
    browser = p.chromium.launch(headless=True, args=["--disable-http2"])
    kwargs = dict(user_agent=USER_AGENT, locale="en-CA",
                  timezone_id="America/Toronto",
                  viewport={"width": 1366, "height": 900},
                  ignore_https_errors=True)
    path = os.environ.get(storage_state_env or "") if storage_state_env else None
    if path and os.path.exists(path):
        kwargs["storage_state"] = path
        print(f"  using storage state {path}")
    return browser, browser.new_context(**kwargs)
