# Veracity Game Engine Specification

Version 0.2

Date 2026-10-24

Status Draft for implementation

Scope Rust game engine and versioned API, with Solidity contracts on Polygon Amoy

This revision supersedes version 0.1. It replaces the custom blockchain build with an application deployed to an existing testnet. It implements a deliberately reduced version of the Veracity dispute mechanism.

This specification defines the game engine and its API. The separately owned
experiment harness is integrated under `harness/`. Experiment execution, agent models,
prompts, jury sampling, deliberation, simulated bribes, observation
permissions, and research metrics belong to that external harness. Research
requirements below describe its context, not additional engine components.

## 1. Purpose

Build a small research environment in which agents create claims, challenge claims, assess evidence, vote, and receive contract-enforced payouts. Use it to measure how agent behaviour changes with incentives and opportunities to coordinate.

The Rust game service validates API actions and records protocol operations.
Solidity enforces bonds, voting rules, and settlement. Polygon Amoy supplies
transaction execution and blockchain consensus. The external harness controls
experiments and observations.

The blockchain provides an observable record and enforces the specified payment rules. It does not determine factual truth, detect collusion automatically, or establish that agents are aligned.

## 2. Changes from version 0.1

| Original requirement                                 | Version 0.2 decision                                              |
| ---------------------------------------------------- | ----------------------------------------------------------------- |
| Build a sovereign EVM chain                          | Deploy Solidity contracts to Polygon Amoy                         |
| Implement consensus and validator staking            | Reuse the existing network                                        |
| Build an EVM, mempool, P2P layer, and state database | Remove these implementation requirements                          |
| Operate a custom RPC service, explorer, and faucet   | Use existing services                                             |
| Create VERA or TVERA                                 | Use native test POL for gas and bonds                             |
| Large set of protocol contracts                      | One non-upgradeable Veracity contract                             |
| Public identity registry                             | Experiment-controlled participant addresses                       |
| On-chain jury sampling and randomness beacon         | Seeded jury assignment in Rust                                    |
| Queued and sequential challenges                     | One designated challenger and at most one challenge per episode   |
| Jury invitations, replacements, and extensions       | Fixed jury, fixed deadlines, and deterministic timeout settlement |
| On-chain reputation and assessment evaluation        | Record and evaluate off-chain                                     |
| Required social feed and wallet UI                   | Rust CLI and machine-readable results first                       |

The core mechanism retained is equal creator and challenger bonds, juror bonds, commit-reveal voting, and distribution of the losing bond. Public identity, decentralised selection, repeated challenges, and reputation are deferred. Results from this reduced mechanism must be described accordingly.

## 3. System boundaries

| Component          | Responsibilities                                                                                         |
| ------------------ | -------------------------------------------------------------------------------------------------------- |
| Rust game service  | Expose the game API, validate actions, preserve artifacts and transaction intents, and return game state |
| External harness   | Load scenarios, assign roles, control observations, execute agents, schedule trials, and evaluate results |
| Rust chain adapter | Encode calls, sign transactions, track nonces and receipts, and collect contract events                  |
| Solidity contract  | Register episode rules, escrow bonds, verify commitments, count votes, and credit withdrawals            |
| Polygon Amoy       | Execute transactions and provide the public ledger                                                       |
| Engine storage     | Store game configuration, claim/evidence/assessment artifacts, vote secrets, operations, and receipts    |

Begin with one Rust process, one SQLite database, and a local artifact directory. An external queue, separate indexer service, web server, and distributed agent infrastructure are unnecessary for the MVP.

Separate deterministic protocol bookkeeping from model calls and network I/O. Local random seeds make assignment reproducible. They do not make model outputs or public network timing deterministic.

## 4. Networks and tooling

### 4.1 Development and public execution

| Setting                   | Local development              | Public experiment                                                                         |
| ------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------- |
| Network                   | Anvil                          | Polygon Amoy                                                                              |
| Chain ID                  | 31337                          | 80002                                                                                     |
| Native gas and bond asset | Anvil development currency     | Test POL                                                                                  |
| HTTP RPC                  | `http://127.0.0.1:8545`        | Configured provider, with `https://polygon-amoy.drpc.org` as a documented public endpoint |
| Explorer                  | Optional                       | `https://amoy.polygonscan.com/`                                                           |
| Funding                   | Prefunded development accounts | Existing Amoy faucets and operator-funded experiment wallets                              |

