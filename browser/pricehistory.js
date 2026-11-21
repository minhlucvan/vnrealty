/* Price-history chart extractor (self-contained; READ-ONLY): area price-trend pages on batdongsan.com.vn
 * ("Biểu đồ giá", "Lịch sử giá", price analysis pages) and guland street-price pages, plus any page whose chart
 * uses Highcharts, Chart.js or ECharts.
 *
 * How it is used: the human or the lead agent opens the chart page in their own Chrome (scroll the chart into view
 * so it renders), then injects this file with the claude-in-chrome javascript_tool
 * (`python3 -m vnrealty.cli browser script pricehistory`), saves the returned JSON with `capture save`, and ingests
 * it with vnrealty.forecast.series.ingest_capture (the caller maps scope_text to a ward / district / street).
 *
 * Strategies, in order; every strategy that finds something contributes items:
 *   1. chart libraries already on the page: Highcharts.charts[i].series[j].data, Chart.js instances
 *      (config.data.labels + datasets), ECharts instances (echarts.getInstanceByDom → getOption()).
 *   2. embedded JSON: script tags of type application/json / ld+json / __NEXT_DATA__, and window state objects
 *      (__NEXT_DATA__, __NUXT__, __INITIAL_STATE__, __APOLLO_STATE__), searched for arrays of {date|month, price|value}.
 *   3. labelled tables whose first column reads as months (fallback).
 * No clicks, no network, no storage. Months are normalised to YYYY-MM where the label allows; values are passed
 * through raw (numbers or text) — all number parsing is done in Python.
 * Output: {site, url, seen_at, kind: 'series', items: [{scope_text, ptype_text, unit_text, source_hint,
 *          points: [[YYYY-MM, value]]}], warnings}.
 * The pure helpers are returned instead of the envelope when globalThis.__PRICEHISTORY_EXPORT__ is set (node tests).
 */
