"""Check the browser ports (web/deal.js, web/scale.js) against the Python engine (vnrealty/deal).

Runs both on a grid of deals and ladders and fails on any difference beyond rounding. Needs node on PATH.
    python3 web/check_parity.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, replace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from vnrealty.deal.engine import Deal, analyse  # noqa: E402
from vnrealty.deal.scale import Scale, scale_run  # noqa: E402

base = Deal()
DEALS = [base, replace(base, loan=0.0), replace(base, grace_months=12, teaser_years=3, lease_up_months=6),
         replace(base, rent=12e6, price_growth=0.0), replace(base, term_years=8, hold_years=12, loan=2.2e9),
         replace(base, price=2e9, value_after=2e9, renovation=0.0, build_cost=1.2e9, build_months=12, building_life_years=30, loan=1.5e9, rent=30e6),
         replace(base, price=2e9, value_after=2e9, renovation=150e6, build_cost=1.8e9, build_months=9, building_life_years=25, loan=0.6e9,
                 rent=150e6, ramp_months=6, cogs=0.35, staff=25e6, management=0.0, rent_tax=0.045, vacancy=0.0)]
LADDERS = [Scale(), Scale(refi_years=0), Scale(cash0=5e9, max_units=12, save_month=40e6), Scale(ltv_cap=0.3, reserve_months=12)]
KEYS = ["cost", "cash_in", "loan_used", "peak_cash_out", "irr", "irr_unlevered", "npv", "profit", "payback_month",
        "break_even_rent", "loan_max", "sale_net"]
END = ["units", "value", "debt", "cash", "net_worth", "monthly_cash"]


def close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def main() -> int:
    py_deals = [{k: analyse(d)[k] for k in KEYS} for d in DEALS]
    py_lad = [{k: scale_run(DEALS[0], s)["end"][k] for k in END} for s in LADDERS]
    js = f"""
const {{dealAnalyse}} = require({json.dumps(os.path.join(HERE, 'deal.js'))});
const {{scaleRun}} = require({json.dumps(os.path.join(HERE, 'scale.js'))});
const deals = {json.dumps([asdict(d) for d in DEALS])}, ladders = {json.dumps([asdict(s) for s in LADDERS])};
const K = {json.dumps(KEYS)}, E = {json.dumps(END)};
console.log(JSON.stringify({{deals: deals.map(d => {{ const a = dealAnalyse(d); return Object.fromEntries(K.map(k => [k, a[k]])); }}),
  ladders: ladders.map(s => {{ const r = scaleRun(deals[0], s); return Object.fromEntries(E.map(k => [k, r.end[k]])); }})}}));
"""
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    bad = [(i, k, py_deals[i][k], out["deals"][i][k]) for i in range(len(DEALS)) for k in KEYS if not close(py_deals[i][k], out["deals"][i][k])]
    bad += [(f"ladder{i}", k, py_lad[i][k], out["ladders"][i][k]) for i in range(len(LADDERS)) for k in END if not close(py_lad[i][k], out["ladders"][i][k])]
    if bad:
        for b in bad[:20]:
            print("MISMATCH", b)
        return 1
    print(f"parity OK: {len(DEALS)} deals x {len(KEYS)} metrics, {len(LADDERS)} ladders x {len(END)} end values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
