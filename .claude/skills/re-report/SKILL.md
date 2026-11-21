---
name: re-report
description: Render dashboards and dossiers: market, listing, deal, compare, portfolio, plan — self-contained HTML plus Markdown under data/reports. Triggers on "báo cáo", "dashboard", "report", "export".
when_to_use: Producing a shareable or archivable view.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-report

`python3 -m vnrealty.cli report <market|listing|deal|compare|portfolio|plan> <subject>` writes HTML and Markdown under
`data/reports/` (private). Open the HTML in the browser pane, or give the path. Reports contain personal data, so do
not publish them unless the user asks. If they do, strip addresses and owner details first.
