"""Real SDK -> HTTP -> Rust -> Solidity acceptance, with an explicit local clock."""

import unittest
import uuid

import pytest

from game_api.client import CoreClient, CoreHTTPError
from game_api.generated import ProtocolParameters, RegisterEpisode
from game_api.local_engine import LocalEngine

pytestmark = pytest.mark.integration


async def test_local_engine_authorizes_the_full_fifteen_juror_roster():
    episode_id = f"sdk_{uuid.uuid4().hex}"
    async with LocalEngine() as local:
        client = local.client
        await client.wait_operation(
            await client.register_episode(
                RegisterEpisode(
                    episode_id=episode_id,
                    creator_id="creator",
                    challenger_id="challenger",
                    juror_ids=[f"juror-{n}" for n in range(1, 16)],
                    treasury_id="treasury",
                    parameters=ProtocolParameters(
                        beta_wei="1000",
                        gamma_bps=1000,
                        posting_duration_secs=300,
                        challenge_duration_secs=300,
                        commit_duration_secs=300,
                        reveal_duration_secs=300,
                    ),
                ),
                idempotency_key="register-fifteen",
            )
        )
        await client.wait_operation(
            await client.post_claim(
                episode_id, "creator", "A recorded claim.", idempotency_key="claim"
            )
        )
        await client.wait_operation(
            await client.challenge(
                episode_id, "challenger", "A recorded objection.", idempotency_key="challenge"
            )
        )
        operation = await client.wait_operation(
            await client.commit(
                episode_id,
                "juror-15",
                "CREATOR_SUPPORTED",
                "Recorded assessment.",
                idempotency_key="commit-fifteen",
            )
        )
        assert operation.actor_id == "juror-15" and operation.transaction.receipt.confirmed
        episode = await client.get_episode(episode_id)
        assert len(episode.jurors) == 15
        assert next(j for j in episode.jurors if j.actor_id == "juror-15").commitment is not None


class ClientIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_actions_reconnect_pending_reconciliation_and_exact_settlement(self):
        # Larger than a binary64 integer can retain. The local signers are funded
        # with 10,000 ETH, so these base-unit stakes still fit their real balances.
        beta = 100 * (2**54 + 1)
        episode_id = f"sdk_{uuid.uuid4().hex}"
        jurors = ["juror-1", "juror-2", "juror-3"]
        credentials = {actor: f"dev-{actor}" for actor in ["creator", "challenger", *jurors]}
        async with LocalEngine() as local:
            client = local.client
            registration = RegisterEpisode(
                episode_id=episode_id,
                creator_id="creator",
                challenger_id="challenger",
                juror_ids=jurors,
                treasury_id="treasury",
                parameters=ProtocolParameters(
                    beta_wei=str(beta),
                    gamma_bps=1000,
                    posting_duration_secs=300,
                    challenge_duration_secs=300,
                    commit_duration_secs=300,
                    reveal_duration_secs=300,
                ),
            )
            await client.wait_operation(
                await client.register_episode(registration, idempotency_key="register")
            )
            await client.wait_operation(
                await client.post_claim(
                    episode_id, "creator", "Exact settlement claim.\n", idempotency_key="claim"
                )
            )
            await client.wait_operation(
                await client.challenge(
                    episode_id,
                    "challenger",
                    "Exact counter-evidence.\n",
                    idempotency_key="challenge",
                )
            )

            # A handle can be saved before the chain has included a transaction.
            await local.rpc("evm_setAutomine", [False])
            try:
                pending = await client.commit(
                    episode_id,
                    jurors[0],
                    "CREATOR_SUPPORTED",
                    "Saved assessment.\n",
                    idempotency_key="saved-commit-key",
                )
                self.assertIn(pending.status, {"prepared", "submitted"})
                transaction_hash = pending.transaction.transaction_hash
                api_url = client.api_url
                await client.close()

                # New Python client, same deployment: no Python episode mapping,
                # in-memory committed set, or locally retained ballot is needed.
                async with CoreClient(
                    api_url, operator_token="dev-operator", participant_tokens=credentials
                ) as resumed:
                    saved = await resumed.get_operation(pending.operation_id)
                    reconciled = await resumed.reconcile_operation(saved)
                    self.assertEqual(reconciled.transaction.transaction_hash, transaction_hash)
                    self.assertEqual(reconciled.operation_id, pending.operation_id)
                    await local.rpc("evm_mine", [])
                    await local.rpc("evm_setAutomine", [True])
                    confirmed = await resumed.wait_operation(pending.operation_id)
                    self.assertTrue(confirmed.transaction.receipt.success)
                    self.assertTrue(confirmed.transaction.receipt.confirmed)

                    # Replaying a command after a lost response recovers its
                    # existing handle and original transaction, without a new bond.
                    replayed = await resumed.commit(
                        episode_id,
                        jurors[0],
                        "CREATOR_SUPPORTED",
                        "Saved assessment.\n",
                        idempotency_key="saved-commit-key",
                    )
                    self.assertEqual(replayed.operation_id, pending.operation_id)
                    self.assertEqual(replayed.transaction.transaction_hash, transaction_hash)
                    for juror in jurors[1:]:
                        await resumed.wait_operation(
                            await resumed.commit(
                                episode_id,
                                juror,
                                "CREATOR_SUPPORTED",
                                f"Assessment for {juror}.\n",
                                idempotency_key=f"commit-{juror}",
                            )
                        )
                    committed = await resumed.get_episode(episode_id)
                    self.assertEqual(
                        committed.total_deposited_wei, str(2 * beta + 3 * (beta // 10))
                    )
                    self.assertEqual(committed.phase, "COMMIT")

                    # Settlement does no hidden revealing or clock advancement.
                    with self.assertRaises(CoreHTTPError) as rejected:
                        await resumed.settle(episode_id, idempotency_key="early-settlement")
                    self.assertEqual(rejected.exception.status, 409)
                    self.assertEqual(rejected.exception.problem.code, "ACTION_REJECTED")
                    state = await resumed.get_episode(episode_id)
                    self.assertEqual(state.phase, "COMMIT")
                    self.assertFalse(any(juror.revealed for juror in state.jurors))

                    await local.advance_to_deadline(episode_id, "commit_deadline")
                    for juror in jurors:
                        await resumed.wait_operation(
                            await resumed.reveal(
                                episode_id, juror, idempotency_key=f"reveal-{juror}"
                            )
                        )
                    state = await resumed.get_episode(episode_id)
                    self.assertEqual(state.phase, "REVEAL")
                    self.assertTrue(all(juror.revealed for juror in state.jurors))
                    await local.advance_to_deadline(episode_id, "reveal_deadline")
                    await resumed.wait_operation(
                        await resumed.settle(episode_id, idempotency_key="final-settlement")
                    )
                    settlement = await resumed.get_settlement(episode_id)
                    self.assertEqual(settlement.outcome, "SETTLED_CREATOR")
                    self.assertEqual(settlement.winner_payout, str(beta * 8 // 5))
                    self.assertEqual(settlement.protocol_fee, str(beta // 10))
                    self.assertEqual(settlement.total_deposited, settlement.total_credited)
                    self.assertEqual(set(settlement.juror_payouts.values()), {str(beta // 5)})
                    balances = await resumed.get_balances(episode_id)
                    self.assertEqual(balances.entitlements["creator"], settlement.winner_payout)
                    self.assertEqual(
                        balances.withdrawal_credits["creator"], settlement.winner_payout
                    )
                    self.assertEqual(
                        int(settlement.total_deposited),
                        int(settlement.winner_payout)
                        + int(settlement.protocol_fee)
                        + sum(map(int, settlement.juror_payouts.values())),
                    )
            finally:
                await local.rpc("evm_setAutomine", [True])


if __name__ == "__main__":
    unittest.main()


# Anvil's first default development account; models recognise it on sight.
ANVIL_DEFAULT_ACCOUNT = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


@pytest.mark.integration
async def test_seeded_network_has_its_own_stable_accounts_and_back_dated_clock():
    import time

    genesis = int(time.time()) - 3 * 86400
    seen = []
    for _ in range(2):
        async with LocalEngine(key_seed=301, genesis_timestamp=genesis) as local:
            participants = await local.client.participants()
            seen.append({p.actor_id: p.address.lower() for p in participants})
            assert abs(await local.latest_timestamp() - genesis) < 600
    async with LocalEngine() as default:
        defaults = {p.actor_id: p.address.lower() for p in await default.client.participants()}
    assert ANVIL_DEFAULT_ACCOUNT.lower() in defaults.values()
    assert ANVIL_DEFAULT_ACCOUNT.lower() not in seen[0].values()
    # The same seed gives the same accounts, so paired arms see identical addresses.
    assert seen[0] == seen[1]


async def test_executed_credit_transfers_are_read_from_contract_events():
    from veracity_harness.runner import credit_transfers

    episode_id = f"sdk_{uuid.uuid4().hex}"
    async with LocalEngine() as local:
        client = local.client
        first_block = int(await local.rpc("eth_blockNumber", []), 16)
        registration = RegisterEpisode(
            episode_id=episode_id,
            creator_id="creator",
            challenger_id="challenger",
            juror_ids=["juror-1", "juror-2", "juror-3"],
            treasury_id="treasury",
            parameters=ProtocolParameters(
                beta_wei="1000",
                gamma_bps=1000,
                posting_duration_secs=300,
                challenge_duration_secs=300,
                commit_duration_secs=300,
                reveal_duration_secs=300,
            ),
        )
        await client.wait_operation(
            await client.register_episode(registration, idempotency_key="register")
        )
        await client.wait_operation(
            await client.post_claim(episode_id, "creator", "Unchallenged.\n", idempotency_key="c")
        )
        await local.expire_episode(episode_id)
        assert await credit_transfers(local, client, first_block) == []
        operation = await client.wait_operation(
            await client.transfer_credits(
                episode_id, "creator", "juror-2", 400, idempotency_key="pay"
            )
        )
        assert operation.status == "confirmed"
        (transfer,) = await credit_transfers(local, client, first_block)
        assert {key: transfer[key] for key in ("sender", "recipient", "amount_wei")} == {
            "sender": "creator",
            "recipient": "juror-2",
            "amount_wei": "400",
        }
        assert transfer["transaction_hash"] == operation.transaction.transaction_hash
        balances = await client.get_balances(episode_id)
        assert balances.withdrawal_credits["creator"] == "600"
        assert balances.withdrawal_credits["juror-2"] == "400"
