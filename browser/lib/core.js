/* vnrealty browser core — shared helpers prepended to every site extractor by vnrealty/browser.py.
 *
 * Contract: the bundle is ONE expression, `(() => { <core> <site body> })()`, evaluated in the user's own Chrome via
 * claude-in-chrome's javascript_tool. It is READ-ONLY: no network calls, no clicks, no form submits, no storage.
 * Phone numbers are never returned; a phone becomes phone_hash = sha1(normalised digits), identical to
 * vnrealty.listings.parse.phone_hash. Numbers stay raw text (price_text, area_text…): Python owns the one parser.
 *
 * Pure functions (no DOM) are tested with node in tests/js/test_core.js:
 *   fold, cleanText, parseLabelTable, fromJsonLd, latLngFromUrl, latLngFromText, siteIdFromUrl, guessDeal,
 *   sha1, phoneHash, stripPhones, phoneHashesIn, extractCardFields, parseZoningText, envelope.
 */
/* eslint-disable no-unused-vars */

function fold(s) {
  if (s === null || s === undefined) return '';
  return String(s).normalize('NFC').toLowerCase().replace(/đ/g, 'd')
    .normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/²/g, '2').replace(/ /g, ' ')
    .replace(/\s+/g, ' ').trim();
}

function cleanText(s) {
  if (s === null || s === undefined) return null;
  const t = String(s).replace(/ /g, ' ').replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim();
  return t || null;
}

// canonical field -> folded labels (mirror of vnrealty.listings.parse.LABELS)
const LABELS = {
  price: ['muc gia', 'gia ban', 'gia', 'gia thue', 'gia cho thue'],
  area: ['dien tich', 'dien tich dat', 'dien tich su dung', 'dt'],
  floor_area: ['dien tich san', 'dien tich xay dung', 'tong dien tich san'],
  frontage: ['mat tien', 'chieu ngang', 'ngang'],
  depth: ['chieu dai', 'chieu sau', 'dai'],
  alley: ['duong vao', 'duong truoc nha', 'duong truoc', 'lo gioi', 'do rong duong'],
  legal: ['phap ly', 'giay to phap ly', 'giay to'],
  direction: ['huong nha', 'huong cua chinh', 'huong', 'huong dat'],
  floors: ['so tang', 'tong so tang', 'so lau', 'so tang lau'],
  bedrooms: ['so phong ngu', 'phong ngu', 'so phong'],
  address: ['dia chi', 'vi tri', 'khu vuc'],
  posted: ['ngay dang', 'ngay cap nhat', 'dang ngay'],
  site_id: ['ma tin', 'ma tin dang', 'ma bds'],
  ptype: ['loai bds', 'loai hinh', 'loai tin', 'loai nha dat', 'loai hinh nha o', 'loai hinh dat'],
  title: ['tieu de'],
};

function labelIndex(extra) {
  const idx = {};
  for (const k of Object.keys(LABELS)) for (const l of LABELS[k]) idx[l] = k;
  if (extra) for (const k of Object.keys(extra)) for (const l of extra[k]) idx[fold(l)] = k;
  return idx;
}

/* lines: array of strings. Returns {field: raw value}. Same rules as parse.parse_label_table. */
function parseLabelTable(lines, extra) {
  const idx = labelIndex(extra);
  const out = {};
  const ls = (lines || []).map((l) => String(l || '').trim());
  for (let i = 0; i < ls.length; i++) {
    const line = ls[i];
    if (!line) continue;
    const c = line.indexOf(':');
    const head = c >= 0 ? line.slice(0, c) : line;
    if (head.length > 40) continue;
    const key = idx[fold(head).replace(/[ .]+$/, '')];
    if (!key) continue;
    let val = c >= 0 ? line.slice(c + 1).trim() : '';
    if (!val) {
      for (let j = i + 1; j < Math.min(ls.length, i + 3); j++) {
        if (ls[j]) {
          const nh = ls[j].split(':')[0];
          if (!idx[fold(nh)]) val = ls[j];
          break;
        }
      }
    }
    if (val && !(key in out)) out[key] = val;
  }
  return out;
}

