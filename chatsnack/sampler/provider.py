"""Lazy SDK boundary for Decisions and Jev; return validated normalized results."""

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Mapping
import os
from typing import Any, Dict

from .adapters import normalize_decisions, typesafe_execution, wire_request


_sync_client = ContextVar('sampler_sync_client', default=None)


def _client_options(params):
    """Translate nonsecret Sampler settings into the selected SDK's options."""
    options = {key: getattr(params, key) for key in ('timeout', 'base_url')
               if getattr(params, key) is not None}
    if params.api_key_env is not None:
        key = os.getenv(params.api_key_env)
        if not key or not key.strip():
            raise ValueError(f'Missing credential environment variable {params.api_key_env}')
        options['api_key'] = key
    if params.retry is not None:
        if params.effective_provider == 'openai':
            options.update(params.retry)
        else:
            from typesafe_sdk import RetryPolicy
            options['retry'] = RetryPolicy(**params.retry)
    return options


def create_sync_client(params):
    """Construct the lazy sync SDK client for a reusable Sampler."""
    if params.effective_provider == 'openai':
        from openai import OpenAI
        return OpenAI(**_client_options(params))
    else:
        from typesafe_sdk import TypeSafeClient
        return TypeSafeClient(**_client_options(params))


def create_async_client(params):
    """Construct a scoped async SDK client for one evaluation."""
    if params.effective_provider == 'openai':
        from openai import AsyncOpenAI
        return AsyncOpenAI(**_client_options(params))
    else:
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
    """Decode TypeSafe 0.7 Pydantic responses; mapping transports stay usable."""
    return response if isinstance(response, Mapping) else response.model_dump(mode='json')


def _long_context_retry(wire, error):
    """Extend one rejected request only for Jev's explicit 400 context-limit code."""
    # Verified 2026-10-22: https://docs.typesafe.ai/api/errors
    # Extended limits: https://docs.typesafe.ai/models#long-context
    if error.status != 400:
        return None
    body = error.body
    codes = [body.get(key) for key in ('code', 'error', 'detail')] if isinstance(body, Mapping) else [body]
    for code in codes:
        if isinstance(code, Mapping):
            code = code.get('error_type', code.get('code', code.get('type')))
        if code == 'max_tokens_exceeded':
            return {**wire, 'extra_headers': {**wire.get('extra_headers', {}),
                                             'TypeSafe-Danger-Zone-Long-Context': 'true'}}
    return None


def evaluate_sync(request, params):
    """Submit synchronously, retaining an activated client or scoping a standalone one."""
    client = _sync_client.get()
    def submit(client):
        """Encode and normalize at the boundary, leaving shared decoding strict."""
        if params.effective_provider == 'openai':
            wire = wire_request(request, params)
            return normalize_decisions(client.post('/decisions', body=wire, cast_to=Dict[str, Any]), request)
        from typesafe_sdk import TypeSafeAPIError
        wire = typesafe_execution(request)
        try:
            return _builtins(client.system_one(**wire))
        except TypeSafeAPIError as error:
            extended = _long_context_retry(wire, error)
            if extended is None:
                raise
            return _builtins(client.system_one(**extended))
    if client is not None:
        if callable(client):
            client = client()
        return submit(client)
    client = create_sync_client(params)
    try:
        return submit(client)
    finally:
        client.close()


async def evaluate(request, params):
    """Submit asynchronously and close the client on the active event loop."""
    client = create_async_client(params)
    try:
        if params.effective_provider == 'openai':
            wire = wire_request(request, params)
            return normalize_decisions(await client.post('/decisions', body=wire, cast_to=Dict[str, Any]), request)
        from typesafe_sdk import TypeSafeAPIError
        wire = typesafe_execution(request)
        try:
            return _builtins(await client.system_one(**wire))
        except TypeSafeAPIError as error:
            extended = _long_context_retry(wire, error)
            if extended is None:
                raise
            return _builtins(await client.system_one(**extended))
    finally:
        if params.effective_provider == 'openai':
            await client.close()
        else:
            await client.aclose()
