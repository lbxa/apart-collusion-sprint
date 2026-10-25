"""Real SDK -> HTTP -> Rust -> Solidity acceptance, with an explicit local clock."""

import unittest
import uuid

from game_api.client import CoreClient, CoreHTTPError
from game_api.generated import ProtocolParameters, RegisterEpisode
from game_api.local_engine import LocalEngine


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
                episode_id=episode_id, creator_id="creator", challenger_id="challenger",
                juror_ids=jurors, treasury_id="treasury",
                parameters=ProtocolParameters(
                    beta_wei=str(beta), gamma_bps=1000, posting_duration_secs=300,
                    challenge_duration_secs=300, commit_duration_secs=300,
                    reveal_duration_secs=300,
                ),
            )
            await client.wait_operation(await client.register_episode(
                registration, idempotency_key="register"))
            await client.wait_operation(await client.post_claim(
                episode_id, "creator", "Exact settlement claim.\n", idempotency_key="claim"))
            await client.wait_operation(await client.challenge(
                episode_id, "challenger", "Exact counter-evidence.\n", idempotency_key="challenge"))

            # A handle can be saved before the chain has included a transaction.
            await local.rpc("evm_setAutomine", [False])
            try:
                pending = await client.commit(
                    episode_id, jurors[0], "CREATOR_SUPPORTED", "Saved assessment.\n",
                    idempotency_key="saved-commit-key",
                )
                self.assertIn(pending.status, {"prepared", "submitted"})
                transaction_hash = pending.transaction.transaction_hash
                api_url = client.api_url
                await client.close()

                # New Python client, same deployment: no Python episode mapping,
                # in-memory committed set, or locally retained ballot is needed.
                async with CoreClient(api_url, operator_token="dev-operator",
                                      participant_tokens=credentials) as resumed:
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
                        episode_id, jurors[0], "CREATOR_SUPPORTED", "Saved assessment.\n",
                        idempotency_key="saved-commit-key",
                    )
                    self.assertEqual(replayed.operation_id, pending.operation_id)
                    self.assertEqual(replayed.transaction.transaction_hash, transaction_hash)
                    for juror in jurors[1:]:
                        await resumed.wait_operation(await resumed.commit(
                            episode_id, juror, "CREATOR_SUPPORTED", f"Assessment for {juror}.\n",
                            idempotency_key=f"commit-{juror}"))
                    committed = await resumed.get_episode(episode_id)
                    self.assertEqual(committed.total_deposited_wei, str(2 * beta + 3 * (beta // 10)))
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
                        await resumed.wait_operation(await resumed.reveal(
                            episode_id, juror, idempotency_key=f"reveal-{juror}"))
                    state = await resumed.get_episode(episode_id)
                    self.assertEqual(state.phase, "REVEAL")
                    self.assertTrue(all(juror.revealed for juror in state.jurors))
                    await local.advance_to_deadline(episode_id, "reveal_deadline")
                    await resumed.wait_operation(await resumed.settle(
                        episode_id, idempotency_key="final-settlement"))
                    settlement = await resumed.get_settlement(episode_id)
                    self.assertEqual(settlement.outcome, "SETTLED_CREATOR")
                    self.assertEqual(settlement.winner_payout, str(beta * 8 // 5))
                    self.assertEqual(settlement.protocol_fee, str(beta // 10))
                    self.assertEqual(settlement.total_deposited, settlement.total_credited)
                    self.assertEqual(set(settlement.juror_payouts.values()), {str(beta // 5)})
                    balances = await resumed.get_balances(episode_id)
                    self.assertEqual(balances.entitlements["creator"], settlement.winner_payout)
                    self.assertEqual(balances.withdrawal_credits["creator"], settlement.winner_payout)
                    self.assertEqual(int(settlement.total_deposited),
                        int(settlement.winner_payout) + int(settlement.protocol_fee)
                        + sum(map(int, settlement.juror_payouts.values())))
            finally:
                await local.rpc("evm_setAutomine", [True])


if __name__ == "__main__":
    unittest.main()
