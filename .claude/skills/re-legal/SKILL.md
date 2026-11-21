---
name: re-legal
description: Due diligence and transaction costs for a Vietnamese property: title type, owners, mortgages, zoning, permits, disputes, road boundary, area match, and the itemised taxes and fees for buyer and seller. Triggers on "pháp lý", "sổ hồng", "thuế phí", "công chứng", "due diligence", "transaction costs".
when_to_use: Before any offer or deposit.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-legal

1. Run `legal checklist <subject>` to open or show the checklist. Each item has why it matters and where to verify
   (land registration office, ward, notary). Update an item with `legal set <subject> <item> ok|issue|na --note …`.
2. Run `legal costs <price> --role buyer|seller [--official <value>] --json` for itemised costs with their legal
   basis.
3. Point to what must be verified in person or with a lawyer. This is a checklist, not legal advice.
