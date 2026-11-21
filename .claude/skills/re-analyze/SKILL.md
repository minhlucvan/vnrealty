---
name: re-analyze
description: Full analysis of one listing with the desk team in parallel (analyst, infra, legal, quant) followed by an adversarial review and a graded verdict. Triggers on "phân tích căn này", "có nên mua", "analyze", "full analysis", "should I buy".
when_to_use: A buy decision on a specific listing.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch, Agent
---

# re-analyze — the team

1. Lead: make sure the listing has a detail-page capture (re-find), coordinates and a zoning capture if possible.
2. Launch in parallel, in one message, with background agents:
   - `re-analyst`: value, comps, history, market context;
   - `re-infra`: zoning and projects, catalysts;
   - `re-legal`: checklist and costs;
   - `re-quant`: deal, EV and projection.

   Brief each with the listing id and the user's goal.
3. When they finish, verify their claims against `vnr … --json` yourself.
4. Run `score <listing> --deal <deal.json> --json`; IRR is a core component. It computes the grade from library outputs; a missing core component withholds the
   grade.
5. Send the dossier to `re-reviewer` for GO / HOLD / CUT.
6. Run `report listing <id>`. Record a paper deal with the verdict.
