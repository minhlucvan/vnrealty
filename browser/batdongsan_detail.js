/* batdongsan.com.vn DETAIL page (…-pr<id>) — spec table, address, description, map pin. Read-only.
 * (browser/batdongsan.js handles search-result pages in the compact 'srp' row format.)
 * Selectors from knowledge of the re__pr-* markup, NOT verified live; falls back to the generic
 * label/JSON-LD reader. Bundled after lib/core.js. */
const SITE = 'batdongsan';
const g = genericDetail(SITE);
const it = g.item;
const spec = {};
for (const row of $all('.re__pr-specs-content-item')) {
  const k = txt($1('.re__pr-specs-content-item-title', row)), v = txt($1('.re__pr-specs-content-item-value', row));
  if (k && v) spec[k] = v;
}
for (const row of $all('.re__pr-short-info-item')) {
  const k = txt($1('.title', row)), v = txt($1('.value', row));
  if (k && v) spec[k] = v;
}
const lab = parseLabelTable(Object.keys(spec).map((k) => k + ': ' + spec[k]));
it.labels = Object.assign({}, it.labels, lab);
it.title = txt($1('h1.re__pr-title, .re__pr-title')) || it.title;
it.address = txt($1('.re__pr-short-description.js__pr-address, .js__pr-address')) || lab.address || it.address;
it.price_text = lab.price || it.price_text;
it.area_text = lab.area || it.area_text;
it.posted_text = lab.posted || it.posted_text;
it.site_id = lab.site_id || siteIdFromUrl(location.href, SITE) || it.site_id;
const desc = txt($1('.re__pr-description .re__detail-content, .re__section-body.re__detail-content'));
if (desc) { it.description = stripPhones(desc).slice(0, 4000); const hs = phoneHashesIn(desc); if (hs.length) it.phone_hash = hs[0]; }
const map = $1('.re__pr-map iframe, iframe[data-src*="maps"], iframe[src*="maps"]');
if (map) { const ll = latLngFromUrl(map.getAttribute('data-src') || map.getAttribute('src')); if (ll) { it.lat = ll.lat; it.lng = ll.lng; } }
return envelope(SITE, 'detail', [makeItem(SITE, it)], g.warnings);
