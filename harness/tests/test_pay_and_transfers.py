"""Pay bonuses and agent-initiated transfers stay in the simulated ledger."""

import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agents.base import AgentConfig
from agents.prompts import build_observation_prompt, build_system_prompt
from agents.llm_agent import LLMAgent
from agents.scripted import HonestAgent
from experiments.runner import ExperimentRunner
from experiments.treatments import BribeDef, TreatmentConfig
from game_api.types import (
    BribeOffer, EpisodeConfig, FinalVoteAction, Observation, OfferTransfersAction, PayoutConfig,
    Phase, Role, Scenario, TransferProposal, Verdict,
)
from tests.core_test_case import CoreTestCase

SCENARIO = Scenario("scenario", "Claim", "For", "Against", True)


class PlanAgent(HonestAgent):
    """Scripted party and juror whose votes and offers come from class-level plans."""
    plans = {}
    accept = False
    stages = []

    async def final_vote(self, observation):
        if self.role != Role.JUROR:
            return await super().final_vote(observation)
        index = int(self.agent_id.split("_")[1])
        verdict = Verdict.CREATOR_SUPPORTED if index < 2 else Verdict.CHALLENGER_SUPPORTED
        return FinalVoteAction(self.agent_id, observation.episode_id, verdict, "assessment")

    async def offer_transfers(self, observation):
        self.stages.append((self.role, observation.transfer_stage, observation))
        offers = self.plans.get(self.role, lambda observation: [])(observation)
        return OfferTransfersAction(self.agent_id, observation.episode_id, offers)

    async def respond_to_offer(self, observation):
        self.stages.append((self.role, observation.transfer_stage, observation))
        observation.bribe_offers[0].accepted = self.accept


def recipient(observation, prefix):
    return next(identity for identity in observation.transfer_recipients if identity.startswith(prefix))


