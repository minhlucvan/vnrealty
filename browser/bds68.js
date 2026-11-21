/* bds68.com.vn — markup not verified: generic reader on detail pages, link-card heuristic on lists. Read-only. */
const SITE = 'bds68';
const isDetail = /\d{5,}(?:\.html?)?\/?$/.test(location.pathname) && document.querySelectorAll('h1').length === 1;
if (isDetail) { const g = genericDetail(SITE); return envelope(SITE, 'detail', [g.item], g.warnings); }
return envelope(SITE, 'search', cardsByLink(SITE, /bds68\.com\.vn\/.+\d{5,}/), ['link-card heuristic (markup unverified)']);
