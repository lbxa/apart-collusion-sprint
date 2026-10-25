"""Provider-failure handling at the LLM boundary."""

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


if __name__ == "__main__":
    unittest.main()
