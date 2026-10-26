"""Acceptance tests for the real Python harness -> Rust API -> Anvil stack.

These tests deliberately require the built engine and pinned Foundry tools.
They require actual contract execution and never call a model provider.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

from experiments.runner import ExperimentRunner
from experiments.treatments import TreatmentConfig
from game_api.core_engine import CoreEngineAPI
from game_api.money import base_units_to_tokens
from game_api.types import EpisodeConfig, PayoutConfig, Phase, Scenario, Verdict


ROOT = Path(__file__).resolve().parents[2]


class CoreIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def _get(self, api: CoreEngineAPI, path: str) -> dict:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(f"{api.api_url}{path}") as response:
                self.assertEqual(response.status, 200, await response.text())
                return await response.json()

    async def _rpc(self, api: CoreEngineAPI, method: str, params: list):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.post(api.rpc_url, json={
                "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
            }) as response:
                self.assertEqual(response.status, 200)
                data = await response.json()
                self.assertNotIn("error", data)
                return data["result"]

    async def _listening(self, url: str) -> bool:
        address = urlsplit(url)
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(address.hostname, address.port), timeout=2,
            )
        except (OSError, TimeoutError):
            return False
        writer.close()
        await writer.wait_closed()
        return True

    async def _pending_transaction(self, api: CoreEngineAPI, action: asyncio.Task) -> dict:
        async with asyncio.timeout(10):
            while True:
                pending = await self._rpc(api, "eth_pendingTransactions", [])
                if pending:
                    return pending[0]
                if action.done():
                    self.fail("action finished before its real transaction reached Anvil")
                await asyncio.sleep(0.01)

    async def _register(
        self, api: CoreEngineAPI, *, jury_size: int = 3,
        payout: PayoutConfig | None = None,
    ) -> tuple[str, str, str, list[str], str]:
        episode = f"integration_{uuid.uuid4().hex}"
        creator = f"creator_{episode}"
        challenger = f"challenger_{episode}"
        jurors = [f"juror_{index}_{episode}" for index in range(jury_size)]
        treasury = f"treasury_{episode}"
        config = EpisodeConfig(
            episode_id=episode, payout=payout or PayoutConfig(),
            jury_size=jury_size, deliberation_rounds=1,
        )
        actual = await api.register_episode(config, creator, challenger, jurors, treasury)
        self.assertEqual(actual, episode)
        return episode, creator, challenger, jurors, treasury

    async def _open(self, api: CoreEngineAPI, **kwargs):
        episode, creator, challenger, jurors, treasury = await self._register(api, **kwargs)
        self.assertTrue(await api.post_claim(episode, creator, content="A test claim.\n"))
        self.assertTrue(await api.challenge(episode, challenger, evidence="Test counter-evidence.\n"))
        return episode, creator, challenger, jurors, treasury

    async def _assert_authoritative(self, api: CoreEngineAPI, result) -> dict:
        raw = await self._get(api, f"/v1/episodes/{result.episode_id}/settlement")
        self.assertEqual(result.engine_evidence, raw)
        self.assertEqual(api.backend, "core")
        self.assertEqual(raw["deployment"]["chain_id"], 31337)
        self.assertEqual(raw["total_deposited"], raw["total_credited"])
        distributed = (
            int(raw["winner_payout"])
            + sum(map(int, raw["juror_payouts"].values()))
            + int(raw["protocol_fee"])
            + sum(map(int, raw["forfeited_bonds"].values()))
            + sum(map(int, raw["refunds"].values()))
        )
        self.assertEqual(distributed, int(raw["total_deposited"]))
        self.assertEqual(result.winner_payout, base_units_to_tokens(raw["winner_payout"]))
        self.assertEqual(result.protocol_fee, base_units_to_tokens(raw["protocol_fee"]))
        return raw

    async def test_00_autodetects_integrated_repository_and_cleans_up_both_processes(self):
        api = CoreEngineAPI()
        try:
            await api.start()
            health = await self._get(api, "/v1/health")
            self.assertEqual(health["api_version"], "v1")
            self.assertEqual(health["deployment"], api.deployment)
            self.assertEqual(api.deployment["chain_id"], 31337)
            self.assertTrue(api.deployment["contract_address"].startswith("0x"))
            self.assertNotEqual(urlsplit(api.api_url).port, 0)
            self.assertEqual(await self._rpc(api, "eth_chainId", []), "0x7a69")
            api_url, rpc_url = api.api_url, api.rpc_url
        finally:
            await api.stop()
        self.assertFalse(await self._listening(api_url))
        self.assertFalse(await self._listening(rpc_url))

    async def test_context_manager_cleans_up_after_a_caller_failure(self):
        api_url = rpc_url = ""
        with self.assertRaisesRegex(RuntimeError, "caller failure"):
            async with CoreEngineAPI() as api:
                api_url, rpc_url = api.api_url, api.rpc_url
                self.assertEqual((await self._get(api, "/v1/health"))["api_version"], "v1")
                raise RuntimeError("caller failure")
        self.assertFalse(await self._listening(api_url))
        self.assertFalse(await self._listening(rpc_url))

    async def test_both_winners_all_jury_sizes_pay_minority_and_preserve_integer_dust(self):
        async with CoreEngineAPI() as api:
            for jury_size, juror_units, protocol_units in [(3, 200, 100), (5, 160, 100), (7, 142, 106)]:
                for verdict, phase in [
                    (Verdict.CREATOR_SUPPORTED, Phase.SETTLED_CREATOR),
                    (Verdict.CHALLENGER_SUPPORTED, Phase.SETTLED_CHALLENGER),
                ]:
                    with self.subTest(jury_size=jury_size, verdict=verdict):
                        episode, creator, challenger, jurors, treasury = await self._open(api, jury_size=jury_size)
                        majority = jury_size // 2 + 1
                        votes = {}
                        for index, juror in enumerate(jurors):
                            vote = verdict if index < majority else (
                                Verdict.CHALLENGER_SUPPORTED
                                if verdict == Verdict.CREATOR_SUPPORTED else Verdict.CREATOR_SUPPORTED
                            )
                            votes[juror] = vote
                            self.assertTrue(await api.cast_vote(episode, juror, vote, assessment=f"Assessment {index}.\n"))
                        result = await api.settle(episode)
                        raw = await self._assert_authoritative(api, result)
                        self.assertEqual(result.outcome, phase)
                        winner = creator if verdict == Verdict.CREATOR_SUPPORTED else challenger
                        self.assertEqual(result.winner_id, winner)
                        self.assertEqual(result.final_votes, votes)
                        self.assertEqual(raw["winner_payout"], "1600")
                        self.assertEqual(raw["protocol_fee"], str(protocol_units))
                        self.assertEqual(set(result.juror_payouts), set(jurors))
                        for amount in result.juror_payouts.values():
                            self.assertEqual(amount, base_units_to_tokens(juror_units))
                        self.assertFalse(result.forfeited_bonds)
                        balances = await api.get_balances(episode)
                        self.assertEqual(balances[winner], 16)
                        self.assertEqual(balances[treasury], base_units_to_tokens(protocol_units))

    async def test_configuration_controls_low_stakes_bonds_and_custom_payout_shares(self):
        cases = [
            (PayoutConfig(creator_bet=1, challenger_bet=1, juror_bond=0.1), "100", 1000, "160", "20", "10"),
            (PayoutConfig(creator_bet=10, challenger_bet=10, juror_bond=2, winner_pct=0.8,
                          juror_pool_pct=0.15, protocol_pct=0.05), "1000", 2000, "1800", "250", "50"),
        ]
        async with CoreEngineAPI() as api:
            for payout, beta, gamma, winner, juror_payout, protocol in cases:
                with self.subTest(payout=payout):
                    episode, _, _, jurors, _ = await self._open(api, payout=payout)
                    state = await self._get(api, f"/v1/episodes/{episode}")
                    self.assertEqual(state["configuration"]["parameters"]["beta_wei"], beta)
                    self.assertEqual(state["configuration"]["parameters"]["gamma_bps"], gamma)
                    for juror in jurors:
                        await api.cast_vote(episode, juror, Verdict.CREATOR_SUPPORTED, assessment="Evidence supports the claim.\n")
                    raw = await self._assert_authoritative(api, await api.settle(episode))
                    self.assertEqual(raw["winner_payout"], winner)
                    self.assertEqual(set(raw["juror_payouts"].values()), {juror_payout})
                    self.assertEqual(raw["protocol_fee"], protocol)

    async def test_absent_jurors_have_no_deposit_or_forfeiture_and_do_not_lower_quorum(self):
        async with CoreEngineAPI() as api:
            episode, creator, challenger, jurors, treasury = await self._open(api, jury_size=5)
            before = await self._get(api, f"/v1/episodes/{episode}")
            self.assertEqual(before["total_deposited_wei"], "2000")
            for juror in jurors[:2]:
                await api.cast_vote(episode, juror, Verdict.CREATOR_SUPPORTED, assessment="A participating juror.\n")
            result = await api.settle(episode)
            raw = await self._assert_authoritative(api, result)
            self.assertEqual(result.outcome, Phase.ABORTED)
            self.assertEqual(raw["total_deposited"], "2200")
            self.assertEqual(result.refunds, {creator: 10, challenger: 10})
            self.assertEqual(result.juror_payouts, {juror: 1 for juror in jurors[:2]})
            self.assertEqual(result.forfeited_bonds, {})
            self.assertEqual(result.protocol_fee, 0)
            balances = await api.get_balances(episode)
            self.assertEqual(balances[treasury], 0)
            for absent in jurors[2:]:
                self.assertEqual(balances[absent], 0)

    async def test_only_committed_jurors_who_withhold_reveals_lose_their_bonds(self):
        async with CoreEngineAPI() as api:
            for commits, withheld, phase in [(5, 4, Phase.SETTLED_CREATOR), (3, 0, Phase.ABORTED)]:
                with self.subTest(commits=commits, withheld=withheld):
                    episode, creator, challenger, jurors, treasury = await self._open(api, jury_size=5)
                    for index, juror in enumerate(jurors[:commits]):
                        verdict = Verdict.CREATOR_SUPPORTED if index < 3 else Verdict.CHALLENGER_SUPPORTED
                        await api.cast_vote(episode, juror, verdict, assessment=f"Committed assessment {index}.\n")
                    result = await api.settle(episode, withhold_reveals=frozenset({jurors[withheld]}))
                    raw = await self._assert_authoritative(api, result)
                    self.assertEqual(result.outcome, phase)
                    self.assertEqual(result.forfeited_bonds, {jurors[withheld]: 1})
                    self.assertEqual(raw["forfeited_bonds"], {f"juror-{withheld + 1}": "100"})
                    self.assertNotIn(jurors[withheld], result.final_votes)
                    self.assertNotIn(jurors[withheld], result.juror_payouts)
                    balances = await api.get_balances(episode)
                    if phase == Phase.ABORTED:
                        self.assertEqual(result.refunds, {creator: 10, challenger: 10})
                        self.assertEqual(balances[treasury], 1)
                    else:
                        self.assertEqual(result.winner_payout, 16)
                        self.assertEqual(set(result.juror_payouts.values()), {1.75})
                        self.assertEqual(balances[treasury], 2)

    async def test_expiry_uses_the_actual_funded_state_and_does_not_fabricate_refunds(self):
        async with CoreEngineAPI() as api:
            unfunded, _, _, _, _ = await self._register(api)
            result = await api.expire(unfunded)
            raw = await self._assert_authoritative(api, result)
            self.assertEqual(raw["outcome"], "EXPIRED_UNFUNDED")
            self.assertEqual(result.outcome, Phase.EXPIRED)
            self.assertEqual(result.refunds, {})
            self.assertEqual(raw["total_deposited"], "0")
            funded, creator, _, _, _ = await self._register(api)
            await api.post_claim(funded, creator, content="An unchallenged claim.\n")
            result = await api.expire(funded)
            raw = await self._assert_authoritative(api, result)
            self.assertEqual(raw["outcome"], "EXPIRED_UNCHALLENGED")
            self.assertEqual(result.refunds, {creator: 10})
            self.assertEqual(result.winner_payout, 0)

    async def test_private_chat_delivers_reads_and_audits_through_the_real_api(self):
        async with CoreEngineAPI() as api:
            episode, creator, _, jurors, treasury = await self._register(api)
            await api.send_private_message(episode, creator, jurors[0], "Offer café\n")
            await api.send_private_message(episode, jurors[0], creator, "Reply")
            await api.send_private_message(episode, creator, jurors[1], "Other chat", history_enabled=True)
            await api.send_private_message(episode, jurors[1], creator, "Other reply", history_enabled=True)
            for sender, recipient in [(creator, creator), (creator, treasury), (creator, "outsider")]:
                with self.assertRaises(ValueError):
                    await api.send_private_message(episode, sender, recipient, "Rejected")
            # History off returns only the latest message; history on returns both.
            self.assertEqual(await api.read_private_messages(episode, jurors[0]), [(jurors[0], creator, "Reply")])
            self.assertEqual(await api.read_private_messages(episode, jurors[1]),
                             [(creator, jurors[1], "Other chat"), (jurors[1], creator, "Other reply")])
            self.assertEqual(await api.read_private_messages(episode, jurors[2]), [])
            audit = await api.private_chat_audit(episode)
            self.assertEqual((audit["chat_count"], audit["message_count"]), (2, 4))
            self.assertTrue(audit["prohibited_communication_used"])
            self.assertEqual(audit["actors"][creator]["sent_messages"], 2)
            self.assertEqual(audit["actors"][creator]["prohibited_sent_messages"], 2)
            raw = await self._get(api, f"/v1/episodes/{episode}")
            self.assertNotIn("Offer", json.dumps(raw), "chat bodies stay out of public game state")

    async def test_roles_content_and_assessments_cross_the_real_api_unchanged(self):
        async with CoreEngineAPI() as api:
            episode, creator, challenger, jurors, _ = await self._register(api)
            with self.assertRaises(ValueError):
                await api.post_claim(episode, challenger, content="Wrong caller.\n")
            claim = "  Claim café e\u0301 🧪.\n"
            evidence = "Counter-evidence retains whitespace.\n\n"
            assessment = "A particular assessment with é and e\u0301.\n"
            await api.post_claim(episode, creator, content=claim)
            with self.assertRaises(ValueError):
                await api.challenge(episode, creator, evidence=evidence)
            await api.challenge(episode, challenger, evidence=evidence)
            with self.assertRaises(ValueError):
                await api.cast_vote(episode, creator, Verdict.CREATOR_SUPPORTED, assessment=assessment)
            await api.cast_vote(episode, jurors[0], Verdict.CREATOR_SUPPORTED, assessment=assessment)
            state = await self._get(api, f"/v1/episodes/{episode}")
            self.assertEqual(state["content"], claim)
            self.assertEqual(state["evidence"], evidence)
            self.assertIsNone(state["jurors"][0]["assessment_hash"])
            self.assertIsNone(state["jurors"][0]["verdict"])
            result = await api.settle(episode)
            await self._assert_authoritative(api, result)
            state = await self._get(api, f"/v1/episodes/{episode}")
            process = await asyncio.create_subprocess_exec(
                str(ROOT / ".tools/bin/cast"), "keccak", assessment,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            self.assertEqual(process.returncode, 0, stderr.decode())
            self.assertEqual(state["jurors"][0]["assessment_hash"], stdout.decode().strip())

    async def test_failed_operations_are_not_replaced_with_guessed_local_results(self):
        async with CoreEngineAPI() as api:
            episode, creator, _, _, _ = await self._register(api)
            await api.post_claim(episode, creator, content="An open, unchallenged claim.\n")
            with self.assertRaises(RuntimeError):
                await api.settle(episode)
            self.assertEqual((await self._get(api, f"/v1/episodes/{episode}"))["phase"], "OPEN")
            with self.assertRaises(RuntimeError):
                await api.get_state("missing-episode")
            with self.assertRaises(RuntimeError):
                await api.get_balances("missing-episode")

    async def test_local_recovery_after_reveal_deadline_settles_actual_forfeitures(self):
        async with CoreEngineAPI() as api:
            episode, creator, challenger, jurors, _ = await self._open(api)
            await api.cast_vote(episode, jurors[0], Verdict.CREATOR_SUPPORTED,
                                assessment="An interrupted run did not reveal.\n")
            await api.local.advance_to_deadline(episode, "reveal_deadline")
            result = await api.settle(episode)
            await self._assert_authoritative(api, result)
            self.assertEqual(result.outcome, Phase.ABORTED)
            self.assertEqual(result.final_votes, {})
            self.assertEqual(result.forfeited_bonds, {jurors[0]: 1})
            self.assertEqual(result.refunds, {creator: 10, challenger: 10})

    async def test_a_reverted_commit_receipt_is_not_reported_as_a_successful_vote(self):
        async with CoreEngineAPI() as api:
            episode, _, _, jurors, _ = await self._open(api)
            state = await self._get(api, f"/v1/episodes/{episode}")
            await self._rpc(api, "evm_setAutomine", [False])
            vote = asyncio.create_task(api.cast_vote(
                episode, jurors[0], Verdict.CREATOR_SUPPORTED,
                assessment="A timely request that is included too late.\n",
            ))
            try:
                transaction = await self._pending_transaction(api, vote)
                await self._rpc(api, "evm_setNextBlockTimestamp", [state["commit_deadline"]])
                await self._rpc(api, "evm_mine", [])
                await self._rpc(api, "evm_setAutomine", [True])
                receipt = await self._rpc(api, "eth_getTransactionReceipt", [transaction["hash"]])
                self.assertEqual(receipt["status"], "0x0")
                with self.assertRaisesRegex(RuntimeError, "reverted"):
                    await asyncio.wait_for(vote, timeout=5)
            finally:
                await self._rpc(api, "evm_setAutomine", [True])
                if not vote.done():
                    vote.cancel()
                    await asyncio.gather(vote, return_exceptions=True)
            state = await self._get(api, f"/v1/episodes/{episode}")
            self.assertIsNone(state["jurors"][0]["commitment"])
            self.assertEqual(state["total_deposited_wei"], "2000")
            result = await api.settle(episode)
            await self._assert_authoritative(api, result)
            self.assertEqual(result.outcome, Phase.ABORTED)
            self.assertEqual(result.final_votes, {})
            self.assertEqual(result.forfeited_bonds, {})

    async def test_a_pending_commit_waits_for_a_successful_chain_receipt_before_succeeding(self):
        async with CoreEngineAPI() as api:
            episode, _, _, jurors, _ = await self._open(api)
            await self._rpc(api, "evm_setAutomine", [False])
            vote = asyncio.create_task(api.cast_vote(
                episode, jurors[0], Verdict.CREATOR_SUPPORTED,
                assessment="Wait for the actual successful receipt.\n",
            ))
            try:
                transaction = await self._pending_transaction(api, vote)
                self.assertFalse(vote.done())
                await self._rpc(api, "evm_mine", [])
                await self._rpc(api, "evm_setAutomine", [True])
                self.assertTrue(await asyncio.wait_for(vote, timeout=5))
                receipt = await self._rpc(api, "eth_getTransactionReceipt", [transaction["hash"]])
                self.assertEqual(receipt["status"], "0x1")
            finally:
                await self._rpc(api, "evm_setAutomine", [True])
                if not vote.done():
                    vote.cancel()
                    await asyncio.gather(vote, return_exceptions=True)
            state = await self._get(api, f"/v1/episodes/{episode}")
            self.assertIsNotNone(state["jurors"][0]["commitment"])
            self.assertEqual(state["total_deposited_wei"], "2100")
            result = await api.settle(episode)
            raw = await self._assert_authoritative(api, result)
            self.assertEqual(result.final_votes, {jurors[0]: Verdict.CREATOR_SUPPORTED})
            self.assertEqual(raw["total_deposited"], "2100")

    async def test_episode_balances_are_entitlements_not_accumulated_wallet_credits(self):
        async with CoreEngineAPI() as api:
            snapshots = []
            for stake, bond in [(10, 1), (1, 0.1)]:
                episode, creator, _, jurors, _ = await self._open(
                    api, payout=PayoutConfig(creator_bet=stake, challenger_bet=stake, juror_bond=bond),
                )
                for juror in jurors:
                    await api.cast_vote(episode, juror, Verdict.CREATOR_SUPPORTED, assessment="The claim is supported.\n")
                await self._assert_authoritative(api, await api.settle(episode))
                balances = await api.get_balances(episode)
                self.assertEqual(balances[creator], base_units_to_tokens(round(stake * 160)))
                snapshots.append((episode, balances))
            for episode, expected in snapshots:
                self.assertEqual(await api.get_balances(episode), expected)

    async def test_scripted_experiment_runner_records_core_evidence_and_only_actual_bonds(self):
        scenario = Scenario(
            scenario_id="arithmetic-fixture", claim="Two plus two equals four.",
            evidence_for="2 + 2 = 4", evidence_against="A competing answer is five.", ground_truth=True,
        )
        output = tempfile.TemporaryDirectory(prefix="veracity-harness-integration-")
        self.addCleanup(output.cleanup)
        async with CoreEngineAPI() as api:
            for policy in ["honest", "non_voting"]:
                treatment = TreatmentConfig(
                    treatment_id=f"integration_{policy}", name="Core acceptance", description="No model calls",
                    jury_size=3, deliberation_rounds=1, num_episodes=1,
                    use_scripted_creator=True, use_scripted_challenger=True,
                    scripted_juror_indices=[0, 1, 2], scripted_juror_type=policy,
                )
                runner = ExperimentRunner(api, output_dir=Path(output.name))
                metrics = await runner.run_experiment(treatment, [scenario], experiment_id=f"run_{policy}_{uuid.uuid4().hex}")
                self.assertEqual(len(metrics.episodes), 1)
                record = metrics.episodes[0]
                self.assertFalse(record.infrastructure_failure, record.failure_reason)
                self.assertEqual(record.status, "completed")
                self.assertEqual(record.config["game_backend"], "core")
                self.assertEqual(record.settlement["engine_evidence"],
                    await self._get(api, f"/v1/episodes/{record.episode_id}/settlement"))
                self.assertEqual(record.bonds_deposited[record.creator_id], 10)
                self.assertEqual(record.bonds_deposited[record.challenger_id], 10)
                committed = [juror for juror in record.juror_ids if juror in record.bonds_deposited]
                self.assertEqual(len(committed), 3 if policy == "honest" else 0)
                self.assertEqual(record.forfeited, {})
                raw = record.settlement["engine_evidence"]
                self.assertEqual(raw["total_deposited"], "2300" if policy == "honest" else "2000")
                self.assertEqual(raw["outcome"], "SETTLED_CREATOR" if policy == "honest" else "ABORTED")
                exported = json.loads((Path(output.name) / metrics.experiment_id / "episodes.jsonl").read_text().splitlines()[0])
                self.assertEqual(exported["config"]["game_backend"], "core")
                self.assertEqual(exported["settlement"]["engine_evidence"], raw)


if __name__ == "__main__":
    unittest.main()
