/* batdongsan.com.vn search-results extractor (site body; bundled after browser/lib/core.js).
 * READ-ONLY: reads the cards already on the page. No clicks, no network, no storage.
 * Never returns agent names or phones: titles pass through stripPhones; the agent block is not read.
 * Returns envelope('batdongsan','srp', rows) where each row is a compact array
 *   [prid, category_slug, price_text, area_text, ppm_text, location_text, published_text, vip_type, bedrooms_text, title]
 * Numbers stay raw text; vnrealty/listings/parse.py parses them.
 */
const COLS = ['prid', 'category', 'price_text', 'area_text', 'ppm_text', 'location', 'published', 'vip', 'bedrooms', 'title'];
const rows = [];
for (const c of document.querySelectorAll('.js__card-listing')) {
  const q = (s) => cleanText(c.querySelector(s)?.innerText);
  const href = c.querySelector('a')?.getAttribute('href') || '';
  const cat = (href.split('/')[1] || '').replace(/-(duong|pho|xa|phuong|du-an|prj).*$/, '');
  const loc = (q('.re__card-location') || '').replace(/^·\s*/, '');
  const title = stripPhones((q('.re__card-title') || '').slice(0, 90));
  rows.push([c.getAttribute('prid'), cat, q('.re__card-config-price'), q('.re__card-config-area'),
    q('.re__card-config-price_per_m2'), loc, q('.re__card-published-info-published-at'), c.getAttribute('vtp'),
    q('.re__card-config-bedroom'), title]);
}
const total = cleanText(document.querySelector('#count-number, .re__srp-total-count')?.innerText);
const env = envelope('batdongsan', 'srp', rows, rows.length ? [] : ['no cards found']);
env.columns = COLS; env.total_text = total;
return JSON.stringify(env);