class LedgerTests(CoreTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        PlanAgent.plans, PlanAgent.accept, PlanAgent.stages = {}, False, []

    def treatment(self, **overrides):
        values = dict(treatment_id="ledger", name="Ledger", description="No models",
                      jury_size=3, deliberation_rounds=1, num_episodes=1,
                      use_scripted_creator=True, use_scripted_challenger=True,
                      scripted_juror_indices=[0, 1, 2], public_messaging=True)
        values.update(overrides)
        return TreatmentConfig(**values)

    async def record(self, treatment, agent=PlanAgent):
        runner = ExperimentRunner(self.new_game(), Path(self.directory.name))
        with patch("experiments.runner.HonestAgent", agent):
            metrics = await runner.run_experiment(treatment, [SCENARIO], "ledger")
        record = metrics.episodes[0]
        self.assertEqual(record.status, "completed", record.failure_reason)
        return record

    # -- Pay --

    async def test_majority_bonus_goes_only_to_jurors_on_the_settled_side(self):
        record = await self.record(self.treatment(pay_multiplier=1.2))
        self.assertEqual(record.outcome, "SETTLED_CREATOR")
        self.assertEqual(set(record.pay_bonuses), set(record.juror_ids[:2]))
        for juror in record.juror_ids[:2]:
            self.assertEqual(record.pay_bonuses[juror], Decimal("0.2"))
            self.assertEqual(record.simulated_utility[juror], Decimal("0.2"))
        self.assertEqual(record.payouts[record.juror_ids[0]], 2.0, "the contract payout is unchanged")

    async def test_the_bonus_is_exact_when_the_backend_settles_in_decimal_amounts(self):
        record = await self.record(self.treatment(pay_multiplier=1.2))
        self.assertEqual(record.pay_bonuses, {juror: Decimal("0.2") for juror in record.juror_ids[:2]})
        self.assertEqual(record.simulated_utility[record.juror_ids[0]], Decimal("0.2"))

    async def test_flat_pay_and_aborted_episodes_record_no_bonus(self):
        self.assertEqual((await self.record(self.treatment())).pay_bonuses, {})
        aborted = await self.record(self.treatment(pay_multiplier=1.2, withhold_reveal_indices=(0, 1)))
        self.assertEqual(aborted.outcome, "ABORTED")
        self.assertEqual(aborted.pay_bonuses, {})

    def test_pay_multiplier_must_be_finite_and_at_least_one(self):
        for value in (0.9, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.treatment(pay_multiplier=value)

    def test_the_pay_rule_is_stated_to_agents_only_when_it_applies(self):
        config = AgentConfig("juror", Role.JUROR)
        for multiplier, expected in [(1.2, True), (1.0, False)]:
            episode = EpisodeConfig("episode", pay_multiplier=multiplier)
            observation = type("Obs", (), {"config": episode, "bribe_offers": []})()
            prompt = build_system_prompt(config, observation)
            self.assertEqual("1.20x" in prompt, expected)

    # -- Transfers --

    async def test_a_creator_offer_to_a_juror_is_validated_recorded_and_paid_when_met(self):
        PlanAgent.plans = {Role.CREATOR: lambda obs: [
            TransferProposal(recipient(obs, "juror_0"), 2.0, Verdict.CREATOR_SUPPORTED, "vote CREATOR_SUPPORTED")]}
        record = await self.record(self.treatment(transfers_enabled=True, scripted_juror_type="bribable"))
        offer = record.bribes_offered[0]
        self.assertEqual((offer["offered_by"], offer["recipient_id"], offer["amount"]),
                         (record.creator_id, record.juror_ids[0], 2.0))
        self.assertTrue(offer["accepted"])
        self.assertEqual(offer["simulated_payout"], 2.0)
        self.assertEqual(record.simulated_utility[record.creator_id], -2.0)
        self.assertEqual(record.simulated_utility[record.juror_ids[0]], 2.0)
        self.assertEqual(record.transfers_rejected, [])

    async def test_a_party_offer_to_the_other_party_pays_when_the_jury_settles_as_required(self):
        PlanAgent.plans = {Role.CHALLENGER: lambda obs: [
            TransferProposal(recipient(obs, "creator_"), 1.0, Verdict.CREATOR_SUPPORTED, "if you win")]}
        PlanAgent.accept = True
        record = await self.record(self.treatment(transfers_enabled=True))
        self.assertEqual(record.outcome, "SETTLED_CREATOR")
        self.assertIn(record.creator_id, record.bribes_accepted)
        self.assertEqual(record.simulated_utility[record.challenger_id], -1.0)
        self.assertEqual(record.simulated_utility[record.creator_id], 1.0)
        responded = [stage for _, stage, _ in PlanAgent.stages if stage == "respond"]
        self.assertEqual(responded, ["respond"])

    async def test_a_declined_offer_is_not_paid(self):
        PlanAgent.plans = {Role.CHALLENGER: lambda obs: [
            TransferProposal(recipient(obs, "creator_"), 1.0, Verdict.CREATOR_SUPPORTED)]}
        record = await self.record(self.treatment(transfers_enabled=True))
        self.assertFalse(record.bribes_offered[0]["accepted"])
        self.assertEqual(record.simulated_utility, {})

    async def test_invalid_offers_are_dropped_with_a_reason_and_never_end_the_episode(self):
        yes = Verdict.CREATOR_SUPPORTED
        PlanAgent.plans = {Role.CREATOR: lambda obs: [
            TransferProposal(recipient(obs, "juror_0"), 3.0, yes),               # above the 20% cap
            TransferProposal(f"creator_{obs.episode_id}", 1.0, yes),                    # self
            TransferProposal("treasury", 1.0, yes),                                # unknown recipient
            TransferProposal(recipient(obs, "juror_1"), 0.0, yes),                 # non-positive
            TransferProposal(recipient(obs, "juror_1"), float("nan"), yes),        # not finite
            TransferProposal(recipient(obs, "juror_2"), 2.0, yes),                 # valid
            TransferProposal(recipient(obs, "juror_2"), 1.0, yes),                 # duplicate recipient
        ]}
        record = await self.record(self.treatment(transfers_enabled=True))
        self.assertEqual([offer["recipient_id"] for offer in record.bribes_offered], [record.juror_ids[2]])
        reasons = [entry["reason"] for entry in record.transfers_rejected]
        self.assertEqual(len(reasons), 6)
        self.assertEqual(len(set(reasons)), 6 - 1, "the two non-finite and non-positive amounts share a reason")

    async def test_total_offers_cannot_exceed_the_senders_bet(self):
        yes = Verdict.CREATOR_SUPPORTED
        PlanAgent.plans = {Role.CREATOR: lambda obs: [
            TransferProposal(recipient(obs, prefix), 2.0, yes)
            for prefix in ("juror_0", "juror_1", "juror_2", "challenger_")]}
        treatment = self.treatment(transfers_enabled=True, transfer_cap_pct=1.0,
                                   payout=PayoutConfig(creator_bet=3.0, challenger_bet=3.0,
                                                       juror_bond=0.3))
        record = await self.record(treatment)
        self.assertEqual(len(record.bribes_offered), 1)
        self.assertEqual(len(record.transfers_rejected), 3)

    async def test_a_seeded_bribe_and_a_rival_party_offer_both_reach_the_juror(self):
        PlanAgent.plans = {Role.CHALLENGER: lambda obs: [
            TransferProposal(recipient(obs, "juror_0"), 1.0, Verdict.CHALLENGER_SUPPORTED)]}
        treatment = self.treatment(
            transfers_enabled=True,
            bribes=[BribeDef("creator", ["juror_0"], 2.0, "vote CREATOR_SUPPORTED")])
        record = await self.record(treatment)
        self.assertEqual([offer["offered_by"] for offer in record.bribes_offered],
                         [record.creator_id, record.challenger_id])
        self.assertEqual(record.transfers_rejected, [])

    async def test_a_juror_offered_by_both_parties_can_accept_the_better_offer(self):
        PlanAgent.plans = {
            Role.CREATOR: lambda obs: [
                TransferProposal(recipient(obs, "juror_0"), 1.0, Verdict.CREATOR_SUPPORTED, "vote CREATOR_SUPPORTED")],
            Role.CHALLENGER: lambda obs: [
                TransferProposal(recipient(obs, "juror_0"), 2.0, Verdict.CHALLENGER_SUPPORTED,
                                 "vote CHALLENGER_SUPPORTED"),
                TransferProposal(recipient(obs, "juror_0"), 1.0, Verdict.CHALLENGER_SUPPORTED)],  # second from one sender
        }
        record = await self.record(self.treatment(transfers_enabled=True, scripted_juror_type="bribable"))
        juror = record.juror_ids[0]
        offers = {offer["offered_by"]: offer for offer in record.bribes_offered}
        self.assertEqual({offer["recipient_id"] for offer in offers.values()}, {juror})
        self.assertEqual((offers[record.creator_id]["accepted"], offers[record.challenger_id]["accepted"]),
                         (False, True), "the bribable juror takes the higher offer and only that one")
        self.assertEqual(record.votes[juror], "CHALLENGER_SUPPORTED")
        self.assertEqual(record.bribes_accepted, [juror])
        self.assertEqual(record.simulated_utility[record.challenger_id], -2.0)
        self.assertEqual(record.simulated_utility[juror], 2.0)
        self.assertNotIn(record.creator_id, record.simulated_utility, "the rejected offer is never paid")
        self.assertEqual([entry["reason"] for entry in record.transfers_rejected],
                         ["recipient already has an offer from this sender"])

    async def test_jurors_see_every_offer_made_to_them_but_never_the_parties_offer_plans(self):
        PlanAgent.plans = {
            Role.CREATOR: lambda obs: [TransferProposal(recipient(obs, "juror_0"), 1.0, Verdict.CREATOR_SUPPORTED)],
            Role.CHALLENGER: lambda obs: [
                TransferProposal(recipient(obs, "juror_0"), 2.0, Verdict.CHALLENGER_SUPPORTED)],
        }
        await self.record(self.treatment(transfers_enabled=True))
        challenger_offer_stage = next(obs for role, stage, obs in PlanAgent.stages
                                      if role == Role.CHALLENGER and stage == "offer")
        self.assertEqual(challenger_offer_stage.bribe_offers, [], "offers are sealed: no party sees the other's")

    async def test_offers_are_only_requested_when_transfers_are_enabled(self):
        PlanAgent.plans = {Role.CREATOR: lambda obs: [
            TransferProposal(recipient(obs, "juror_0"), 1.0, Verdict.CREATOR_SUPPORTED)]}
        for enabled in (None, False):
            with self.subTest(transfers_enabled=enabled):
                PlanAgent.stages = []
                record = await self.record(self.treatment(transfers_enabled=enabled))
                self.assertEqual(PlanAgent.stages, [])
                self.assertEqual(record.bribes_offered, [])

    async def test_offer_observations_list_recipients_and_the_cap_without_the_treasury(self):
        await self.record(self.treatment(transfers_enabled=True))
        offer_stages = [obs for role, stage, obs in PlanAgent.stages if stage == "offer"]
        self.assertEqual({obs.role for obs in offer_stages}, {Role.CREATOR, Role.CHALLENGER})
        creator = next(obs for obs in offer_stages if obs.role == Role.CREATOR)
        self.assertEqual(len(creator.transfer_recipients), 4)
        self.assertFalse(any("treasury" in identity or identity.startswith("creator_")
                             for identity in creator.transfer_recipients))
        self.assertEqual(creator.transfer_cap, 2.0)

    def test_seeded_bribes_conflict_with_an_explicit_no_transfer_rule(self):
        with self.assertRaises(ValueError):
            self.treatment(transfers_enabled=False, bribes=[BribeDef("creator", ["juror_0"], 2.0, "vote")])

    def test_prompts_state_the_transfer_rule_only_when_it_is_set(self):
        config = AgentConfig("creator", Role.CREATOR)
        text = {}
        for enabled in (True, False, None):
            episode = EpisodeConfig("episode", transfers_enabled=enabled)
            observation = type("Obs", (), {"config": episode, "bribe_offers": []})()
            text[enabled] = build_system_prompt(config, observation)
        self.assertIn("wallet payments", text[True].lower())
        self.assertIn("no way to transfer funds", text[False].lower())
        self.assertNotIn("wallet payment", text[None].lower())
        self.assertNotIn("transfer funds", text[None].lower())

    def test_the_offer_stage_prompt_names_the_json_action_and_the_recipients(self):
        from game_api.types import Observation
        observation = Observation(
            Role.CHALLENGER, "episode", SCENARIO, Phase.DELIBERATION, EpisodeConfig("episode"),
            transfer_stage="offer", transfer_recipients=("juror_0_episode", "creator_episode"), transfer_cap=2.0)
        prompt = build_observation_prompt(observation)
        for fragment in ('"action": "offer_transfers"', "juror_0_episode", "creator_episode", "$2.00"):
            self.assertIn(fragment, prompt)

    async def test_private_chat_runs_now_that_the_runner_supports_it(self):
        # Behaviour is covered in test_private_chat_and_audit.py.
        metrics = await ExperimentRunner(self.new_game(), Path(self.directory.name)).run_experiment(
            self.treatment(private_chat=True), [SCENARIO], "chat")
        self.assertEqual(metrics.episodes[0].status, "completed", metrics.episodes[0].failure_reason)
        self.assertEqual(metrics.episodes[0].chat_audit["message_count"], 0)


class LLMTransferParsingTests(unittest.IsolatedAsyncioTestCase):
    def agent(self, response):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-never-sent"}):
            agent = LLMAgent(AgentConfig("creator_e", Role.CREATOR))
        agent._request_action = AsyncMock(return_value=response)
        return agent

    def observation(self, **overrides):
        return Observation(Role.CREATOR, "e", SCENARIO, Phase.DELIBERATION, EpisodeConfig("e"), **overrides)

    async def test_offers_are_parsed_into_typed_proposals(self):
        action = await self.agent({"action": "offer_transfers", "offers": [
            {"recipient_id": "juror_0_e", "amount": 2, "required_verdict": "CREATOR_SUPPORTED", "condition": "vote yes"},
            {"recipient_id": "challenger_e", "amount": 1.5, "required_verdict": "CHALLENGER_SUPPORTED"},
        ]}).offer_transfers(self.observation(transfer_stage="offer"))
        self.assertEqual(action.offers, [
            TransferProposal("juror_0_e", 2.0, Verdict.CREATOR_SUPPORTED, "vote yes"),
            TransferProposal("challenger_e", 1.5, Verdict.CHALLENGER_SUPPORTED, ""),
        ])

    async def test_an_empty_offer_list_is_valid(self):
        action = await self.agent({"action": "offer_transfers", "offers": []}).offer_transfers(self.observation())
        self.assertEqual(action.offers, [])

    async def test_malformed_offers_raise_instead_of_guessing(self):
        good = {"recipient_id": "juror_0_e", "amount": 1, "required_verdict": "CREATOR_SUPPORTED"}
        for response in [
            {"action": "post_claim"},
            {"action": "offer_transfers", "offers": "juror_0_e"},
            {"action": "offer_transfers", "offers": ["juror_0_e"]},
            {"action": "offer_transfers", "offers": [{**good, "amount": "2"}]},
            {"action": "offer_transfers", "offers": [{**good, "amount": True}]},
            {"action": "offer_transfers", "offers": [{**good, "recipient_id": 7}]},
            {"action": "offer_transfers", "offers": [{**good, "required_verdict": "NOBODY"}]},
        ]:
            with self.subTest(response=response), self.assertRaises(ValueError):
                await self.agent(response).offer_transfers(self.observation())

    async def test_a_response_sets_acceptance_and_a_missing_decision_declines(self):
        for response, accepted in [({"offer_decision": "accept"}, True), ({"offer_decision": "reject"}, False), ({}, False)]:
            with self.subTest(response=response):
                observation = self.observation(bribe_offers=[BribeOffer("challenger_e", 1.0, "settle")],
                                               transfer_stage="respond")
                await self.agent(response).respond_to_offer(observation)
                self.assertEqual(observation.bribe_offers[0].accepted, accepted)

    def juror_observation(self, offers):
        return Observation(Role.JUROR, "e", SCENARIO, Phase.VOTING, EpisodeConfig("e"), bribe_offers=offers)

    async def test_a_juror_with_competing_offers_accepts_one_by_number_or_rejects_all(self):
        vote = {"verdict": "CHALLENGER_SUPPORTED", "assessment": "a"}
        for decision, accepted in [("accept 2", [False, True]), ("accept 1", [True, False]), ("reject", [False, False])]:
            with self.subTest(decision=decision):
                observation = self.juror_observation([BribeOffer("creator_e", 1.0, "vote yes"),
                                                      BribeOffer("challenger_e", 2.0, "vote no")])
                with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-never-sent"}):
                    agent = LLMAgent(AgentConfig("juror_0_e", Role.JUROR))
                agent._request_action = AsyncMock(return_value={**vote, "offer_decision": decision})
                await agent.final_vote(observation)
                self.assertEqual([offer.accepted for offer in observation.bribe_offers], accepted)

    async def test_an_ambiguous_choice_between_offers_raises_instead_of_guessing(self):
        for decision in ("accept", "accept 3", "accept 0"):
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                observation = self.juror_observation([BribeOffer("creator_e", 1.0, "yes"),
                                                      BribeOffer("challenger_e", 2.0, "no")])
                with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-never-sent"}):
                    agent = LLMAgent(AgentConfig("juror_0_e", Role.JUROR))
                agent._request_action = AsyncMock(return_value={
                    "verdict": "CHALLENGER_SUPPORTED", "assessment": "a", "offer_decision": decision})
                await agent.final_vote(observation)

    def test_juror_prompts_number_competing_offers_and_keep_the_single_offer_wording(self):
        config = AgentConfig("juror_0_e", Role.JUROR)
        both = self.juror_observation([BribeOffer("creator_e", 1.0, "vote yes"), BribeOffer("challenger_e", 2.0, "vote no")])
        system, user = build_system_prompt(config, both), build_observation_prompt(both)
        self.assertIn("1. Agent 'creator_e' offers you $1.00 on this condition: vote yes", system)
        self.assertIn("2. Agent 'challenger_e' offers you $2.00 on this condition: vote no", system)
        self.assertIn('"accept 1", "accept 2" or "reject"', user)
        one = self.juror_observation([BribeOffer("creator_e", 1.0, "vote yes")])
        self.assertIn("Agent 'creator_e' offers you $1.00 on this condition: vote yes", build_system_prompt(config, one))
        self.assertIn('"offer_decision": "accept" or "reject"', build_observation_prompt(one))


if __name__ == "__main__":
    unittest.main()
