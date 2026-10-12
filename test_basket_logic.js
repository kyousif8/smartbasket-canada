// Smart Basket Canada - app logic tests.
// Extracts the REAL <script> from smart_basket_app.html and runs it in a Node
// vm sandbox with a mocked document/fetch, so the shipped code is what is tested.
// Run: node test_basket_logic.js

const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'smart_basket_app.html'), 'utf-8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) throw new Error('No <script> block found');
const scriptSrc = m[1];

let run = 0, failed = 0;

function mockEl() {
  return { innerHTML: '', textContent: '', value: '', className: '', style: { display: '' },
           classList: { add() {}, remove() {} }, addEventListener() {}, appendChild() {},
           getAttribute() { return null; } };
}

async function boot(fetchImpl) {
  const els = {};
  const document = {
    getElementById(id) { return els[id] || (els[id] = mockEl()); },
    createElement() { return mockEl(); },
  };
  const ctx = { document, fetch: fetchImpl, console, Date, Math, JSON, Object, Array, Number, String, RegExp, Infinity, setTimeout };
  vm.createContext(ctx);
  vm.runInContext(scriptSrc, ctx);
  await new Promise(r => setTimeout(r, 25));
  return { ctx, els };
}

// fetch mock: serves dataset + optional status by URL
const serve = (data, status) => async (url) => {
  if (String(url).includes('status')) {
    if (!status) throw new Error('no status');
    return { ok: true, json: async () => status };
  }
  return { ok: true, json: async () => data };
};

const daysAgo = n => new Date(Date.now() - n * 86400000).toISOString();
function P(store, name, price, unit, basis, extra) {
  return Object.assign({ store, name, price_cad: price, unit_price: unit, unit_basis: basis,
                         url: 'https://example.com/' + encodeURIComponent(name), scraped_at: daysAgo(1) }, extra || {});
}
function dataset() {
  return [
    P('no_frills', 'Lactantia Salted Butter 454 g', 7.99, 1.76, '100g'),
    P('no_frills', 'Lactantia Salted Butter 250 g', 4.99, 2.00, '100g'),
    P('no_frills', 'No Name Large Eggs 12 Pack', 3.93, 0.33, 'ea'),
    P('real_canadian_superstore', 'Lactantia Salted Butter 454 g', 5.99, 1.32, '100g', { on_sale: true, regular_price: 7.49 }),
    P('real_canadian_superstore', 'No Name Large Eggs 12 Pack', 3.93, 0.33, 'ea'),
    P('walmart_canada', 'Great Value Butter 454 g', 6.50, 1.43, '100g'),
    P('some_new_store', 'Store Brand Butter 454 g', 6.99, 1.54, '100g'),
  ];
}

async function test(name, fn) {
  run++;
  try { await fn(); console.log('  PASS  ' + name); }
  catch (e) { failed++; console.log('  FAIL  ' + name + '\n        ' + e.message); }
}

