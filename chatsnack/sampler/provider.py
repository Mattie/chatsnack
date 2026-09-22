"""Jev SDK boundary; defer provider imports until evaluation."""

from contextlib import contextmanager
from contextvars import ContextVar
import os


_sync_client = ContextVar('sampler_sync_client', default=None)


def _client_options(params):
    """Translate serializable Sampler settings into TypeSafe SDK options."""
    from typesafe_sdk import RetryPolicy

    options = {key: getattr(params, key) for key in ('timeout', 'base_url')
               if getattr(params, key) is not None}
    if params.api_key_env is not None:
        key = os.getenv(params.api_key_env)
        if not key or not key.strip():
            raise ValueError(f'Missing credential environment variable {params.api_key_env}')
        options['api_key'] = key
    if params.retry is not None:
        options['retry'] = RetryPolicy(**params.retry)
    return options


def create_sync_client(params):
    """Construct the lazy sync SDK client for a reusable Sampler."""
    from typesafe_sdk import TypeSafeClient
    return TypeSafeClient(**_client_options(params))


def create_async_client(params):
    """Construct a scoped async SDK client for one evaluation."""
    from typesafe_sdk import AsyncTypeSafeClient
    return AsyncTypeSafeClient(**_client_options(params))


@contextmanager
def use_sync_client(client):
    """Make one Sampler-owned sync client visible to the provider boundary."""
    token = _sync_client.set(client)
    try:
        yield
    finally:
        _sync_client.reset(token)


def _builtins(response):
    """Convert SDK response structs into the mapping consumed by Sample decoding."""
    import msgspec
    return msgspec.to_builtins(response, str_keys=True)


def evaluate_sync(request, params):
    """Submit synchronously, retaining an activated client or scoping a standalone one."""
    client = _sync_client.get()
    if client is not None:
        if callable(client):
            client = client()
        return _builtins(client.system_one(**request))
    client = create_sync_client(params)
    try:
        return _builtins(client.system_one(**request))
    finally:
        client.close()


async def evaluate(request, params):
    """Submit asynchronously and close the client on the active event loop."""
    client = create_async_client(params)
    try:
        return _builtins(await client.system_one(**request))
    finally:
        await client.aclose()
