"""
Offline parser tests built from REAL page text captured from the live sites.
Core check: price / size must agree with the unit price the site itself shows.

Run:  python -m unittest test_parsers -v      (no browser or network needed)
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import common
import merge_datasets
from common import parse_generic_tile, parse_pcx_tile

NF = "https://www.nofrills.ca"
SS = "https://www.realcanadiansuperstore.ca"
WM = "https://www.walmart.ca"


class LoblawTiles(unittest.TestCase):
    def test_regular_price_butter(self):
        r = parse_pcx_tile(
            "Prepared in Canada Lactantia Salted Butter 454 g, $1.76/100g",
            "Prepared in Canada Lactantia Salted Butter 454 g, $1.76/100g $7.99",
            "/en/salted-butter/p/20639926_EA?source=nspt", "no_frills", NF)
        self.assertEqual(r["name"], "Prepared in Canada Lactantia Salted Butter 454 g")
        self.assertEqual(r["price_cad"], 7.99)
        self.assertEqual((r["unit_price"], r["unit_basis"]), (1.76, "100g"))
        self.assertFalse(r["on_sale"])
        self.assertTrue(r["url"].startswith(NF + "/en/salted-butter/p/"))
        # price / size agrees with the displayed unit price
        calc, basis = common.compute_unit_price(7.99, r["name"])
        self.assertEqual(basis, "100g")
        self.assertAlmostEqual(calc, 1.76, places=2)

    def test_sale_price_and_sponsored_prefix(self):
        r = parse_pcx_tile(
            "Sponsored ViolifeDairy Free Cream Cheese 200 g, $2.50/100g",
            "sale: $5.00 , formerly: $6.29 Sponsored ViolifeDairy Free Cream Cheese 200 g, $2.50/100g",
            "/en/dairy-free-cream-cheese/p/1", "no_frills", NF)
        self.assertEqual(r["price_cad"], 5.00)
        self.assertEqual(r["regular_price"], 6.29)
        self.assertTrue(r["on_sale"])
        self.assertFalse(r["name"].startswith("Sponsored"))
        calc, _ = common.compute_unit_price(5.00, r["name"])
        self.assertAlmostEqual(calc, 2.50, places=2)

    def test_multibuy_uses_regular_price_for_ranking(self):
        r = parse_pcx_tile(
            "PillsburyCrescents Original Dough, 8 Pieces 226 g, $1.10/100g",
            "sale: $1.74 MIN 2 , formerly: $2.49 PillsburyCrescents Original Dough, 8 Pieces 226 g, $1.10/100g",
            "/en/crescents/p/2", "real_canadian_superstore", SS)
        self.assertEqual(r["price_cad"], 2.49)          # single-unit price
        self.assertEqual(r["deal_price"], 1.74)
        self.assertEqual(r["deal_min_qty"], 2)
        self.assertFalse(r["on_sale"])
        calc, _ = common.compute_unit_price(2.49, r["name"])
        self.assertAlmostEqual(calc, 1.10, places=2)     # unit price = REGULAR price

    def test_eggs_per_each_unit(self):
        r = parse_pcx_tile(
            "No NameLarge Size Eggs 12 Pack 12 ea, $0.33/1ea",
            "No NameLarge Size Eggs 12 Pack 12 ea, $0.33/1ea $3.93",
            "/en/eggs/p/3", "no_frills", NF)
        self.assertEqual(r["price_cad"], 3.93)
        self.assertEqual((r["unit_price"], r["unit_basis"]), (0.33, "ea"))
        calc, basis = common.compute_unit_price(3.93, r["name"])
        self.assertEqual(basis, "ea")
        self.assertAlmostEqual(calc, 0.33, places=2)

    def test_multiline_innertext_is_collapsed(self):
        r = parse_pcx_tile("Lactantia\nSalted Butter\n454 g, $1.76/100g",
                           "Lactantia\nSalted Butter\n454 g, $1.76/100g\n$7.99",
                           "/en/b/p/4", "no_frills", NF)
        self.assertEqual(r["name"], "Lactantia Salted Butter 454 g")
        self.assertEqual(r["price_cad"], 7.99)

    def test_unit_price_not_mistaken_for_price(self):
        # no main price present -> must return None, not the $1.76 unit price
        r = parse_pcx_tile("Lactantia Salted Butter 454 g, $1.76/100g",
                           "Lactantia Salted Butter 454 g, $1.76/100g",
                           "/en/b/p/5", "no_frills", NF)
        self.assertIsNone(r)


class WalmartTiles(unittest.TestCase):
    def test_current_price_and_cents_unit(self):
        r = parse_generic_tile(
            "Your Fresh Market Cheese Bagels current price $2.47 55¢/100g",
            "/en/ip/cheese-bagels/1", "walmart_canada", WM,
            name_hint="Your Fresh Market Cheese Bagels")
        self.assertEqual(r["price_cad"], 2.47)
        self.assertEqual((r["unit_price"], r["unit_basis"]), (0.55, "100g"))
        self.assertFalse(r["on_sale"])

    def test_now_was_pricing(self):
        r = parse_generic_tile(
            "Now $3.97 current price Now $3.97, Was $4.48 $1.75/100g",
            "/en/ip/philly/2", "walmart_canada", WM,
            name_hint="Philadelphia Original Cream Cheese")
        self.assertEqual(r["price_cad"], 3.97)
        self.assertEqual(r["regular_price"], 4.48)
        self.assertTrue(r["on_sale"])
        self.assertEqual(r["unit_price"], 1.75)

    def test_avg_price_produce(self):
        r = parse_generic_tile("avg price $1.89 42¢/100g",
                               "/en/ip/apples/3", "walmart_canada", WM,
                               name_hint="Gala Apples")
        self.assertEqual(r["price_cad"], 1.89)
        self.assertTrue(r.get("price_is_avg"))
        self.assertEqual(r["unit_price"], 0.42)

    def test_name_fallback_from_lines(self):
        r = parse_generic_tile("Oikos Greek Yogurt\ncurrent price $6.46",
                               "/en/ip/y/4", "walmart_canada", WM)
        self.assertEqual(r["name"], "Oikos Greek Yogurt")

    def test_real_walmart_innertext_samples(self):
        # Captured from a live walmart.ca category page (tile innerText)
        r = parse_generic_tile(
            "Astro Original Balkan Style Plain Yogurt 6%, 750g\nBest seller\nAdd\n$3.67\n"
            "current price $3.67\n49\u00a2/100g\nAstro Original Balkan Style Plain Yogurt 6%, 750g",
            "/en/ip/astro/1", "walmart_canada", WM,
            name_hint="Astro Original Balkan Style Plain Yogurt 6%, 750g")
        self.assertEqual(r["price_cad"], 3.67)
        self.assertEqual((r["unit_price"], r["unit_basis"]), (0.49, "100g"))
        calc, _ = common.compute_unit_price(3.67, r["name"])
        self.assertAlmostEqual(calc, 0.49, places=2)
        r2 = parse_generic_tile(
            "Armstrong Medium Cheddar Cheese Slices\nAdd\n$6.27\ncurrent price $6.27\n"
            "Armstrong Medium Cheddar Cheese Slices\n27\n4.8 out of 5 stars. 27 reviews",
            "/en/ip/arm/2", "walmart_canada", WM)
        self.assertEqual(r2["name"], "Armstrong Medium Cheddar Cheese Slices")
        self.assertEqual(r2["price_cad"], 6.27)


class UnitMath(unittest.TestCase):
    def test_conversions(self):
        self.assertEqual(common.normalize_unit_price(2.10, 1, "kg"), (0.21, "100g"))
        self.assertEqual(common.normalize_unit_price(1.50, 1, "l"), (0.15, "100ml"))
        self.assertEqual(common.normalize_unit_price(4.50, 100, "ml"), (4.5, "100ml"))
        self.assertEqual(common.normalize_unit_price(2.00, 1, "lb")[1], "100g")

    def test_multipack_size(self):
        self.assertEqual(common.parse_size("Coca-Cola 12 x 355 mL"), (4260.0, "ml"))
        self.assertEqual(common.parse_size("Neilson 2% Milk 4 L"), (4000.0, "ml"))

    def test_block_detection(self):
        self.assertTrue(common.looks_blocked("Robot or human? Activate and hold the button"))
        self.assertFalse(common.looks_blocked("Lactantia Salted Butter $7.99"))


class MergeLogic(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.cwd)

    def _rec(self, store, url, price=5.0, days_old=0):
        ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
        return {"store": store, "name": "Butter 454 g", "price_cad": price,
                "url": url, "scraped_at": ts}

    def _write(self, name, data):
        with open(name, "w") as f:
            json.dump(data, f)

    def test_dedupe_keeps_newest_and_drops_invalid(self):
        self._write("loblaw_products.json", [
            self._rec("no_frills", "u1", 5.0, days_old=3),
            self._rec("no_frills", "u1", 4.0, days_old=0),
            {"store": "no_frills", "name": "", "price_cad": 1, "url": "bad"},
            self._rec("no_frills", "u2", 0),
        ])
        out = merge_datasets.load_all()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["price_cad"], 4.0)

    def test_empty_store_is_carried_over(self):
        self._write("smart_basket_dataset.json", [self._rec("walmart_canada", "w1", days_old=5)])
        self._write("loblaw_products.json", [self._rec("no_frills", "u1")])
        merge_datasets.main()
        data = json.load(open("smart_basket_dataset.json"))
        wm = [r for r in data if r["store"] == "walmart_canada"]
        self.assertEqual(len(wm), 1)
        self.assertTrue(wm[0]["carried_over"])
        status = json.load(open("smart_basket_status.json"))
        self.assertTrue(status["stores"]["walmart_canada"]["carried_over"])

    def test_too_old_carry_over_is_dropped(self):
        self._write("smart_basket_dataset.json", [self._rec("walmart_canada", "w1", days_old=40)])
        self._write("loblaw_products.json", [self._rec("no_frills", "u1")])
        merge_datasets.main()
        data = json.load(open("smart_basket_dataset.json"))
        self.assertFalse(any(r["store"] == "walmart_canada" for r in data))

    def test_empty_run_keeps_existing_dataset(self):
        self._write("smart_basket_dataset.json", [self._rec("no_frills", "u1")])
        merge_datasets.main()
        data = json.load(open("smart_basket_dataset.json"))
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main()
