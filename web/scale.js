/* Portfolio ladder: grow a real-estate business by repeating one deal (deal.js) as the unit.

   Every unit is priced by dealScheduleAll, so a book of one unit held to the deal's own horizon reproduces
   dealAnalyse exactly (test_scale.js pins that). Month by month:
     1. each owned unit pays its month's equity cash flow (NOI − mortgage − own build money), and any cash-out
        refinance loan takes its payment;
     2. savings come in; property managers are paid once the book outgrows self-management;
     3. a refinance fires on a unit when it reaches refi_years: new debt up to refi_ltv of today's value;
     4. one new unit is bought when ALL hold: units < max_units, the unit earns a positive NOI, cash after its peak equity need still covers
        reserve_months of the whole book's debt service, the unit's own DSCR clears dscr_min, and portfolio LTV
        after the purchase stays at or under ltv_cap.
   A unit bought later costs more: price-type fields move with price_growth, rent with rent_growth, costs with
   cost_growth, and the loan keeps the same share of the price — cut to the DSCR maximum when that is lower, as a bank
   would size it. Needs deal.js loaded first. */
const SCALE_DEFAULT = {cash0: 2e9, save_month: 20e6, horizon_years: 15, max_units: 8, reserve_months: 6, refi_years: 5, refi_ltv: 0.5,
  refi_cost: 0.01, ltv_cap: 0.6, mgr_every: 4, mgr_cost: 12e6, target_month: 50e6, last_buy_years: 2};