Amoy network values follow Polygon documentation checked on 2026-10-24. Keep RPC endpoints configurable because availability and rate limits can change. Polygon documentation links to available faucet services.

Use Anvil for unit tests, rapid iteration, and larger batches. Use Amoy for public end-to-end experiments and inspectable settlement. Do not require every exploratory run to use a public network.

### 4.2 Implementation choices

| Area                      | Initial choice                                            |
| ------------------------- | --------------------------------------------------------- |
| Runtime                   | Rust with Tokio                                           |
| Ethereum integration      | Alloy with typed bindings generated from the contract ABI |
| Configuration and records | Serde, TOML configuration, and JSON Lines exports         |
| Local database            | SQLite                                                    |
| Contract development      | Solidity and Foundry                                      |
| Contract tests            | Forge unit, fuzz, and invariant tests                     |
| Telemetry                 | Rust tracing and structured logs                          |

Pin Rust, dependencies, Foundry, and the Solidity compiler in the repository. Set the compiler EVM target explicitly and verify its output on the selected networks before running experiments. There is no custom EVM implementation or network fork to maintain.

## 5. External experiment context

An experiment contains one or more independent episodes. Each episode contains one claim, one creator, one designated challenger, and a fixed jury. An unchallenged episode has no vote or jury payouts.

Only the episode's game identity, roster, and protocol parameters are engine
inputs. The external harness owns the experiment, scenario, model, treatment,
and evaluation records below. The engine does not require those records in
order to instantiate or play a game.

| Record     | Required information                                                                          |
| ---------- | --------------------------------------------------------------------------------------------- |
| Experiment | Unique ID, hypothesis, configuration hash, code revision, dataset version, and seeds          |
| Episode    | Unique bytes32 ID, experiment ID, scenario ID, assigned participants, and protocol parameters |
| Agent      | Agent ID, address, role, model identifier, prompt version, and declared objective             |
| Scenario   | Claim, evidence, observation permissions, and ground truth where available                    |
| Action     | Agent, phase, structured request, validation result, and transaction reference if submitted   |
| Message    | Sender, allowed recipients, channel, phase, and exact content                                 |
| Outcome    | Contract result, evaluator result, payouts, costs, and completion status                      |

Freeze the episode configuration before posting. Record role assignments and communication permissions before observing model outputs. Never change labels or treatment rules after seeing the verdict.

Ground truth belongs to the external evaluator. The external harness controls
scenario visibility and private observations. The game engine holds signing
keys and unrevealed vote material; it does not receive hidden truth labels or
manage treatment-specific observations.

## 6. External harness integration

The external harness adapts its agents to structured game API actions. The
engine validates those actions and invokes the appropriate contract function.
The engine's automated protocol tests do not constitute an experiment harness;
no scripted or model-backed research agents are production engine components.

Agents supply artifact text and decisions. Rust saves the artifact bytes, computes their hashes, generates vote salts, and builds commitments and transaction calldata. Models do not need to calculate cryptographic hashes or construct raw transactions.

| Role             | Available protocol actions                                              |
| ---------------- | ----------------------------------------------------------------------- |
| Creator          | Submit a claim and bond                                                 |
| Challenger       | Challenge with evidence and a matching bond, or abstain                 |
| Juror            | Commit a verdict and assessment hash with a juror bond, then reveal     |
| All participants | Read permitted observations and request withdrawal of their own credits |

The external harness owns deliberation scheduling and behavioral treatment
instructions. The core owns an append-only public forum per episode through
`/v1`; see `docs/public-forum.md`. Assigned participants share chronological
history, with identity derived from credentials. Durable metadata audits record
senders, timestamps, round annotations, message sizes, and exact read responses.
Operator transcript access is separate from participant use. The harness's
public-messaging treatment controls its own sends and observations, not engine
authorization. Forum messages remain off-chain and never change game phases.
For experimental observation, the core also exposes episode-scoped private
two-person chat through `/v1`; see `docs/private-chat.md`. Communication is
prohibited by default but remains technically available, with durable usage
and policy-violation flags. Only the operator can provision permitted controls.
History-enabled participants can read the conversation; history-disabled
participants see only the latest message. The operator retains full private
transcripts and metadata audits in both modes. Chat settings are immutable per
conversation, messages remain off-chain, and chat never changes game phases,
financial rules, or contract evidence. Callers cannot execute shell commands,
access engine storage, select another signer, or bypass chat membership.

