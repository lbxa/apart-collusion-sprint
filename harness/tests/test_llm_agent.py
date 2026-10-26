"""Provider-failure handling at the LLM boundary."""

import json
import os
import traceback
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx2
from openai import RateLimitError

from agents.base import AgentConfig
from agents.llm_agent import LLMAgent
from game_api.types import EpisodeConfig, Observation, Phase, Role, Scenario


class LLMProviderErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_error_redacts_provider_response_body(self):
        marker = "account-id-and-provider-body-must-not-reach-logs"
        response = httpx2.Response(
            429,
            request=httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
        )
        rate_limit = RateLimitError("Error code: 429 - " + marker,
                                    response=response, body={"error": marker})
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_: (_ for _ in ()).throw(rate_limit))))
        observation = Observation(
            Role.JUROR, "episode", Scenario("scenario", "Claim", "For", "Against", True),
            Phase.DELIBERATION, EpisodeConfig("episode"),
        )

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-only"}), \
                patch("agents.llm_agent.AsyncOpenAI", return_value=client):
            agent = LLMAgent(AgentConfig("juror", Role.JUROR))
            with self.assertRaises(RuntimeError) as raised:
                await agent._request_action(observation)

        rendered = "".join(traceback.format_exception(raised.exception))
        self.assertEqual(str(raised.exception), "LLM provider openrouter request failed: rate_limited (HTTP 429)")
        self.assertNotIn(marker, rendered)

    async def test_a_reply_cut_off_at_the_token_cap_is_reported_as_truncated(self):
        # Reasoning models spend max_tokens on hidden reasoning, so the visible
        # reply can stop mid-JSON or before it starts.
        observation = Observation(
            Role.CREATOR, "episode", Scenario("scenario", "Claim", "For", "Against", True),
            Phase.SETUP, EpisodeConfig("episode"),
        )
        for content in ("", '{"action": "post_claim", "claim_text": "unfini'):
            async def create(**_):
                return SimpleNamespace(choices=[SimpleNamespace(
                    finish_reason="length", message=SimpleNamespace(content=content))])

            client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            with self.subTest(content=content), patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-only"}), \
                    patch("agents.llm_agent.AsyncOpenAI", return_value=client):
                agent = LLMAgent(AgentConfig("creator", Role.CREATOR))
                with self.assertRaisesRegex(ValueError, "reached max_tokens=8192"):
                    await agent._request_action(observation)

    async def test_models_without_hidden_reasoning_record_only_the_stated_reasoning(self):
        async def create(**_):
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
                content='{"action": "post_claim", "claim_text": "Claim", "reasoning": "stated"}'))])

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        observation = Observation(
            Role.CREATOR, "episode", Scenario("scenario", "Claim", "For", "Against", True),
            Phase.SETUP, EpisodeConfig("episode"),
        )
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-only"}), \
                patch("agents.llm_agent.AsyncOpenAI", return_value=client):
            agent = LLMAgent(AgentConfig("creator", Role.CREATOR))
            await agent.decide(observation)
        self.assertEqual(agent.reasoning_log, [{
            "agent_id": "creator", "role": "CREATOR", "phase": "SETUP", "round": 0,
            "output": {"action": "post_claim", "claim_text": "Claim"},
            "reasoning": None, "stated_reasoning": "stated", "provider": None, "retries": 0,
        }])

    async def test_one_unreadable_reply_is_retried_once_and_the_retry_recorded(self):
        # The model occasionally closes its JSON early or misses a delimiter (~0.4% of calls).
        observation = Observation(
            Role.CREATOR, "episode", Scenario("scenario", "Claim", "For", "Against", True),
            Phase.SETUP, EpisodeConfig("episode"),
        )
        good = '{"action": "post_claim", "claim_text": "Claim"}'
        cases = [([('{"action": "post_claim"}, "claim_text": "x"', "stop"), (good, "stop")], True),
                 ([("", "stop"), ("not json", "stop")], False),
                 ([("{", "length"), ("{", "length")], False)]
        for replies, retried in cases:
            requests = []

            async def create(**request):
                requests.append(request)
                content, finish = replies[len(requests) - 1]
                return SimpleNamespace(choices=[SimpleNamespace(
                    finish_reason=finish, message=SimpleNamespace(content=content))])

            client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            with self.subTest(replies=replies), patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-only"}), \
                    patch("agents.llm_agent.AsyncOpenAI", return_value=client):
                agent = LLMAgent(AgentConfig("creator", Role.CREATOR))
                if retried:
                    self.assertEqual(await agent._request_action(observation), json.loads(good))
                    self.assertEqual(agent.reasoning_log[0]["retries"], 1)
                else:
                    with self.assertRaises(ValueError):
                        await agent._request_action(observation)
                    self.assertEqual(agent.reasoning_log, [])
                self.assertEqual(len(requests), 2, "exactly one retry")
                self.assertEqual(requests[0]["messages"], requests[1]["messages"], "the retry repeats the prompt")


if __name__ == "__main__":
    unittest.main()
