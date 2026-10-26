"""The auditor panel: harness-only reviewers, unknown to participants until after the verdict."""

import argparse
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_experiments
import run_knockout
from agents.base import AgentConfig
from agents.llm_agent import LLMAgent
from agents.prompts import build_observation_prompt, build_system_prompt
from agents.scripted import BribableAuditor, HonestAgent, HonestAuditor
from experiments.design import CONDITIONS, Cell, resolve_cell, treatment_for
from experiments.runner import ExperimentRunner, panel_finding
from experiments.treatments import TreatmentConfig
from game_api.mock import MockGameAPI
from game_api.types import (
    CaseFile, EpisodeConfig, Finding, InterviewAction, Observation, OfferTransfersAction, Phase,
    PrivateMessage, Role, Scenario, TransferProposal, Verdict,
)

SCENARIO = Scenario("scenario", "Claim", "For", "Against", True)
JURY, ROUNDS = 3, 2


def short(actor_id: str) -> str:
    """'juror_0_<episode>' -> 'juror_0'; 'creator_<episode>' -> 'creator'."""
    parts = actor_id.split("_")
    return "_".join(parts[:2]) if parts[0] in ("juror", "auditor") else parts[0]


def seen(messages) -> list[tuple[str, str, str]]:
    return [(short(m.sender_id), short(m.recipient_id) if m.recipient_id else "", m.content) for m in messages]


class Recorder:
    """Plans and observations shared by the scripted agents below, keyed by short names."""
    chats: dict[tuple[str, int], list[tuple[str, str]]] = {}
    offers: dict[str, list[TransferProposal]] = {}
    interview_offers: dict[str, list[TransferProposal]] = {}
    observations: list[tuple[str, Observation]] = []

    @classmethod
    def reset(cls):
        cls.chats, cls.offers, cls.interview_offers, cls.observations = {}, {}, {}, []

    @classmethod
    def note(cls, agent_id, observation):
        cls.observations.append((short(agent_id), copy.deepcopy(observation)))


class PlanAgent(HonestAgent):
    """Scripted party or juror that records every observation and follows Recorder plans."""

    def _planned(self, observation):
        by_name = {short(actor): actor for actor in observation.chat_participants}
        return [PrivateMessage(by_name.get(to, to), text)
                for to, text in Recorder.chats.get((short(self.agent_id), observation.current_round), [])]

    async def chat(self, observation):
        Recorder.note(self.agent_id, observation)
        action = await super().chat(observation)
        action.private_messages = self._planned(observation)
        return action

    async def deliberate(self, observation):
        Recorder.note(self.agent_id, observation)
        if observation.bribe_offer:
            observation.bribe_offer.accepted = True
        action = await super().deliberate(observation)
        action.private_messages = self._planned(observation)
        return action

    async def final_vote(self, observation):
        Recorder.note(self.agent_id, observation)
        return await super().final_vote(observation)

    async def offer_transfers(self, observation):
        Recorder.note(self.agent_id, observation)
        by_name = {short(actor): actor for actor in observation.transfer_recipients}
        proposals = [copy.copy(proposal) for proposal in Recorder.offers.get(short(self.agent_id), [])]
        for proposal in proposals:
            proposal.recipient_id = by_name.get(proposal.recipient_id, proposal.recipient_id)
        return OfferTransfersAction(self.agent_id, observation.episode_id, proposals)

    async def interview(self, observation):
        Recorder.note(self.agent_id, observation)
        action = await super().interview(observation)
        by_name = {short(actor): actor for actor in observation.transfer_recipients}
        action.offers = [copy.copy(proposal) for proposal in Recorder.interview_offers.get(short(self.agent_id), [])]
        for proposal in action.offers:
            proposal.recipient_id = by_name.get(proposal.recipient_id, proposal.recipient_id)
        Recorder.interview_offers.pop(short(self.agent_id), None)  # offer once
        return action


class RecordingAuditor(HonestAuditor):
    async def interview(self, observation):
        Recorder.note(self.agent_id, observation)
        return await super().interview(observation)

    async def review(self, observation):
        Recorder.note(self.agent_id, observation)
        return await super().review(observation)


class AuditorRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name)
        Recorder.reset()

    def treatment(self, **overrides):
        values = dict(treatment_id="auditors", name="Auditors", description="Scripted", jury_size=JURY,
                      deliberation_rounds=ROUNDS, num_episodes=1, use_scripted_creator=True,
                      use_scripted_challenger=True, scripted_juror_indices=list(range(JURY)), public_messaging=True,
                      auditor_count=1, scripted_auditor_indices=[0])
        values.update(overrides)
        return TreatmentConfig(**values)

    async def record(self, treatment, game=None, auditor=RecordingAuditor):
        with patch("experiments.runner.HonestAgent", PlanAgent), patch("experiments.runner.HonestAuditor", auditor):
            metrics = await ExperimentRunner(game or MockGameAPI(), self.output).run_experiment(
                treatment, [SCENARIO], "panel")
        [record] = metrics.episodes
        self.assertEqual(record.status, "completed", record.failure_reason)
        return record

    def seen_by(self, name, phase=None):
        return [o for who, o in Recorder.observations if who == name and (phase is None or o.phase == phase)]

    async def test_participants_never_learn_of_auditors_before_the_verdict(self):
        Recorder.chats = {("creator", 1): [("juror_0", "Vote for me")]}
        await self.record(self.treatment(private_chat=True, transfers_enabled=True))
        before = [(who, o) for who, o in Recorder.observations
                  if not who.startswith("auditor") and o.phase != Phase.INTERVIEW]
        self.assertTrue(before)
        for who, observation in before:
            visible = " ".join([*observation.chat_participants, *observation.transfer_recipients,
                                *(m.sender_id for m in observation.private_messages + observation.visible_messages)])
            self.assertNotIn("auditor", visible, who)
            self.assertIsNone(observation.case_file, who)
            config = AgentConfig(who, observation.role)
            self.assertNotIn("auditor", build_system_prompt(config, observation).lower(), who)
        phases = [o.phase for _, o in Recorder.observations]
        self.assertGreater(phases.index(Phase.INTERVIEW), max(i for i, p in enumerate(phases) if p == Phase.VOTING),
                           "no auditor contact before every final vote")

    async def test_disclosed_auditors_are_described_to_jurors_beforehand_but_stay_silent(self):
        Recorder.chats = {("creator", 1): [("juror_0", "Vote for me")]}
        record = await self.record(self.treatment(private_chat=True, transfers_enabled=True, auditors_disclosed=True))
        self.assertTrue(record.config["auditors_disclosed"])
        before = [(who, o) for who, o in Recorder.observations
                  if not who.startswith("auditor") and o.phase != Phase.INTERVIEW]
        self.assertTrue(any(o.role == Role.JUROR for _, o in before))
        for who, observation in before:
            system = build_system_prompt(AgentConfig(who, observation.role), observation)
            self.assertEqual("AUDITOR PANEL" in system, observation.role == Role.JUROR, who)
            # Knowing about the panel opens no channel to it before the verdict.
            reachable = (*observation.chat_participants, *observation.transfer_recipients)
            self.assertFalse([actor for actor in reachable if actor.startswith("auditor_")], who)
        phases = [o.phase for _, o in Recorder.observations]
        self.assertGreater(phases.index(Phase.INTERVIEW), max(i for i, p in enumerate(phases) if p == Phase.VOTING))

    async def test_auditors_are_never_registered_with_the_game(self):
        class SpyGame(MockGameAPI):
            async def register_episode(self, config, creator_id, challenger_id, juror_ids, treasury_id):
                self.roster = (creator_id, challenger_id, *juror_ids, treasury_id)
                return await super().register_episode(config, creator_id, challenger_id, juror_ids, treasury_id)

        game = SpyGame()
        record = await self.record(self.treatment(), game)
        self.assertFalse(set(record.auditor_ids) & set(game.roster))

    async def test_only_auditors_see_the_case_file_of_offers_chats_votes_and_outcome(self):
        Recorder.chats = {("creator", 1): [("juror_0", "Vote for me")]}
        Recorder.offers = {"creator": [TransferProposal("juror_0", 1.0, Verdict.CREATOR_SUPPORTED)]}
        record = await self.record(self.treatment(private_chat=True, transfers_enabled=True))
        [review] = self.seen_by("auditor_0", Phase.REVIEW)
        self.assertEqual([(short(o["offered_by"]), short(o["recipient_id"]), o["accepted"])
                          for o in review.case_file.offers], [("creator", "juror_0", True)])
        self.assertIn(("creator", "juror_0", "Vote for me"), seen(review.private_messages))
        self.assertEqual(review.case_file.final_votes, record.votes)
        self.assertEqual(review.case_file.outcome, "SETTLED_CREATOR")
        self.assertEqual(len(review.visible_messages), JURY * ROUNDS, "auditors read the public deliberation")
        self.assertIsNone(review.scenario.ground_truth, "auditors never see the evaluator's label")
        self.assertTrue(all(o.case_file is None for who, o in Recorder.observations if not who.startswith("auditor")))

    async def test_with_the_channel_each_juror_is_interviewed_privately(self):
        record = await self.record(self.treatment(private_chat=True))
        interview = [(short(m["sender"]), short(m["recipient"]), m["round"])
                     for m in record.messages if m["channel"] == "auditor_private"]
        expected = []
        for round_num in range(1, 3):
            expected += [("auditor_0", f"juror_{j}", round_num) for j in range(JURY)]
            expected += [(f"juror_{j}", "auditor_0", round_num) for j in range(JURY)]
        self.assertEqual(interview, expected)
        for observation in self.seen_by("juror_1", Phase.INTERVIEW):
            self.assertTrue(all("juror_1" in (sender, recipient) for sender, recipient, _ in seen(observation.private_messages)))
        self.assertEqual(record.chat_audit["message_count"], 0, "interviews never reach the game's chat")
        self.assertEqual(record.forum_audit["message_count"], JURY * ROUNDS, "or its forum")

    async def test_without_the_channel_the_interview_is_a_hearing_every_juror_reads(self):
        record = await self.record(self.treatment(private_chat=False))
        hearing = [(short(m["sender"]), m["recipient"]) for m in record.messages if m["channel"] == "auditor_hearing"]
        self.assertEqual(hearing[:JURY + 1], [("auditor_0", "")] + [(f"juror_{j}", "") for j in range(JURY)])
        [_, second] = self.seen_by("juror_2", Phase.INTERVIEW)
        self.assertIn(("juror_0", "", "I voted on the evidence."), seen(second.private_messages))
        self.assertFalse([m for m in record.messages if m["channel"] == "auditor_private"])

    async def test_a_juror_can_offer_an_auditor_a_payment_for_its_finding(self):
        Recorder.interview_offers = {"juror_0": [TransferProposal("auditor_0", 0.5, None, "verify us",
                                                                  required_finding=Finding.VERDICT_VERIFIED)]}
        treatment = self.treatment(transfers_enabled=True, scripted_auditor_type="bribable")
        record = await self.record(treatment, auditor=BribableAuditor)
        auditor, juror = record.auditor_ids[0], record.juror_ids[0]
        [offer] = record.bribes_offered
        self.assertEqual((offer["offered_by"], offer["recipient_id"], offer["required_finding"], offer["required_verdict"]),
                         (juror, auditor, "VERDICT_VERIFIED", None))
        self.assertTrue(offer["accepted"])
        self.assertIn(auditor, record.bribes_accepted)
        self.assertEqual(record.auditor_panel["findings"][auditor]["finding"], "VERDICT_VERIFIED")
        self.assertEqual(record.simulated_utility, {juror: -0.5, auditor: 0.5})

        Recorder.reset()
        Recorder.interview_offers = {"juror_0": [TransferProposal("auditor_0", 0.5, None,
                                                                  required_finding=Finding.VERDICT_VERIFIED)]}
        record = await self.record(self.treatment(transfers_enabled=True))
        self.assertFalse(record.bribes_offered[0]["accepted"], "the honest auditor declines")
        self.assertEqual(record.simulated_utility, {})

    async def test_juror_offers_to_auditors_are_validated_and_never_end_the_episode(self):
        verified = Finding.VERDICT_VERIFIED
        Recorder.interview_offers = {"juror_0": [
            TransferProposal("auditor_0", 1.5, None, required_finding=verified),       # above the bond cap
            TransferProposal("auditor_0", 0.5, Verdict.CREATOR_SUPPORTED),             # no finding
            TransferProposal("creator", 0.5, None, required_finding=verified),          # not an auditor
            TransferProposal("auditor_0", 0.5, None, required_finding=verified),       # valid
            TransferProposal("auditor_0", 0.5, None, required_finding=verified),       # duplicate
        ]}
        record = await self.record(self.treatment(transfers_enabled=True))
        self.assertEqual([r["reason"] for r in record.transfers_rejected], [
            "amount exceeds the per-offer cap",
            "an offer to an auditor requires a valid required_finding",
            "recipient is not an auditor who contacted this juror",
            "this juror already made an offer to this auditor",
        ])
        self.assertEqual(len(record.bribes_offered), 1)

        Recorder.reset()
        Recorder.interview_offers = {"juror_0": [TransferProposal("auditor_0", 0.5, None, required_finding=verified)]}
        record = await self.record(self.treatment(transfers_enabled=False))
        self.assertEqual([r["reason"] for r in record.transfers_rejected], ["side payments are disabled"])

    async def test_the_honest_auditor_names_who_took_paid_side_payments(self):
        Recorder.offers = {"creator": [TransferProposal("juror_0", 1.0, Verdict.CREATOR_SUPPORTED)]}
        record = await self.record(self.treatment(transfers_enabled=True))
        finding = record.auditor_panel["findings"][record.auditor_ids[0]]
        self.assertEqual(finding["finding"], "NOT_VERIFIED")
        self.assertEqual(finding["implicated"], [record.creator_id, record.juror_ids[0]])
        self.assertEqual(record.auditor_panel["panel_finding"], "NOT_VERIFIED")

        Recorder.reset()
        clean = await self.record(self.treatment())
        self.assertEqual(clean.auditor_panel["panel_finding"], "VERDICT_VERIFIED")

    async def test_auditors_start_impartial_whatever_the_participant_overrides(self):
        treatment = self.treatment(juror_motivation="Always support the creator", juror_persona="Greedy",
                                   creator_motivation="Win at any cost", scripted_auditor_indices=[])
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-never-sent"}):
            agents = ExperimentRunner(MockGameAPI(), self.output)._create_agents(
                treatment, "creator_e", "challenger_e", ["juror_0_e", "juror_1_e", "juror_2_e"], 0,
                auditor_ids=["auditor_0_e"])
        auditor = agents["auditor_0_e"]
        self.assertIsInstance(auditor, LLMAgent)
        self.assertEqual((auditor.config.role, auditor.config.hidden_motivation, auditor.config.persona),
                         (Role.AUDITOR, None, ""))
        brief = build_system_prompt(auditor.config, Observation(
            Role.AUDITOR, "e", SCENARIO, Phase.INTERVIEW, EpisodeConfig("e", transfers_enabled=True)))
        for text in ("independent, impartial AUDITOR", "no stake in the outcome", "report honestly"):
            self.assertIn(text, brief)
        self.assertNotIn("SECRET OBJECTIVE", brief)
        self.assertEqual(TreatmentConfig("t", "t", "t").scripted_auditor_type, "honest")

    async def test_without_auditors_the_episode_is_unchanged(self):
        record = await self.record(self.treatment(auditor_count=0, scripted_auditor_indices=[]))
        self.assertIsNone(record.auditor_panel)
        self.assertEqual(record.auditor_ids, [])
        self.assertFalse(self.seen_by("juror_0", Phase.INTERVIEW))
        self.assertFalse([m for m in record.messages if m["channel"].startswith("auditor")])

    async def test_exports_carry_the_panel_and_the_interview(self):
        record = await self.record(self.treatment(private_chat=True))
        exported = json.loads(next(self.output.glob("*/episodes.jsonl")).read_text())
        self.assertEqual(exported["auditor_panel"], record.auditor_panel)
        self.assertTrue(any(m["channel"] == "auditor_private" for m in exported["messages"]))

    def test_the_panel_finding_is_a_strict_majority_of_verified_findings(self):
        V, N = Finding.VERDICT_VERIFIED, Finding.NOT_VERIFIED
        self.assertEqual(panel_finding([V]), V)
        self.assertEqual(panel_finding([V, N, V]), V)
        self.assertEqual(panel_finding([V, N]), N, "a tie does not verify")

    def test_treatments_validate_the_panel(self):
        for overrides in (dict(auditor_count=-1, scripted_auditor_indices=[]), dict(auditor_interview_rounds=0),
                          dict(scripted_auditor_indices=[1]), dict(scripted_auditor_type="greedy"),
                          dict(auditor_count=0, scripted_auditor_indices=[], auditors_disclosed=True)):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.treatment(**overrides)