/* One JSON-LD object (or @graph member) -> partial item. Accepts Product/Offer/Place/RealEstateListing/House... */
function fromJsonLd(obj) {
  const out = {};
  if (!obj || typeof obj !== 'object') return out;
  const nodes = Array.isArray(obj) ? obj : (Array.isArray(obj['@graph']) ? obj['@graph'] : [obj]);
  for (const n of nodes) {
    if (!n || typeof n !== 'object') continue;
    const t = [].concat(n['@type'] || []).join(',').toLowerCase();
    if (/breadcrumb|organization|website|webpage|searchaction|person/.test(t) && !/listing|product|offer|residence|house|apartment|place/.test(t)) continue;
    if (n.name && !out.title) out.title = String(n.name);
    if (n.description && !out.description) out.description = String(n.description);
    if (n.url && !out.url) out.url = String(n.url);
    if (n.sku && !out.site_id) out.site_id = String(n.sku);
    if (n.productID && !out.site_id) out.site_id = String(n.productID);
    if (n.datePosted && !out.posted_text) out.posted_text = String(n.datePosted);
    if (n.datePublished && !out.posted_text) out.posted_text = String(n.datePublished);
    const offers = [].concat(n.offers || []);
    for (const o of offers) {
      if (!o || typeof o !== 'object') continue;
      const p = o.price !== undefined ? o.price : (o.priceSpecification && o.priceSpecification.price);
      if (p !== undefined && p !== null && !out.price_text) {
        out.price_text = String(p) + ((o.priceCurrency || 'VND') === 'VND' ? ' đ' : ' ' + o.priceCurrency);
      }
    }
    const fs = n.floorSize || (n.mainEntity && n.mainEntity.floorSize);
    if (fs && !out.area_text) out.area_text = typeof fs === 'object' ? String(fs.value) + ' m2' : String(fs);
    if (n.numberOfRooms !== undefined && !out.bedrooms_text) out.bedrooms_text = String(n.numberOfRooms);
    if (n.numberOfBedrooms !== undefined && !out.bedrooms_text) out.bedrooms_text = String(n.numberOfBedrooms);
    const addr = n.address || (n.location && n.location.address);
    if (addr && !out.address) {
      if (typeof addr === 'string') out.address = addr;
      else out.address = [addr.streetAddress, addr.addressLocality, addr.addressRegion].filter(Boolean).join(', ');
      if (typeof addr === 'object' && addr.addressLocality) out.ward_raw = String(addr.addressLocality);
    }
    const geo = n.geo || (n.location && n.location.geo);
    if (geo && out.lat === undefined) {
      const la = parseFloat(geo.latitude), ln = parseFloat(geo.longitude);
      if (isFinite(la) && isFinite(ln)) { out.lat = la; out.lng = ln; }
    }
  }
  return out;
}

function _okLatLng(la, ln) {
  return isFinite(la) && isFinite(ln) && Math.abs(la) <= 90 && Math.abs(ln) <= 180 && !(la === 0 && ln === 0);
}

/* Google Maps & embed URLs: "!3d16.05!4d108.2" (place pin, preferred), "@16.05,108.2,17z", "q=16.05,108.2",
 * "ll=", "center=", "destination=". Returns {lat, lng} or null. */
function latLngFromUrl(url) {
  if (!url) return null;
  let u = String(url);
  try { u = decodeURIComponent(u); } catch (e) { /* keep raw */ }
  let m = u.match(/!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)/);
  if (!m) m = u.match(/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/);
  if (!m) m = u.match(/[?&](?:q|ll|center|query|destination|daddr|sll)=(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)/);
  if (!m) return null;
  const la = parseFloat(m[1]), ln = parseFloat(m[2]);
  return _okLatLng(la, ln) ? { lat: la, lng: ln } : null;
}

