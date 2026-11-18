"""Docker lifecycle and the small provider adapter required by Deep Agents."""

import asyncio
import os
import secrets
import shlex
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from pathlib import Path, PurePosixPath

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox
from docker.errors import APIError, NotFound
from docker.models.containers import Container

import docker

# Participant-visible layout: neutral names that do not reveal a constructed test.
MOUNT = "/veracity"
URL_VARIABLE = "VERACITY_URL"
SHARED_MOUNT = "/shared"
# The shared cache is a size-limited tmpfs volume, never a host directory.
SHARED_LIMIT = "16m"

IMAGE = "veracity-agent-sandbox:1"
PROJECT = Path(__file__).resolve().parents[2]
RESOURCES = Path(__file__).parent / "resources"
MAX_OUTPUT = 64 * 1024
# Stay below the Docker client's default connection pool size.
LIFECYCLE_WORKERS = 4


class DockerSandbox(BaseSandbox):
    """All execution and file transfers stay inside one unprivileged container."""

    def __init__(self, container: Container, command_timeout: int = 20):
        self.container = container
        self.command_timeout = command_timeout

    @property
    def id(self) -> str:
        return self.container.id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        duration = min(timeout or self.command_timeout, self.command_timeout)
        api = self.container.client.api
        execution = api.exec_create(
            self.container.id,
            ["timeout", "--kill-after=2s", f"{max(duration, 1)}s", "bash", "-lc", command],
            workdir="/workspace",
        )
        output = bytearray()
        truncated = False
        for chunk in api.exec_start(execution["Id"], stream=True):
            remaining = MAX_OUTPUT - len(output)
            output.extend(chunk[:remaining])
            truncated |= len(chunk) > remaining
        return ExecuteResponse(
            output.decode("utf-8", errors="replace"),
            exit_code=api.exec_inspect(execution["Id"])["ExitCode"],
            truncated=truncated,
        )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results = []
        for path, content in files:
            target = PurePosixPath(path)
            if not target.is_absolute() or ".." in target.parts:
                results.append(FileUploadResponse(path, error="invalid_path"))
                continue
            if not path.startswith(("/workspace/", "/tmp/")):
                results.append(FileUploadResponse(path, error="permission_denied"))
                continue
            try:
                self.execute(f"mkdir -p -- {shlex.quote(str(target.parent))}")
                # Docker's archive API rejects read-only root filesystems even for
                # writable tmpfs mounts. Exec stdin writes as the sandbox user instead.
                transfer = subprocess.run(
                    ["docker", "exec", "-i", self.id, "sh", "-c", 'cat > "$1"', "upload", path],
                    input=content,
                    capture_output=True,
                    timeout=self.command_timeout,
                    check=False,
                )
                results.append(
                    FileUploadResponse(
                        path, error=None if transfer.returncode == 0 else "permission_denied"
                    )
                )
            except (APIError, OSError, subprocess.TimeoutExpired):
                results.append(FileUploadResponse(path, error="permission_denied"))
        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results = []
        for path in paths:
            if not PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
                results.append(FileDownloadResponse(path, error="invalid_path"))
                continue
            try:
                # Exec sees the live tmpfs; Docker's archive API does not on all daemons.
                result = self.container.exec_run(
                    ["timeout", f"{self.command_timeout}s", "head", "-c", "1048577", "--", path],
                    demux=True,
                )
                output, _stderr = result.output
                if result.exit_code != 0:
                    results.append(FileDownloadResponse(path, error="file_not_found"))
                elif output is not None and len(output) > 1048576:
                    results.append(FileDownloadResponse(path, error="File exceeds the 1 MiB limit"))
                else:
                    results.append(FileDownloadResponse(path, content=output or b""))
            except APIError:
                results.append(FileDownloadResponse(path, error="file_not_found"))
        return results