The external harness must isolate agent memory and observations. No agent code
or model adapter runs inside the game engine.

The engine holds isolated test-wallet signers and signs validated protocol
actions. Keys are never returned through the API or public exports. Serialize
outgoing transactions per address and retain pending state across restarts.

Protocol rewards and behavioural objectives must be explicit. Receiving test POL does not itself train a model or prove that it optimises wealth. Record whether agents are instructed to maximise a score, whether rewards enter a learning loop, or whether behaviour is evaluated without adaptation.

## 7. Minimal on-chain protocol

### 7.1 Contract and authority

Deploy one non-upgradeable `Veracity` contract containing episode registration, claim and challenge records, bond escrow, voting, settlement, and withdrawal credits.

An operator may register new episodes. Registration fixes the creator, challenger, jury, treasury recipient, configuration hash, bond sizes, payout split, and phase durations. Existing episodes cannot be edited or cancelled by the operator.

Require distinct nonzero creator and challenger addresses. Juror addresses must be unique, nonzero, and different from both parties. The treasury must be distinct from episode participants. Enforce an odd jury size from 3 to 7, with 5 as the default.

This is a controlled experiment roster, not proof of unique human identity or decentralised jury selection. A separate identity contract is unnecessary. The operator cannot choose verdicts, redirect credits, withdraw participant escrow, or override deadlines.

### 7.2 Lifecycle

| State               | Entry condition                                              | Permitted next result                                                |
| ------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------- |
| Registered          | Operator fixes the episode                                   | Creator posts or episode expires unfunded                            |
| Open                | Creator posts the claim and beta                             | Designated challenger challenges or creator is refunded after expiry |
| Commit              | Challenger submits evidence and beta                         | Selected jurors submit commitments and juror bonds                   |
| Reveal              | Commit deadline is reached                                   | Committed jurors reveal valid votes and assessment hashes            |
| SettledCreator      | Reveal deadline passed and creator has the required votes    | Withdrawal of credited balances                                      |
| SettledChallenger   | Reveal deadline passed and challenger has the required votes | Withdrawal of credited balances                                      |
| Aborted             | Reveal deadline passed without a majority                    | Party bond refunds and juror bond accounting                         |
| ExpiredUnchallenged | Challenge deadline passed without a challenge                | Full creator bond refund                                             |
| ExpiredUnfunded     | Posting deadline passed without a creator deposit            | No financial settlement                                              |

Commit and reveal phases may be derived from stored deadlines rather than requiring a separate transaction to advance each phase. Emit events for recorded actions and terminal transitions.

Store a posting deadline at registration. Posting starts the challenge window. A challenge starts the commit window, followed by the reveal window. Use on-chain timestamps in seconds. For each window, accept actions while `block.timestamp < deadline`; the next phase starts at `block.timestamp >= deadline`.

No background contract task runs automatically. The Rust runner submits settlement transactions. Anyone may also call settlement or expiry after the relevant deadline, so stopping the runner cannot make recovery operator-dependent.

### 7.3 Entry points

| Function          | Caller and effect                                                                       |
| ----------------- | --------------------------------------------------------------------------------------- |
| `registerEpisode` | Operator records immutable participants and parameters                                  |
| `postClaim`       | Assigned creator supplies the content hash and exactly beta in native currency          |
| `challenge`       | Assigned challenger supplies the evidence hash and exactly beta before challenge expiry |
| `commitVote`      | Selected juror submits one commitment and exactly the juror bond during Commit          |
| `revealVote`      | Same juror reveals the committed verdict, assessment hash, and salt during Reveal       |
| `settle`          | Anyone settles or aborts a challenged episode after the reveal deadline                 |
| `expire`          | Anyone expires an unfunded or unchallenged episode after its deadline                   |
| `withdraw`        | Caller receives only their own accumulated withdrawal credit                            |

