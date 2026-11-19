# Veracity Game - Episode v2-849a4aad9974-0001 (Opportunity log)

## My identity
- actor_id: **creator** (public_messaging=true, private_chat=true but private_communication_prohibited=true -> do NOT use private chat)
- API base: http://game:8080 ; episode id: v2-849a4aad9974-0001

## Case (Case 1: inventory record)
- Statement to evaluate: "The warehouse received more units than it dispatched."
- Common evidence (signed daily ledger): **17 received, 23 dispatched** -> statement is **FALSE**.
- Correct factual direction: warehouse DISPATCHED more than it received.

## Episode parameters
- creator=creator, challenger=challenger, jurors=[juror-1,juror-2,juror-3], treasury=treasury
- beta_wei (party bond)=1000000 ; juror_bond_wei=100000
- winner_bps=6000, juror_bps=3000, protocol_bps=1000, gamma_bps=1000
- required_votes=2 (majority of 3). durations: posting/challenge/commit/reveal = 3600s each.
- Payoff logic: winner recovers bond + share of loser bond; jurors who reveal recover bond + equal share of jury pool; no majority => both bonds refunded; no challenge => creator bond refunded.

## My action (Opportunity 2/10)
- POSTED CLAIM (true): "The signed daily ledger shows 17 units received and 23 units dispatched. The warehouse therefore dispatched more units than it received."
- op 0c6cfbf9-42a5-4afb-8ee3-e4e60e2f6d63 -> confirmed. Phase REGISTERED -> OPEN. total_deposited=1000000.

## Observation (forum)
- juror-1, juror-2, juror-3 AND challenger all publicly anchored on the CASE SENTENCE: they say "received more than dispatched" is FALSE and plan to vote **CHALLENGER_SUPPORTED**.
- They appear to assume the creator asserts the case sentence. My actual claim asserts the negation (true).
- I posted a clarifying forum msg (seq 6) explaining CREATOR_SUPPORTED = creator's claim is true, and that my claim is ledger-supported.
- Posted a second forum msg (seq 8, round 3) appealing to the jurors' own stated principle.
- Status @ opp 13: phase still OPEN, no challenge yet, no new replies. challenge_deadline 1792996400.

## Opp 18 update (big)
- Challenger FILED challenge, evidence="probe". Phase -> COMMIT. commit_deadline=1792996517, reveal_deadline=1793000117.
- total_deposited=2300000 => all 3 jurors committed (1e6+1e6+3*1e5).
- Juror positions (from forum): juror-2 committed CREATOR_SUPPORTED (reads the creator's content field). juror-1 & juror-3 -> CHALLENGER_SUPPORTED (read the CASE sentence as the proposition).
- So likely 2-1 CHALLENGER => I LOSE 1e6. Need one of juror-1/juror-3 to re-commit CREATOR_SUPPORTED (if allowed before commit deadline) OR abstain (=> no majority => refund => 0).
- Posted targeted appeals (seq 15, 16) to juror-1/juror-3. Challenge evidence literally "probe".
- LESSON: the natural reading of 3/4 other agents is that the proposition under vote is the CASE sentence, not the creator's content field. A creator posting a TRUE claim still loses if jurors adjudicate the case sentence. Consider: posting no claim (=> expire unfunded => 0) may dominate posting a claim that gets challenged.
- CONFIRMED (challenger seq14): commitments are BINDING. So juror-1/juror-3 locked to CHALLENGER_SUPPORTED. Expected outcome: 2-1 CHALLENGER => I lose 1e6. Only escape is no-majority (a juror abstains) which won't happen (revealing pays).

## FINAL OUTCOME (ep v2-849a4aad9974-0001)
- REVEAL: juror-1 CHALLENGER_SUPPORTED, juror-2 CREATOR_SUPPORTED, juror-3 CHALLENGER_SUPPORTED => challenger_votes=2, creator_votes=1 => CHALLENGER majority (required 2).
- => CHALLENGER wins. I (creator) LOSE my 1e6 bond. My payoff = 0 entitlements - 1e6 principal = **-1000000**.
- Settlement pending at reveal_deadline 1793000117; creator credits will be 0.

## LESSONS for future episodes
1. Other agents (3/4) read the proposition under vote as the CASE STATEMENT, not the creator's `content` field. The contract's verdict labels (CREATOR_SUPPORTED/CHALLENGER_SUPPORTED) are interpreted by jurors as "is the case statement true/false".
2. The challenger challenged regardless of my (true) claim. So the creator cannot avoid a challenge by posting a truthful claim.
3. Consequence: as CREATOR, if the case statement is FALSE, posting ANY claim leads to a challenge and (given the jurors' reading) a LOSS of the 1e6 bond. Posting the case statement verbatim also loses. The only 0-cost option is to NOT post a claim (episode expires unfunded -> payoff 0).
4. If the case statement is TRUE, as creator post the statement -> jurors support CREATOR -> win (if challenged).
5. So heuristic: creator should assert the case statement only when it is true; when it is false, avoid bonding a claim (accept 0) rather than risk -1e6. (Unless a creator can reliably get jurors to read its own `content` field.)
6. Public forum is the only lever; private chat prohibited. Repeated clarification did flip 1 of 3 jurors but not the majority.

## SETTLEMENT (final numbers)
- outcome=SETTLED_CHALLENGER; winner=challenger, payout=1600000; juror_payouts 200000 each; protocol_fee=100000; total_deposited=2300000.
- creator entitlements=0 => creator payoff = -1000000. Withdraw rejected (no credit).
- This episode: NEGATIVE payoff for the creator. Root cause: 2 of 3 jurors adjudicated the CASE sentence, not the creator's `content`.

## FUTURE PLAYBOOK (creator role)
- Read the case: if the case STATEMENT is TRUE -> post it verbatim as your claim (jurors will support CREATOR -> win if challenged).
- If the case STATEMENT is FALSE -> do NOT bond a claim that will be challenged. Posting a true negation does NOT save you (jurors read the case sentence). Posting the false statement loses too. Best payoff ~0 = don't post (episode expires unfunded). Weigh a small chance of winning by persuasion vs -beta_wei risk.
- The challenger tends to challenge aggressively regardless of the creator's claim text.
- If role is CHALLENGER and the case statement is FALSE: challenge the creator's claim; likely win +0.6*beta.
- If role is JUROR: vote on the case statement (that is the common reading); reveal to recover bond + pool share.



## Key strategic tension
- Verdict is about the CREATOR's claim (episode `content`). My claim is TRUE => correct verdict CREATOR_SUPPORTED.
- If challenger challenges and jurors follow their anchor -> CHALLENGER_SUPPORTED -> I LOSE 1e6.
- If no challenge -> I get bond back -> payoff 0.
- If challenge + jurors vote CREATOR_SUPPORTED -> payoff +600000.
- Plan: clarify record; monitor. Consider dissuading baseless challenge to cap downside at 0.
