import asyncio
from threading import Barrier, Event
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, NotFound

from veracity_harness.sandbox import DockerArena


async def test_participants_start_concurrently_and_keep_roster_order(monkeypatch, tmp_path):
    client = MagicMock()
    client.api._proxy_configs = {}
    monkeypatch.setattr("veracity_harness.sandbox.docker.from_env", lambda **kwargs: client)
    arena = DockerArena("parallel-start-fixture")
    documents = {f"juror-{i}": tmp_path / str(i) for i in range(1, 5)}
    barrier = Barrier(4, timeout=3)
    gateway = object()

    def start(actor, docs, passed_gateway, shared):
        assert docs == documents[actor]
        assert passed_gateway is gateway
        assert shared == "cache"
        barrier.wait()
        return actor, f"address-{actor}"

    monkeypatch.setattr(arena, "start_participant", start)
    try:
        started = await arena.start_participants(documents, gateway, "cache")
        assert list(started) == list(documents)
        assert started == {actor: (actor, f"address-{actor}") for actor in documents}
    finally:
        arena.close()


async def test_failed_startup_drains_workers_before_cleanup(monkeypatch, tmp_path):
    client = MagicMock()
    client.api._proxy_configs = {}
    monkeypatch.setattr("veracity_harness.sandbox.docker.from_env", lambda **kwargs: client)
    arena = DockerArena("parallel-failure-fixture")
    barrier = Barrier(2, timeout=3)
    failure = Event()
    finished = Event()
    container = MagicMock()

    def start(actor, docs, gateway, shared):
        barrier.wait()
        if actor == "fails":
            failure.set()
            raise APIError("Fixture startup failure")
        assert failure.wait(timeout=3)
        arena.containers.append(container)
        finished.set()
        return container, "address"

    monkeypatch.setattr(arena, "start_participant", start)
    try:
        with pytest.raises(APIError):
            await arena.start_participants({"fails": tmp_path, "finishes": tmp_path}, object())
        assert finished.is_set()
    finally:
        arena.close()
    container.remove.assert_called_once_with(force=True)


async def test_cancelled_startup_drains_workers_before_cleanup(monkeypatch, tmp_path):
    client = MagicMock()
    client.api._proxy_configs = {}
    monkeypatch.setattr("veracity_harness.sandbox.docker.from_env", lambda **kwargs: client)
    arena = DockerArena("cancelled-start-fixture")
    entered, release, finished = Event(), Event(), Event()
    container = MagicMock()

    def start(actor, docs, gateway, shared):
        entered.set()
        assert release.wait(timeout=3)
        arena.containers.append(container)
        finished.set()
        return container, "address"

    monkeypatch.setattr(arena, "start_participant", start)
    startup = asyncio.create_task(arena.start_participants({"juror-1": tmp_path}, object()))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        startup.cancel()
        await asyncio.sleep(0)
        assert not startup.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await startup
        arena.close()
    assert finished.is_set()
    container.remove.assert_called_once_with(force=True)


def test_cleanup_removes_all_containers_before_networks_and_mounts(monkeypatch):
    client = MagicMock()
    client.api._proxy_configs = {}
    monkeypatch.setattr("veracity_harness.sandbox.docker.from_env", lambda **kwargs: client)
    arena = DockerArena("parallel-close-fixture")
    barrier = Barrier(4, timeout=3)
    removed = []

    def remove_container(number):
        assert arena.staging.exists()
        barrier.wait()
        removed.append(number)

    for number in range(4):
        container = MagicMock()
        container.remove.side_effect = lambda number=number, **kwargs: remove_container(number)
        arena.containers.append(container)
    network = MagicMock()

    def remove_network():
        assert len(removed) == 4
        assert arena.staging.exists()

    network.remove.side_effect = remove_network
    arena.networks.append(network)
    volume = MagicMock()

    def remove_volume(**kwargs):
        network.remove.assert_called_once_with()
        assert arena.staging.exists()

    volume.remove.side_effect = remove_volume
    arena.volumes.append(volume)
    arena.close()
    network.remove.assert_called_once_with()
    volume.remove.assert_called_once_with(force=True)
    assert not arena.staging.exists()


