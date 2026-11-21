---
name: re-portfolio
description: Operate owned units: units, leases, tenants, rent roll, monthly close (paid, partial, overdue), expenses, renewals, deposits, and portfolio value, debt, equity and yield. Triggers on "danh mục", "tiền thuê tháng này", "khách thuê", "portfolio", "rent roll", "monthly close".
when_to_use: Owner-operator bookkeeping and the monthly close.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-portfolio

- Setup:
  - `unit add <id> <name> --ptype … --ward … --cost … --bought-at … --loan …`
  - `lease add <unit> --tenant <alias> --rent … --start …`
  - `txn add <unit> <amount> <category> --at …`

  Use tenant aliases, not full names, unless the user wants names (data/ is private either way).
- Run `portfolio --json` for the summary and `portfolio close <YYYY-MM> --json` for the monthly close (arrears with
  days late, expenses, net cash, renewals due within 60 days, alerts).
- Run `report portfolio` for the dashboard. Follow with `re-risk` monthly.
- **One unit, everything:** `report asset <unit-id>` writes the asset page. It covers:
  - status alert and open actions;
  - value, range and your position (share, paid, gain, return a year);
  - how the value is built and its history;
  - plan options and what-ifs;
  - projection and sell-or-hold;
  - money, leases, timeline, due diligence, notes, images, a map of nearby projects, and documents.
- Owner records the database does not model go in the private `data/portfolio/<id>.json`: timeline, actions, documents,
  images, funding, gaps, `plan_sensitivities`, `project_setup`. The plan inputs go in `data/portfolio/<id>.plan.json`.
  Both are optional.
- The page carries owner records. It stays in `data/reports/`, which is private, and is never published.
