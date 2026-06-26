from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from sandbox.providers.base import ExecuteResult, SandboxProvider
from sandbox.providers.docker_provider import DockerProvider
from shared.models import SandboxConfig


class TestSandboxProviderABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            SandboxProvider()


class TestExecuteResult:
    def test_dataclass(self):
        r = ExecuteResult(exit_code=0, stdout="out", stderr="err")
        assert r.exit_code == 0
        assert r.stdout == "out"
        assert r.stderr == "err"

    def test_nonzero_exit(self):
        r = ExecuteResult(exit_code=1, stdout="", stderr="command failed")
        assert r.exit_code == 1


class TestDockerProvider:
    @pytest.fixture
    def provider(self):
        return DockerProvider()

    @pytest.fixture
    def config(self):
        return SandboxConfig(
            image="test-image:latest",
            cpu="1",
            memory="256m",
            timeout=300,
            network=False,
        )

    @pytest.mark.asyncio
    async def test_create_success(self, provider, config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"container-id\n", b""))
            mock_exec.return_value = mock_proc

            handle = await provider.create(config)
            assert handle == "container-id"

    @pytest.mark.asyncio
    async def test_create_failure(self, provider, config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"docker error"))
            mock_exec.return_value = mock_proc

            with pytest.raises(RuntimeError, match="docker run failed"):
                await provider.create(config)

    @pytest.mark.asyncio
    async def test_create_with_network_enabled(self, provider):
        config = SandboxConfig(image="img", network=True, env_vars={"KEY": "VAL"})
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"cid\n", b""))
            mock_exec.return_value = mock_proc

            await provider.create(config)

            call_args = mock_exec.await_args[0]
            assert "--network=none" not in call_args
            assert "-e" in call_args
            assert "KEY=VAL" in call_args

    @pytest.mark.asyncio
    async def test_execute_success(self, provider):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"output\n", b""))
            mock_exec.return_value = mock_proc

            result = await provider.execute("cid", "echo hello")
            assert isinstance(result, ExecuteResult)
            assert result.exit_code == 0
            assert result.stdout == "output\n"

    @pytest.mark.asyncio
    async def test_execute_timeout(self, provider):
        import asyncio

        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
            mock_exec.return_value = mock_proc

            result = await provider.execute("cid", "sleep 100", timeout=1)
            assert result.exit_code == -1
            assert "timed out" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_with_env(self, provider):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_exec.return_value = mock_proc

            await provider.execute("cid", "echo $VAR", env={"VAR": "hello"})

            call_args = mock_exec.await_args[0]
            assert "-e" in call_args
            assert "VAR=hello" in call_args

    @pytest.mark.asyncio
    async def test_write_file(self, provider):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            await provider.write_file("cid", "/home/user/test.txt", "hello content")
            # Should not raise

    @pytest.mark.asyncio
    async def test_write_file_failure(self, provider):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"", b"permission denied"))
            mock_proc.returncode = 1

            # execute will fail with subprocess error - need to handle differently
            # First call (mkdir) succeeds, second call (write) fails
            mock_exec.side_effect = [
                AsyncMock(returncode=0, communicate=AsyncMock(return_value=(b"", b""))),
                mock_proc
            ]

            with pytest.raises(RuntimeError, match="write_file failed"):
                await provider.write_file("cid", "/home/user/test.txt", "content")

    @pytest.mark.asyncio
    async def test_read_file(self, provider):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"file contents\n", b""))
            mock_exec.return_value = mock_proc

            content = await provider.read_file("cid", "/home/user/test.txt")
            assert content == "file contents\n"

    @pytest.mark.asyncio
    async def test_read_file_failure(self, provider):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"no such file"))
            mock_exec.return_value = mock_proc

            with pytest.raises(RuntimeError, match="read_file failed"):
                await provider.read_file("cid", "/nonexistent")

    @pytest.mark.asyncio
    async def test_destroy(self, provider):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.wait = AsyncMock(return_value=0)
            mock_exec.return_value = mock_proc

            await provider.destroy("cid")
            # Should not raise

            call_args = mock_exec.await_args[0]
            assert "docker" in call_args[0]
            assert "rm" in call_args
