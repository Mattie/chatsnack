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
        self._aclient = None
        self._lock = threading.Lock()

    def bind(self, params):
        """Track authored connection settings until an opened client fixes the binding."""
        signature = connection_signature(params)
        if signature == self._signature:
            return
        if self._client is not None or self._aclient is not None:
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
        """Return the async SDK client, constructing it once across callers."""
        if self._aclient is None:
            with self._lock:
                if self._aclient is None:
                    self._aclient = provider.create_async_client(self._params)
        return self._aclient

    def close(self):
        """Close opened clients from synchronous code."""
        if self._aclient is not None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise RuntimeError('Use await close_a() inside an event loop.')
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._aclient is not None:
            result = self._aclient.aclose()
            if inspect.isawaitable(result):
                asyncio.run(result)
            self._aclient = None

    async def close_a(self):
        """Close opened sync and async clients from asynchronous code."""
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._aclient is not None:
            result = self._aclient.aclose()
            if inspect.isawaitable(result):
                await result
            self._aclient = None