const _deal = typeof module !== 'undefined' && typeof dealScheduleAll === 'undefined' ? require('./deal.js') : null;
const _sched = _deal ? _deal.dealScheduleAll : (typeof dealScheduleAll !== 'undefined' ? dealScheduleAll : null);
const _anal = _deal ? _deal.dealAnalyse : (typeof dealAnalyse !== 'undefined' ? dealAnalyse : null);
function sPay(bal, rate, months) { const r = rate / 12; if (months <= 0) return bal; return r === 0 ? bal / months : bal * r / (1 - Math.pow(1 + r, -months)); }
function scaleUnit(d, t) {
  const gp = Math.pow(1 + d.price_growth, t / 12), gr = Math.pow(1 + d.rent_growth, t / 12), gc = Math.pow(1 + d.cost_growth, t / 12);
  return Object.assign({}, d, {price: d.price * gp, value_after: d.value_after * gp, renovation: d.renovation * gc, build_cost: d.build_cost * gc,
    loan: d.loan * gp, rent: d.rent * gr, running_costs: d.running_costs * gc, staff: d.staff * gc});
}
function scaleRun(d, s) {
  s = Object.assign({}, SCALE_DEFAULT, s);
  const H = Math.round(s.horizon_years * 12), lastBuy = H - Math.round(s.last_buy_years * 12), units = [], buys = [], months = [], blocked = {};
  let cash = s.cash0, targetMonth = null;
  const managers = n => s.mgr_every > 0 ? Math.max(0, Math.ceil(n / s.mgr_every) - 1) : 0;
  for (let t = 0; t <= H; t++) {
    let noi = 0, ds = 0, flow = 0, value = 0, debt = 0, refiIn = 0;
    units.forEach(u => {
      const k = t - u.month, r = u.rows[k];
      if (k >= 1) {
        flow += r.net; noi += r.noi; ds += r.payment;
        if (u.refi > 0) { const i = u.refi * u.refiRate / 12, p = Math.min(u.refiPay, u.refi + i); u.refi = Math.max(0, u.refi - (p - i)); flow -= p; ds += p; }
      }
      if (s.refi_years > 0 && k === Math.round(s.refi_years * 12) && k >= u.openM) {
        const room = r.value * s.refi_ltv - r.balance - u.refi;
        if (room > 0) { u.refi += room; u.refiRate = u.d.float_rate; u.refiPay = sPay(u.refi, u.refiRate, u.d.term_years * 12); refiIn += room * (1 - s.refi_cost); }
      }
      value += r.value; debt += r.balance + u.refi;
    });
    const overhead = t >= 1 ? managers(units.length) * s.mgr_cost * Math.pow(1 + d.cost_growth, t / 12) : 0, save = t >= 1 ? s.save_month : 0;
    cash += flow + save - overhead + refiIn;
    const opCash = noi - ds - overhead;
    if (targetMonth === null && t >= 1 && units.length && opCash >= s.target_month) targetMonth = t;
    let bought = null;
    if (units.length < s.max_units && t <= lastBuy) {
      /* the bank sizes the loan: the deal's share of the price, cut to what the DSCR floor allows, so a unit that would
         fail the floor is bought with a bigger down payment rather than refused */
      let ud = scaleUnit(d, t), a = _anal(ud);
      if (a.loan_max !== null && ud.loan > a.loan_max) { ud = Object.assign({}, ud, {loan: a.loan_max}); a = _anal(ud); }
      const rows = _sched(Object.assign({}, ud, {hold_years: Math.max(1, Math.ceil((H - t) / 12))}));
      const dsNext = ds + a.stable.debt_service, reserve = s.reserve_months * dsNext, uval = rows[0].value || (ud.value_after + ud.build_cost);
      const ltvAfter = (debt + a.loan_used) / (value + ud.value_after + ud.build_cost);
      const why = a.stable.noi <= 0 ? 'noi' : cash - a.peak_cash_out < reserve ? 'cash' : (a.stable.dscr !== null && a.stable.dscr < ud.dscr_min - 1e-9) ? 'dscr' : ltvAfter > s.ltv_cap + 1e-9 ? 'ltv' : null;
      if (why) blocked[why] = (blocked[why] || 0) + 1;
      else {
        cash -= rows[0].spend;
        units.push({month: t, d: ud, rows, refi: 0, refiRate: 0, refiPay: 0, openM: ud.build_months + ud.lease_up_months});
        bought = {month: t, price: ud.price, cost: a.cost, loan: a.loan_used, need: a.peak_cash_out, cash_after: cash, dscr: a.stable.dscr, irr: a.irr};
        buys.push(bought); value += uval; debt += rows[0].balance;
      }
    }
    months.push({month: t, units: units.length, value, debt, cash, noi, debt_service: ds, overhead, op_cash: opCash, refi_in: refiIn,
      equity: value - debt + cash, ltv: value > 0 ? debt / value : 0, dscr: ds > 0 ? noi / ds : null, managers: managers(units.length), bought});
  }
  const e = months[H], sellNet = units.reduce((a, u) => { const r = u.rows[H - u.month]; return a + r.value * (1 - u.d.sell_costs) - r.balance - u.refi; }, 0);
  const years = [];
  for (let y = 1; y <= s.horizon_years; y++) {
    const ms = months.slice((y - 1) * 12 + 1, y * 12 + 1), m = ms[ms.length - 1], sum = f => ms.reduce((a, x) => a + f(x), 0);
    years.push({year: y, units: m.units, value: m.value, debt: m.debt, cash: m.cash, equity: m.equity, ltv: m.ltv, noi: sum(x => x.noi), debt_service: sum(x => x.debt_service),
      overhead: sum(x => x.overhead), op_cash: sum(x => x.op_cash), refi_in: sum(x => x.refi_in), bought: ms.filter(x => x.bought).length + (y === 1 && months[0].bought ? 1 : 0), managers: m.managers});
  }
  return {buys, months, years, blocked, target_month: targetMonth, horizon_months: H,
    end: {units: e.units, value: e.value, debt: e.debt, cash: e.cash, equity: e.equity, net_worth: e.cash + sellNet, monthly_cash: e.op_cash, ltv: e.ltv, dscr: e.dscr, managers: e.managers}};
}
if (typeof module !== 'undefined') module.exports = {scaleRun, scaleUnit, SCALE_DEFAULT};