(() => {
  const fold = (s) => String(s == null ? '' : s).normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase().trim();
  const pad = (n) => (n < 10 ? '0' : '') + n;

  /* Date-ish value → 'YYYY-MM' or null. Epoch numbers (ms > 1e11, else s > 1e9), ISO, MM/YYYY, T3/2025,
   * Tháng 3/2025, Q1/2025 (middle month of the quarter), DD/MM/YYYY. */
  function normMonth(x) {
    if (x == null || typeof x === 'boolean') return null;
    if (typeof x === 'number') {
      if (!isFinite(x) || x <= 1e9) return null;
      const d = new Date(x > 1e11 ? x : x * 1000);
      return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1);
    }
    const s = fold(x);
    let m = s.match(/^(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?/);
    if (m && +m[2] >= 1 && +m[2] <= 12) return m[1] + '-' + pad(+m[2]);
    m = s.match(/(?:q|quy)\s*([1-4])\s*[/\-\s]\s*(\d{4})/);
    if (m) return m[2] + '-' + pad(3 * +m[1] - 1);
    m = s.match(/^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})/);
    if (m && +m[2] >= 1 && +m[2] <= 12) return m[3] + '-' + pad(+m[2]);
    m = s.match(/(?:^|[^\d])(\d{1,2})\s*[/\-.]\s*(\d{4})(?:$|[^\d])/) || s.match(/(?:t|thang|th)\s*(\d{1,2})\s*[/\-\s,]\s*(\d{4})/);
    if (m && +m[1] >= 1 && +m[1] <= 12) return m[2] + '-' + pad(+m[1]);
    return null;
  }

  const DATE_KEYS = ['date', 'month', 'time', 'period', 'thang', 'ngay', 'x', 'label', 'name', 'category', 'key', 'dt', 'timestamp'];
  const VALUE_KEYS = ['price', 'value', 'y', 'avgprice', 'priceavg', 'averageprice', 'avg', 'average', 'median', 'gia', 'giatb', 'pricem2', 'price_m2', 'amount'];
  const isVal = (v) => (typeof v === 'number' && isFinite(v)) || (typeof v === 'string' && /\d/.test(v) && v.length < 24);

  /* One element of a data array → [month, rawValue] or null. Objects use date/value keys; arrays are [x, y]. */
  function pointFrom(o, category) {
    if (o == null) return null;
    if (Array.isArray(o)) {
      if (o.length >= 2 && normMonth(o[0]) && isVal(o[1])) return [normMonth(o[0]), o[1]];
      return null;
    }
    if (typeof o === 'object') {
      const lk = {};
      Object.keys(o).forEach((k) => { lk[k.toLowerCase()] = k; });
      let mo = null;
      for (const k of DATE_KEYS) if (lk[k] !== undefined && normMonth(o[lk[k]])) { mo = normMonth(o[lk[k]]); break; }
      if (!mo && category != null) mo = normMonth(category);
      if (!mo) return null;
      for (const k of VALUE_KEYS) if (lk[k] !== undefined && isVal(o[lk[k]])) return [mo, o[lk[k]]];
      return null;
    }
    if (category != null && isVal(o) && normMonth(category)) return [normMonth(category), o];
    return null;
  }

  /* Sort by month, last value per month wins, drop empties. */
  function dedupePoints(points) {
    const by = {};
    points.forEach((p) => { if (p && p[0] && p[1] !== null && p[1] !== undefined && p[1] !== '') by[p[0]] = p[1]; });
    return Object.keys(by).sort().map((k) => [k, by[k]]);
  }

  /* Points from a values array plus optional category labels (shared by all chart libraries). */
  function pointsFrom(data, categories) {
    const out = [];
    (data || []).forEach((d, i) => {
      const cat = categories ? categories[i] : undefined;
      let p = null;
      if (d && typeof d === 'object' && !Array.isArray(d)) {
        p = pointFrom(d, cat);
        if (!p && cat != null && isVal(d.y)) p = normMonth(cat) ? [normMonth(cat), d.y] : null;
        if (!p && d.value !== undefined && Array.isArray(d.value)) p = pointFrom(d.value);
      } else p = Array.isArray(d) ? pointFrom(d) : pointFrom(d, cat);
      if (p) out.push(p);
    });
    return dedupePoints(out);
  }

  const MIN_POINTS = 3;

  /* Highcharts global → items. Reads series[j].data points (category / x / name) or options.data with xAxis categories. */
  function highchartsSeries(HC) {
    const items = [];
    ((HC && HC.charts) || []).forEach((ch, i) => {
      if (!ch) return;
      const cats = (ch.xAxis && ch.xAxis[0] && ch.xAxis[0].categories) || null;
      const unit = (ch.yAxis && ch.yAxis[0] && ch.yAxis[0].options && ch.yAxis[0].options.title && ch.yAxis[0].options.title.text)
        || (ch.options && ch.options.tooltip && ch.options.tooltip.valueSuffix) || null;
      const title = (ch.title && ch.title.textStr) || (ch.options && ch.options.title && ch.options.title.text) || null;
      (ch.series || []).forEach((s, j) => {
        let data = (s.data || []).map((p) => (p && typeof p === 'object'
          ? { x: p.category !== undefined ? p.category : (p.name !== undefined ? p.name : p.x), y: p.y } : p));
        if (!data.length && s.options && s.options.data) data = s.options.data;
        const pts = pointsFrom(data, cats);
        if (pts.length >= MIN_POINTS) items.push({ source_hint: 'highcharts:' + i + ':' + j, scope_text: title,
          ptype_text: s.name || null, unit_text: (s.tooltipOptions && s.tooltipOptions.valueSuffix) || unit, points: pts });
      });
    });
    return items;
  }

  /* Chart.js global → items (v2 instances is an object, v3+ a registry object keyed by id). */
  function chartjsSeries(CJ) {
    const items = [];
    if (!CJ || !CJ.instances) return items;
    const insts = Array.isArray(CJ.instances) ? CJ.instances : Object.keys(CJ.instances).map((k) => CJ.instances[k]);
    insts.forEach((c, i) => {
      const cfg = (c && (c.config || c.chart && c.chart.config)) || {};
      const d = cfg.data || (c && c.data) || {};
      const labels = d.labels || null;
      const title = cfg.options && cfg.options.plugins && cfg.options.plugins.title && cfg.options.plugins.title.text;
      (d.datasets || []).forEach((ds, j) => {
        const pts = pointsFrom(ds.data, labels);
        if (pts.length >= MIN_POINTS) items.push({ source_hint: 'chartjs:' + i + ':' + j, scope_text: title || null,
          ptype_text: ds.label || null, unit_text: null, points: pts });
      });
    });
    return items;
  }

  /* One ECharts option object → items (xAxis[0].data categories + series[i].data). */
  function echartsOption(opt, tag) {
    const items = [];
    if (!opt) return items;
    const xa = Array.isArray(opt.xAxis) ? opt.xAxis[0] : opt.xAxis;
    const ya = Array.isArray(opt.yAxis) ? opt.yAxis[0] : opt.yAxis;
    const cats = (xa && xa.data) ? xa.data.map((c) => (c && typeof c === 'object' ? c.value : c)) : null;
    const tt = Array.isArray(opt.title) ? opt.title[0] : opt.title;
    (opt.series || []).forEach((s, j) => {
      const pts = pointsFrom(s.data, cats);
      if (pts.length >= MIN_POINTS) items.push({ source_hint: 'echarts:' + tag + ':' + j, scope_text: (tt && tt.text) || null,
        ptype_text: s.name || null, unit_text: (ya && ya.name) || null, points: pts });
    });
    return items;
  }

  /* Recursive search of a JSON-like object for arrays of date/value records. Depth- and size-bounded. */
  function findSeriesInJson(obj, path, out, depth, seen) {
    out = out || []; depth = depth || 0; seen = seen || new Set(); path = path || '$';
    if (obj == null || typeof obj !== 'object' || depth > 12 || seen.has(obj) || out.length > 50) return out;
    seen.add(obj);
    if (Array.isArray(obj)) {
      if (obj.length >= MIN_POINTS) {
        const sample = obj.slice(0, 400);
        const pts = sample.map((o) => pointFrom(o)).filter(Boolean);
        if (pts.length >= MIN_POINTS && pts.length >= 0.6 * sample.length) {
          out.push({ source_hint: 'json:' + path, scope_text: null, ptype_text: null, unit_text: null,
            points: dedupePoints(pts) });
          return out;
        }
      }
      obj.slice(0, 400).forEach((v, i) => findSeriesInJson(v, path + '[' + i + ']', out, depth + 1, seen));
      return out;
    }
    const keys = Object.keys(obj).slice(0, 400);
    const before = out.length;
    keys.forEach((k) => findSeriesInJson(obj[k], path + '.' + k, out, depth + 1, seen));
    // label hints from sibling keys of the found arrays
    const lk = {};
    keys.forEach((k) => { lk[k.toLowerCase()] = k; });
    for (let i = before; i < out.length; i++) {
      const it = out[i];
      if (!it.unit_text) for (const k of ['unit', 'donvi', 'valuesuffix']) if (typeof obj[lk[k]] === 'string') { it.unit_text = obj[lk[k]]; break; }
      if (!it.ptype_text) for (const k of ['name', 'label', 'type', 'category', 'loai']) if (typeof obj[lk[k]] === 'string') { it.ptype_text = obj[lk[k]]; break; }
      if (!it.scope_text) for (const k of ['title', 'location', 'area', 'district', 'ward', 'street', 'khuvuc']) if (typeof obj[lk[k]] === 'string') { it.scope_text = obj[lk[k]]; break; }
    }
    return out;
  }

  /* Rows of cell texts → items: the first column must read as months for ≥ 3 rows; each other column is a series
   * named by the header row. */
  function tableSeries(rows) {
    if (!rows || rows.length < MIN_POINTS + 1) return [];
    const header = rows[0];
    const body = rows.slice(1).filter((r) => normMonth(r[0]));
    if (body.length < MIN_POINTS) return [];
    const items = [];
    for (let c = 1; c < header.length; c++) {
      const pts = dedupePoints(body.map((r) => (r[c] && /\d/.test(r[c]) ? [normMonth(r[0]), r[c].trim()] : null)));
      if (pts.length >= MIN_POINTS) items.push({ source_hint: 'table:' + c, scope_text: null, ptype_text: header[c] || null,
        unit_text: (String(header[c] || '').match(/\(([^)]+)\)/) || [])[1] || null, points: pts });
    }
    return items;
  }

  /* Unit label near a price chart in page text, e.g. 'triệu/m²'. */
  function unitFromText(text) {
    const m = String(text || '').match(/(triệu|tr|tỷ|nghìn|đ|vnđ|vnd)\s*\/\s*m(?:²|2)/i);
    return m ? m[0] : null;
  }

  function siteOf(host) {
    const h = String(host || '').replace(/^www\./, '');
    if (/batdongsan/.test(h)) return 'batdongsan';
    if (/guland/.test(h)) return 'guland';
    return h.split('.')[0] || 'unknown';
  }

  const helpers = { fold, normMonth, pointFrom, pointsFrom, dedupePoints, highchartsSeries, chartjsSeries, echartsOption,
    findSeriesInJson, tableSeries, unitFromText, siteOf };
  const G = typeof globalThis !== 'undefined' ? globalThis : (typeof window !== 'undefined' ? window : {});
  if (G.__PRICEHISTORY_EXPORT__) return helpers;

  /* ---- run in the page ---- */
  const warnings = [];
  let items = [];
  const W = typeof window !== 'undefined' ? window : G;
  const D = typeof document !== 'undefined' ? document : null;
  const safe = (name, fn) => { try { const r = fn(); if (r && r.length) items = items.concat(r); } catch (e) { warnings.push(name + ': ' + e.message); } };
  safe('highcharts', () => highchartsSeries(W.Highcharts));
  safe('chartjs', () => chartjsSeries(W.Chart));
  safe('echarts', () => {
    if (!W.echarts || !W.echarts.getInstanceByDom || !D) return [];
    let out = [];
    Array.prototype.forEach.call(D.querySelectorAll('div,canvas') || [], (el, i) => {
      const inst = W.echarts.getInstanceByDom(el);
      if (inst && inst.getOption) out = out.concat(echartsOption(inst.getOption(), i));
    });
    return out;
  });
  if (!items.length) {
    safe('window-state', () => {
      let out = [];
      ['__NEXT_DATA__', '__NUXT__', '__INITIAL_STATE__', '__APOLLO_STATE__', '__PRELOADED_STATE__'].forEach((k) => {
        if (W[k] && typeof W[k] === 'object') out = out.concat(findSeriesInJson(W[k], k));
      });
      return out;
    });
    safe('script-json', () => {
      if (!D) return [];
      let out = [];
      Array.prototype.forEach.call(D.querySelectorAll('script[type="application/json"],script[type="application/ld+json"],script#__NEXT_DATA__') || [], (s, i) => {
        try { out = out.concat(findSeriesInJson(JSON.parse(s.textContent), 'script' + i)); } catch (e) { /* not JSON */ }
      });
      return out;
    });
  }
  if (!items.length) {
    safe('tables', () => {
      if (!D) return [];
      let out = [];
      Array.prototype.forEach.call(D.querySelectorAll('table') || [], (t) => {
        const rows = Array.prototype.map.call(t.querySelectorAll('tr'), (tr) =>
          Array.prototype.map.call(tr.querySelectorAll('th,td'), (c) => (c.innerText || c.textContent || '').trim()));
        out = out.concat(tableSeries(rows));
      });
      return out;
    });
  }
  const bodyText = D && D.body ? (D.body.innerText || '') : '';
  const pageUnit = unitFromText(bodyText);
  const h1 = D && D.querySelector ? D.querySelector('h1') : null;
  const pageScope = (h1 && (h1.innerText || h1.textContent || '').trim()) || (D && D.title) || null;
  items.forEach((it) => {
    if (!it.unit_text) it.unit_text = pageUnit;
    if (!it.scope_text) it.scope_text = pageScope;
  });
  if (!items.length) warnings.push('no price-history series found (scroll the chart into view, or fall back to get_page_text)');
  if (items.some((it) => !it.unit_text)) warnings.push('unit label not found for some series');
  const loc = typeof location !== 'undefined' ? location : { href: null, hostname: '' };
  return { site: siteOf(loc.hostname), url: loc.href, seen_at: new Date().toISOString(), kind: 'series', items, warnings };
})()
