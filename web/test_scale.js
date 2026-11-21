/* Tests for scale.js (the portfolio ladder on the real-estate page).
     node docs/vn30f-book/build/test_scale.js
   The anchor: a book of ONE unit, bought at month 0 and held to the deal's own horizon, must end with exactly the
   cash the deal engine says that deal makes (dealAnalyse.profit) — the ladder adds no arithmetic of its own. */
const assert = require('assert');
const {dealAnalyse, DEAL_DEFAULT} = require('./deal.js');
const {scaleRun} = require('./scale.js');

/* DEAL_DEFAULT's own DSCR is about 1.17, under its 1.2 floor, so the ladder would (correctly) never buy it. */
const D = Object.assign({}, DEAL_DEFAULT, {dscr_min: 0});
const near = (a, b, tol, msg) => assert.ok(Math.abs(a - b) <= tol * Math.max(1, Math.abs(b)), `${msg}: ${a} vs ${b}`);
const solo = {cash0: 5e9, save_month: 0, horizon_years: DEAL_DEFAULT.hold_years, max_units: 1, reserve_months: 0, refi_years: 0, ltv_cap: 1, mgr_every: 0, last_buy_years: 0};
let n = 0;
function test(name, fn) { fn(); n++; console.log('ok', name); }

test('a unit over the DSCR floor is bought with the loan cut to the floor, not refused', () => {
  const r = scaleRun(DEAL_DEFAULT, solo), a = dealAnalyse(DEAL_DEFAULT);   // its own DSCR is about 1.17 against a 1.2 floor
  assert.ok(a.stable.dscr < DEAL_DEFAULT.dscr_min);
  assert.strictEqual(r.buys.length, 1);
  near(r.buys[0].loan, a.loan_max, 1e-9, 'loan is the DSCR maximum');
  near(r.buys[0].dscr, DEAL_DEFAULT.dscr_min, 1e-6, 'DSCR sits on the floor');
});

test('one unit held to the horizon reproduces dealAnalyse', () => {
  const deals = [D, Object.assign({}, D, {loan: 0}),
    Object.assign({}, D, {price: 2e9, value_after: 2e9, renovation: 0, build_cost: 1.2e9, build_months: 12, building_life_years: 30, loan: 1.5e9, rent: 30e6}),
    Object.assign({}, D, {grace_months: 12, teaser_years: 3, lease_up_months: 6, hold_years: 12})];
  deals.forEach((d, i) => {
    const r = scaleRun(d, Object.assign({}, solo, {horizon_years: d.hold_years})), a = dealAnalyse(d);
    assert.strictEqual(r.buys.length, 1, `deal ${i} buys`);
    assert.strictEqual(r.buys[0].month, 0);
    near(r.end.net_worth - solo.cash0, a.profit, 1e-9, `deal ${i} profit`);
  });
});

test('no money, no purchase, and the reason is cash', () => {
  const r = scaleRun(D, Object.assign({}, solo, {cash0: 1e8}));
  assert.strictEqual(r.buys.length, 0);
  assert.ok(r.blocked.cash > 0);
  assert.strictEqual(r.end.units, 0);
});

test('a property that loses money before any loan is never bought', () => {
  const r = scaleRun(Object.assign({}, D, {dscr_min: 1.2, rent: 1e6}), solo);
  assert.strictEqual(r.buys.length, 0);
  assert.ok(r.blocked.noi > 0);
});

test('an LTV cap below the deal\'s loan share blocks levered purchases', () => {
  const r = scaleRun(D, Object.assign({}, solo, {ltv_cap: 0.2}));
  assert.strictEqual(r.buys.length, 0);
  assert.ok(r.blocked.ltv > 0);
});

test('more savings never buys fewer units', () => {
  const base = Object.assign({}, solo, {cash0: 2e9, max_units: 10, horizon_years: 15, last_buy_years: 2});
  const lo = scaleRun(D, Object.assign({}, base, {save_month: 10e6})), hi = scaleRun(D, Object.assign({}, base, {save_month: 60e6}));
  assert.ok(hi.end.units >= lo.end.units, `${hi.end.units} >= ${lo.end.units}`);
  assert.ok(hi.end.units > 1);
});

test('a refinance pulls cash out and adds debt in that month', () => {
  const s = Object.assign({}, solo, {refi_years: 5, refi_ltv: 0.7, refi_cost: 0.01});
  const r = scaleRun(D, s), m = r.months[60], prev = r.months[59];
  assert.ok(m.refi_in > 0);
  assert.ok(m.debt > prev.debt);
  near(m.debt / m.value, 0.7, 1e-9, 'debt reaches the refinance LTV');
});

test('managers are paid only past self-management', () => {
  const r = scaleRun(D, Object.assign({}, solo, {cash0: 50e9, max_units: 9, mgr_every: 4, mgr_cost: 10e6, horizon_years: 10}));
  const at = k => r.months.find(m => m.units === k);
  assert.strictEqual(at(4).managers, 0);
  assert.strictEqual(at(5).managers, 1);
  assert.strictEqual(at(9).managers, 2);
});

test('purchases stop at last_buy_years before the horizon', () => {
  const r = scaleRun(D, Object.assign({}, solo, {cash0: 50e9, max_units: 1000, horizon_years: 10, last_buy_years: 3}));
  assert.ok(r.buys.every(b => b.month <= 84));
});
console.log(`${n} passed`);
