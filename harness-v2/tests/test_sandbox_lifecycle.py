from unittest.mock import MagicMock

import pytest
from docker.errors import APIError

from veracity_harness.sandbox import DockerArena


def test_container_is_owned_before_start_can_fail(monkeypatch, tmp_path):
    client = MagicMock()
    container = client.containers.create.return_value
    container.start.side_effect = APIError("Fixture startup failure")
    monkeypatch.setattr("veracity_harness.sandbox.docker.from_env", lambda **kwargs: client)
    arena = DockerArena("partial-start-fixture")
    with pytest.raises(APIError):
        arena.start_gateway(tmp_path)
    arena.close()
    container.remove.assert_called_once_with(force=True)
    client.close.assert_called_once()
