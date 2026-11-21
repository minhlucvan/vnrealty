# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

**vnrealty** is a quantitative real-estate investing desk for Vietnam, starting with **Đà Nẵng**. It helps one investor
run real estate as a professional business:
- find and track listings (through Chrome);
- read the market and check zoning and infrastructure;
- reconstruct price history, estimate and project prices;
- model deals and their expected value, plan finances and compare options;
- operate owned units and manage risk.

The edge is method, not speed. That means:
- triangulate independent evidence;
- separate what was asked from what was paid;
- carry uncertainty bands;
- grade every estimate later against what happened.

## Non-negotiable principles

1. **Agents orchestrate; libraries compute.** Every price, yield, IRR, index, projection or risk number comes from a
   tested function in `vnrealty/`, reached through the `vnr` CLI (`--json`). An agent that does arithmetic in prose is a
   defect: move it into a library and run it.
2. **A missing number announces itself.** A method that cannot produce a value returns `Insufficient(reason)`
   (`vnrealty/types.py`). Never substitute a plausible default, never round a gap into a number.
3. **Asking is not selling.** Listing prices are `kind="asking"`. Real sales (`sale_evidence`) are the only ground truth.
   The asking→sale haircut is an explicit, cited parameter, never folded in silently.
4. **Every input is cited and dated.** Listings keep url, capture time and the saved raw page text (`raw_ref`). Projects
   keep `project_evidence`. Reconstructed history is labelled `reconstructed` and carries bands.
5. **Point in time.** Anything taking `as_of` sees only observations with `seen_at <= as_of`. A file's mtime is never
   evidence of recency.
6. **Grade yourself.** Valuations go into the `valuation` table, and decisions go into `deal`. `vnr calibrate` scores
   them against later evidence, and method weights are earned from that record.
7. **Privacy.** `data/` (database, raw pages, dossiers, portfolio, personal finance, reports) is gitignored and stays
   local. Never commit personal records: land certificates, legal briefs, owner names, phone numbers, ID numbers.
   Phone numbers are stored only as `phone_hash`.
8. **Scraping manners.** Personal research pace, public pages only, no logins, no CAPTCHA solving, no bypassing
   blocks, no resale of data. Chrome is the user's own browser, driven via the `claude-in-chrome` tools; save the
   page text and parse it offline.
9. **Not advice.** Reports are decision support for the owner, not licensed financial or legal advice. Legal checks
   point to what must be verified with the land office or a lawyer.

## Layout

```
vnrealty/        the libraries (stdlib only, Python ≥3.12)
  deal/          engine.py (one deal, monthly), scale.py (portfolio ladder), ev.py (scenario EV)
  store/db.py    SQLite schema + connect(); data/vnr.sqlite by default (VNR_DB overrides)
  types.py       ListingObs, Comp, Estimate, Insufficient
  listings/      parse.py (VN strings), sources/<site>.py (page text → ListingObs), dedupe.py, ingest.py
  geo/           wards.py (Đà Nẵng units, 2025 mapping), distance
  market/        index.py, landscape.py, rent.py
  valuation/     comps.py, hedonic.py, official.py, triangulate.py
  history/       reconstruct.py
  projection/    catalysts.py, montecarlo.py
  infra/         catalog.py
  plan/          options.py, finplan.py
  portfolio/     units.py, ops.py, risk.py, ledger.py
  legal/         checklist.py
  score.py       graded verdict from library outputs
  report/        html.py, md.py
  cli.py         `vnr` entry point
web/             deal.js, scale.js (browser ports, parity-checked) + dashboard templates
reference/       public, cited reference data (wards, project seeds, cost and tax tables)
data/            PRIVATE, gitignored
.claude/         skills (router /re + one per job), agents (re-* team), workflows
tests/           unittest, synthetic fixtures; tests/fixtures/<site>/ holds anonymised page text
```

## Mining: Chrome + injected extractors

Collection runs through the investor's own Chrome via the `claude-in-chrome` tools. On every page the flow is:
1. `navigate` to the page.
2. Run `javascript_tool` with the bundled extractor (`python3 -m vnrealty.cli browser script <name>` prints it). It
   returns structured JSON.
3. Save that JSON with `vnr capture save` into `data/raw/<site>/<date>/`.
4. Run `vnr ingest`.

Fall back to `get_page_text` saved as a `.txt` capture when a script finds nothing.

Rules for the extractors:
- They are read-only: no clicks, no form submits, no network calls.
- They never return phone numbers or names. Phones come back only as a hash.
- All number parsing is done once, in Python (`listings/parse.py`).

| Source | Script / tool | Gives |
|---|---|---|
| Listing sites (batdongsan, nhatot/chotot, alonhadat, guland, muaban, bds68) | `browser/<site>.js` | asking and rent listings (search cards and detail pages) |
| Any other site | `browser/generic.js` | JSON-LD, meta tags, labelled spec tables |
| Google Maps | `browser/maps.js` | POIs, coordinates (from the URL), ratings |
| Zoning (guland soi quy hoạch, city planning portal) | `browser/zoning.js` | land-use code, plan and decision for the clicked parcel |
| Social (public Facebook groups and posts) | `browser/social.js` | post text and permalinks; parsed by `parse.parse_post` |
| News, decisions, project status | WebSearch / WebFetch | citations for `project_evidence`, official prices, tax rules |
| Satellite (Esri Wayback) | (planned) port of fincas `hq01_imagery.py` | dated imagery of a lot, change detection |

Only the lead session drives Chrome. Agents read the saved captures and the database.

## Commands

```bash
python3 -m unittest discover -s tests -t .      all tests (run from the repo root)
node web/test_scale.js && python3 web/check_parity.py     browser ports agree with Python
python3 -m vnrealty.cli --help                  the CLI (or `vnr` once installed with pip install -e .)
```

## Conventions

- Stdlib only. No numpy or pandas; the regression in `valuation/hedonic.py` is a small normal-equations solver.
- Money in VND (floats), area in m², rates as fractions (0.105), dates ISO-8601.
- Every public function has type hints and a docstring stating its units.
- Every module has `tests/test_<package>_<module>.py`.
- Vietnamese text is handled with NFC normalisation. `listings/parse.py::fold` strips diacritics for matching.
- Text shown to users can be bilingual. Code identifiers are English.
- Commits: Conventional Commit subjects (`feat(valuation): ...`).