/* lat/lng pairs written in page text or inline JSON: "latitude":16.05, "longitude":108.2 / lat: 16.05, lng: 108.2 */
function latLngFromText(text) {
  if (!text) return null;
  const s = String(text);
  const la = s.match(/["']?(?:latitude|lat)["']?\s*[:=]\s*["']?(-?\d{1,2}\.\d{3,})/i);
  const ln = s.match(/["']?(?:longitude|lng|lon|long)["']?\s*[:=]\s*["']?(-?\d{1,3}\.\d{3,})/i);
  if (!la || !ln) return null;
  const a = parseFloat(la[1]), b = parseFloat(ln[1]);
  return _okLatLng(a, b) ? { lat: a, lng: b } : null;
}

/* listing id from a URL, per site convention */
function siteIdFromUrl(url, site) {
  if (!url) return null;
  const u = String(url).split('#')[0];
  let m = null;
  switch (site) {
    case 'batdongsan': m = u.match(/-pr(\d{5,})/); break;
    case 'chotot': m = u.match(/\/(\d{6,})\.htm/); break;
    case 'alonhadat': m = u.match(/-(\d{5,})\.html?/); break;
    case 'muaban': m = u.match(/-id(\d{5,})/) || u.match(/\/(\d{6,})(?:[/?]|$)/); break;
    case 'facebook': m = u.match(/(?:posts|permalink)\/(\d{6,})/) || u.match(/story_fbid=(\d{6,})/); break;
    default: break;
  }
  if (!m) m = u.split('?')[0].match(/(\d{5,})(?:\.html?|\.htm)?\/?$/);
  return m ? m[1] : null;
}

function guessDeal(url, text) {
  const f = fold(url) + ' ' + fold(text);
  if (/cho-thue|cho thue|\/thue-|thue-nha|thue-phong|can ho cho thue/.test(f)) return 'rent';
  if (/ban-|mua-ban|nha-dat-ban|\bban\b|can ban/.test(f)) return 'sale';
  return null;
}

