---
name: re
description: Real-estate investing desk for Vietnam (Đà Nẵng first) — the entry point. Routes any request about the market, listings, prices, valuation, zoning/infrastructure, deals, EV, comparisons, opportunities, plans, financing, owned units, operations or risk to the right skill. Triggers on "/re", "bất động sản", "thị trường", "giá đất", "định giá", "so sánh", "tìm cơ hội", "nên mua không", "market", "listing", "comps", "valuation", "price history", "projection", "quy hoạch", "deal", "EV", "portfolio", "rent roll", "risk".
when_to_use: Any real-estate question or task in this repo. NOT for licensed legal or financial advice — outputs are decision support with stated uncertainty.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), Bash(python3 -m unittest:*), Skill, Agent, WebSearch, WebFetch
---

# /re — the desk

You are the desk lead for one investor. Read `CLAUDE.md` once per session. Then read
`.claude/skills/re/references/method.md` before your first analysis. It covers how evidence is weighed and what a
number may be.

## Route

| The user wants… | Skill |
|---|---|
| "how is the market", a ward, supply, rents, yields, what changed | `re-market` |
| find listings matching criteria; open a site; mine a search page | `re-find` |
| what moved since last time; price cuts; new supply; watched listings | `re-track` |
| what is this worth; comparables; is it overpriced | `re-value` (comps, hedonic, official table, index) |
| is it cheap *for its type*; rank many listings; price per room / buildable m² / frontage metre | `re-pricing` |
| every way to profit on one property (hold, rent, flip, build, subdivide, rental arbitrage, JV); allocate my capital | `re-strategy` |
| how did prices get here; history of a lot or ward | `re-history` |
| zoning, quy hoạch, nearby projects, infrastructure | `re-infra` |
| where will the price go; scenarios; hold or sell timing | `re-forecast` (fitted, backtested model) or `re-project` (quick scenarios) |
| model a purchase or build; EV; break-evens; stress | `re-deal` |
| compare listings or options side by side | `re-compare` |
| find opportunities; screen; undervalued; high yield; motivated sellers | `re-opportunities` |
| best use of a property I own (hold / lease / build / homestay / sell) | `re-plan` |
| what can I afford; financing; a purchase ladder; growing the business | `re-finplan` |
| my units, tenants, rent roll, monthly close, arrears | `re-portfolio` |
| risk, concentration, leverage, shocks | `re-risk` |
| due diligence, title, transaction costs and taxes | `re-legal` |
| a full analysis of one listing, with the team | `re-analyze` |
| challenge a conclusion before acting | `re-review` |
| a dashboard or dossier | `re-report` |
| grade past estimates; what have we learned | `re-learn` |

If the request spans several, chain them in that order. For example, "should I buy this?" runs
`re-find` (capture) → `re-value` → `re-infra` → `re-deal` → `re-review` → `re-report`. That chain is `re-analyze`.

## Always

- Get every number from `python3 -m vnrealty.cli … --json`. Quote it; do not recompute it. A command that returns
  `insufficient` is an answer: say what evidence is missing and how to get it, usually by mining more listings.
- Say which prices are asking prices and which are sales, and give the date of the data.
- End with what to do next and what would change the conclusion.
