# Archived Game-Builder Handoff

> Historical handoff retained for context. Use [SPEC.md](../SPEC.md),
> [the `/v1` API](../docs/api.md), and [integration notes](../docs/integration.md)
> for implemented rules. The contract controls phases and settlement.
> Requirements, method lists, and checkboxes below record the initial proposal;
> they are not current work items. The Python mock engine has been removed.
> Independent bond posting and synthetic phase commands must not be reintroduced.

This document recorded the initial expectations before the Rust/Solidity
integration. The current harness calls the implemented `/v1` API and owns only
experiments, agents, observations, and metrics; it does not implement game rules.

---

## The Game in One Paragraph

A creator posts a claim and bets $10. A challenger bets $10 against it. A jury of N members each posts a $1 bond, then deliberates over multiple rounds, and finally casts binding votes. The majority verdict wins. The winner gets their $10 back plus 60% of the loser's $10. Jurors who voted split 30% of the loser's $10. The protocol keeps 10%. Jurors who don't vote forfeit their bond. If there's no majority, it's a hung jury — bets are refunded, non-voter bonds are still forfeited.

---

## API the Harness Calls

The harness needs to call these methods in this order. Each takes an `episode_id` (string) and returns success/failure or a result object. The harness calls them via an async Python interface; the game can expose them as REST, gRPC, WebSocket, on-chain transactions, or anything — we just need an adapter layer.

### Method Signatures

```
register_episode(config, creator_id, challenger_id, juror_ids, treasury_id) → episode_id
post_claim(episode_id, creator_id) → bool
challenge(episode_id, challenger_id) → bool
post_juror_bond(episode_id, juror_id) → bool
start_deliberation(episode_id) → bool
start_voting(episode_id) → bool
cast_vote(episode_id, juror_id, verdict) → bool
settle(episode_id) → SettlementResult
expire(episode_id) → SettlementResult
get_state(episode_id) → Phase
get_balances(episode_id) → dict[agent_id → float]
```

### Call Order Per Episode

```
1. register_episode(config, creator, challenger, jurors, treasury)
2. post_claim(episode_id, creator_id)
3. challenge(episode_id, challenger_id)
4. post_juror_bond(episode_id, juror_0)
   post_juror_bond(episode_id, juror_1)
   ... (one per juror)
5. start_deliberation(episode_id)
   — harness runs N rounds of agent discussion internally —
   — game doesn't need to do anything during deliberation —
6. start_voting(episode_id)
7. cast_vote(episode_id, juror_0, CREATOR_SUPPORTED)
   cast_vote(episode_id, juror_1, CHALLENGER_SUPPORTED)
   ... (one per voting juror; some may not vote)
8. settle(episode_id) → SettlementResult
```

If the creator doesn't post a claim, or the challenger doesn't challenge, the harness calls `expire(episode_id)` instead and the episode ends early.

### What the Game Does NOT Need to Handle

The game is blind to these — the harness manages them entirely:

- **Deliberation messages** — agents talk to each other through the harness, not on-chain
- **Straw polls** — non-binding polls during deliberation, harness-only
- **Juror objectives** — which jurors hold a secret objective
- **Bribe simulation** — side payments offered to jurors
- **Agent prompts** — what LLMs see and how they decide
- **Metrics** — verdict accuracy, collusion rates, all measurement

The game just needs to: hold bets, hold bonds, accept votes, and do the math for settlement.

---

## Config Object

Passed to `register_episode`. All values are provided by the harness.

```json
{
  "episode_id": "exp_baseline_abc123_ep0001",
  "payout": {
    "creator_bet": 10.0,
    "challenger_bet": 10.0,
    "winner_pct": 0.60,
    "juror_pool_pct": 0.30,
    "protocol_pct": 0.10,
    "juror_bond": 1.0
  },
  "jury_size": 5,
  "deliberation_rounds": 3
}
```

**`winner_pct + juror_pool_pct + protocol_pct` must equal 1.0.** The harness validates this before sending.

The harness will vary these across experiments:

| Parameter | Range We'll Test |
|---|---|
| `jury_size` | 3, 5, 7, 11, 21, 51, 101 |
| `winner_pct` | 0.40 to 0.80 |
| `juror_pool_pct` | 0.15 to 0.50 |
| `protocol_pct` | 0.05 to 0.30 |
| `juror_bond` | 0.50, 1.0, 2.0, 5.0 |
| `creator_bet` / `challenger_bet` | Usually both 10.0 |
| `deliberation_rounds` | 1, 3, 5, 10 |

---

## Verdict Enum

Two values only:

```
CREATOR_SUPPORTED = 1    (juror sides with the creator's claim)
CHALLENGER_SUPPORTED = 2 (juror sides with the challenger)
```

---

## Phase / State Enum

The game should track these states per episode:

```
SETUP                  → episode registered, waiting for claim
CLAIM_POSTED           → creator posted claim + bet
CHALLENGED             → challenger posted counter-bet
DELIBERATION           → deliberation in progress (harness manages rounds)
VOTING                 → accepting final votes
SETTLED_CREATOR        → creator won
SETTLED_CHALLENGER     → challenger won
ABORTED                → hung jury (no majority)
EXPIRED                → no challenge was posted (or no claim)
```

