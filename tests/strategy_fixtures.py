"""Synthetic opportunity and assumptions shared by the strategy tests (no real listing, no personal data)."""
M = 1e6

OPP = {"price": 3e9, "market_value": 3.3e9, "area_m2": 200, "ward": "w1", "ptype": "house"}

FULL = {
    "hurdle": 0.10, "hold_years": 8, "price_growth": 0.05, "rent_growth": 0.03,
    # buy_hold / long lease
    "rent": 15 * M, "renovation": 150 * M, "running_costs": 1.5 * M,
    # build / jv (Lot fields)
    "buildable_ratio": 0.8, "max_floors": 4, "build_cost_m2": 6.5 * M, "unit_size_m2": 28, "unit_rent": 5 * M,
    "fit_out_per_unit": 35 * M, "running_cost_per_unit": 0.7 * M, "build_ltv": 0.0,
    # flip
    "flip_renovation": 300 * M, "after_repair_value": 3.9e9,
    # subdivide
    "lots": 4, "lot_size_m2": 45, "small_lot_price_m2": 22 * M, "subdivision_cost": 250 * M,
    "subdivision_months": 9, "min_lot_m2": 40,
    # arbitrage
    "master_rent": 25 * M, "lease_years": 5, "arbitrage_fit_out": 400 * M, "sublet_mode": "chdv",
    # businesses
    "homestay_rooms": 6, "homestay_adr": 700e3, "homestay_occ": 0.6, "homestay_staff": 10 * M,
    "homestay_fit_out": 400 * M,
    "chdv_units": 8, "chdv_unit_rate": 6 * M, "chdv_occ": 0.85, "chdv_staff": 6 * M, "chdv_fit_out": 300 * M,
}
