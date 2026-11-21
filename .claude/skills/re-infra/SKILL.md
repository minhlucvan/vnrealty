---
name: re-infra
description: Check zoning (quy hoạch), land-use codes, road boundaries and nearby infrastructure or large projects for a location, update the project catalog with citations, and turn projects into catalysts for projection. Triggers on "quy hoạch", "dự án gần", "hạ tầng", "lộ giới", "zoning", "infrastructure", "nearby projects".
when_to_use: Any location-risk or catalyst question.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch, mcp__claude-in-chrome__navigate, mcp__claude-in-chrome__javascript_tool, mcp__claude-in-chrome__get_page_text, mcp__claude-in-chrome__tabs_create_mcp, mcp__claude-in-chrome__tabs_context_mcp, mcp__claude-in-chrome__computer
---

# re-infra

1. Locate the subject: lat/lng from the listing, a Google Maps capture (`maps` script) or the user.
2. **Zoning.**
   - Open guland.vn/soi-quy-hoach/da-nang at the point in Chrome. Ask the user to click the parcel if needed, then
     inject the `zoning` script.
   - Record the land-use code with `infra zoning add <subject> --code ODT --plan "<plan/decision>" --source <url>`.
     `reference/landuse_codes.json` explains the codes.
   - Red flags: DGT (road), CXK (green), or a lộ giới line through the lot. Escalate these as a legal and zoning risk.
3. **Projects.**
   - `infra near <lat,lng> --km 3 --json` lists the catalog.
   - Search for new ones (WebSearch the ward plus "dự án", "khởi công", "quy hoạch 1/500", "giải phóng mặt bằng").
   - Add each with `infra add …` and `infra cite <id> <url> --claim …`.
   - Status, years, chance and uplift are **judgement**: write the basis.
4. Report the projects by distance, status and expected year; what each would do to this location (catalyst uplift ×
   distance decay); and what to verify at the ward office (an official planning information sheet, "phiếu thông tin
   quy hoạch").
