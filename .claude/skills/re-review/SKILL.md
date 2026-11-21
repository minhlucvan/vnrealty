---
name: re-review
description: Adversarial review of a conclusion or dossier before acting: stale data, asking taken for sale, thin comps, unverified zoning, optimistic rent, catalysts treated as certain, legal gaps. Returns GO / HOLD / CUT with reasons. Triggers on "kiểm tra lại", "challenge", "review", "am I missing something".
when_to_use: Before any offer, deposit or big decision.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch, Agent
---

# re-review

Send the `re-reviewer` agent the dossier and the commands to reproduce it. Relay its verdict and every reason. A HOLD
names what evidence would turn it into a GO.
