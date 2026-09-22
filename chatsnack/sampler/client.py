"""Lazy sync TypeSafe SDK client owned by one reusable Sampler."""

import json
import threading

from . import provider


def connection_signature(params):
    """Identify settings that determine which provider connection may be reused."""
    retry = None if params.retry is None else json.dumps(params.retry, sort_keys=True,
                                                          separators=(',', ':'))
    return params.timeout, retry, params.base_url, params.api_key_env


class _SamplerClient:
    """Own a lazy sync SDK client without entering authored Sampler state."""

    def __init__(self, params):
        self._params = params
        self._signature = connection_signature(params)
        self._client = None
        self._lock = threading.Lock()

    def bind(self, params):
        """Track authored connection settings until an opened client fixes the binding."""
        signature = connection_signature(params)
        if signature == self._signature:
            return
        with self._lock:
            if self._client is not None:
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

    def close(self):
        """Close the opened sync client."""
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            client.close()

    async def close_a(self):
        """Close the opened sync client from asynchronous code."""
        self.close()
