export const meta = {
  name: 'monthly_close',
  description: 'Portfolio monthly close, risk report and calibration for the owned units',
  phases: [{ title: 'Close' }, { title: 'Risk' }],
}
const ARGS = typeof args === 'string' ? JSON.parse(args || '{}') : (args || {})
if (!ARGS.month) throw new Error('monthly_close needs args.month (YYYY-MM)')
const ROOT = '/Users/mac/Documents/vnrealty'
const close = await agent(`Repo ${ROOT}. Run python3 -m vnrealty.cli portfolio close ${ARGS.month} --json and summarise: collections vs schedule, arrears with days late, expenses, net cash, renewals due, alerts. Numbers verbatim from the command.`, { label: 'close', phase: 'Close' })
const risk = await agent(`Repo ${ROOT}. Run python3 -m vnrealty.cli risk --cash ${ARGS.cash ?? '<liquid cash in VND: ask the user, never default>'} --json and python3 -m vnrealty.cli calibrate --json. Rank flags by closeness to a forced sale; give the cheapest fix for each, quantified by re-running with the changed input. Then run vnr report portfolio and return the paths.\n\nClose summary:\n${close}`, { label: 'risk', phase: 'Risk' })
return { month: ARGS.month, close, risk }
