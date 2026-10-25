# Veracity contract

`Veracity` is the non-upgradeable financial authority for `SPEC.md` v0.2.
The experiment harness owns prompts, deliberation, and evaluation.
The contract owns participant eligibility, phase deadlines, escrow, valid
commitment reveals, the full-roster majority, payout arithmetic, and credits.

## Architecture contract

- An immutable operator registers episodes; no operation edits or cancels them.
- Episode configuration and juror commitments are immutable once recorded.
- Actions are accepted strictly before their deadlines. Reveal begins at the
  commit deadline; settlement and expiry begin at the corresponding deadline.
- `settle` owns the deterministic payout policy. It performs no external calls.
- `withdraw` owns payment effects and protects credits with checks-effects-
  interactions and a reentrancy guard; failed transfers revert atomically.
- The EVM transaction is the consistency boundary. A rejected command has no
  partial effect; repeated economic actions are rejected by episode state.
- Rust is an ABI adapter, not a second authority for financial settlement.
- Typed errors classify authorization, invalid parameters, phases, deposits,
  duplicate actions, commitments, and recipient failures.
- Unit and fuzz tests prove boundaries and integer conservation. Stateful
  invariants exercise action sequences and withdrawals on an isolated EVM.

## ABI and amounts

`Config` fixes creator, challenger, a unique odd jury of 3–7, treasury,
configuration hash, party bond `beta`, basis-point shares, and four positive
durations in seconds. Amounts are uint256 native base units, never floats.
The verdict wire values are `0 = CREATOR_SUPPORTED` and
`1 = CHALLENGER_SUPPORTED`.

`getEpisode`, `getJuror`, and `phase` expose game state. `getSettlement`
exposes the immutable terminal payout decomposition. Its `jurorReward`
excludes the refunded juror bond, and `protocolFee` excludes forfeited bonds.
`entitlement(episodeId, recipient)` is the historical episode entitlement;
`credits(recipient)` is the currently withdrawable balance across episodes.
`totalDeposited`, `totalLocked`, `totalCredits`, and `totalWithdrawn` support
liability checks. Unsolicited currency can make contract balance exceed them.

## Verification

```sh
forge test --root contracts
forge fmt --root contracts --check
bash contracts/check-artifact.sh
```

The compiler is pinned to Solidity 0.8.28 and the Cancun EVM target. Tests use
a small local cheat-code interface and need no network test library.
After a deliberate contract change, build with `forge build --root contracts`
and regenerate the committed deployment input with
`bash contracts/check-artifact.sh --write`. The verification gate compares
the normalized generated artifact against that committed file.
The deployment artifact omits compiler AST identifiers, which can change with
the compilation unit despite identical bytecode. Its runtime bytecode contains
immutable placeholders; deployment identity uses the actual on-chain code hash.

## Changelog

### 2026-10-24

- `SPEC.md` v0.2 takes precedence over the harness sketch where they differ:
  jury size is 3–7, commitment posting supplies the juror bond, and fixed
  commit/reveal deadlines replace manually advanced deliberation phases.
- Deployment artifacts retain ABI, creation/runtime bytecode, and compiler
  settings but omit unused AST-ID-keyed immutable references: those IDs vary
  across build/test compilation units even when the deployed bytes do not.
