"""Docker lifecycle and the small provider adapter required by Deep Agents."""

import os
import shlex
import subprocess
from pathlib import Path, PurePosixPath

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox
from docker.errors import APIError, NotFound
from docker.models.containers import Container

import docker

IMAGE = "veracity-agent-sandbox:1"
PROJECT = Path(__file__).resolve().parents[2]
RESOURCES = Path(__file__).parent / "resources"
MAX_OUTPUT = 64 * 1024


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

    def __init__(self, run_id: str):
        self.client = docker.from_env(timeout=45)
        self.run_id = run_id
        self.containers: list[Container] = []
        self.networks = []

    def build_image(self):
        self.client.ping()
        self.client.images.build(path=str(PROJECT / "docker"), tag=IMAGE, rm=True)

    def start_gateway(
        self, policy_directory: Path, audit_directory: Path | None = None
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
            "/opt/veracity_harness/resources/interface.md",
        ]
        if audit_directory is not None:
            audit_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            volumes[str(audit_directory)] = {"bind": "/audit", "mode": "rw"}
            command.extend(["--audit", "/audit/access.jsonl"])
        gateway = self.client.containers.create(
            IMAGE,
            name=f"{self.run_id}-gateway",
            detach=True,
            command=command,
            environment={"PYTHONPATH": "/opt"},
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
        self, actor_id: str, documents: Path, gateway: Container
    ) -> tuple[DockerSandbox, str]:
        network = self.client.networks.create(
            f"{self.run_id}-{actor_id}",
            driver="bridge",
            internal=True,
            labels={"veracity.run": self.run_id},
        )
        self.networks.append(network)
        network.connect(gateway, aliases=["game"])
        container = self.client.containers.create(
            IMAGE,
            name=f"{self.run_id}-{actor_id}",
            detach=True,
            network=network.name,
            user="1000:1000",
            working_dir="/workspace",
            environment={"GAME_URL": "http://game:8080", "HOME": "/workspace"},
            volumes={str(documents): {"bind": "/game", "mode": "ro"}},
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

    def close(self):
        failures = []
        for container in reversed(self.containers):
            try:
                container.remove(force=True)
            except NotFound:
                pass
            except APIError:
                failures.append("container")
        for network in reversed(self.networks):
            try:
                network.remove()
            except NotFound:
                pass
            except APIError:
                failures.append("network")
        self.client.close()
        if failures:
            raise RuntimeError(f"Docker cleanup failed for {len(failures)} resources")