Registration is non-payable. Posting, challenging, and committing reject both underpayment and overpayment. A party cannot bond twice. A juror cannot replace a commitment or reveal twice. Reject zero content, evidence, assessment, and commitment hashes.

No acceptance transaction is required. Committing also posts the juror bond. A juror who never commits has no deposited bond to forfeit, but is recorded as absent.

## 8. Voting and timeout rules

A vote has one of two values, `CREATOR_SUPPORTED` or `CHALLENGER_SUPPORTED`. An abstention is recorded off-chain and does not count toward either side.

The versioned API and contract encode `CREATOR_SUPPORTED` as `uint8(0)` and
`CHALLENGER_SUPPORTED` as `uint8(1)`. Other numeric values are invalid.

Use this commitment definition with standard Solidity ABI encoding, not packed encoding.

```solidity
keccak256(abi.encode(
    block.chainid,
    address(this),
    episodeId,
    jurorAddress,
    verdict,
    assessmentHash,
    salt
))
```

Specify `episodeId`, `assessmentHash`, and `salt` as bytes32, and encode the verdict as uint8 in both implementations. Rust and Solidity must pass shared encoding test vectors.

Generate each salt as a fresh cryptographically random 32-byte secret. Keep salts and unrevealed votes private until Reveal. The public experiment seed must not generate salts. Persist reveal material securely before broadcasting the commitment so a restart does not lose it.

For a configured jury of size n, the required votes are `floor(n / 2) + 1`. Count only valid reveals. Keep the threshold based on the full configured jury even when some jurors are absent.

After the reveal deadline, settle for a side only if it reaches that threshold. Otherwise abort. Do not reduce the threshold, replace jurors, extend deadlines, or let an administrator pick the result. This deliberately replaces the original replacement-and-extension mechanism.

On abort, return both party bonds. Return bonds to jurors who revealed valid votes. Forfeit deposited bonds from jurors who failed to reveal to the treasury. Distribute no losing-bond reward because there is no losing party.

Commit-reveal conceals votes until revelation. It does not prevent private agreements, bribery, vote leakage, or a coordinated majority from reaching a false verdict.

## 9. Bonds and settlement

### 9.1 Parameters

| Parameter   | MVP rule                                                                |
| ----------- | ----------------------------------------------------------------------- |
| beta        | Equal creator and challenger bond, positive integer native base units   |
| gammaBps    | Juror bond multiplier, strictly between 0 and 10000                     |
| jurorBond   | `floor(beta * gammaBps / 10000)`, required to be at least one base unit |
| winnerBps   | Default 6000                                                            |
| jurorBps    | Default 3000                                                            |
| protocolBps | Default 1000                                                            |

Require the three payout shares to sum to 10000. Validate ranges and arithmetic bounds at registration. Use integer arithmetic for all monetary values, with 18 decimal places for native currency amounts.

The 60/30/10 split is an experimental default inherited from the original spec. It is not an established optimum. Bond amounts and phase durations are configuration values chosen before a run. Start with small test amounts and preserve enough separate gas balance to complete voting and withdrawals.

### 9.2 Resolved case

Retain the original conservation equation for distribution of the losing party's bond.

```text
pi_c + sum(pi_j) + pi_p = beta
```

The winner also recovers their own beta. Each qualifying juror also recovers their own juror bond. Those refunds are separate from the equation above.

Qualifying jurors are all jurors with valid timely reveals and nonzero assessment hashes. Pay them equally regardless of which side they supported. The contract checks participation, not assessment quality or factual correctness. Minority voting is not a slashing condition.

For a resolved episode, let m be the number of qualifying jurors. A majority guarantees that m is positive. Compute the reward distribution as follows.

```text
baseProtocol = floor(beta * protocolBps / 10000)
juryPool = floor(beta * jurorBps / 10000)
pi_c = beta - baseProtocol - juryPool
pi_j = floor(juryPool / m)
pi_p = baseProtocol + juryPool - m * pi_j
```

This preserves the original algorithm, including assigning division dust from the jury pool to the treasury. The winner receives any residual from the initial percentage divisions.

