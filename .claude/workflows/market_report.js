export const meta = {
  name: 'market_report',
  description: 'Market read for Đà Nẵng and selected wards from the local database, with cited news context',
  phases: [{ title: 'Wards' }, { title: 'City' }],
}
const ARGS = typeof args === 'string' ? JSON.parse(args || '{}') : (args || {})
if (!ARGS.as_of) throw new Error('market_report needs args.as_of (YYYY-MM-DD); it will not default to the wall clock')
const ROOT = '/Users/mac/Documents/vnrealty', AS_OF = ARGS.as_of, WARDS = ARGS.wards || []
const base = `Repo ${ROOT}. Read CLAUDE.md. As of ${AS_OF}. Numbers only from \`python3 -m vnrealty.cli ... --as-of ${AS_OF} --json\`; news context via WebSearch with citations kept separate from numbers.`
const wards = await parallel(WARDS.map(w => () => agent(`${base}\nWard ${w}: vnr market ${w}, vnr market yields --ward ${w}, coverage. Write a short read: level, trend, liquidity, supply, yields, what changed, thin cells.`, { label: `ward:${w}`, phase: 'Wards' })))
const city = await agent(`${base}\nCity-wide read using vnr market city and these ward reads:\n${wards.join('\n---\n')}\nName the cycle stage from the evidence and what would change it. Then run vnr report market city and return the report paths.`, { label: 'city', phase: 'City' })
return { as_of: AS_OF, wards, city }
