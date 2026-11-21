/* nhatot.com / chotot.com — reads the Next.js state (script#__NEXT_DATA__) which carries structured ads
 * (list_id, subject, price, price_string, size, ward/area/region names, latitude/longitude, params). Seller names,
 * account ids and phones are dropped. Falls back to the generic reader. Read-only. */
const SITE = 'chotot';
const warnings = [];
let state = null;
try { const el = document.getElementById('__NEXT_DATA__'); if (el) state = JSON.parse(el.textContent); } catch (e) { warnings.push('__NEXT_DATA__ unreadable'); }
function adItem(ad) {
  if (!ad || typeof ad !== 'object') return null;
  const params = {};
  for (const p of [].concat(ad.params || [])) if (p && p.label) params[p.label] = p.value;
  const lab = parseLabelTable(Object.keys(params).map((k) => k + ': ' + params[k]),
    { area: ['Diện tích đất'], frontage: ['Chiều ngang'], depth: ['Chiều dài'], legal: ['Giấy tờ pháp lý'], floors: ['Tổng số tầng'], ptype: ['Loại hình nhà ở', 'Loại hình đất', 'Loại hình căn hộ'] });
  const url = ad.list_id ? location.origin + '/' + ad.list_id + '.htm' : null;
  return makeItem(SITE, {
    url: url, site_id: ad.list_id ? String(ad.list_id) : null, title: ad.subject || null,
    price_text: ad.price_string || (ad.price ? String(ad.price) + ' đ' : null),
    area_text: ad.size ? String(ad.size) + ' m2' : (ad.area_v2 ? String(ad.area_v2) + ' m2' : lab.area || null),
    address: [ad.street_name, ad.ward_name, ad.area_name, ad.region_name].filter(Boolean).join(', ') || null,
    ward_raw: [ad.ward_name, ad.area_name].filter(Boolean).join(', ') || null,
    lat: isFinite(parseFloat(ad.latitude)) ? parseFloat(ad.latitude) : null,
    lng: isFinite(parseFloat(ad.longitude)) ? parseFloat(ad.longitude) : null,
    posted_text: ad.list_time ? new Date(Number(ad.list_time)).toISOString() : (ad.date || null),
    ptype_text: ad.category_name || lab.ptype || null,
    deal: ad.type === 'u' || /thue/.test(fold(ad.category_name || '')) ? 'rent' : (ad.type === 's' ? 'sale' : guessDeal(location.href, ad.subject)),
    rooms: ad.rooms || null, bedrooms_text: ad.rooms ? String(ad.rooms) : null,
    description: ad.body || null,
    labels: lab,
  });
}
function find(obj, test, depth) {
  if (!obj || typeof obj !== 'object' || depth > 8) return null;
  if (test(obj)) return obj;
  for (const k of Object.keys(obj)) { const r = find(obj[k], test, depth + 1); if (r) return r; }
  return null;
}
const isDetail = /\/\d{6,}\.htm/.test(location.pathname);
if (state) {
  if (isDetail) {
    const ad = find(state, (o) => o.list_id && o.subject && (o.body !== undefined || o.params), 0);
    if (ad) return envelope(SITE, 'detail', [adItem(ad)], warnings);
  } else {
    const holder = find(state, (o) => Array.isArray(o.ads) && o.ads.length && o.ads[0].list_id, 0);
    if (holder) return envelope(SITE, 'search', holder.ads.map(adItem).filter(Boolean), warnings);
  }
  warnings.push('ads not found in __NEXT_DATA__');
}
if (isDetail) { const g = genericDetail(SITE, { area: ['Diện tích đất'], legal: ['Giấy tờ pháp lý'] }); return envelope(SITE, 'detail', [g.item], warnings.concat(g.warnings)); }
return envelope(SITE, 'search', cardsByLink(SITE, /\/\d{6,}\.htm/), warnings.concat(['used link heuristic']));
