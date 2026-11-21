/* Browser port of libs/riskbudget/property_deal.py (schedule, irr_monthly, analyse, stress). Keys are the Python
   field names, so check_deal_parity.py can compare the two. */
const DEAL_DEFAULT = {price: 3e9, buy_costs: 0.015, renovation: 200e6, value_after: 3.3e9, lease_up_months: 3, build_cost: 0, build_months: 0, building_life_years: 0,
  loan: 1.5e9, teaser_rate: 0.07, teaser_years: 2, float_rate: 0.105, grace_months: 0, term_years: 20, rent: 25e6, rent_growth: 0.03, ramp_months: 0, vacancy: 0.08,
  management: 0.05, cogs: 0, staff: 0, running_costs: 2e6, cost_growth: 0.035, rent_tax: 0.10, price_growth: 0.05, hold_years: 10, sell_costs: 0.03, hurdle: 0.10, dscr_min: 1.2};
function dPay(bal, rate, months) { const r = rate / 12; if (months <= 0) return bal; return r === 0 ? bal / months : bal * r / (1 - Math.pow(1 + r, -months)); }
function dCost(d) { return d.price * (1 + d.buy_costs) + d.renovation + d.build_cost; }
function dLoan(d) { return Math.max(0, Math.min(d.loan, dCost(d))); }
function dealScheduleAll(d) {
  const nTerm = d.term_years * 12, loan = dLoan(d), own = dCost(d) - loan;
  const spend0 = d.price * (1 + d.buy_costs) + d.renovation + (d.build_months <= 0 ? d.build_cost : 0), eq0 = Math.min(spend0, own);
  let ownLeft = own - eq0, bal = spend0 - eq0, built = d.build_months <= 0 ? d.build_cost : 0, pay = 0, curRate = null;
  const rows = [{month: 0, spend: eq0, draw: bal, balance: bal}], ioEnd = Math.max(d.grace_months, d.build_months), openM = d.build_months + d.lease_up_months;
  for (let t = 1; t <= d.hold_years * 12; t++) {
    let spend = 0, draw = 0;
    if (d.build_months > 0 && t <= d.build_months) { const need = d.build_cost / d.build_months; spend = Math.min(need, ownLeft); ownLeft -= spend; draw = need - spend; bal += draw; built += need; }
    const rate = t <= d.teaser_years * 12 ? d.teaser_rate : d.float_rate, interest = bal * rate / 12;
    let payment;
    if (bal <= 0) payment = 0;
    else if (t <= ioEnd) payment = interest;
    else { if (rate !== curRate || t === ioEnd + 1) { pay = dPay(bal, rate, nTerm - (t - 1)); curRate = rate; } payment = t <= nTerm ? Math.min(pay, bal + interest) : 0; }
    const principal = payment > 0 ? payment - interest : 0;
    bal = Math.max(0, bal - principal);
    const y = Math.floor((t - 1) / 12);
    let gross = 0;
    if (t > openM) { const ramp = d.ramp_months > 0 ? Math.min(1, (t - openM) / d.ramp_months) : 1; gross = d.rent * Math.pow(1 + d.rent_growth, y) * ramp; }
    const fixed = (t > d.build_months ? d.running_costs : 0) + (t > openM ? d.staff : 0);
    const collected = gross * (1 - d.vacancy), opex = collected * (d.management + d.cogs) + fixed * Math.pow(1 + d.cost_growth, y);
    const tax = collected * d.rent_tax, noi = collected - opex - tax, g = Math.pow(1 + d.price_growth, t / 12);
    const bfac = d.building_life_years > 0 ? Math.pow(1 + d.cost_growth, t / 12) * Math.max(0, 1 - (Math.max(0, t - d.build_months) / 12) / d.building_life_years) : g;
    rows.push({month: t, rate, payment, interest, principal, balance: bal, rent: gross, collected, opex, tax, noi, cash: noi - payment, spend, draw, net: noi - payment - spend, value: d.value_after * g + built * bfac});
  }
  return rows;
}
function dealSchedule(d) { return dealScheduleAll(d).slice(1); }
function irrMonthly(cfs) {
  const npv = r => cfs.reduce((s, c, t) => s + c / Math.pow(1 + r, t), 0);
  let lo = -0.5, hi = 0.5;
  if (npv(lo) * npv(hi) > 0) return null;
  for (let k = 0; k < 200; k++) { const mid = (lo + hi) / 2; if (npv(lo) * npv(mid) <= 0) hi = mid; else lo = mid; }
  return Math.pow(1 + (lo + hi) / 2, 12) - 1;
}
function dealStable(d) {
  const collected = d.rent * (1 - d.vacancy), noi = collected * (1 - d.management - d.cogs - d.rent_tax) - d.running_costs - d.staff, loan = dLoan(d);
  const ds = loan > 0 ? dPay(loan, d.float_rate, d.term_years * 12) : 0;
  return {rent: d.rent, collected, noi, debt_service: ds, cash: noi - ds, dscr: ds > 0 ? noi / ds : null};
}
function dealAnalyse(d) {
  const all = dealScheduleAll(d), r0 = all[0], rows = all.slice(1), cost = dCost(d), loan = dLoan(d), cashIn = cost - loan;
  const last = rows[rows.length - 1], saleGross = last.value, saleNet = saleGross * (1 - d.sell_costs) - last.balance;
  const eq = [-r0.spend].concat(rows.map(r => r.net)); eq[eq.length - 1] += saleNet;
  const un = [-(d.price * (1 + d.buy_costs) + d.renovation + (d.build_months <= 0 ? d.build_cost : 0))].concat(rows.map(r => r.noi - r.spend - r.draw)); un[un.length - 1] += saleGross * (1 - d.sell_costs);
  const irr = irrMonthly(eq), mh = Math.pow(1 + d.hurdle, 1 / 12) - 1, npv = eq.reduce((s, c, t) => s + c / Math.pow(1 + mh, t), 0), st = dealStable(d);
  const share = 1 - d.management - d.cogs - d.rent_tax, fixed = d.running_costs + d.staff + st.debt_service, k = (1 - d.vacancy) * share;
  const beRent = k > 0 ? fixed / k : null, beOcc = d.rent * share > 0 ? fixed / (d.rent * share) : null;
  const ann = dPay(1, d.float_rate, d.term_years * 12), loanMax = d.dscr_min > 0 && ann > 0 ? Math.max(0, st.noi / d.dscr_min / ann) : null;
  let cum = -r0.spend, payback = null;
  rows.forEach(r => { cum += r.net; if (payback === null && cum >= 0) payback = r.month; });
  const interest = rows.filter(r => r.payment > 0).reduce((s, r) => s + r.interest, 0);
  const split = {rent: rows.reduce((s, r) => s + r.noi, 0), interest: -interest, appreciation: saleGross - d.value_after - d.build_cost,
    renovation_gain: d.value_after - d.price - d.renovation, costs: -(d.price * d.buy_costs + saleGross * d.sell_costs)};
  const years = [];
  for (let y = 0; y < d.hold_years; y++) {
    const rs = rows.slice(y * 12, (y + 1) * 12), e = rs[rs.length - 1], sum = f => rs.reduce((s, r) => s + f(r), 0);
    years.push({year: y + 1, rent: sum(r => r.collected), opex: sum(r => r.opex + r.tax), noi: sum(r => r.noi), debt_service: sum(r => r.payment),
      interest: sum(r => r.payment > 0 ? r.interest : 0), build: sum(r => r.spend + r.draw), cash: sum(r => r.net), balance: e.balance, value: e.value, equity: e.value - e.balance, rate: e.rate});
  }
  const reasons = [];
  if (irr === null || irr < d.hurdle) reasons.push('irr');
  if (st.cash < 0) reasons.push('cash');
  if (st.dscr !== null && st.dscr < d.dscr_min) reasons.push('dscr');
  const after = rows.slice(d.build_months + d.lease_up_months + d.ramp_months), worst = after.length ? Math.min(...after.map(r => r.cash)) : 0;
  let c = 0, peak = 0; eq.slice(0, -1).forEach(v => { c += v; peak = Math.min(peak, c); });
  return {cost, cash_in: cashIn, loan_used: loan, ltv: d.price ? loan / d.price : 0, ltc: cost ? loan / cost : 0, stable: st,
    yield_gross: d.price ? d.rent * 12 / d.price : 0, yield_on_cost: cost ? st.noi * 12 / cost : 0, cash_on_cash: cashIn > 0 ? st.cash * 12 / cashIn : null,
    irr, irr_unlevered: irrMonthly(un), npv, multiple: cashIn > 0 ? eq.slice(1).reduce((s, x) => s + x, 0) / cashIn : null,
    profit: eq.reduce((s, x) => s + x, 0), payback_month: payback, break_even_rent: beRent, break_even_occupancy: beOcc, loan_max: loanMax,
    worst_month_cash: worst, peak_cash_out: -peak, open_month: d.build_months + d.lease_up_months, sale_net: saleNet, split, years, rows, passes: reasons.length === 0, reasons};
}
function dealStress(d) {
  const w = o => dealAnalyse(Object.assign({}, d, o));
  return {rate_up_3: w({float_rate: d.float_rate + 0.03}), rent_down_20: w({rent: d.rent * 0.8}), no_price_growth: w({price_growth: 0}), vacancy_25: w({vacancy: 0.25})};
}
if (typeof module !== 'undefined') module.exports = {dealAnalyse, dealStress, dealSchedule, dealScheduleAll, dealStable, irrMonthly, DEAL_DEFAULT};
