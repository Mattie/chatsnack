"""Jev SDK boundary; defer provider imports until evaluation."""

import os


async def evaluate(request, params):
    """Submit one compiled evaluation with SDK-owned retries and scoped cleanup."""
    from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy
    import msgspec
    options = {key: getattr(params, key) for key in ('timeout', 'base_url')
               if getattr(params, key) is not None}
    if params.api_key_env is not None:
        key = os.getenv(params.api_key_env)
        if not key or not key.strip():
            raise ValueError(f'Missing credential environment variable {params.api_key_env}')
        options['api_key'] = key
    if params.retry is not None:
        options['retry'] = RetryPolicy(**params.retry)
    async with AsyncTypeSafeClient(**options) as client:
        response = await client.system_one(**request)
        return msgspec.to_builtins(response, str_keys=True)
