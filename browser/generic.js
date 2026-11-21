/* Any listing site: JSON-LD + OpenGraph/meta + Vietnamese label tables + embedded map coordinates.
 * kind is 'detail' when a price/area label was found, otherwise a link-card sweep is attempted. Read-only. */
const SITE = (location.hostname || 'unknown').replace(/^www\./, '').split('.')[0];
const g = genericDetail(SITE);
if (g.item.price_text || g.item.area_text) return envelope(SITE, 'detail', [g.item], g.warnings);
const cards = cardsByLink(SITE, /\d{5,}(?:\.html?|\.htm)?\/?(?:\?|$)/);
return envelope(SITE, cards.length ? 'search' : 'detail', cards.length ? cards : [g.item], g.warnings.concat(['generic extractor']));
