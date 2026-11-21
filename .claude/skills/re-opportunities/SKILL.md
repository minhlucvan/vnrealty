---
name: re-opportunities
description: Screen the database for opportunities: priced under the hedonic model or comps, gross yield above the ward median, near a high-chance catalyst, motivated sellers with repeated cuts, mispriced by legal or access. Triggers on "tìm cơ hội", "deal tốt", "rẻ", "opportunities", "undervalued", "screen".
when_to_use: Finding candidates worth a full analysis.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-opportunities

1. Coverage check (`coverage --json`). Screens are only as good as the mined universe, so run `re-find` on thin
   wards first.
2. Run `screen --rule undervalued|yield|catalyst|motivated|all --ward … --json`. Each hit carries the number behind
   it (residual vs hedonic, yield vs ward median, catalyst distance and chance, the number and size of cuts).
3. Remove false positives: missing legal status, a giấy tay title, a kiệt under 2 m, a planning red flag. Cheap for a
   reason is not an opportunity.
4. Present the top 5–10 with why each might be mispriced and what to check. Offer `re-analyze` on the best ones.
