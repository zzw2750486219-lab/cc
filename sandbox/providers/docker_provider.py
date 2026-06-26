from __future__ import annotations

import asyncio
import base64
import json
import shlex
from typing import AsyncIterator

from sandbox.providers.base import ExecuteResult, SandboxProvider
from shared.models import SandboxConfig


class DockerProvider(SandboxProvider):
    """Sandbox provider backed by local Docker via the docker CLI."""

    async def create(self, config: SandboxConfig) -> str:
        cmd = ["docker", "run", "--rm", "-d"]
        cmd.extend(["--cpus", config.cpu])
        cmd.extend(["--memory", config.memory])
        cmd.extend(["--stop-timeout", "10"])
        if not config.network:
            cmd.append("--network=none")
        for k, v in config.env_vars.items():
            cmd.extend(["-e", f"{k}={v}"])
        cmd.append(config.image)
        cmd.extend(["sleep", "infinity"])

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"docker run failed: {stderr.decode().strip()}")
        return stdout.decode().strip()

    async def execute(
        self,
        handle: str,
        cmd: str,
        env: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> ExecuteResult:
        docker_cmd = ["docker", "exec"]
        if env:
            for k, v in env.items():
                docker_cmd.extend(["-e", f"{k}={v}"])
        docker_cmd.append(handle)
        docker_cmd.extend(["bash", "-c", cmd])

        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return ExecuteResult(
                exit_code=proc.returncode or 0,
                stdout=stdout.decode(),
                stderr=stderr.decode(),
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecuteResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
            )

    async def write_file(self, handle: str, path: str, content: str) -> None:
        parent = shlex.quote(path.rsplit("/", 1)[0] if "/" in path else ".")
        safe_path = shlex.quote(path)
        await self.execute(handle, f"mkdir -p {parent}")
        b64 = base64.b64encode(content.encode()).decode()
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", handle, "bash", "-c",
            f"base64 -d > {safe_path}",
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=b64.encode())
        if proc.returncode != 0:
            raise RuntimeError(f"write_file failed: {stderr.decode().strip()}")

    async def read_file(self, handle: str, path: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", handle, "cat", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"read_file failed: {stderr.decode().strip()}")
        return stdout.decode()

    async def stream_events(self, handle: str) -> AsyncIterator[dict]:
        proc = await asyncio.create_subprocess_exec(
            "docker", "logs", "-f", handle,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                yield {"event": "log", "data": line.decode().rstrip()}
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

    async def destroy(self, handle: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", handle,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
