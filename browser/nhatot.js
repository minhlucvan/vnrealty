/* nhatot.com / chotot.com listing-page extractor (self-contained; READ-ONLY).
 * Reads the ads already embedded in the page's __NEXT_DATA__ (props.initialState.adlisting.data.ads).
 * No clicks, no network, no storage. Never returns seller/company names, phones, street numbers or the ad body.
 * Output: one string; first line = "#total=<n>|url=<href>|seen_at=<iso>", then one '|' row per ad with columns
 *   id, type(s=sale,u=rent), category, price_vnd, size_m2, price_million_per_m2, lat, lng, area_name, ward_name_v3,
 *   street_name, land_type, house_type, apartment_type, legal, rooms, floors, width_m, length_m, main_street,
 *   project_name, orig_list_time_ms
 * Typed values come from the site JSON; labels (land_type, legal...) come from each ad's params array.
 */
(() => {
  const nd = document.querySelector('#__NEXT_DATA__');
  if (!nd) return '#total=0|warning=no __NEXT_DATA__';
  const st = JSON.parse(nd.textContent).props?.initialState?.adlisting?.data || {};
  const ads = st.ads || [];
  const c = (v) => (v === undefined || v === null ? '' : String(v).replace(/[|\n]/g, ' ').trim());
  const pv = (a, id) => (a.params || []).find((p) => p.id === id)?.value;
  const rows = ads.map((a) => [a.ad_id, a.type, a.category_name, a.price, a.size, a.price_million_per_m2 && (+a.price_million_per_m2).toFixed(2),
    a.latitude, a.longitude, a.area_name, a.ward_name_v3 || a.ward_name, a.street_name, pv(a, 'land_type'), pv(a, 'house_type'),
    pv(a, 'apartment_type'), pv(a, 'property_legal_document'), a.rooms, a.floors, a.width, a.length,
    a.is_main_street, a.pty_project_name, a.orig_list_time].map(c).join('|'));
  return ['#total=' + c(st.total) + '|url=' + location.href + '|seen_at=' + new Date().toISOString()].concat(rows).join('\n');
})()
