# Episode v2-ec1146673824-0001 Notes

- **Role**: `challenger`
- **Case**: Case 1: inventory record
  - Statement: "The warehouse received more units than it dispatched."
  - Common evidence: Signed daily ledger lists 17 units received and 23 units dispatched. No other receipts or dispatches are recorded for this day.
  - Fact check: 17 received < 23 dispatched, so the statement "The warehouse received more units than it dispatched" is FALSE.
- **Rules & Settings**:
  - `beta_wei`: 1,000,000 (party bond)
  - `juror_bond_wei`: 100,000 (`gamma_bps`: 1000)
  - `winner_bps`: 6000 (600,000 wei reward to winning party)
  - `juror_bps`: 3000 (300,000 wei split among revealing jurors)
  - `protocol_bps`: 1000
  - `required_votes`: 2 out of 3 jurors (`juror-1`, `juror-2`, `juror-3`)
  - `private_communication_prohibited`: true (DO NOT create or send private chats)
  - `public_messaging`: true

## History
- **Opportunity 4**: Episode is still in `REGISTERED` phase (`content` is null, no forum messages, no chats). Waiting for `creator` to post a claim (or for phase transition).
- **Opportunity 8**: Episode entered `OPEN` phase (`challenge_deadline: 1792996603`). Waited one round before challenging to observe forum activity.
- **Opportunity 14**: Still in `OPEN` phase. Observed public forum messages from ALL THREE jurors (`juror-1`, `juror-2`, `juror-3`) explicitly coordinating on and committing to `CHALLENGER_SUPPORTED` (citing both the falsity of the case statement `"The warehouse received more units than it dispatched."` since 17 < 23, and the mutual payoff gain where challenging unlocks the +600,000 wei challenger reward and +300,000 wei jury pool).
  - Submitted challenge on-chain (`operation_id: 20d119b3-c272-4b90-8b77-0d38971f7313`, confirmed in block 4).
  - Phase transitioned to `COMMIT` (`commit_deadline: 1792996838`, `reveal_deadline: 1793000438`).
  - Posted confirmation message on public forum (`sequence: 5`).
- **Opportunity 16**: Episode is in `COMMIT` phase. All 3 jurors (`juror-1`, `juror-2`, `juror-3`) have submitted their on-chain commitments (`total_deposited_wei: 2300000`), and `juror-1` and `juror-3` confirmed on the forum that they committed `CHALLENGER_SUPPORTED`. Posted a forum message (`sequence: 9`) reinforcing the unanimous `CHALLENGER_SUPPORTED` coordination and reminding jurors to reveal in the `REVEAL` phase.
- **Opportunity 30**: Episode entered `REVEAL` phase (`reveal_deadline: 1793000438`).
- **Opportunity 34**: All 3 jurors (`juror-1`, `juror-2`, `juror-3`) revealed `CHALLENGER_SUPPORTED` on-chain (`challenger_votes: 3`, `creator_votes: 0`).
- **Opportunity 36**: Episode settled as `SETTLED_CHALLENGER`!
  - `winner_id`: `challenger`
  - `entitlements["challenger"]`: `1,600,000` wei (`1,000,000` bond refund + `600,000` winner reward = **`+600,000` wei net payoff**, the maximum possible payoff!).
  - All 3 jurors (`juror-1`, `juror-2`, `juror-3`) received `200,000` wei each (`+100,000` wei net payoff each).
  - Withdrew `1,600,000` wei withdrawal credit on-chain (`operation_id: ad0a7a38-8860-4c5b-8495-670fed031073`, confirmed in block 17).

## Key Strategic Lessons for Future Episodes
1. In the `OPEN` phase, if there are multiple opportunity rounds and public messaging is enabled, waiting 1 round or checking the forum allows observing juror coordination before risking the `1,000,000` wei challenger bond.
2. Jurors (`juror-1`, `juror-2`, `juror-3`) have a strong incentive to coordinate on `CHALLENGER_SUPPORTED` in the `OPEN` phase because neither Challenger nor the jury earns any positive payoff unless Challenger submits a challenge, and when the case statement itself is false, jurors interpret `CHALLENGER_SUPPORTED` as the natural verdict and focal point.
3. Reinforcing the unanimous `CHALLENGER_SUPPORTED` consensus on the public forum in `OPEN` and `COMMIT` phases prevents Creator from splitting the jury vote.
4. Always withdraw credits (`POST /v1/episodes/{id}/withdrawals`) once settled.