Credit the winner with `beta + pi_c`. Credit each qualifying juror with `jurorBond + pi_j`. Credit the treasury with pi_p and any forfeited juror bonds. The losing party receives no party-bond refund.

On expiry without a challenge, return the creator's full beta and charge no dispute fee. Mark the outcome as unchallenged, without assigning a truth label.

### 9.3 Payment safety

Settlement updates state and accrues credits once. It makes no external payments. Withdrawals use checks-effects-interactions and a reentrancy guard. A failed recipient transfer must revert without destroying the recipient's credit or blocking other withdrawals.

For each episode, deposits equal remaining locked liabilities plus withdrawal credits plus amounts already withdrawn. Across the contract, its balance must cover locked liabilities and outstanding credits. Forced or unsolicited native currency may create surplus, so do not require exact equality with the raw contract balance.

There is no administrator sweep of escrow and no upgrade proxy. Bound every juror loop by the maximum jury size. A separate treasury contract is unnecessary because the treasury withdraws its own credits like any other recipient.

## 10. Jury assignment and trust assumptions

The external harness samples jurors without replacement from its configured
eligible pool using a recorded seed and a pinned sampling implementation. It
supplies the fixed roster to the game API. Freeze that roster at registration
and reject party conflicts on-chain.

For paired comparisons, reuse scenario and role assignments while changing the treatment. Record which agent slots hold an assigned adversarial objective. Any deliberate override of random assignment must appear in the manifest.

Seeded assignment is reproducible but operator-controlled and potentially predictable. It is not manipulation-resistant randomness, public Sybil resistance, or evidence of independent ownership of addresses. Do not use block timestamps or block hashes as a substitute for those properties.

The MVP trusts the operator for scenario construction, assignment, private observations, and complete logging. The contract independently enforces registered protocol rules. Keep this distinction visible in research claims.

## 11. External harness experiments

Start with claims that have independently checkable answers. Separate verdict accuracy from evidence of coordination.

| Condition                  | Question                                                                               |
| -------------------------- | -------------------------------------------------------------------------------------- |
| Independent baseline       | How accurate are agents under the mechanism without an assigned adversarial objective? |
| Individual juror objective | Does a privately assigned objective alter an individual juror's vote?                  |
| Creator bribe offers       | Do jurors support a creator's false claim when given a simulated bribe offer?          |
| Reveal withholding         | Can enough jurors withholding their reveals force aborts, and what bonds are lost?     |

Compare minority and majority shares of adversarial jurors while keeping the total jury size fixed. Include scripted honest and adversarial policies to verify that the expected protocol outcomes are reachable before interpreting model behaviour.

For the MVP, simulated bribe offers and side rewards are recorded in a separate experimental utility ledger. They are not enforced payouts from the Veracity contract. Label them as simulated and do not mix them into native-currency conservation or on-chain profit.

Predefine trial counts, adversarial juror assignments, allowed channels, and success criteria. Log all completed, aborted, failed, and excluded episodes with reasons. A shared wrong answer alone is not evidence of collusion because agents can share errors or training data. Prompted coordination demonstrates behaviour under the specified treatment, not spontaneous emergence.

### 11.1 Required measurements

| Metric                      | Definition                                                                                                                  |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Verdict accuracy            | Correct contract verdicts divided by settled episodes with known ground truth                                               |
| False-verdict rate          | Incorrect contract verdicts divided by settled episodes with known ground truth                                             |
| Attack success rate         | Attack-target outcomes divided by all assigned attack episodes, with abort and infrastructure counts reported separately    |
| Completion rate             | Settled episodes divided by all scheduled episodes                                                                          |
| Valid reveal rate           | Valid revealed votes divided by assigned jury slots                                                                         |
| Participation loss          | Juror bonds forfeited through failed revelation                                                                             |
| Infrastructure failure rate | Episodes blocked by RPC, funding, model-provider, or runner failures divided by scheduled episodes                          |

Report unknown-truth and unchallenged episodes separately. Record both the agent's chosen action and transaction inclusion outcome so a network delay is not silently classified as intentional non-participation. Use repeated trials and report uncertainty rather than presenting one successful attack as a measured rate.

## 12. Data collection and integrity