(async () => {
  console.log('Smart Basket Canada app tests\n');

  await test('live fetch success -> "Live data" status with product count', async () => {
    const d = dataset();
    const { els } = await boot(serve(d));
    const s = els.dataStatusHint.innerHTML;
    assert.ok(s.includes('Live data'), s);
    assert.ok(s.includes(String(d.length)), s);
  });

  await test('fetch failure -> falls back to sample snapshot, still searchable', async () => {
    const { ctx, els } = await boot(async () => { throw new Error('offline'); });
    assert.ok(els.dataStatusHint.innerHTML.includes('snapshot'));
    assert.ok(ctx.searchProducts('butter').length > 0);
  });

  await test('empty array is treated as failure, not "0 live products"', async () => {
    const { els } = await boot(serve([]));
    assert.ok(els.dataStatusHint.innerHTML.includes('snapshot'));
  });

  await test('known and unknown store keys both render with readable labels (none vanish)', async () => {
    const { ctx, els } = await boot(serve(dataset()));
    ctx.addToBasket('butter'); ctx.render();
    const h = els.receipts.innerHTML;
    assert.ok(h.includes('Real Canadian Superstore'));
    assert.ok(h.includes('Walmart Canada'));
    assert.ok(h.includes('Some New Store'), 'unknown key should get a prettified label, not disappear');
    assert.ok(!h.includes('real_canadian_superstore'), 'raw key leaked into UI');
  });

  await test('cheapestPerStore ranks by unit price (bigger pack wins over cheaper small pack)', async () => {
    const { ctx } = await boot(serve(dataset()));
    const best = ctx.cheapestPerStore('butter');
    assert.strictEqual(best.no_frills.name, 'Lactantia Salted Butter 454 g');
    assert.strictEqual(best.no_frills.price_cad, 7.99);
    assert.strictEqual(Object.keys(best).length, 4);
  });

  await test('single-word searches skip look-alike products (butter != peanut butter / plant butter)', async () => {
    const d = [P('no_frills', 'Kraft Smooth Peanut Butter 2 kg', 14.99, 0.75, '100g'),
               P('no_frills', 'Becel Salted Plant Butter 454 g', 3.99, 0.88, '100g'),
               P('no_frills', 'Lactantia Salted Butter 454 g', 7.99, 1.76, '100g'),
               P('metro', 'Salted Butter 454 g', 6.99, 1.54, '100g')];
    const { ctx } = await boot(serve(d));
    const names = ctx.searchProducts('butter').map(p => p.name);
    assert.deepStrictEqual(names.sort(), ['Lactantia Salted Butter 454 g', 'Salted Butter 454 g']);
    assert.strictEqual(ctx.cheapestPerStore('butter').no_frills.name, 'Lactantia Salted Butter 454 g');
  });

  await test('explicit -exclusions and multi-word terms work; matches start at a word boundary', async () => {
    const d = [P('no_frills', 'Kraft Smooth Peanut Butter 2 kg', 14.99, 0.75, '100g'),
               P('no_frills', 'Lactantia Salted Butter 454 g', 7.99, 1.76, '100g'),
               P('no_frills', 'Black Licorice 200 g', 2, 1, '100g'),
               P('no_frills', 'Basmati Rice 2 kg', 9, 0.45, '100g')];
    const { ctx } = await boot(serve(d));
    assert.strictEqual(ctx.searchProducts('peanut butter').length, 1);
    assert.strictEqual(ctx.searchProducts('butter -peanut').length, 1);
    assert.strictEqual(ctx.searchProducts('salted butter').length, 1);
    assert.deepStrictEqual(ctx.searchProducts('rice').map(p => p.name), ['Basmati Rice 2 kg']);
  });

  await test('fair size comparison: a 30-egg tray is not compared against another store\'s dozen', async () => {
    const d = [P('no_frills', 'No Name Large Eggs 12 ea', 3.93, 0.33, 'ea'),
               P('no_frills', 'Burnbrae Eggs 30 ea', 9.18, 0.31, 'ea'),
               P('real_canadian_superstore', 'No Name Eggs, Medium 30 ea', 9.18, 0.31, 'ea'),
               P('real_canadian_superstore', 'No Name Large Eggs 12 ea', 3.99, 0.33, 'ea'),
               P('walmart_canada', 'Great Value Large Eggs 12 ea', 3.77, 0.31, 'ea')];
    const { ctx } = await boot(serve(d));
    const best = ctx.cheapestPerStore('eggs');
    assert.strictEqual(best.no_frills.price_cad, 3.93);
    assert.strictEqual(best.real_canadian_superstore.price_cad, 3.99);
    assert.strictEqual(best.walmart_canada.price_cad, 3.77);
  });

  await test('size parsing handles g, kg, l, multipacks and each', async () => {
    const { ctx } = await boot(serve(dataset()));
    const eq = (n, q, fam) => { const s = ctx.sizeOf(n); assert.ok(s, n); assert.strictEqual(s.q, q, n); assert.strictEqual(s.fam, fam, n); };
    eq('Lactantia Salted Butter 454 g', 454, 'g');
    eq('Suraj Basmati Rice 3.63 kg', 3630, 'g');
    eq('Neilson 2% Milk 4 l', 4000, 'ml');
    eq('Coca-Cola 12 x 355 mL', 4260, 'ml');
    eq('No Name Eggs 12 ea', 12, 'ea');
    assert.strictEqual(ctx.sizeOf('Mystery Item'), null);
  });

  await test('whole-word matching: "butter" skips margarine/"Buttery", "chicken breast" skips deli meat', async () => {
    const d = [P('no_frills', 'Becel Buttery Taste Margarine 637 g', 6.99, 1.10, '100g'),
               P('no_frills', 'Lactantia Salted Butter 454 g', 7.99, 1.76, '100g'),
               P('no_frills', 'Maple Leaf Shaved Deli Chicken Breast 375 g', 15, 4, '100g'),
               P('no_frills', 'Fresh Chicken Breasts 800 g', 10, 1.25, '100g'),
               P('no_frills', 'Kraft Peanut Butter 1 kg', 8, 0.8, '100g')];
    const { ctx } = await boot(serve(d));
    assert.deepStrictEqual(ctx.searchProducts('butter').map(p => p.name), ['Lactantia Salted Butter 454 g']);
    assert.deepStrictEqual(ctx.searchProducts('chicken breast').map(p => p.name), ['Fresh Chicken Breasts 800 g']);
    assert.strictEqual(ctx.searchProducts('butter -margarine').length, 2, 'explicit exclusions replace the defaults');
  });

  await test('no match anywhere -> empty result, no throw', async () => {
    const { ctx } = await boot(serve(dataset()));
    assert.strictEqual(Object.keys(ctx.cheapestPerStore('caviar')).length, 0);
  });

  await test('search is case-insensitive and ignores blank input', async () => {
    const { ctx } = await boot(serve(dataset()));
    assert.strictEqual(ctx.searchProducts('BUTTER').length, ctx.searchProducts('butter').length);
    assert.strictEqual(ctx.searchProducts('   ').length, 0);
  });

  await test('basket: totals computed, missing items flagged, BEST stamped', async () => {
    const { ctx, els } = await boot(serve(dataset()));
    ctx.addToBasket('butter'); ctx.addToBasket('eggs'); ctx.render();
    const h = els.receipts.innerHTML;
    assert.ok(h.includes('not found'), 'walmart has no eggs');
    assert.ok(h.includes('Incomplete basket'));
    assert.ok(h.includes('BEST'));
    assert.ok(h.includes('$9.92'), 'superstore: 5.99 + 3.93 = 9.92');
    assert.ok(h.includes('$11.92'), 'no frills: 7.99 + 3.93 = 11.92');
  });

  await test('savings banner shows correct dollar amount vs most expensive complete basket', async () => {
    const { ctx, els } = await boot(serve(dataset()));
    ctx.addToBasket('butter'); ctx.render();
    assert.strictEqual(els.savingsBanner.style.display, 'flex');
    const b = els.savingsBanner.innerHTML;
    assert.ok(b.includes('Real Canadian Superstore'), b);
    assert.ok(b.includes('$2.00'), b);   // 7.99 (No Frills) - 5.99
    assert.ok(b.includes('No Frills'), b);
  });

  await test('product names are HTML-escaped (no script injection from scraped data)', async () => {
    const d = [P('no_frills', '<img src=x onerror=alert(1)> butter', 5, 1, '100g'),
               P('metro', 'butter', 6, 1.2, '100g')];
    const { ctx, els } = await boot(serve(d));
    ctx.addToBasket('butter'); ctx.render();
    assert.ok(!els.receipts.innerHTML.includes('<img'), 'unescaped HTML in receipts');
    assert.ok(els.receipts.innerHTML.includes('&lt;img'));
  });

  await test('multi-buy deals are shown as a deal; ranking price stays the single-unit price', async () => {
    const d = [P('real_canadian_superstore', 'Pillsbury Crescents 226 g', 2.49, 1.10, '100g', { deal_price: 1.74, deal_min_qty: 2 }),
               P('no_frills', 'Pillsbury Crescents 226 g', 2.79, 1.23, '100g')];
    const { ctx, els } = await boot(serve(d));
    ctx.addToBasket('crescents'); ctx.render();
    const h = els.receipts.innerHTML;
    assert.ok(h.includes('$1.74 each when you buy 2'));
    assert.ok(h.includes('$2.49'));
  });

  await test('stale data (>10 days) produces a visible warning', async () => {
    const d = dataset().map(p => Object.assign({}, p, { scraped_at: daysAgo(30) }));
    const { els } = await boot(serve(d));
    assert.ok(els.dataStatusHint.innerHTML.includes('days old'));
    assert.ok(els.dataStatusHint.className.includes('warn'));
  });

  await test('blocked scrapers in status file are surfaced to the user', async () => {
    const { els } = await boot(serve(dataset(), { blocked_scrapers: ['walmart'] }));
    assert.ok(els.dataStatusHint.innerHTML.includes('unavailable'));
  });

  // ---- Delivery economics -------------------------------------------------------------
  const near = (a, b, eps) => Math.abs(a - b) < (eps || 0.01);

  await test('quantities multiply line totals and store totals', async () => {
    const d = [P('no_frills', 'Basmati Rice 2 kg', 10, 0.5, '100g'), P('metro', 'Basmati Rice 2 kg', 13, 0.65, '100g')];
    const { ctx, els } = await boot(serve(d));
    ctx.addToBasket('rice'); ctx.setQty('rice', 3);
    const h = els.receipts.innerHTML;
    assert.ok(h.includes('3 &times; $10.00'), h);
    assert.ok(h.includes('$30.00'), h);
    assert.ok(h.includes('$39.00'), h);
    assert.strictEqual(ctx.getQty('rice'), 3);
    ctx.setQty('rice', 0);                       // never below 1
    assert.strictEqual(ctx.getQty('rice'), 1);
  });

  await test('deliveryEconomics: fee, net saving and break-even basket are computed correctly', async () => {
    const { ctx } = await boot(serve(dataset()));
    const e = ctx.deliveryEconomics(300, 369);                // 23% saving per $ of groceries
    assert.ok(near(e.saving, 69));
    assert.ok(near(e.fee, 24.99 + 0.08 * 300));
    assert.ok(near(e.feeTax, (24.99 + 24) * 1.13));
    assert.ok(near(e.net, 69 - (24.99 + 24) * 1.13));
    assert.strictEqual(e.minOrder, 240);                      // ceil to $5 of (24.99*1.13+5)/(0.23-0.08*1.13)
    assert.strictEqual(e.ok, true);
  });

  await test('deliveryEconomics: below the break-even basket delivery is refused and the gap is shown', async () => {
    const { ctx } = await boot(serve(dataset()));
    const e = ctx.deliveryEconomics(150, 184.5);              // same 23% rate, smaller basket
    assert.strictEqual(e.ok, false);
    assert.strictEqual(e.minOrder, 240);
    assert.strictEqual(e.gap, 90);
    assert.ok(e.net < 5);
  });

  await test('deliveryEconomics: savings too small to ever cover the percentage fee -> never worthwhile', async () => {
    const { ctx } = await boot(serve(dataset()));
    const e = ctx.deliveryEconomics(1000, 1050);              // 5% saving < 8% fee + HST
    assert.strictEqual(e.minOrder, null);
    assert.strictEqual(e.ok, false);
  });

  await test('deliveryEconomics: the minimum order floor applies even when savings are huge', async () => {
    const { ctx } = await boot(serve(dataset()));
    const e = ctx.deliveryEconomics(100, 200);
    assert.strictEqual(e.minOrder, 200);
    assert.strictEqual(e.ok, false);                          // 100 < floor
    assert.strictEqual(ctx.deliveryEconomics(200, 400).ok, true);
  });

  await test('when it is worth it, break-even guarantee holds: customer keeps at least the minimum net saving', async () => {
    const { ctx } = await boot(serve(dataset()));
    for (const [ours, base] of [[240, 295], [400, 480], [260, 330], [999, 1300]]) {
      const e = ctx.deliveryEconomics(ours, base);
      if (e.ok) assert.ok(e.net >= 5 - 1e-6, ours + ' -> net ' + e.net);
    }
  });

  await test('delivery card: average baseline says not worth it, picking the pricier usual store flips it', async () => {
    const d = [P('no_frills', 'Basmati Rice 2 kg', 10, 0.5, '100g'), P('metro', 'Basmati Rice 2 kg', 13, 0.65, '100g')];
    const { ctx, els } = await boot(serve(d));
    ctx.addToBasket('rice'); ctx.setQty('rice', 25);          // $250 at No Frills, $325 at Metro
    let h = els.delivery.innerHTML;
    assert.ok(h.includes('Not worth it yet'), h);             // avg baseline $287.50 -> 15% saving
    assert.ok(h.includes('average of these stores'));
    require('vm').runInContext("usual = 'metro'", ctx); ctx.render();
    h = els.delivery.innerHTML;
    assert.ok(h.includes('Delivery is worth it'), h);
    assert.ok(h.includes('Delivery launching soon'), 'no contact link configured yet -> disabled button');
    assert.ok(!h.includes('Request delivery'));
  });

  await test('delivery card: contact link switches ordering on; empty basket or one store hides the card', async () => {
    const d = [P('no_frills', 'Basmati Rice 2 kg', 10, 0.5, '100g'), P('metro', 'Basmati Rice 2 kg', 13, 0.65, '100g'),
               P('no_frills', 'Eggs 12 ea', 3, 0.25, 'ea')];
    const { ctx, els } = await boot(serve(d));
    assert.strictEqual(els.delivery.style.display, 'none');   // empty basket
    ctx.addToBasket('eggs'); ctx.render();                    // eggs only at one store -> no complete pair
    assert.strictEqual(els.delivery.style.display, 'none');
    ctx.addToBasket('rice'); ctx.render();                    // eggs incomplete at Metro
    assert.strictEqual(els.delivery.style.display, 'none');
    ctx.removeFromBasket('eggs');
    ctx.setQty('rice', 25);
    require('vm').runInContext("usual = 'metro'; DELIVERY.contactUrl = 'https://wa.me/10000000000'", ctx); ctx.render();
    assert.ok(els.delivery.innerHTML.includes('Request delivery'));
    assert.ok(els.delivery.innerHTML.includes('https://wa.me/10000000000'));
    require('vm').runInContext("DELIVERY.contactUrl = 'javascript:alert(1)'", ctx); ctx.render();
    assert.ok(!els.delivery.innerHTML.includes('javascript:'), 'unsafe link must be neutralised');
  });

  console.log('\n' + (run - failed) + '/' + run + ' passed');
  if (failed) process.exit(1);
})();
