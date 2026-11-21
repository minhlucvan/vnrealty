/* Planning maps — guland.vn "soi quy hoạch" or the Đà Nẵng planning portal. The human (or agent, with a normal
 * click) selects the parcel FIRST; this script only reads the info panel that is then visible. Returns raw panel
 * text plus parsed land-use codes (ODT/ONT/DGT/CXK…), plan name, decision number, density/height. Read-only. */
const SITE = /guland/.test(location.hostname) ? 'guland_map' : (location.hostname || 'planning').replace(/^www\./, '');
const warnings = [];
const KEY = /quy hoạch|mục đích sử dụng|ký hiệu|loại đất|thửa|mật độ xây dựng|chức năng/i;
const cands = $all('.leaflet-popup-content, .ol-popup, .esri-popup, [class*="popup"], [class*="info"], [class*="panel"], [class*="sidebar"], aside, .modal-body')
  .filter((el) => el.offsetParent !== null && KEY.test(el.innerText || ''));
cands.sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
const panel = cands[0];
if (!panel) warnings.push('no visible planning info panel — click the parcel first');
const raw = panel ? stripPhones(cleanText(panel.innerText)).slice(0, 4000) : null;
const parsed = parseZoningText(raw || '');
const ll = latLngFromUrl(location.href) || latLngFromText(location.hash);
return envelope(SITE, 'zoning', panel ? [Object.assign({ raw_text: raw, lat: ll ? ll.lat : null, lng: ll ? ll.lng : null, url: location.href }, parsed)] : [], warnings);
