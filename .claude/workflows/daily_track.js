export const meta = {
  name: 'daily_track',
  description: 'Re-run saved listing searches in Chrome, ingest the captures, and report price moves and new supply',
  phases: [{ title: 'Track' }],
}
const ARGS = typeof args === 'string' ? JSON.parse(args || '{}') : (args || {})
const ROOT = '/Users/mac/Documents/vnrealty'
const out = await agent(`Repo ${ROOT}. Follow .claude/skills/re-track/SKILL.md exactly: for each saved search (python3 -m vnrealty.cli search list --json) open it in Chrome, inject the site extractor (vnr browser script <site>), save captures (vnr capture save), then vnr ingest data/raw and vnr track --since ${ARGS.since || '<last search run>'} --json. Public pages only, no logins, stop on any CAPTCHA. Report cuts, new supply, relists, gone-after-cut, with numbers verbatim.`, { label: 'track', phase: 'Track' })
return { out }
