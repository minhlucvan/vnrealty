// Plain-node tests for the pure helpers in browser/pricehistory.js. Run: node tests/js/test_pricehistory.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', '..', 'browser', 'pricehistory.js'), 'utf8');
globalThis.__PRICEHISTORY_EXPORT__ = true;
const H = eval(src);
delete globalThis.__PRICEHISTORY_EXPORT__;

let n = 0;
function t(name, fn) { fn(); n++; }

t('normMonth', () => {
  assert.strictEqual(H.normMonth('2025-03'), '2025-03');
  assert.strictEqual(H.normMonth('T3/2025'), '2025-03');
  assert.strictEqual(H.normMonth('Tháng 11/2024'), '2024-11');
  assert.strictEqual(H.normMonth('Q2/2025'), '2025-05');
  assert.strictEqual(H.normMonth('15/03/2025'), '2025-03');
  assert.strictEqual(H.normMonth(Date.UTC(2025, 2, 1)), '2025-03');
  assert.strictEqual(H.normMonth('abc'), null);
  assert.strictEqual(H.normMonth(42), null);
});

t('pointFrom objects and arrays', () => {
  assert.deepStrictEqual(H.pointFrom({ month: '03/2025', avgPrice: 41.5 }), ['2025-03', 41.5]);
  assert.deepStrictEqual(H.pointFrom({ Date: '2025-04-01', Value: '42,1' }), ['2025-04', '42,1']);
  assert.deepStrictEqual(H.pointFrom([Date.UTC(2025, 4, 1), 43]), ['2025-05', 43]);
  assert.strictEqual(H.pointFrom({ foo: 1 }), null);
  assert.deepStrictEqual(H.dedupePoints([['2025-02', 2], ['2025-01', 1], ['2025-02', 3], ['2025-03', null]]),
    [['2025-01', 1], ['2025-02', 3]]);
});

t('highcharts', () => {
  const HC = { charts: [undefined, {
    title: { textStr: 'Giá đất Ngũ Hành Sơn' }, xAxis: [{ categories: ['T1/2025', 'T2/2025', 'T3/2025'] }],
    yAxis: [{ options: { title: { text: 'triệu/m²' } } }],
    series: [{ name: 'Đất nền', data: [{ category: 'T1/2025', y: 40 }, { category: 'T2/2025', y: 41 }, { category: 'T3/2025', y: 42 }] },
             { name: 'short', data: [{ x: 1, y: 2 }] }] }] };
  const r = H.highchartsSeries(HC);
  assert.strictEqual(r.length, 1);
  assert.strictEqual(r[0].ptype_text, 'Đất nền');
  assert.strictEqual(r[0].unit_text, 'triệu/m²');
  assert.deepStrictEqual(r[0].points, [['2025-01', 40], ['2025-02', 41], ['2025-03', 42]]);
  const r2 = H.highchartsSeries({ charts: [{ series: [{ name: 'x', data: [
    { x: Date.UTC(2024, 0, 1), y: 1 }, { x: Date.UTC(2024, 1, 1), y: 2 }, { x: Date.UTC(2024, 2, 1), y: 3 }] }] }] });
  assert.strictEqual(r2[0].points[2][0], '2024-03');
});

t('chartjs v2 and v3', () => {
  const ds = { labels: ['01/2025', '02/2025', '03/2025'], datasets: [{ label: 'Nhà phố', data: [60, 61, 62.5] }] };
  assert.strictEqual(H.chartjsSeries({ instances: { 0: { config: { data: ds } } } })[0].points.length, 3);
  assert.strictEqual(H.chartjsSeries({ instances: [{ data: ds }] })[0].ptype_text, 'Nhà phố');
  assert.deepStrictEqual(H.chartjsSeries(undefined), []);
});

t('echarts option', () => {
  const r = H.echartsOption({ title: [{ text: 'Hòa Quý' }], xAxis: [{ data: ['2025-01', '2025-02', '2025-03'] }],
    yAxis: { name: 'tr/m2' }, series: [{ name: 'Đất', data: [30, 31, 32] }, { data: [['2025-01', 5], ['2025-02', 6], ['2025-03', 7]] }] }, 0);
  assert.strictEqual(r.length, 2);
  assert.strictEqual(r[0].scope_text, 'Hòa Quý');
  assert.deepStrictEqual(r[1].points[0], ['2025-01', 5]);
});

t('embedded json search', () => {
  const state = { props: { pageProps: { chart: { title: 'Sơn Trà', unit: 'triệu/m²', name: 'Căn hộ',
    items: [{ date: '2025-01-01', price: 50 }, { date: '2025-02-01', price: 51 }, { date: '2025-03-01', price: 52 }] },
    other: [1, 2, 3] } } };
  const r = H.findSeriesInJson(state, '__NEXT_DATA__');
  assert.strictEqual(r.length, 1);
  assert.strictEqual(r[0].unit_text, 'triệu/m²');
  assert.strictEqual(r[0].scope_text, 'Sơn Trà');
  assert.strictEqual(r[0].ptype_text, 'Căn hộ');
  assert.ok(r[0].source_hint.indexOf('chart.items') > 0);
  const cyc = {}; cyc.self = cyc;
  assert.deepStrictEqual(H.findSeriesInJson(cyc), []);
});

t('table fallback and helpers', () => {
  const r = H.tableSeries([['Thời gian', 'Giá TB (triệu/m²)', 'Ghi chú'], ['T1/2025', '40,5', ''], ['T2/2025', '41', ''],
    ['T3/2025', '41,8', 'x'], ['Tổng', '', '']]);
  assert.strictEqual(r.length, 1);
  assert.strictEqual(r[0].unit_text, 'triệu/m²');
  assert.deepStrictEqual(r[0].points[0], ['2025-01', '40,5']);
  assert.strictEqual(H.unitFromText('Giá trung bình 45 triệu/m² tại'), 'triệu/m²');
  assert.strictEqual(H.siteOf('www.guland.vn'), 'guland');
  assert.strictEqual(H.siteOf('batdongsan.com.vn'), 'batdongsan');
});

console.log(JSON.stringify({ passed: n }));