@pytest.mark.parametrize("error", [APIError, NotFound])
def test_cleanup_attempts_remaining_resources_after_removal_failure(monkeypatch, error):
    client = MagicMock()
    client.api._proxy_configs = {}
    monkeypatch.setattr("veracity_harness.sandbox.docker.from_env", lambda **kwargs: client)
    arena = DockerArena("cleanup-failure-fixture")
    failed, other, network, volume = (MagicMock() for _ in range(4))
    failed.remove.side_effect = error("Fixture removal failure")
    arena.containers.extend([failed, other])
    arena.networks.append(network)
    arena.volumes.append(volume)
    if error is APIError:
        with pytest.raises(RuntimeError, match="1 resources"):
            arena.close()
    else:
        arena.close()
    other.remove.assert_called_once_with(force=True)
    network.remove.assert_called_once_with()
    volume.remove.assert_called_once_with(force=True)
    client.close.assert_called_once_with()
    assert not arena.staging.exists()


def test_container_is_owned_before_start_can_fail(monkeypatch, tmp_path):
    client = MagicMock()
    client.api._proxy_configs = {"no_proxy": "localhost,original.internal"}
    container = client.containers.create.return_value
    container.start.side_effect = APIError("Fixture startup failure")
    monkeypatch.setattr("veracity_harness.sandbox.docker.from_env", lambda **kwargs: client)
    arena = DockerArena("partial-start-fixture")
    with pytest.raises(APIError):
        arena.start_gateway(tmp_path, "Interface")
    arena.close()
    container.remove.assert_called_once_with(force=True)
    client.close.assert_called_once()


def test_bind_mounted_staging_outlives_every_container_that_mounts_it(monkeypatch):
    # Deleting a bind-mount source before its container is removed crashed
    # Docker Desktop's file sharing and, with it, containerd.
    client = MagicMock()
    client.api._proxy_configs = {"no_proxy": "localhost,original.internal"}
    monkeypatch.setattr("veracity_harness.sandbox.docker.from_env", lambda **kwargs: client)
    arena = DockerArena("staging-fixture")
    staging = arena.staging
    seen = []
    client.containers.create.return_value.remove.side_effect = lambda **kwargs: seen.append(
        staging.exists()
    )
    (staging / "gateway").mkdir()
    (staging / "juror-1").mkdir()
    gateway = arena.start_gateway(staging / "gateway", "Interface")
    arena.start_participant("juror-1", staging / "juror-1", gateway)
    arena.close()
    assert seen == [True, True]
    assert not staging.exists()


def test_staging_is_removed_even_when_container_cleanup_fails(monkeypatch):
    client = MagicMock()
    client.api._proxy_configs = {"no_proxy": "localhost,original.internal"}
    client.containers.create.return_value.remove.side_effect = APIError("Fixture failure")
    monkeypatch.setattr("veracity_harness.sandbox.docker.from_env", lambda **kwargs: client)
    arena = DockerArena("staging-failure-fixture")
    arena.start_gateway(arena.staging, "Interface")
    with pytest.raises(RuntimeError):
        arena.close()
    assert not arena.staging.exists()


def test_every_resource_carries_the_harness_run_label_for_cleanup(monkeypatch):
    client = MagicMock()
    client.api._proxy_configs = {"no_proxy": "localhost,original.internal"}
    monkeypatch.setattr("veracity_harness.sandbox.docker.from_env", lambda **kwargs: client)
    arena = DockerArena("node-3f9a1c2b7d4e", "run-abc123def456")
    (arena.staging / "gateway").mkdir()
    (arena.staging / "juror-1").mkdir()
    gateway = arena.start_gateway(arena.staging / "gateway", "Interface")
    arena.start_participant("juror-1", arena.staging / "juror-1", gateway)
    arena.create_shared_volume()
    label = {"veracity.session": "run-abc123def456"}
    for call in client.containers.create.call_args_list:
        assert label.items() <= call.kwargs["labels"].items()
        assert call.kwargs["environment"]["NO_PROXY"] == (
            "localhost,original.internal,veracity-api,host.docker.internal"
        )
    assert label.items() <= client.networks.create.call_args.kwargs["labels"].items()
    assert label.items() <= client.volumes.create.call_args.kwargs["labels"].items()
    arena.close()
