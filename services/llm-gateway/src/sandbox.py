"""Sandboxed code execution via ephemeral Docker containers.

Each execution creates a fresh container from the ai-lab-sandbox image,
writes the code as a file via put_archive, runs it, collects output,
and force-removes the container.  No network, strict resource limits,
non-root user inside the container.

The Docker client connects via the host socket (mounted into the
gateway container at /var/run/docker.sock).
"""

import asyncio
import io
import logging
import tarfile
import uuid

import aiodocker

from ai_lab_common.config import settings

logger = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 50 * 1024  # 50 KB

# Language -> (file extension, command to execute the file)
_LANGUAGES = {
    "python": ("code.py", ["python3", "-u", "/home/sandbox/code.py"]),
    "javascript": ("code.js", ["node", "/home/sandbox/code.js"]),
    "bash": ("code.sh", ["bash", "/home/sandbox/code.sh"]),
}

# Limit concurrent sandbox executions to avoid exhausting VM resources.
_semaphore = asyncio.Semaphore(3)

# Lazy-initialized Docker client (module-level singleton).
_docker: aiodocker.Docker | None = None


async def _get_docker() -> aiodocker.Docker:
    global _docker
    if _docker is None:
        _docker = aiodocker.Docker()
    return _docker


async def close():
    """Close the Docker client.  Called during gateway shutdown."""
    global _docker
    if _docker is not None:
        await _docker.close()
        _docker = None


def _make_tar(filename: str, content: str) -> bytes:
    """Create an in-memory tar archive containing a single file."""
    data = content.encode("utf-8")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=filename)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf.read()


async def run_code(code: str, language: str) -> str:
    """Execute code in an isolated Docker container.

    Args:
        code: Source code to execute.
        language: One of "python", "javascript", "bash".

    Returns:
        Combined stdout + stderr, truncated to MAX_OUTPUT_BYTES.
    """
    language = language.lower().strip()
    if language not in _LANGUAGES:
        return f"Error: unsupported language '{language}'. Use: {', '.join(_LANGUAGES)}"

    filename, cmd = _LANGUAGES[language]
    container_name = f"sandbox-{uuid.uuid4().hex[:12]}"
    timeout = settings.SANDBOX_TIMEOUT
    memory = settings.SANDBOX_MEMORY_MB * 1024 * 1024

    async with _semaphore:
        docker = await _get_docker()
        container = None
        try:
            container = await docker.containers.create_or_replace(
                name=container_name,
                config={
                    "Image": settings.SANDBOX_IMAGE,
                    "Cmd": cmd,
                    "HostConfig": {
                        "Memory": memory,
                        "MemorySwap": memory,       # no swap
                        "CpuPeriod": 100_000,
                        "CpuQuota": 100_000,         # 1 CPU core
                        "PidsLimit": 64,
                        "NetworkMode": "none",
                        "SecurityOpt": ["no-new-privileges"],
                    },
                    "NetworkDisabled": True,
                    "User": "sandbox",
                },
            )

            # Write code into the container as a file
            tar_data = _make_tar(filename, code)
            await container.put_archive("/home/sandbox", tar_data)

            # Start execution
            await container.start()
            logger.info("Sandbox started: %s (%s, %ds timeout)", container_name, language, timeout)

            # Wait for completion with timeout
            try:
                result = await asyncio.wait_for(container.wait(), timeout=timeout)
                exit_code = result["StatusCode"]
            except asyncio.TimeoutError:
                try:
                    await container.kill()
                except Exception:
                    pass
                logger.warning("Sandbox timed out: %s", container_name)
                return f"Error: execution timed out after {timeout}s"

            # Collect output
            logs = await container.log(stdout=True, stderr=True)
            output = "".join(logs)

            # Truncate
            if len(output.encode("utf-8")) > MAX_OUTPUT_BYTES:
                output = output[:MAX_OUTPUT_BYTES] + "\n... (output truncated at 50KB)"

            if exit_code != 0:
                output = f"[exit code {exit_code}]\n{output}"

            logger.info("Sandbox finished: %s (exit=%d, %d bytes output)", container_name, exit_code, len(output))
            return output if output.strip() else "(no output)"

        except aiodocker.exceptions.DockerError as e:
            logger.error("Sandbox Docker error: %s", e)
            return f"Error: sandbox unavailable — {e.message}"
        except Exception as e:
            logger.error("Sandbox execution failed: %s", e)
            return f"Error: {e}"
        finally:
            if container is not None:
                try:
                    await container.delete(force=True)
                except Exception as e:
                    logger.warning("Failed to remove sandbox %s: %s", container_name, e)