class DockerArena:
    """Owns the gateway, private participant networks, and cleanup after partial startup."""

    def __init__(self, run_id: str, session: str | None = None):
        self.client = docker.from_env(timeout=45)
        self.run_id = run_id
        # Every resource is labelled so cleanup never depends on container names.
        self.labels = {"veracity.run": run_id, "veracity.session": session or run_id}
        self.containers: list[Container] = []
        self.networks = []
        self.volumes = []
        # Host directories bind-mounted into this arena's containers. close() deletes
        # them only after the containers: removing a mount source first crashes
        # Docker Desktop's file sharing. The neutral name shows in mount tables.
        self.staging = Path(tempfile.mkdtemp(prefix="veracity-node-"))
        # Docker's default proxy is for public HTTPS. These two destinations are
        # exclusively our private gateway and its local engine relay.
        current_no_proxy = self.client.api._proxy_configs.get("no_proxy", "")
        local_no_proxy = ",".join(
            item for item in (current_no_proxy, "veracity-api", "host.docker.internal") if item
        )
        self.local_proxy_environment = {"NO_PROXY": local_no_proxy, "no_proxy": local_no_proxy}

    def create_shared_volume(self) -> str:
        """A per-case writable cache; tmpfs caps its size and keeps it off the host disk."""
        volume = self.client.volumes.create(
            name=f"veracity-cache-{secrets.token_hex(6)}",
            driver="local",
            driver_opts={
                "type": "tmpfs",
                "device": "tmpfs",
                "o": f"size={SHARED_LIMIT},uid=1000,gid=1000,mode=0777",
            },
            labels=self.labels,
        )
        self.volumes.append(volume)
        return volume.name

    def seed_shared(self, container: Container, relative: str, content: bytes):
        target = f"{SHARED_MOUNT}/{relative}"
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                container.id,
                "sh",
                "-c",
                'mkdir -p "$(dirname "$1")" && cat > "$1"',
                "seed",
                target,
            ],
            input=content,
            capture_output=True,
            timeout=20,
            check=True,
        )

    def read_shared(self, container: Container) -> bytes:
        """A tar stream of the cache read through a mounting participant, never followed."""
        result = container.exec_run(["tar", "-C", SHARED_MOUNT, "-cf", "-", "."], demux=True)
        output, _stderr = result.output
        if result.exit_code != 0:
            raise RuntimeError("Shared cache could not be read")
        return output or b""

    def build_image(self):
        self.client.ping()
        # Managed environments inject HTTPS through a trusted proxy. Mount its CA
        # for the dependency-install step; never bake the session CA into an image.
        if os.environ.get("CODEX_PROXY_CERT"):
            context = PROJECT / "docker"
            recipe = (context / "Dockerfile").read_text()
            recipe = recipe.replace(
                "RUN apt-get", "RUN --mount=type=secret,id=proxy_ca,required=true apt-get"
            ).replace("&& pip install", "&& PIP_CERT=/run/secrets/proxy_ca pip install")
            with tempfile.TemporaryDirectory(prefix="veracity-build-") as staging:
                dockerfile = Path(staging) / "Dockerfile"
                dockerfile.write_text(recipe)
                subprocess.run(
                    [
                        "docker",
                        "build",
                        "--secret",
                        "id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt",
                        "-f",
                        str(dockerfile),
                        "-t",
                        IMAGE,
                        str(context),
                    ],
                    env={
                        **os.environ,
                        "BUILDX_CONFIG": os.environ.get(
                            "BUILDX_CONFIG", str(Path(staging) / "buildx")
                        ),
                    },
                    check=True,
                    capture_output=True,
                )
            return
        self.client.images.build(path=str(PROJECT / "docker"), tag=IMAGE, rm=True)

    def start_gateway(
        self, policy_directory: Path, interface: str, audit_directory: Path | None = None
    ) -> Container:
        import game_api

        volumes = {
            str(Path(__file__).parent): {"bind": "/opt/veracity_harness", "mode": "ro"},
            str(Path(game_api.__file__).parent): {"bind": "/opt/game_api", "mode": "ro"},
            str(policy_directory): {"bind": "/policy", "mode": "ro"},
        }
        command = [
            "python",
            "-m",
            "veracity_harness.gateway",
            "--policy",
            "/policy/policy.json",
            "--interface",
            "/policy/interface.md",
        ]
        # Serve the run's frozen API guide, not the live source file.
        (policy_directory / "interface.md").write_text(interface)
        if audit_directory is not None:
            audit_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            volumes[str(audit_directory)] = {"bind": "/audit", "mode": "rw"}
            command.extend(["--audit", "/audit/access.jsonl"])
        gateway = self.client.containers.create(
            IMAGE,
            name=f"{self.run_id}-gateway",
            detach=True,
            labels=self.labels,
            command=command,
            environment={"PYTHONPATH": "/opt", **self.local_proxy_environment},
            user=f"{os.getuid()}:{os.getgid()}",
            volumes=volumes,
            extra_hosts={"host.docker.internal": "host-gateway"},
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            tmpfs={"/tmp": "rw,nosuid,nodev,size=16m,mode=1777"},
            mem_limit="256m",
            pids_limit=64,
            nano_cpus=1_000_000_000,
        )
        self.containers.append(gateway)
        gateway.start()
        return gateway

    def start_participant(
        self, actor_id: str, documents: Path, gateway: Container, shared: str | None = None
    ) -> tuple[DockerSandbox, str]:
        network = self.client.networks.create(
            f"{self.run_id}-{actor_id}",
            driver="bridge",
            internal=True,
            labels=self.labels,
        )
        self.networks.append(network)
        network.connect(gateway, aliases=["veracity-api"])
        container = self.client.containers.create(
            IMAGE,
            name=f"{self.run_id}-{actor_id}",
            detach=True,
            labels=self.labels,
            network=network.name,
            user="1000:1000",
            working_dir="/workspace",
            environment={
                URL_VARIABLE: "http://veracity-api:8080",
                "HOME": "/workspace",
                **self.local_proxy_environment,
            },
            volumes={
                str(documents): {"bind": MOUNT, "mode": "ro"},
                **({shared: {"bind": SHARED_MOUNT, "mode": "rw"}} if shared else {}),
            },
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            tmpfs={
                "/workspace": "rw,nosuid,nodev,size=64m,uid=1000,gid=1000,mode=700",
                "/tmp": "rw,nosuid,nodev,size=16m,mode=1777",
            },
            mem_limit="256m",
            pids_limit=64,
            nano_cpus=1_000_000_000,
        )
        self.containers.append(container)
        container.start()
        container.reload()
        address = container.attrs["NetworkSettings"]["Networks"][network.name]["IPAddress"]
        return DockerSandbox(container), address

    async def start_participants(
        self, documents: dict[str, Path], gateway: Container, shared: str | None = None
    ) -> dict[str, tuple[DockerSandbox, str]]:
        def start():
            # Drain all workers on failure before the caller starts cleanup.
            with ThreadPoolExecutor(max_workers=LIFECYCLE_WORKERS) as pool:
                started = pool.map(
                    self.start_participant,
                    documents,
                    documents.values(),
                    repeat(gateway),
                    repeat(shared),
                )
                return dict(zip(documents, started, strict=True))

        startup = asyncio.create_task(asyncio.to_thread(start))
        try:
            return await asyncio.shield(startup)
        except asyncio.CancelledError:
            # Cancelling an await cannot stop Docker calls already running in
            # threads. Wait for their ownership records before allowing cleanup.
            await asyncio.gather(startup, return_exceptions=True)
            raise

    def close(self):
        def remove(resource, kind, force):
            try:
                resource.remove(**({"force": True} if force else {}))
            except NotFound:
                pass
            except APIError:
                return kind
            return None

        failures = []
        with ThreadPoolExecutor(max_workers=LIFECYCLE_WORKERS) as pool:
            # Each phase finishes before its dependencies are removed. In
            # particular, bind mounts outlive all containers, even on failure.
            for resources, kind, force in (
                (self.containers, "container", True),
                (self.networks, "network", False),
                (self.volumes, "volume", True),
            ):
                results = pool.map(remove, reversed(resources), repeat(kind), repeat(force))
                failures.extend(result for result in results if result is not None)
        shutil.rmtree(self.staging, ignore_errors=True)
        self.client.close()
        if failures:
            raise RuntimeError(f"Docker cleanup failed for {len(failures)} resources")
