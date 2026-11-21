// Plain-node tests for the pure helpers in browser/lib/core.js. Run: node tests/js/test_core.js
// Prints one JSON line {"sha1_phone": ...} at the end so the Python test can compare hashes with parse.phone_hash.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', '..', 'browser', 'lib', 'core.js'), 'utf8');
const C = new Function(src + '\nreturn {fold, parseLabelTable, fromJsonLd, latLngFromUrl, latLngFromText, siteIdFromUrl, guessDeal, sha1, phoneHash, stripPhones, phoneHashesIn, extractCardFields, parseZoningText, envelope};')();

let n = 0;
function t(name, fn) { fn(); n++; }

t('fold', () => {
  assert.strictEqual(C.fold('  Phường Hoà Quý  Đà Nẵng '), 'phuong hoa quy da nang');
  assert.strictEqual(C.fold('103 m²'), '103 m2');
});

t('parseLabelTable next-line and colon forms', () => {
  const r = C.parseLabelTable(['Mức giá', '3,25 tỷ', 'Diện tích', '103 m²', 'Mặt tiền: 5 m', 'Đường vào', '6 m',
    'Pháp lý', 'Sổ đỏ/ Sổ hồng', 'Hướng nhà: Đông Nam', 'Số tầng', '3 tầng', 'Số phòng ngủ', '4 phòng',
    'Địa chỉ: Hòa Quý, Ngũ Hành Sơn', 'Ngày đăng', '12/11/2026', 'Mã tin', '41234567']);
  assert.strictEqual(r.price, '3,25 tỷ');
  assert.strictEqual(r.area, '103 m²');
  assert.strictEqual(r.frontage, '5 m');
  assert.strictEqual(r.alley, '6 m');
  assert.strictEqual(r.legal, 'Sổ đỏ/ Sổ hồng');
  assert.strictEqual(r.direction, 'Đông Nam');
  assert.strictEqual(r.floors, '3 tầng');
  assert.strictEqual(r.bedrooms, '4 phòng');
  assert.strictEqual(r.address, 'Hòa Quý, Ngũ Hành Sơn');
  assert.strictEqual(r.posted, '12/11/2026');
  assert.strictEqual(r.site_id, '41234567');
});

t('parseLabelTable: a label followed by another label has no value', () => {
  const r = C.parseLabelTable(['Mức giá', 'Diện tích', '80 m2']);
  assert.strictEqual(r.price, undefined);
  assert.strictEqual(r.area, '80 m2');
});

t('parseLabelTable extra labels', () => {
  const r = C.parseLabelTable(['Đường trước nhà: 7m'], { alley: ['Đường trước nhà'] });
  assert.strictEqual(r.alley, '7m');
});

t('fromJsonLd', () => {
  const r = C.fromJsonLd({ '@context': 'https://schema.org', '@graph': [
    { '@type': 'BreadcrumbList', name: 'crumbs' },
    { '@type': 'RealEstateListing', name: 'Bán nhà kiệt 4m Hòa Quý', sku: '998877', datePosted: '2026-11-01',
      offers: { '@type': 'Offer', price: 3250000000, priceCurrency: 'VND' }, floorSize: { value: 100, unitCode: 'MTK' },
      address: { streetAddress: 'Kiệt 12 Lê Văn Hiến', addressLocality: 'Hòa Quý', addressRegion: 'Đà Nẵng' },
      geo: { latitude: '15.99', longitude: '108.25' } }] });
  assert.strictEqual(r.title, 'Bán nhà kiệt 4m Hòa Quý');
  assert.strictEqual(r.site_id, '998877');
  assert.strictEqual(r.price_text, '3250000000 đ');
  assert.strictEqual(r.area_text, '100 m2');
  assert.strictEqual(r.ward_raw, 'Hòa Quý');
  assert.strictEqual(r.address, 'Kiệt 12 Lê Văn Hiến, Hòa Quý, Đà Nẵng');
  assert.strictEqual(r.lat, 15.99);
  assert.deepStrictEqual(C.fromJsonLd(null), {});
});

t('latLngFromUrl', () => {
  assert.deepStrictEqual(C.latLngFromUrl('https://www.google.com/maps/place/X/@16.06,108.22,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d16.0612!4d108.2234'), { lat: 16.0612, lng: 108.2234 });
  assert.deepStrictEqual(C.latLngFromUrl('https://www.google.com/maps/@16.05,108.2,15z'), { lat: 16.05, lng: 108.2 });
  assert.deepStrictEqual(C.latLngFromUrl('https://maps.google.com/maps?q=16.0011,108.2611&z=15&output=embed'), { lat: 16.0011, lng: 108.2611 });
  assert.deepStrictEqual(C.latLngFromUrl('https://maps.google.com/maps?q=16.0011%2C108.2611'), { lat: 16.0011, lng: 108.2611 });
  assert.strictEqual(C.latLngFromUrl('https://example.com/no-coords'), null);
  assert.strictEqual(C.latLngFromUrl('https://x/@0,0,3z'), null);
});

