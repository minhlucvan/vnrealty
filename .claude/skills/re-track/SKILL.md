---
name: re-track
description: Re-run saved searches and watched listings, then report what moved: price cuts and raises, new supply, relists, listings gone. Triggers on "có gì mới", "giá giảm", "track", "what changed", "price cuts", "theo dõi giá".
when_to_use: Daily or weekly tracking passes, and the scheduled daily_track workflow.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch, mcp__claude-in-chrome__navigate, mcp__claude-in-chrome__javascript_tool, mcp__claude-in-chrome__get_page_text, mcp__claude-in-chrome__tabs_create_mcp, mcp__claude-in-chrome__tabs_context_mcp, mcp__claude-in-chrome__computer
---

# re-track — what moved

1. List the saved searches with `python3 -m vnrealty.cli search list --json`. For each one, run the re-find page flow on
   its URL (first 2–3 pages), then `search touch <name>`.
2. Re-open the detail page of every watched listing (`listings --watched --json`) and capture it.
3. Run `ingest data/raw`, then `track --since <last run> --json`. This returns cuts and raises (% and VND), new
   listings, relists and gone listings. `track mark-gone --days 30` is conservative: it only acts on listings from
   searches that were re-run.
4. Report:
   - the biggest cuts first, because repeated cuts mark motivated sellers;
   - new supply by ward;
   - listings gone after a cut, which probably sold near the last price. Offer to record these as weak sale evidence
     with `sale add … --confidence weak`;
   - an updated market line from `market <ward> --json`.
5. Write the pass to the journal (`journal add track "<summary>"`).