The engine keeps claims, evidence, and assessments off-chain. Store their exact
UTF-8 bytes with LF line endings before hashing with Keccak-256. Do not apply
silent trimming or Unicode normalisation after hashing. Hash configuration
using a documented canonical JSON encoding shared by all writers. The external
harness stores its own prompts, model outputs, observations, and messages; these
are not game engine records.

The contract stores episode IDs, configuration hashes, claim and evidence hashes, participant addresses, parameters, deadlines, commitments, revealed votes, terminal results, and withdrawal credits. Emit events for registrations, deposits, commitments, reveals, settlement or expiry, forfeitures, credited payouts, and withdrawals.

Each export must retain enough information to join agent behaviour to the ledger.

| Category       | Required fields                                                                                                                   |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Provenance     | Experiment and episode IDs, configuration digest, code revision, model and prompt versions                                        |
| Execution      | Observations, visible messages, structured actions, validation failures, token usage, and model latency                           |
| Chain evidence | Chain ID, contract address, transaction hash, receipt status, block number and hash, log index, gas used, and effective gas price |
| Evaluation     | Reference label where available, evaluator version, predicted and actual outcome, reward components, and failure reason           |

Generate SQLite records and JSON Lines exports from the same collected event stream. SQLite is the local research record, while contract state is authoritative for financial settlement. Rebuild the contract projection by replaying logs from its deployment block. Model observations and private messages require their off-chain records and cannot be reconstructed from the blockchain alone.

A hash proves correspondence to anchored bytes, not that evidence is true or that logs are complete. Retain referenced artifacts and disclose missing data. Keep keys and unrevealed salts out of shareable exports.

## 13. Chain adapter reliability

At startup, verify the expected chain ID, contract address, deployed code hash, and ABI version. Support only explicitly configured Anvil and Amoy targets in the MVP. Refuse accidental mainnet execution.

Estimate fees through the selected provider and enforce configured transaction budgets. Check that each wallet can cover its bond and expected gas before starting an episode. Do not let an LLM choose arbitrary gas limits, recipient addresses, or transaction value.

Persist transaction intent, sender nonce, signed transaction hash, and broadcast status. After an uncertain submission, reconcile by transaction hash and nonce before retrying. A retry must not become a second economic action.

Distinguish submitted, included, reverted, and sufficiently confirmed transactions. A receipt is not itself a finality guarantee. Use a provider-supported and validated finalized-block policy where available. If only confirmation depth is available, record the chosen depth and label results accordingly rather than calling them finalized.

Record block hashes and deduplicate events by chain ID, contract address, block hash, transaction hash, and log index. Recheck canonical block hashes during catch-up and rewind affected projections after a reorganisation. Apply bounded backoff for RPC rate limits and reconnects.

Contract deadlines use chain time. The external harness schedules its actions
with a margin for model latency, transaction inclusion, and confirmation; the
engine does not schedule experiments or extend phases. Choose longer public
windows than local test windows. Infrastructure failure does not permit
retrospective changes to registered rules.

## 14. Implementation layout and build order

| Path           | Purpose                                                                                  |
| -------------- | ---------------------------------------------------------------------------------------- |
| `contracts/`   | Foundry project, Veracity contract, deployment script, and contract tests                |
| `core/`        | Rust executable with API, game, chain, and storage modules                             |
| `harness/`     | Python experiments and agents that call the engine's versioned HTTP API                |
| `configs/`     | Game service deployment configuration                                                  |
| `deployments/` | Chain IDs, addresses, deployment blocks, compiler settings, code hashes, and ABI digests |

Start with modules in one Rust crate. Split crates or services when implementation needs justify it.

| Phase | Deliverable and completion condition                                                      |
| ----- | ----------------------------------------------------------------------------------------- |
| 1     | Contract tests cover every terminal outcome and conserve deposited funds                  |
| 2     | Game API tests complete claim, challenge, commit/reveal, settlement, and withdrawal on Anvil |
| 3     | External team integrates its harness; model adapters and treatment execution remain outside the engine |
| 4     | Same contract and game API flow completes on Amoy with public transaction references      |
| 5     | External harness runs paired trials and produces analysis using game API results          |

Before Amoy execution, record the exact deployment manifest, fund isolated test wallets, verify the deployed bytecode, and complete a small smoke run. Bulk local runs and public-network runs must be identified separately in the results.

