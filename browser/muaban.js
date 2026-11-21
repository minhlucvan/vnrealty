/* muaban.net real-estate — Next.js state if present (ads with title/price/area/address), else generic.
 * Markup not verified. Read-only. */
const SITE = 'muaban';
const warnings = [];
let state = null;
try { const el = document.getElementById('__NEXT_DATA__'); if (el) state = JSON.parse(el.textContent); } catch (e) { warnings.push('__NEXT_DATA__ unreadable'); }
const isDetail = /-id\d{5,}/.test(location.pathname);
if (isDetail) { const g = genericDetail(SITE); return envelope(SITE, 'detail', [g.item], warnings.concat(g.warnings)); }
let items = [];
if (state) {
  const stack = [state]; let guard = 0;
  while (stack.length && guard++ < 20000) {
    const o = stack.pop();
    if (Array.isArray(o)) { for (const x of o) if (x && typeof x === 'object') stack.push(x); continue; }
    if (!o || typeof o !== 'object') continue;
    if (o.title && (o.price !== undefined || o.price_display) && (o.url || o.id)) {
      const url = o.url ? new URL(o.url, location.origin).href : null;
      items.push(makeItem(SITE, { url: url, site_id: o.id ? String(o.id) : siteIdFromUrl(url, SITE), title: o.title,
        price_text: o.price_display || (o.price ? String(o.price) + ' đ' : null), area_text: o.area ? String(o.area) + ' m2' : null,
        address: o.address || o.location || null, ward_raw: o.ward_name || o.district_name || null, posted_text: o.publish_at || o.created_at || null,
        deal: guessDeal(url || location.href, o.title) }));
      continue;
    }
    for (const k of Object.keys(o)) if (o[k] && typeof o[k] === 'object') stack.push(o[k]);
  }
}
if (!items.length) { items = cardsByLink(SITE, /-id\d{5,}/); warnings.push('used link heuristic'); }
return envelope(SITE, 'search', items, warnings);