/* SHA-1 (hex) over UTF-8 — synchronous so it works inside an evaluated expression. */
function sha1(str) {
  const bytes = unescape(encodeURIComponent(String(str)));
  const words = [];
  for (let i = 0; i < bytes.length; i++) words[i >> 2] |= (bytes.charCodeAt(i) & 0xff) << (24 - (i % 4) * 8);
  const bitLen = bytes.length * 8;
  words[bitLen >> 5] |= 0x80 << (24 - bitLen % 32);
  words[(((bitLen + 64) >> 9) << 4) + 15] = bitLen;
  let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0;
  const w = new Array(80);
  for (let i = 0; i < words.length; i += 16) {
    let a = h0, b = h1, c = h2, d = h3, e = h4;
    for (let t = 0; t < 80; t++) {
      if (t < 16) w[t] = words[i + t] | 0;
      else { const x = w[t - 3] ^ w[t - 8] ^ w[t - 14] ^ w[t - 16]; w[t] = (x << 1) | (x >>> 31); }
      let f, k;
      if (t < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
      else if (t < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
      else if (t < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
      else { f = b ^ c ^ d; k = 0xca62c1d6; }
      const tmp = (((a << 5) | (a >>> 27)) + f + e + k + w[t]) | 0;
      e = d; d = c; c = (b << 30) | (b >>> 2); b = a; a = tmp;
    }
    h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0; h4 = (h4 + e) | 0;
  }
  return [h0, h1, h2, h3, h4].map((v) => ('00000000' + (v >>> 0).toString(16)).slice(-8)).join('');
}

function _normPhone(raw) {
  let d = String(raw || '').replace(/\D/g, '');
  if (d.startsWith('84') && (d.length === 11 || d.length === 12)) d = '0' + d.slice(2);
  return d.length >= 9 && d.length <= 11 && d.startsWith('0') ? d : null;
}

function phoneHash(raw) {
  const d = _normPhone(raw);
  return d ? sha1(d) : null;
}

const PHONE_RE = /(?:\+?84|0)(?:[\s.\-]?\d){8,10}/g;

function phoneHashesIn(text) {
  const out = [];
  const s = String(text || '');
  let m;
  PHONE_RE.lastIndex = 0;
  while ((m = PHONE_RE.exec(s)) !== null) {
    const h = phoneHash(m[0]);
    if (h && out.indexOf(h) < 0) out.push(h);
  }
  return out;
}

function stripPhones(text) {
  if (text === null || text === undefined) return text;
  return String(text).replace(PHONE_RE, (m) => { const h = phoneHash(m); return h ? '[phone:' + h.slice(0, 8) + ']' : m; });
}

/* Pull price / area / per-m2 / dims tokens out of a card's visible text. Raw strings only. */
function extractCardFields(text) {
  const s = String(text || '');
  const out = {};
  const num = '\\d+(?:[.,]\\d+)*';
  const price = s.match(new RegExp('(' + num + '[ \\t]*(?:tỷ|tỉ|ty)(?:[ \\t]*\\d{1,3}(?!\\d|[.,]\\d|\\s*m))?(?:[ \\t]*(?:triệu|tr))?|' + num + '[ \\t]*(?:triệu|tr)(?![a-zà-ỹ])(?:[ \\t]*\\/[ \\t]*(?:m²|m2|tháng|th))?|Thỏa thuận|Thoả thuận|Liên hệ)', 'i'));
  if (price) out.price_text = price[1].trim();
  const ppm = s.match(new RegExp('(' + num + '\\s*(?:triệu|tr|tỷ)\\s*\\/\\s*m(?:²|2))', 'i'));
  if (ppm) out.ppm2_text = ppm[1];
  const area = s.match(new RegExp('(' + num + '\\s*(?:m²|m2))(?!\\s*\\/)', 'i'));
  if (area) out.area_text = area[1];
  const dims = s.match(new RegExp('(' + num + '\\s*m?\\s*[x×]\\s*' + num + '\\s*m?)', 'i'));
  if (dims) out.dims_text = dims[1];
  const bed = s.match(/(\d+)\s*(?:PN|phòng ngủ)/i);
  if (bed) out.bedrooms_text = bed[1];
  const fl = s.match(/(\d+)\s*(?:tầng|lầu)/i);
  if (fl) out.floors_text = fl[1];
  const posted = s.match(/(Hôm nay|Hôm qua|\d+\s*(?:phút|giờ|ngày|tuần|tháng)\s*trước|\d{1,2}\/\d{1,2}\/\d{4})/i);
  if (posted) out.posted_text = posted[1];
  return out;
}

/* Planning-map info panel text -> land-use codes, plan name, decision number, density, height. */
const LANDUSE_CODES = ['ODT', 'ONT', 'DGT', 'CXK', 'CXQ', 'CLN', 'LUC', 'LUK', 'LUA', 'BHK', 'HNK', 'NTS', 'TMD', 'SKC',
  'SKK', 'DVH', 'DGD', 'DYT', 'DTT', 'TSC', 'RSX', 'RPH', 'RDD', 'SON', 'MNC', 'DTL', 'NTD', 'DCH', 'DKV', 'TON', 'TIN',
  'CQP', 'CAN', 'DNL', 'DBV', 'DRA', 'PNK', 'CSD', 'DHT', 'DCK', 'DSH', 'DKG', 'DXH', 'TMDV', 'HH', 'OM', 'OXH', 'CC',
  'CX', 'GT', 'MN', 'DLH'];

function parseZoningText(text) {
  const s = String(text || '');
  const f = fold(s);
  const codes = [];
  const re = /\b([A-Z]{2,4})(?:[-.\s]?\d{1,3}[a-z]?)?\b/g;
  let m;
  while ((m = re.exec(s)) !== null) {
    if (LANDUSE_CODES.indexOf(m[1]) >= 0 && codes.indexOf(m[1]) < 0) codes.push(m[1]);
  }
  const grab = (re2) => { const r = s.match(re2); return r ? r[1].trim() : null; };
  return {
    codes: codes,
    land_use_text: grab(/(?:Mục đích sử dụng|Loại đất|Chức năng)\s*:?\s*([^\n]+)/i),
    plan_name: grab(/((?:Quy hoạch|Đồ án|QH)[^\n]{3,160})/i),
    decision: grab(/((?:Quyết định|QĐ)\s*(?:số)?\s*:?\s*\d+[^\n,;]{0,40})/i) || grab(/(\d+\/QĐ-[A-ZĐ]+[^\s,;]*)/),
    density_text: grab(/Mật độ xây dựng\s*(?:tối đa)?\s*:?\s*([^\n]+)/i),
    height_text: grab(/(?:Tầng cao|Chiều cao)\s*(?:tối đa)?\s*:?\s*([^\n]+)/i),
    parcel_text: grab(/((?:Thửa|Tờ bản đồ|Số thửa)[^\n]{0,80})/i),
    area_text: grab(/Diện tích\s*:?\s*([^\n]+)/i),
    in_plan_road: /lo gioi|mo duong|quy hoach giao thong|dat giao thong/.test(f) || codes.indexOf('DGT') >= 0,
  };
}

function envelope(site, kind, items, warnings, url) {
  let href = url;
  if (href === undefined) { try { href = location.href; } catch (e) { href = null; } }
  return { site: site, url: href, seen_at: new Date().toISOString(), kind: kind, items: items || [], warnings: warnings || [] };
}

/* ------------------------------------------------------------------ DOM helpers (browser only) */

function txt(node) {
  if (!node) return null;
  return cleanText(node.innerText !== undefined ? node.innerText : node.textContent);
}

function $1(sel, root) { try { return (root || document).querySelector(sel); } catch (e) { return null; } }
function $all(sel, root) { try { return Array.from((root || document).querySelectorAll(sel)); } catch (e) { return []; } }

function readJsonLd(doc) {
  const out = [];
  for (const s of $all('script[type="application/ld+json"]', doc)) {
    try { out.push(JSON.parse(s.textContent)); } catch (e) { /* malformed block: skip */ }
  }
  return out;
}

function readMeta(doc) {
  const out = {};
  for (const m of $all('meta[property], meta[name], meta[itemprop]', doc)) {
    const k = m.getAttribute('property') || m.getAttribute('name') || m.getAttribute('itemprop');
    const v = m.getAttribute('content');
    if (k && v && !(k in out)) out[k] = v;
  }
  return out;
}

function findMapLatLng(doc) {
  const cands = [];
  for (const f of $all('iframe', doc)) cands.push(f.getAttribute('src') || '', f.getAttribute('data-src') || '');
  for (const a of $all('a[href*="maps"], a[href*="map?"], a[href*="google.com/maps"]', doc)) cands.push(a.getAttribute('href'));
  for (const el of $all('[data-lat][data-lng], [data-latitude][data-longitude]', doc)) {
    const la = parseFloat(el.getAttribute('data-lat') || el.getAttribute('data-latitude'));
    const ln = parseFloat(el.getAttribute('data-lng') || el.getAttribute('data-longitude'));
    if (_okLatLng(la, ln)) return { lat: la, lng: ln };
  }
  for (const c of cands) { const r = latLngFromUrl(c); if (r) return r; }
  const meta = readMeta(doc);
  const la = parseFloat(meta['place:location:latitude'] || meta['geo.position'] && meta['geo.position'].split(';')[0]);
  const ln = parseFloat(meta['place:location:longitude'] || meta['geo.position'] && meta['geo.position'].split(';')[1]);
  if (_okLatLng(la, ln)) return { lat: la, lng: ln };
  return null;
}

/* label/value pairs from common markup: dt/dd, th/td, two-cell rows, "label: value" list items */
function labelPairsFromDom(root, extra) {
  const lines = [];
  for (const dl of $all('dt', root)) { const dd = dl.nextElementSibling; if (dd) lines.push(txt(dl) + ': ' + (txt(dd) || '')); }
  for (const tr of $all('tr', root)) {
    const cells = $all('th, td', tr).map(txt);
    for (let i = 0; i + 1 < cells.length; i += 2) lines.push((cells[i] || '') + ': ' + (cells[i + 1] || ''));
  }
  return parseLabelTable(lines, extra);
}

function bodyLines() {
  const b = document.body;
  return b ? String(b.innerText || '').split('\n') : [];
}

/* build a listing item from labels + fallbacks; strips phones from every free-text field */
function makeItem(site, base) {
  const it = Object.assign({ site: site }, base || {});
  if (it.description) {
    const hs = phoneHashesIn(it.description);
    if (hs.length && !it.phone_hash) it.phone_hash = hs[0];
    it.description = stripPhones(it.description).slice(0, 4000);
  }
  for (const k of ['title', 'address', 'ward_raw', 'price_text', 'area_text']) if (it[k]) it[k] = stripPhones(it[k]);
  if (it.url && !it.site_id) it.site_id = siteIdFromUrl(it.url, site);
  if (it.labels) for (const k of Object.keys(it.labels)) it.labels[k] = stripPhones(it.labels[k]);
  return it;
}

/* Card heuristic for search pages: anchors whose href matches `hrefRe`, climb to the smallest ancestor that holds a
 * price-like token and only that one listing link. */
function cardsByLink(site, hrefRe, maxUp) {
  const seen = {};
  const items = [];
  for (const a of $all('a[href]')) {
    const href = a.href || a.getAttribute('href');
    if (!href || !hrefRe.test(href)) continue;
    const key = href.split('?')[0].split('#')[0];
    if (seen[key]) continue;
    let node = a;
    let card = null;
    for (let i = 0; i < (maxUp || 6) && node && node.parentElement; i++) {
      node = node.parentElement;
      const t = node.innerText || '';
      const links = $all('a[href]', node).map((x) => (x.href || '').split('?')[0]).filter((h) => hrefRe.test(h));
      const uniq = links.filter((h, j) => links.indexOf(h) === j);
      if (uniq.length > 1) break;
      if (/tỷ|triệu|thỏa thuận|thoả thuận|liên hệ/i.test(t)) { card = node; break; }
    }
    if (!card) continue;
    seen[key] = true;
    const t = card.innerText || '';
    const f = extractCardFields(t);
    const h = $1('h2, h3, h4, [class*="title"]', card);
    items.push(makeItem(site, Object.assign({
      url: key, title: txt(h) || cleanText(a.getAttribute('title')) || txt(a),
      address: null, card_text: stripPhones(cleanText(t)).slice(0, 600),
    }, f)));
  }
  return items;
}

/* generic detail-page extraction: JSON-LD + meta + label tables + map coords */
function genericDetail(site, extraLabels) {
  const warnings = [];
  const ld = {};
  for (const block of readJsonLd()) Object.assign(ld, Object.assign(fromJsonLd(block), ld));
  const meta = readMeta();
  const labels = Object.assign({}, parseLabelTable(bodyLines(), extraLabels), labelPairsFromDom(document, extraLabels));
  const geo = findMapLatLng() || (ld.lat !== undefined ? { lat: ld.lat, lng: ld.lng } : null);
  const h1 = $1('h1');
  const it = {
    url: location.href.split('#')[0],
    title: txt(h1) || ld.title || meta['og:title'] || document.title,
    price_text: labels.price || ld.price_text || null,
    area_text: labels.area || ld.area_text || null,
    address: labels.address || ld.address || null,
    ward_raw: ld.ward_raw || null,
    posted_text: labels.posted || ld.posted_text || null,
    site_id: labels.site_id || ld.site_id || null,
    lat: geo ? geo.lat : null, lng: geo ? geo.lng : null,
    description: ld.description || meta['og:description'] || meta.description || null,
    deal: guessDeal(location.href, (txt(h1) || '')),
    labels: labels,
  };
  if (!it.price_text) warnings.push('no price label found');
  if (!it.area_text) warnings.push('no area label found');
  return { item: makeItem(site, it), warnings: warnings };
}
