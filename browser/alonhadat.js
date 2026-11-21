/* alonhadat.com.vn — detail (…-<id>.html with .property / .moreinfor table) and lists (.content-item).
 * Its "Đường trước nhà" row is the lane/road width in front. Read-only. */
const SITE = 'alonhadat';
const EXTRA = { alley: ['Đường trước nhà'], floors: ['Số lầu'], ptype: ['Loại BĐS'] };
const detailRoot = $1('.property, .detail');
if (detailRoot && $1('h1', detailRoot)) {
  const g = genericDetail(SITE, EXTRA);
  const it = g.item;
  const lab = Object.assign({}, labelPairsFromDom($1('.moreinfor, .infor') || detailRoot, EXTRA));
  it.labels = Object.assign({}, it.labels, lab);
  it.title = txt($1('.title h1, h1', detailRoot)) || it.title;
  it.price_text = txt($1('.price .value', detailRoot)) || lab.price || it.price_text;
  it.area_text = txt($1('.square .value', detailRoot)) || lab.area || it.area_text;
  it.address = txt($1('.address .value', detailRoot)) || lab.address || it.address;
  it.posted_text = txt($1('.date', detailRoot)) || it.posted_text;
  const desc = txt($1('.detail.text-content, .detail-text', detailRoot));
  if (desc) { it.description = stripPhones(desc).slice(0, 4000); const hs = phoneHashesIn(desc); if (hs.length) it.phone_hash = hs[0]; }
  return envelope(SITE, 'detail', [makeItem(SITE, it)], g.warnings);
}
const items = [];
for (const card of $all('.content-item')) {
  const a = $1('.ct_title a, a[href$=".html"]', card);
  if (!a) continue;
  const href = (a.href || '').split('?')[0];
  items.push(makeItem(SITE, {
    url: href, site_id: siteIdFromUrl(href, SITE), title: txt(a),
    price_text: txt($1('.ct_price', card)), area_text: txt($1('.ct_dt', card)), dims_text: txt($1('.ct_kt', card)),
    address: txt($1('.ct_dis', card)), ward_raw: txt($1('.ct_dis', card)), posted_text: txt($1('.ct_date', card)),
    description: txt($1('.ct_brief', card)), deal: guessDeal(location.href, txt(a)),
  }));
}
return envelope(SITE, 'search', items.length ? items : cardsByLink(SITE, /-\d{5,}\.html?$/), items.length ? [] : ['used link heuristic']);
