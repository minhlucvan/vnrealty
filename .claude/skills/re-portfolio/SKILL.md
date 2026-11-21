---
name: re-portfolio
description: Operate owned units: units, leases, tenants, rent roll, monthly close (paid, partial, overdue), expenses, renewals, deposits, and portfolio value, debt, equity and yield. Triggers on "danh mục", "tiền thuê tháng này", "khách thuê", "portfolio", "rent roll", "monthly close".
when_to_use: Owner-operator bookkeeping and the monthly close.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-portfolio

- Setup:
  - `unit add …`
  - `lease add <unit> --tenant <alias> --rent … --start …`
  - `txn add <unit> <amount> <category> --at …`

  Use tenant aliases, not full names, unless the user wants names (data/ is private either way).
- Run `portfolio --json` for the summary and `portfolio close <YYYY-MM> --json` for the monthly close (arrears with
  days late, expenses, net cash, renewals due within 60 days, alerts).
- Run `report portfolio` for the dashboard. Follow with `re-risk` monthly.
