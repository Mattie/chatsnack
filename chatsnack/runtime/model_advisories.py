"""Narrow provider diagnostics that never alter caller-authored request options."""

import warnings
from urllib.parse import urlsplit


# Reusable GPT-6 limits. Model registrations below record where they are verified;
# sharing a family name alone does not establish support for an unlisted variant.
_GPT6_REQUEST_LIMITS = {
    "unsupported_options": ("temperature", "top_p", "top_logprobs"),
    "chat_completions": {
        "unsupported_options": ("logprobs",),
        "tools_require_responses": True,
    },
    "responses": {"unsupported_include": ("message.output_text.logprobs",)},
}
_MODEL_REQUEST_LIMITS = {
    # Verified 2026-09-09 for this exact model on the direct OpenAI endpoint.
    # https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters
    "gpt-6-astra": _GPT6_REQUEST_LIMITS,
}


def warn_model_options(options, client, runtime_family):
    """Apply registered request limits on the submitting OpenAI SDK endpoint.

    The SDK's resolved URL accounts for injected clients and environment defaults.
    Unknown endpoints and aliases remain provider-owned. ``extra_body`` can
    override top-level options, so inspect its effective values without mutation.
    """
    effective = dict(options)
    if isinstance(options.get("extra_body"), dict):
        effective.update(options["extra_body"])
    model = effective.get("model")
    if not isinstance(model, str):
        return
    limits = _MODEL_REQUEST_LIMITS.get(model)
    if limits is None:
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

    runtime_limits = limits.get(runtime_family, {})
    unsupported = [key for key in (*limits.get("unsupported_options", ()),
                                   *runtime_limits.get("unsupported_options", ()))
                   if effective.get(key) is not None]
    if runtime_limits.get("tools_require_responses") and (
        effective.get("tools") or effective.get("functions")
    ):
        warnings.warn(
            f"Model '{model}' tools require Responses. Construct a new "
            "Chat(runtime='responses') to use utensils. Passing through to provider unchanged.",
            stacklevel=3,
        )
    include = effective.get("include")
    if isinstance(include, (list, tuple)):
        unsupported.extend(
            f"include: {item}" for item in runtime_limits.get("unsupported_include", ())
            if item in include
        )
    if unsupported:
        warnings.warn(
            f"Model '{model}' does not support {', '.join(unsupported)}. "
            "Remove these options for this model. Passing through to provider unchanged.",
            stacklevel=3,
        )
