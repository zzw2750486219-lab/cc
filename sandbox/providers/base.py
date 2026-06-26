from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator

from shared.models import SandboxConfig


@dataclass
class ExecuteResult:
    exit_code: int
    stdout: str
    stderr: str


class SandboxProvider(ABC):
    """Abstract sandbox provider — create, execute commands, read/write files, stream events, destroy."""

    @abstractmethod
    async def create(self, config: SandboxConfig) -> str:
        """Provision a sandbox and return a handle (e.g. container ID)."""
        ...

    @abstractmethod
    async def execute(
        self,
        handle: str,
        cmd: str,
        env: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> ExecuteResult:
        """Run a command inside the sandbox."""
        ...

    @abstractmethod
    async def write_file(self, handle: str, path: str, content: str) -> None:
        """Write content to a file inside the sandbox."""
        ...

    @abstractmethod
    async def read_file(self, handle: str, path: str) -> str:
        """Read a file from inside the sandbox."""
        ...

    @abstractmethod
    async def stream_events(self, handle: str) -> AsyncIterator[dict]:
        """Stream sandbox events (e.g. container logs) as an async iterator of dicts."""
        ...

    @abstractmethod
    async def destroy(self, handle: str) -> None:
        """Tear down the sandbox."""
        ...
