"""Narrow provider diagnostics that never alter caller-authored request options."""

import warnings
from urllib.parse import urlsplit


def warn_astra_options(options, client, runtime_family):
    """Warn only for the verified Astra ID on the submitting OpenAI SDK endpoint.

    The SDK's resolved URL accounts for injected clients and environment defaults.
    Unknown endpoints and aliases remain provider-owned. ``extra_body`` can
    override top-level options, so inspect its effective values without mutation.
    """
    effective = dict(options)
    if isinstance(options.get("extra_body"), dict):
        effective.update(options["extra_body"])
    if effective.get("model") != "gpt-6-astra":
        return
    try:
        endpoint = urlsplit(str(getattr(client, "base_url", "")))
        direct_openai = (
            endpoint.scheme == "https"
            and endpoint.hostname == "api.openai.com"
            and endpoint.port in (None, 443)
            and endpoint.path.rstrip("/") == "/v1"
        )
    except ValueError:
        return
    if not direct_openai:
        return

    # Verified 2026-09-08 for this exact model and endpoint.
    # https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters
    unsupported = [key for key in ("temperature", "top_p", "top_logprobs")
                   if effective.get(key) is not None]
    if runtime_family == "chat_completions":
        if effective.get("logprobs") is not None:
            unsupported.append("logprobs")
        if effective.get("tools") or effective.get("functions"):
            warnings.warn(
                "Model 'gpt-6-astra' tools require Responses. Construct a new "
                "Chat(runtime='responses') to use utensils. Passing through to provider unchanged.",
                stacklevel=3,
            )
    else:
        include = effective.get("include")
        if isinstance(include, (list, tuple)) and "message.output_text.logprobs" in include:
            unsupported.append("include: message.output_text.logprobs")
    if unsupported:
        warnings.warn(
            f"Model 'gpt-6-astra' does not support {', '.join(unsupported)}. "
            "Remove these options for OpenAI Astra requests. Passing through to provider unchanged.",
            stacklevel=3,
        )
