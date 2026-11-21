/* Google Maps place page or search results — POI name, address, category, rating, review count, lat/lng.
 * lat/lng come from the URL (!3d…!4d… pin preferred, else @lat,lng viewport centre — flagged). Read-only. */
const SITE = 'google_maps';
const warnings = [];
const url = location.href;
const items = [];
const feed = $1('div[role="feed"]');
if (feed) {
  for (const a of $all('a.hfpxzc, a[href*="/maps/place/"]', feed)) {
    const href = a.href || '';
    const ll = latLngFromUrl(href);
    const card = a.closest('div[jsaction], div.Nv2PK') || a.parentElement;
    const t = card ? (card.innerText || '') : '';
    const rating = t.match(/(\d[.,]\d)\s*\(?([\d.,]+)?\)?/);
    items.push({ name: cleanText(a.getAttribute('aria-label')) || null, url: href.split('?')[0],
      lat: ll ? ll.lat : null, lng: ll ? ll.lng : null, rating_text: rating ? rating[1] : null,
      reviews_text: rating && rating[2] ? rating[2] : null,
      card_text: stripPhones(cleanText(t) || '').slice(0, 300) });
  }
  return envelope(SITE, 'map', items, warnings);
}
const pin = /!3d-?\d/.test(url);
const ll = latLngFromUrl(url);
if (!pin) warnings.push('no !3d!4d pin in URL; lat/lng is the viewport centre');
const addrBtn = $1('button[data-item-id="address"]');
const rev = $all('span[aria-label]').map((s) => s.getAttribute('aria-label')).find((l) => /review|đánh giá|bài đánh giá/i.test(l || ''));
items.push({
  name: txt($1('h1.DUwDvf, h1')) || (document.title || '').replace(/ - Google Maps$/, ''),
  address: addrBtn ? cleanText((addrBtn.getAttribute('aria-label') || '').replace(/^(Address|Địa chỉ):\s*/i, '')) : null,
  category: txt($1('button.DkEaL, button[jsaction*="category"]')),
  rating_text: txt($1('div.F7nice span[aria-hidden="true"]')),
  reviews_text: rev || null,
  lat: ll ? ll.lat : null, lng: ll ? ll.lng : null, latlng_source: pin ? 'pin' : (ll ? 'viewport' : null),
  url: url.split('?')[0],
});
return envelope(SITE, 'map', items, warnings);
