"""Lazy TypeSafe SDK clients owned by one reusable Sampler."""

import asyncio
import inspect
import json
import threading

from . import provider


def connection_signature(params):
    """Identify settings that determine which provider connection may be reused."""
    retry = None if params.retry is None else json.dumps(params.retry, sort_keys=True,
                                                          separators=(',', ':'))
    return params.timeout, retry, params.base_url, params.api_key_env


class _SamplerClient:
    """Own lazy sync and async SDK clients without entering authored Sampler state."""

    def __init__(self, params):
        self._params = params
        self._signature = connection_signature(params)
        self._client = None
        self._aclients = {}
        self._lock = threading.Lock()

    def bind(self, params):
        """Track authored connection settings until an opened client fixes the binding."""
        signature = connection_signature(params)
        if signature == self._signature:
            return
        with self._lock:
            if self._client is not None or self._aclients:
                raise RuntimeError(
                    'Sampler connection settings changed after evaluation. Close the Sampler '
                    'before using the new settings.'
                )
            self._params = params
            self._signature = signature

    @property
    def signature(self):
        """Return the authored connection identity used for override isolation."""
        return self._signature

    @property
    def client(self):
        """Return the sync SDK client, constructing it once even across request threads."""
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = provider.create_sync_client(self._params)
        return self._client

    @property
    def aclient(self):
        """Return one retained SDK client for the current event loop."""
        loop = asyncio.get_running_loop()
        with self._lock:
            for closed_loop in [owner for owner in self._aclients if owner.is_closed()]:
                self._aclients.pop(closed_loop, None)
            client = self._aclients.get(loop)
            if client is None:
                client = provider.create_async_client(self._params)
                self._aclients[loop] = client
            return client

    @staticmethod
    async def _close_async_client(client):
        """Close an async SDK client while running on its owning event loop."""
        result = client.aclose()
        if inspect.isawaitable(result):
            await result

    def close(self):
        """Close opened clients from synchronous code."""
        if self._aclients:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise RuntimeError('Use await close_a() inside an event loop.')
        with self._lock:
            client, self._client = self._client, None
            async_clients = list(self._aclients.items())
            self._aclients.clear()
        if client is not None:
            client.close()
        for loop, async_client in async_clients:
            if loop.is_closed():
                continue
            closing = self._close_async_client(async_client)
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(closing, loop).result()
            else:
                loop.run_until_complete(closing)

    async def close_a(self):
        """Close opened sync and async clients from asynchronous code."""
        current_loop = asyncio.get_running_loop()
        with self._lock:
            client, self._client = self._client, None
            async_clients = list(self._aclients.items())
            self._aclients.clear()
        if client is not None:
            client.close()
        for loop, async_client in async_clients:
            if loop.is_closed():
                continue
            if loop is current_loop:
                await self._close_async_client(async_client)
            elif loop.is_running():
                closing = asyncio.run_coroutine_threadsafe(
                    self._close_async_client(async_client), loop,
                )
                await asyncio.wrap_future(closing)
            else:
                await asyncio.to_thread(
                    loop.run_until_complete, self._close_async_client(async_client),
                )