## 15. Verification and acceptance

| Area                   | Required check                                                                                                  |
| ---------------------- | --------------------------------------------------------------------------------------------------------------- |
| Registration           | Duplicate jurors, party conflicts, invalid jury size, duplicate IDs, and invalid parameters are rejected        |
| Bonds                  | Exact deposits are enforced and double deposits are rejected                                                    |
| Commit integrity       | Rust and Solidity agree on commitment encoding; incorrect salt, address, verdict, or assessment hash fails      |
| Phase boundaries       | Actions at each deadline obey the same exclusive and inclusive rules                                            |
| Verdicts               | Creator and challenger outcomes both work; the full-jury threshold is never reduced                             |
| Timeouts               | Missing commits, missing reveals, and no-majority cases settle according to the specified refund rules          |
| Expiry                 | Unfunded and unchallenged episodes expire safely without inappropriate fees                                     |
| Accounting             | Fuzz tests cover rounding and invariants cover locked funds, credits, withdrawals, and single settlement        |
| Withdrawals            | Reentrant and reverting recipients cannot steal funds or block other recipients                                 |
| Operator boundary      | Operator cannot edit active rules, choose verdicts, or withdraw participant balances                            |
| Engine recovery        | Restart resumes pending transactions and retained reveal material without duplicate actions                     |
| Collection             | Duplicate events and simulated reorganisations do not duplicate payouts or research records                     |
| Engine privacy         | Role credentials cannot select another signer; keys and unrevealed vote material stay out of public API output |
| End-to-end             | Both winning sides and a timeout complete through withdrawal on Anvil; a full challenged flow completes on Amoy |
| External research output | The separate harness joins game results with its own treatments, observations, and evaluation records        |

The game engine MVP is complete when its versioned API exposes the specified
game actions and state, the contracts enforce settlement without manual payout
decisions, and local-chain tests verify the rules and protocol evidence.
Treatment execution, scored observations, and research analysis are acceptance
criteria for the separate external harness.

## 16. Deferred extensions

Extend only when a research question requires it. Candidates include multiple challenges, juror replacement, stronger identity checks, manipulation-resistant jury randomness, reputation, quality-weighted rewards, enforced side-payment experiments, richer agent isolation, and a web interface.

A custom blockchain, custom consensus protocol, native token launch, bridge, production financial deployment, and public permissionless identity system are outside this MVP. Amoy experiments measure behaviour under test conditions and do not establish real-money incentive compatibility or general alignment guarantees.

## 17. API implementation boundary

The implementation exposes the game through a versioned `/v1` HTTP API with an
OpenAPI document and the integration guide in `docs/api.md`. This presentation
replaces the earlier CLI-first assumption. The external experiment harness owns
agent models, prompts, role sampling, private observations, deliberation,
simulated utility, and research metrics. It supplies and
records an explicit roster and provenance when instantiating an episode.

The Python harness is integrated in this repository under `harness/` and remains
a separate process and ownership boundary. It calls the Rust API; experiment
logic must not move into the engine.

The game service owns immutable episode registration, artifact integrity,
isolated signing, durable operation recovery, chain evidence, and contract-backed
queries. The monetary, voting, deadline, and settlement rules above remain
unchanged. `harness/GAME_BUILDER_HANDOFF.md` is an integration wish list rather than a
replacement protocol; its floating amounts, larger juries, direct votes, and
manual phase transitions are not implemented as game rules.

## 18. References

- [Original Veracity paper, A New Incentive Model For Content Trust](https://arxiv.org/abs/2507.09972)
- [Polygon network details and RPC endpoints](https://docs.polygon.technology/pos/reference/rpc-endpoints/)
- [Polygon faucet](https://faucet.polygon.technology/)
- [Amoy explorer](https://amoy.polygonscan.com/)
- [Alloy getting started](https://alloy.rs/introduction/getting-started/)
- [Foundry](https://getfoundry.sh/)
- [Foundry Anvil configuration source](https://foundry-rs.github.io/foundry/src/anvil/config.rs.html)

The paper motivates the incentive mechanism. The episode restrictions, agent interface, timeout policy, and experiment methodology in this revision are implementation and research-design choices.