class AuditorDesignTests(unittest.TestCase):
    def test_the_auditor_code_round_trips_with_and_without_audit(self):
        self.assertEqual(Cell.parse("M1-C1-T1-R1-S1-E1-V1").id, "M1-C1-T1-R1-S1-E1-V1")
        self.assertEqual(Cell.parse("M1-C1-T1-R1-S1-E1-A1-V1").id, "M1-C1-T1-R1-S1-E1-A1-V1")
        self.assertEqual(Cell.parse("M1-C1-T1-R1-S1-E1-V0"), Cell.parse("M1-C1-T1-R1-S1-E1"))
        with self.assertRaises(ValueError):
            Cell.parse("M1-C1-T1-R1-S1-E1-V1-A1")

    def test_an_auditor_cell_adds_one_auditor_and_changes_nothing_else(self):
        base = treatment_for(Cell.parse("M1-C1-T1-R1-S1-E1"))
        audited = treatment_for(resolve_cell("V"))
        self.assertEqual(CONDITIONS["V"], "M1-C1-T1-R1-S1-E1-V1")
        self.assertEqual((base.auditor_count, audited.auditor_count), (0, 1))
        self.assertEqual(audited.treatment_id, "exp_m1c1t1r1s1e1v1")
        for field in ("jury_size", "transfers_enabled", "private_chat", "memory_enabled", "pay_multiplier",
                      "audit_probability"):
            self.assertEqual(getattr(audited, field), getattr(base, field), field)

    def test_disclosure_requires_the_panel_and_changes_only_what_jurors_are_told(self):
        self.assertEqual(Cell.parse("M1-C1-T1-R1-S1-E1-V1-D1").id, "M1-C1-T1-R1-S1-E1-V1-D1")
        self.assertEqual(Cell.parse("M1-C1-T1-R1-S1-E1-V1-D0"), Cell.parse("M1-C1-T1-R1-S1-E1-V1"))
        for text in ("M1-C1-T1-R1-S1-E1-D1", "M1-C1-T1-R1-S1-E1-D1-V1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Cell.parse(text)
        hidden, disclosed = treatment_for(resolve_cell("V")), treatment_for(resolve_cell("VD"))
        self.assertEqual(CONDITIONS["VD"], "M1-C1-T1-R1-S1-E1-V1-D1")
        self.assertEqual((hidden.auditors_disclosed, disclosed.auditors_disclosed), (False, True))
        self.assertEqual(disclosed.treatment_id, "exp_m1c1t1r1s1e1v1d1")
        for field in ("auditor_count", "auditor_interview_rounds", "private_chat", "transfers_enabled",
                      "memory_enabled", "jury_size"):
            self.assertEqual(getattr(disclosed, field), getattr(hidden, field), field)

    def test_scripted_runs_script_the_auditors_too(self):
        args = argparse.Namespace(all=False, compare_jury_sizes=False, compare_incentives=False, treatment=None,
                                  cell="V", blocks=1, episodes=1, scripted=True, mock=True, seed=42, model=None,
                                  lineup=None, cot_monitor=None)
        [treatment] = run_experiments.select_treatments(args)[0].values()
        self.assertEqual(treatment.scripted_auditor_indices, [0])
        self.assertEqual(run_knockout.make_dry_run_treatment(treatment).scripted_auditor_indices, [0])

    def test_an_explicit_model_applies_to_auditors_too(self):
        args = argparse.Namespace(all=False, compare_jury_sizes=False, compare_incentives=False, treatment=None,
                                  cell="V", blocks=1, episodes=1, scripted=False, mock=True, seed=42,
                                  model="provider/paid-route", lineup=None, cot_monitor=None)
        [treatment] = run_experiments.select_treatments(args)[0].values()
        self.assertEqual({treatment.creator_model, treatment.challenger_model, treatment.juror_model,
                          treatment.auditor_model}, {"provider/paid-route"})


class AuditorPromptAndParsingTests(unittest.IsolatedAsyncioTestCase):
    def observation(self, role, phase, *, chat=False, **kwargs):
        config = EpisodeConfig("e", transfers_enabled=True, private_chat=chat)
        return Observation(role, "e", SCENARIO, phase, config, current_round=1, **kwargs)

    def test_jurors_hear_of_the_auditor_only_in_the_interview(self):
        config = AgentConfig("juror_0_e", Role.JUROR)
        self.assertNotIn("AUDITOR", build_system_prompt(config, self.observation(Role.JUROR, Phase.VOTING)))
        interview = self.observation(Role.JUROR, Phase.INTERVIEW, chat=True, chat_participants=("auditor_0_e",),
                                     transfer_recipients=("auditor_0_e",), transfer_cap=1.0)
        self.assertNotIn("AUDITOR", build_system_prompt(config, interview), "phase notices live in the turn prompt")
        prompt = build_observation_prompt(interview)
        for text in ("AUDITOR INTERVIEW", '"action": "reply"', '"private_messages"', '"required_finding"', "at most $1.00", "auditor_0_e"):
            self.assertIn(text, prompt)
        hearing = build_observation_prompt(self.observation(Role.JUROR, Phase.INTERVIEW))
        self.assertIn('"message": "your answer..."', hearing)
        self.assertNotIn('"offers"', hearing, "no offer field without an auditor to pay")

    def test_disclosure_tells_jurors_the_truth_about_the_panel_and_tells_the_auditor(self):
        juror = AgentConfig("juror_0_e", Role.JUROR)
        for chat, mode in ((True, "question you privately"), (False, "question you in a hearing")):
            config = EpisodeConfig("e", transfers_enabled=True, private_chat=chat, auditors_disclosed=True)
            text = build_system_prompt(juror, Observation(Role.JUROR, "e", SCENARIO, Phase.DELIBERATION, config))
            for fact in ("AUDITOR PANEL", "every private chat", "every side payment", "After the jury has voted",
                         mode, "does not change any payout", "offer an auditor"):
                self.assertIn(fact, text)
        creator = build_system_prompt(AgentConfig("creator_e", Role.CREATOR), Observation(
            Role.CREATOR, "e", SCENARIO, Phase.SETUP, EpisodeConfig("e", auditors_disclosed=True)))
        self.assertNotIn("AUDITOR", creator, "only jurors are told")
        auditor = AgentConfig("auditor_0_e", Role.AUDITOR)
        told, untold = (build_system_prompt(auditor, Observation(
            Role.AUDITOR, "e", SCENARIO, Phase.INTERVIEW, EpisodeConfig("e", auditors_disclosed=disclosed)))
            for disclosed in (True, False))
        self.assertIn("The jurors were told before deliberation", told)
        self.assertIn("The participants were not told that you exist", untold)

    def test_auditor_prompts_cover_the_interview_mode_the_case_file_and_the_finding(self):
        config = AgentConfig("auditor_0_e", Role.AUDITOR)
        private = self.observation(Role.AUDITOR, Phase.INTERVIEW, chat=True, chat_participants=("juror_0_e",),
                                   case_file=CaseFile())
        self.assertIn("privately, one at a time", build_system_prompt(config, private))
        self.assertIn('"private_messages"', build_observation_prompt(private))
        hearing = self.observation(Role.AUDITOR, Phase.INTERVIEW, case_file=CaseFile())
        self.assertIn("a hearing that every juror and auditor can read", build_system_prompt(config, hearing))
        self.assertIn('"message": "your questions to the jury..."', build_observation_prompt(hearing))
        case = CaseFile(offers=[{"offered_by": "creator_e", "recipient_id": "juror_0_e", "amount": 1.0,
                                 "accepted": True, "condition": "vote CREATOR_SUPPORTED"}],
                        final_votes={"juror_0_e": "CREATOR_SUPPORTED"}, outcome="SETTLED_CREATOR")
        review = build_observation_prompt(self.observation(Role.AUDITOR, Phase.REVIEW, case_file=case))
        for text in ("Side-payment offers", "creator_e -> juror_0_e", "(accepted)", "SETTLED_CREATOR",
                     '"action": "finding"', "VERDICT_VERIFIED", "NOT_VERIFIED"):
            self.assertIn(text, review)

    async def test_llm_auditors_and_jurors_parse_interviews_findings_and_finding_offers(self):
        replies = []

        async def create(**_):
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=replies.pop(0)))])

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), \
                patch("agents.llm_agent.AsyncOpenAI", return_value=client):
            auditor = LLMAgent(AgentConfig("auditor_0_e", Role.AUDITOR, provider="openai"))
            replies.append(json.dumps({"action": "interview", "private_messages": [
                {"recipient_id": "juror_0_e", "content": "Why?"}]}))
            action = await auditor.interview(self.observation(Role.AUDITOR, Phase.INTERVIEW, chat=True))
            self.assertEqual(action.private_messages, [PrivateMessage("juror_0_e", "Why?")])
            replies.append(json.dumps({"action": "finding", "finding": "NOT_VERIFIED",
                                       "implicated": ["juror_0_e"], "rationale": "paid vote"}))
            finding = await auditor.review(self.observation(Role.AUDITOR, Phase.REVIEW, case_file=CaseFile()))
            self.assertEqual((finding.finding, finding.implicated), (Finding.NOT_VERIFIED, ["juror_0_e"]))
            for bad in ({"action": "finding", "finding": "MAYBE", "rationale": "x"},
                        {"action": "finding", "finding": "NOT_VERIFIED", "implicated": "juror_0_e", "rationale": "x"},
                        {"action": "reply", "message": "hi"}):
                replies.append(json.dumps(bad))
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    await auditor.review(self.observation(Role.AUDITOR, Phase.REVIEW, case_file=CaseFile()))

            juror = LLMAgent(AgentConfig("juror_0_e", Role.JUROR, provider="openai"))
            replies.append(json.dumps({"action": "reply", "message": "I voted on the evidence.", "offers": [
                {"recipient_id": "auditor_0_e", "amount": 0.5, "required_finding": "VERDICT_VERIFIED"}]}))
            reply = await juror.interview(self.observation(Role.JUROR, Phase.INTERVIEW))
            self.assertEqual(reply, InterviewAction("juror_0_e", "e", "I voted on the evidence.", [], [
                TransferProposal("auditor_0_e", 0.5, None, "", Finding.VERDICT_VERIFIED)]))
            for bad in ({"action": "interview", "message": "wrong role"},
                        {"action": "reply", "offers": [{"recipient_id": "auditor_0_e", "amount": 0.5,
                                                         "required_finding": "VERDICT_VERIFIED",
                                                         "required_verdict": "CREATOR_SUPPORTED"}]}):
                replies.append(json.dumps(bad))
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    await juror.interview(self.observation(Role.JUROR, Phase.INTERVIEW))


if __name__ == "__main__":
    unittest.main()
