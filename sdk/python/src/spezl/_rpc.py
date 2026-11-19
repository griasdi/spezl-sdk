from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from typing import Any

from ._types import SpezlError

CLOSE_TIMEOUT = 20.0
"""Seconds `close` gives `spezl serve` to end after its shutdown, before it is killed. It
covers serve's stream stop (5 s + 5 s), goodbye and its 5 s flush."""


class Connection:
    """JSON-RPC 2.0 over the stdin/stdout of a `spezl serve` child process."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self._proc = proc
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._queue: asyncio.Queue[dict | None] = asyncio.Queue()
        self._exit_code: int | None = None
        # Serializes write and drain: two requests at once must not interleave their bytes,
        # and asyncio allows only one `drain` waiter on a stream.
        self._write_lock = asyncio.Lock()
        self._reader = asyncio.create_task(self._read_loop())

    @staticmethod
    async def open(binary: str, home: str | None) -> Connection:
        args = [*(["--home", home] if home else []), "serve"]
        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=None,
                limit=8 * 1024 * 1024,
            )
        except FileNotFoundError:
            raise SpezlError(
                f"spezl not found at {binary}: put it on PATH or set SPEZL_BIN"
            ) from None
        except OSError as e:
            raise SpezlError(f"cannot start {binary}: {e}") from e
        return Connection(proc)

    @property
    def exit_code(self) -> int | None:
        """Exit code of serve; `None` while it is still running."""
        return self._exit_code

    async def request(self, method: str, params: dict | None = None) -> Any:
        stdin = self._proc.stdin
        if self._exit_code is not None:
            raise SpezlError(f"spezl serve exited with code {self._exit_code}")
        if stdin is None or stdin.is_closing():
            raise SpezlError("spezl serve is shutting down")
        rid = self._next_id
        self._next_id += 1
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        # Before the future is registered: a ValueError (NaN) or TypeError reaches the caller
        # and leaves nothing pending.
        line = json.dumps(msg, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            async with self._write_lock:
                stdin.write(line)
                await stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            # The read loop reports the exit code through the pending future.
            pass
        except BaseException:
            self._pending.pop(rid, None)
            raise
        return await fut

    async def notifications(self) -> AsyncIterator[dict]:
        """Yield notification objects (`method`, `params`) until serve has exited."""
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    async def _read_loop(self) -> None:
        stdout = self._proc.stdout
        assert stdout is not None
        try:
            while True:
                line = await stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                self._route(obj)
        except (ValueError, asyncio.LimitOverrunError):
            # A line over the limit: the stream is broken. Without a kill, serve would keep
            # running and the wait below would never end.
            if self._proc.returncode is None:
                self._proc.kill()
        finally:
            self._exit_code = await self._proc.wait()
            err = SpezlError(f"spezl serve exited with code {self._exit_code}")
            pending, self._pending = self._pending, {}
            for fut in pending.values():
                if not fut.done():
                    fut.set_exception(err)
            self._queue.put_nowait(None)

    def _route(self, obj: dict) -> None:
        rid = obj.get("id")
        if isinstance(rid, int) and "method" not in obj:
            fut = self._pending.pop(rid, None)
            if fut is None or fut.done():
                return
            error = obj.get("error")
            if error is not None:
                fut.set_exception(
                    SpezlError(str(error.get("message", "")), error.get("code"))
                )
            else:
                fut.set_result(obj.get("result"))
        elif rid is None and isinstance(obj.get("error"), dict):
            # A reply to a line serve could not parse or accept: no request owns it.
            print(
                f"spezl: serve refused a request: {obj['error'].get('message')}",
                file=sys.stderr,
                flush=True,
            )
        elif "method" in obj and "id" not in obj:
            self._queue.put_nowait(obj)

    async def close(self) -> None:
        stdin = self._proc.stdin
        if stdin is not None and not stdin.is_closing():
            stdin.close()
        # `asyncio.wait`, not `wait_for`: a timeout must not cancel the reader, which still
        # has to report the exit code.
        done, _ = await asyncio.wait({self._reader}, timeout=CLOSE_TIMEOUT)
        if not done and self._proc.returncode is None:
            self._proc.kill()
        await self._reader
