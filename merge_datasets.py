"""
Smart Basket Canada - merge step
================================
Combines every scraper's JSON into:
  smart_basket_dataset.json  - flat list of products (what the app loads)
  smart_basket_status.json   - per-store counts, newest scrape time, block flags

Safety rules:
  * Invalid rows (no name / price <= 0) are dropped; duplicates by URL keep the newest.
  * If a store comes back EMPTY this run (e.g. blocked), its previous records are
    carried over for up to MAX_CARRY_DAYS and flagged carried_over=true, so the app
    does not lose a store overnight. Their original scraped_at is kept so the app
    can show how old those prices are.
  * If the merged result would be empty, the existing dataset is left untouched.
"""

import glob
import json
import os
from datetime import datetime, timedelta, timezone

INPUT_FILES = [
    "loblaw_products.json",
    "walmart_products.json",
    "metro_products.json",
    "sobeys_products.json",
]
OUTPUT_FILE = "smart_basket_dataset.json"
STATUS_FILE = "smart_basket_status.json"
MAX_CARRY_DAYS = 21
STALE_WARN_DAYS = 10


def _load(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError) as e:
        print(f"WARNING: could not read {path}: {e}")
        return []


def _valid(rec):
    return (isinstance(rec, dict) and rec.get("name") and rec.get("store")
            and isinstance(rec.get("price_cad"), (int, float))
            and rec["price_cad"] > 0 and rec.get("url"))


def _parse_ts(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def load_all():
    by_url = {}
    for path in INPUT_FILES:
        for rec in _load(path):
            if not _valid(rec):
                continue
            old = by_url.get(rec["url"])
            if old is None or _parse_ts(rec.get("scraped_at")) > _parse_ts(old.get("scraped_at")):
                by_url[rec["url"]] = rec
    return list(by_url.values())


def carry_over_missing_stores(fresh, previous):
    have = {r["store"] for r in fresh}
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_CARRY_DAYS)
    carried = []
    for rec in previous:
        if rec.get("store") in have or not _valid(rec):
            continue
        if _parse_ts(rec.get("scraped_at")) < cutoff:
            continue
        rec = dict(rec)
        rec["carried_over"] = True
        carried.append(rec)
    return carried


def search(products, term):
    t = term.lower()
    return [p for p in products if t in p["name"].lower()]


def cheapest_per_store(products, term):
    best = {}
    for p in search(products, term):
        cur = best.get(p["store"])
        if cur is None or p["price_cad"] < cur["price_cad"]:
            best[p["store"]] = p
    return best


def build_status(products, carried_stores):
    stores = {}
    for p in products:
        s = stores.setdefault(p["store"], {"count": 0, "newest": None})
        s["count"] += 1
        ts = p.get("scraped_at")
        if ts and (s["newest"] is None or _parse_ts(ts) > _parse_ts(s["newest"])):
            s["newest"] = ts
    for k in stores:
        stores[k]["carried_over"] = k in carried_stores
    scraper_status = {}
    for path in glob.glob("status_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
            scraper_status[st.get("scraper", path)] = st
        except (OSError, ValueError):
            pass
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "region": "Greater Toronto Area (prices depend on the store each site assigns)",
        "stores": stores,
        "scrapers": scraper_status,
        "blocked_scrapers": [k for k, v in scraper_status.items() if v.get("blocked")],
    }


def main():
    fresh = load_all()
    previous = _load(OUTPUT_FILE)
    carried = carry_over_missing_stores(fresh, previous)
    merged = fresh + carried
    if not merged:
        print("Nothing to merge - keeping the existing dataset untouched.")
        return
    carried_stores = {r["store"] for r in carried}
    if carried_stores:
        print(f"NOTE: carried over previous data for: {sorted(carried_stores)}")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    status = build_status(merged, carried_stores)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    print(f"Merged {len(merged)} products from {len(status['stores'])} stores:")
    for k, v in sorted(status["stores"].items()):
        print(f"  {k}: {v['count']} (newest {v['newest']})")
    newest = max((_parse_ts(p.get("scraped_at")) for p in merged))
    age = datetime.now(timezone.utc) - newest
    if age > timedelta(days=STALE_WARN_DAYS):
        print(f"WARNING: newest data is {age.days} days old.")
    if status["blocked_scrapers"]:
        print(f"WARNING: blocked scrapers: {status['blocked_scrapers']}")


if __name__ == "__main__":
    main()