---

## Settlement Result

This is the critical return value from `settle()`. The harness uses every field.

```json
{
  "episode_id": "exp_baseline_abc123_ep0001",
  "outcome": "SETTLED_CREATOR",
  "final_votes": {
    "juror_0_...": "CREATOR_SUPPORTED",
    "juror_1_...": "CHALLENGER_SUPPORTED",
    "juror_2_...": "CREATOR_SUPPORTED"
  },
  "winner_id": "creator_...",
  "winner_payout": 16.0,
  "juror_payouts": {
    "juror_0_...": 1.60,
    "juror_1_...": 1.60,
    "juror_2_...": 1.60
  },
  "protocol_fee": 1.0,
  "forfeited_bonds": {
    "juror_3_...": 1.0,
    "juror_4_...": 1.0
  },
  "refunds": {}
}
```

### Settlement Math

Given `loser_bet` = the losing side's bet (same as winner's bet in symmetric setup):

| Recipient | Gets | Example ($10/$10, 60/30/10, 5 jurors all voting) |
|---|---|---|
| Winner | own bet + `winner_pct × loser_bet` | $10 + $6 = **$16** |
| Each voting juror | bond + `(juror_pool_pct × loser_bet) / num_voters` | $1 + $0.60 = **$1.60** |
| Protocol | `protocol_pct × loser_bet` | **$1.00** |
| Non-voter | loses bond (forfeited to protocol) | **-$1.00** |

**Hung jury** (no side reaches `jury_size // 2 + 1` votes):

| Recipient | Gets |
|---|---|
| Creator | bet refunded ($10) |
| Challenger | bet refunded ($10) |
| Voters | bond refunded ($1) |
| Non-voters | bond forfeited |

---

## What the Harness Uses Each Field For

| Field | Purpose |
|---|---|
| `outcome` | Compared against ground truth to measure verdict accuracy |
| `winner_payout` | Tracks financial outcomes for profit analysis |
| `juror_payouts` | Per-juror profit/loss calculation |
| `protocol_fee` | Total system cost tracking |
| `forfeited_bonds` | Measures participation loss from non-voter attacks |
| `refunds` | Tracks money returned in hung jury / expiry cases |
| `final_votes` | Per-juror vote record for correlation analysis |

---

## State File Alternative

If calling a live API is hard to set up immediately, the game can dump state as a JSON or markdown file after settlement and the harness can read it. We have a parser for both formats. See `GAME_API_CONTRACT.md` for the exact markdown format.

---

## What We're Testing (So You Understand Why)

The harness runs the same scenarios under different conditions and compares outcomes. The game doesn't need to know about any of this, but it helps to understand the goal:

1. **Baseline** — honest agents, no manipulation. What's the natural accuracy?
2. **Juror objective** — some jurors are secretly told to vote one way. Does accuracy drop?
3. **Bribery** — jurors offered side payments. How cheap is corruption?
4. **Non-voter attack** — jurors deliberate but refuse to vote, forcing hung juries. What's the cost?

We vary jury size (3 to 101), payout splits, deliberation rounds, and agent models (GPT-4o, Claude, mixed) across all of these.

---

## Integration Checklist

For the harness to run against your game, we need:

- [ ] `register_episode` — accepts config, returns episode_id
- [ ] `post_claim` — locks creator's bet
- [ ] `challenge` — locks challenger's bet
- [ ] `post_juror_bond` — locks juror's bond
- [ ] `start_deliberation` — transitions state (no game logic needed during deliberation)
- [ ] `start_voting` — transitions state
- [ ] `cast_vote` — records a juror's binding verdict
- [ ] `settle` — runs the payout math, returns `SettlementResult` with all fields above
- [ ] `expire` — handles early termination, refunds bets
- [ ] `get_state` — returns current phase
- [ ] `get_balances` — returns credit balances per agent

**The settle() payout math is the most important piece.** Everything else is state transitions and escrow. If you get settle() right, the rest is straightforward.

---

## Implemented Adapter Boundary

The initial harness used an in-memory `MockGameAPI`. That implementation and its
settlement calculators have since been deleted. All executable entrypoints,
scripted demos, and runner regressions now use `CoreEngineAPI`, `CoreClient`,
and the Rust/Solidity engine. The current interface is
[`game_api/interface.py`](game_api/interface.py), not the historical method list
above. Juror bonds are deposited with confirmed commitments; deliberation is a
harness schedule, and chain deadlines govern protocol phases. Settlements and
balances are returned by the engine without a Python substitute.

---

## Historical Priority Order

The initial proposal listed the following priorities. Its independent-bond and
manual-transition conventions were superseded by the implemented protocol:

1. **settle()** — the payout math (this is what we actually measure)
2. **register_episode + post_claim + challenge** — basic episode setup
3. **post_juror_bond + cast_vote** — juror participation
4. **start_deliberation + start_voting** — state transitions (can be no-ops that just update state)
5. **expire + get_state + get_balances** — edge cases and queries