t('latLngFromText', () => {
  assert.deepStrictEqual(C.latLngFromText('{"latitude":16.0544,"longitude":108.2022}'), { lat: 16.0544, lng: 108.2022 });
  assert.strictEqual(C.latLngFromText('nothing'), null);
});

t('siteIdFromUrl', () => {
  assert.strictEqual(C.siteIdFromUrl('https://batdongsan.com.vn/ban-nha-rieng-duong-x-phuong-hoa-quy-pr41234567', 'batdongsan'), '41234567');
  assert.strictEqual(C.siteIdFromUrl('https://www.nhatot.com/mua-ban-nha-dat-da-nang/123456789.htm', 'chotot'), '123456789');
  assert.strictEqual(C.siteIdFromUrl('https://alonhadat.com.vn/ban-dat-hoa-quy-12345678.html', 'alonhadat'), '12345678');
  assert.strictEqual(C.siteIdFromUrl('https://muaban.net/bat-dong-san/ban-nha-id71234567', 'muaban'), '71234567');
  assert.strictEqual(C.siteIdFromUrl('https://www.facebook.com/groups/123/posts/9876543210/', 'facebook'), '9876543210');
  assert.strictEqual(C.siteIdFromUrl('https://example.vn/tin/abc', 'generic'), null);
});

t('guessDeal', () => {
  assert.strictEqual(C.guessDeal('https://batdongsan.com.vn/cho-thue-nha-rieng-da-nang', ''), 'rent');
  assert.strictEqual(C.guessDeal('https://batdongsan.com.vn/ban-dat-da-nang', ''), 'sale');
  assert.strictEqual(C.guessDeal('https://x.vn/abc', 'hello'), null);
});

t('sha1 known vectors', () => {
  assert.strictEqual(C.sha1('abc'), 'a9993e364706816aba3e25717850c26c9cd0d89d');
  assert.strictEqual(C.sha1(''), 'da39a3ee5e6b4b0d3255bfef95601890afd80709');
  assert.strictEqual(C.sha1('The quick brown fox jumps over the lazy dog'), '2fd4e1c67a2d28fced849ee1bb76e7391b93eb12');
});

t('phones never leak', () => {
  assert.strictEqual(C.phoneHash('+84 900 000 001'), C.phoneHash('0900.000.001'));
  assert.strictEqual(C.phoneHash('12'), null);
  const s = C.stripPhones('Liên hệ 0900 000 001 hoặc 0900000002 nhé');
  assert.ok(!/0900 000 001|0900000002/.test(s), s);
  assert.ok(/\[phone:[0-9a-f]{8}\]/.test(s));
  assert.strictEqual(C.phoneHashesIn('0900 000 001, +84900000001').length, 1);
});

t('extractCardFields', () => {
  const r = C.extractCardFields('Bán nhà kiệt 4m Hòa Quý\n3,25 tỷ · 103 m² · 31,55 tr/m² · 3 PN\nNgũ Hành Sơn, Đà Nẵng\nĐăng hôm nay');
  assert.strictEqual(r.price_text, '3,25 tỷ');
  assert.strictEqual(r.area_text, '103 m²');
  assert.strictEqual(r.ppm2_text, '31,55 tr/m²');
  assert.strictEqual(r.bedrooms_text, '3');
  assert.strictEqual(C.extractCardFields('Giá: Thỏa thuận, 80 m2').price_text, 'Thỏa thuận');
  assert.strictEqual(C.extractCardFields('5x20m, 2 tỷ 350').price_text, '2 tỷ 350');
  assert.strictEqual(C.extractCardFields('5x20m, 2 tỷ 350').dims_text, '5x20m');
});

t('parseZoningText', () => {
  const r = C.parseZoningText('Thông tin quy hoạch\nThửa đất số 12, tờ bản đồ 34\nMục đích sử dụng: Đất ở đô thị (ODT)\nKý hiệu lô: ODT-05\nQuy hoạch phân khu ven biển Ngũ Hành Sơn\nQuyết định số 1234/QĐ-UBND ngày 01/02/2024\nMật độ xây dựng: 80%\nTầng cao: 5 tầng\nMột phần thuộc DGT');
  assert.deepStrictEqual(r.codes, ['ODT', 'DGT']);
  assert.strictEqual(r.land_use_text, 'Đất ở đô thị (ODT)');
  assert.ok(/^Quyết định số 1234/.test(r.decision), r.decision);
  assert.strictEqual(r.density_text, '80%');
  assert.strictEqual(r.height_text, '5 tầng');
  assert.strictEqual(r.in_plan_road, true);
  assert.deepStrictEqual(C.parseZoningText('').codes, []);
});

t('envelope', () => {
  const e = C.envelope('x', 'detail', [{ a: 1 }], [], 'https://x');
  assert.strictEqual(e.site, 'x');
  assert.ok(/^\d{4}-\d{2}-\d{2}T/.test(e.seen_at));
  assert.deepStrictEqual(Object.keys(e).sort(), ['items', 'kind', 'seen_at', 'site', 'url', 'warnings']);
});

console.log(JSON.stringify({ ok: n, sha1_phone: C.phoneHash('0900 000 001') }));
