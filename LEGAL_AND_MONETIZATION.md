# Legal risk and monetization notes (not legal advice)

Please have a Canadian lawyer review this before you charge money, run ads or promote the app publicly.

## Where the risk actually is
1. **Terms of use / contract.** Grocery sites' terms generally prohibit automated access.
   Breach of contract is the most realistic claim, and it matters more once you earn revenue.
   Canadian courts have found liability for scraping in at least one reported case
   (Century 21 Canada v. Rogers, BC, 2011): confirm with a lawyer.
2. **Circumventing access controls.** Anything that evades blocks (proxies to dodge bot or geo blocks,
   CAPTCHA tricks, fake sessions) moves you toward the Criminal Code's unauthorized computer use
   provisions. This project deliberately has none: scrapers stop when blocked.
3. **Copyright / trademark.** Prices are facts; photos, descriptions and logos are not. The scrapers
   collect only name, price, size, unit price, URL. Do not add images or logos. Name stores
   only to identify them, and keep the "not affiliated" notice.
4. **Competition Act / misleading savings claims.** Prices differ by store and by day. Never claim
   guaranteed savings; keep the scrape date visible and the disclaimer in the footer.
5. **Privacy (PIPEDA).** No personal data is collected today. If you add accounts, email lists
   or analytics, you need a privacy policy and consent.

## Safer ways to build a business on this idea
- **Get permission / use official data:** ask retailers or Flipp-style flyer aggregators about a data
  licence or partnership; some chains publish digital flyers openly.
- **Affiliate / referral programs** and grocery-delivery referral fees (Instacart, etc.) instead of
  reselling scraped prices.
- **Crowdsourced prices:** users submit receipts or shelf prices (you own that data and avoid the
  scraping issue). Add open data such as Open Food Facts for product identity.
- **Freemium on features, not data:** basket optimisation across stores, price-drop alerts, meal-plan
  budgeting, built on whichever lawful data source you secure.
- Start non-commercial, keep traffic light, honour any cease-and-desist immediately.

## Operating rules baked into the code
robots.txt checked per URL - slow requests - stop on bot-check - no proxies - no images - disclaimers
and data age shown in the app.
