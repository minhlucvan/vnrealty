---
name: re-find
description: Find and capture listings with the investor's Chrome — open listing sites, Google Maps, zoning maps or public social groups, inject the desk's extractor scripts, save the JSON captures and ingest them. Triggers on "tìm nhà", "tìm đất", "tìm căn", "find listings", "search batdongsan", "mine this page", "capture this listing", "lấy tin rao".
when_to_use: Collecting listings or page data into the local database. Only the lead session drives Chrome. NOT for logins, CAPTCHAs or paid data.
allowed-tools: Read, Bash(python3 -m vnrealty.cli:*), mcp__claude-in-chrome__tabs_context_mcp, mcp__claude-in-chrome__tabs_create_mcp, mcp__claude-in-chrome__navigate, mcp__claude-in-chrome__javascript_tool, mcp__claude-in-chrome__get_page_text, mcp__claude-in-chrome__read_page, mcp__claude-in-chrome__find, mcp__claude-in-chrome__computer, WebSearch
---

# re-find — mine listings through Chrome

Load the Chrome tools in one ToolSearch call: tabs_context_mcp, tabs_create_mcp, navigate, javascript_tool,
get_page_text, read_page, find, computer. Work in a new tab, not one of the user's open tabs.

## 1. Turn the request into searches
Criteria are ward(s), property type, price range, area, alley width, legal status, and sale or rent. Build the site
search URLs:
- **batdongsan.com.vn:** `/ban-dat-<ward-slug>-da-nang`, `/ban-nha-rieng-…`, `/cho-thue-…`.
- **nhatot.com:** `/mua-ban-dat-da-nang`, with filters in the query string.
- **alonhadat.com.vn, guland.vn, muaban.net, bds68.com.vn:** their search pages.

Save each one so the tracker can re-run it: `python3 -m vnrealty.cli search add <name> <site> <url> --criteria '<json>'`.

## 2. On every page
1. `navigate` to the URL. Wait for it to load and scroll once so lazy cards render.
2. Get the extractor: `python3 -m vnrealty.cli browser script <site>`. Sites are batdongsan, chotot, alonhadat,
   guland, muaban, bds68, generic, maps, zoning and social.
3. `javascript_tool` with that script. It returns `{site, url, seen_at, kind, items, warnings}`.
4. Save the result: write the JSON to a temp file, then `python3 -m vnrealty.cli capture save <file>`, which stores
   it under `data/raw/<site>/<date>/`.
5. If `items` is empty or the warnings say the layout changed, fall back to `get_page_text` and save it as a text
   capture: `capture save --text <file> --url … --site … --kind search`. Note it, so `re-quant` can fix the
   extractor.
6. Paginate: next page URL, up to the number of pages the user asked for (default 3). Keep a research pace of a few
   seconds between pages.

Then `python3 -m vnrealty.cli ingest data/raw --json` gives counts of new listings and new price observations.

## 3. Other sources
- **Detail pages** of shortlisted listings: same flow. They add legal status, alley width, frontage and
  coordinates.
- **Google Maps** (`maps` script): POIs near a lot, such as schools, markets, the beach and hospitals, and
  coordinates from the URL.
- **Zoning** (`zoning` script): on guland.vn/soi-quy-hoach/da-nang, click the parcel first (the user can do it), then
  run the script. Store the result through `re-infra`.
- **Public Facebook groups** (`social` script, e.g. groups for Đà Nẵng land): returns post texts only, no names or
  phones. Ingest parses them with `parse_post`. Treat them as low-confidence asking prices.

## 4. Report
Tell the user:
- how many pages and listings, and how many new ones;
- the price range found, using `python3 -m vnrealty.cli listings --ward … --json`;
- a shortlist (top by `vnr screen`);
- which pages needed the text fallback.

Never paste phone numbers or seller names.

## Hard rules
- Public pages only.
- No logins. No CAPTCHA solving: if one appears, stop and tell the user.
- No form submits other than the site's own search filters.
- Do not open a seller's phone-reveal button.
- Keep it to personal research volume.
