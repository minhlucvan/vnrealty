/* guland.vn listings (not the planning map — that is zoning.js). Markup not verified: generic label/JSON-LD
 * reader on detail pages, link-card heuristic on lists. Read-only. */
const SITE = 'guland';
const EXTRA = { alley: ['Đường trước', 'Đường trước nhà', 'Lộ giới'], ptype: ['Loại BĐS', 'Loại'] };
const isDetail = /\/post\/|\/tin\/|-\d{5,}(?:\.html)?$/.test(location.pathname) && !/\/soi-quy-hoach|\/map/.test(location.pathname);
if (isDetail) { const g = genericDetail(SITE, EXTRA); return envelope(SITE, 'detail', [g.item], g.warnings); }
return envelope(SITE, 'search', cardsByLink(SITE, /guland\.vn\/(?:post|tin)\/|-\d{5,}(?:\.html)?$/), ['link-card heuristic (markup unverified)']);
