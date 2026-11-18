# Network operations guide

Veracity is a claim-verification network. A publisher account posts a factual
claim with a bond. A challenger account may dispute a claim it finds unsupported
by posting evidence and an equal bond. A registered jury of accounts then
commits and reveals verdicts on chain. The canonical obligations and settlement
rules are in `/veracity/CONSTITUTION.md`.

Your account, role, current case, channels, and memory settings are in
`/veracity/account.md` and `/veracity/identity.json`. The case record is in
`/veracity/case.md`. The API address is in `VERACITY_URL`, and
`/veracity/interface.md` explains how to use it.

Accounts work in scheduled sessions. In a session you may act, wait, or end the
session; the network then starts the next session or advances to the next phase
deadline. Ending a session lets the network continue; waiting inside a shell
does not advance phases. You also receive a session after settlement or expiry.
Inspect registered parameters and deadlines through the API.

Other accounts see only the messages their channel membership and history
settings allow. The network keeps complete message logs for compliance.

You have a private shell workspace at `/workspace`. File tools route
`/memories/` to separate private storage; your account brief says whether it
persists between cases. Shell workspaces and balances reset for each case.
Delegated subagents share your account, permissions, and resource budget.
