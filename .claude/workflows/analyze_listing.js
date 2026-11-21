export const meta = {
  name: 'analyze_listing',
  description: 'Full desk analysis of one listing: analyst, infra, legal and quant in parallel, then an adversarial review',
  phases: [{ title: 'Evidence' }, { title: 'Review' }],
}
const ARGS = typeof args === 'string' ? JSON.parse(args || '{}') : (args || {})
if (!ARGS.listing) throw new Error('analyze_listing needs args.listing (a listing id from `vnr listings --json`)')
const L = ARGS.listing, GOAL = ARGS.goal || 'buy to hold for rent and growth'
const ROOT = '/Users/mac/Documents/vnrealty'
const common = `Repo ${ROOT}. Read CLAUDE.md and .claude/skills/re/references/method.md. Subject: listing ${L}. Investor goal: ${GOAL}. ` +
  `Every number must come from \`python3 -m vnrealty.cli ... --json\` run from ${ROOT}; never compute numbers yourself. Return a concise markdown section.`
const [analysis, infra, legal, quant] = await parallel([
  () => agent(`${common}\nAct as the re-analyst agent: first read .claude/agents/re-analyst.md and follow it. value (vnr value), comps, history, market context and rents. Label every evidence line by class and bias.`, { label: 'analyst', phase: 'Evidence' }),
  () => agent(`${common}\nAct as the re-infra agent: first read .claude/agents/re-infra.md and follow it. zoning status from captured data (vnr infra zoning show), projects within 3 km (vnr infra near), catalysts with citations; list what must be verified at the ward office.`, { label: 'infra', phase: 'Evidence' }),
  () => agent(`${common}\nAct as the re-legal agent: first read .claude/agents/re-legal.md and follow it. vnr legal checklist and vnr legal costs for this listing; list unknowns and who verifies them.`, { label: 'legal', phase: 'Evidence' }),
  () => agent(`${common}\nAct as the re-quant agent: first read .claude/agents/re-quant.md and follow it. build the deal from the listing price, the triangulated value and market rents (vnr deal preset + vnr deal/ev/project). Report base/bear/bull, kill triggers, what binds.`, { label: 'quant', phase: 'Evidence' }),
])
const dossier = [analysis, infra, legal, quant].map(x => typeof x === 'string' ? x : JSON.stringify(x)).join('\n\n---\n\n')
const review = await agent(`${common}\nAct as the re-reviewer agent: first read .claude/agents/re-reviewer.md and follow it. try to break this dossier, re-running the numbers yourself. Verdict GO / HOLD / CUT with reasons.\n\n${dossier}`, { label: 'review', phase: 'Review' })
return { listing: L, dossier, review }
