import asyncio
import inspect
import os
from typing import Any, Optional

import openai


_LEGACY_ENDPOINT_ENV_VARS = (
    "OPENAI_API_BASE",
    "OPENAI_AZURE_ENDPOINT",
)


class AiClient:
    """Own lazy sync and async OpenAI clients for one Chat endpoint."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key_env: Optional[str] = None,
    ):
        if api_key is None and api_key_env:
            api_key = os.getenv(api_key_env)
            if api_key is None or not api_key.strip():
                raise ValueError(
                    f"Credential environment variable '{api_key_env}' is not set or is blank."
                )
        self._api_key = api_key
        self.base_url = base_url
        self.api_key_env = api_key_env
        self._client: Any = None
        self._aclient: Any = None

    def _client_kwargs(self, client_class) -> dict:
        """Build ordinary SDK options without ambient OpenAI tenant headers."""
        if self.base_url is None:
            legacy_endpoint_vars = [
                name
                for name in _LEGACY_ENDPOINT_ENV_VARS
                if os.getenv(name, "").strip()
            ]
            if legacy_endpoint_vars:
                names = ", ".join(legacy_endpoint_vars)
                raise ValueError(
                    f"Legacy endpoint environment settings are no longer supported: {names}. "
                    "Configure base_url and api_key_env on the Chat or in "
                    "its YAML. For ordinary global OpenAI SDK configuration, use "
                    "OPENAI_BASE_URL."
                )
        kwargs = {}
        if self._api_key is not None:
            kwargs["api_key"] = self._api_key
        if self.base_url is not None:
            kwargs["base_url"] = self.base_url
            supported = inspect.signature(client_class).parameters
            for name in ("organization", "project"):
                if name in supported:
                    kwargs[name] = openai.Omit()
            if "default_headers" in supported:
                # OpenAI 3.x merges OPENAI_CUSTOM_HEADERS into every ordinary
                # client. A per-Chat custom endpoint must not inherit headers
                # intended for another provider; its named key stays explicit.
                headers = {}
                for line in os.getenv("OPENAI_CUSTOM_HEADERS", "").splitlines():
                    name, separator, _ = line.partition(":")
                    if separator and name.strip():
                        headers[name.strip()] = openai.Omit()
                if self._api_key is not None:
                    headers["Authorization"] = f"Bearer {self._api_key}"
                kwargs["default_headers"] = headers
        return kwargs

    @property
    def client(self):
        """Return the sync SDK client, constructing it on first use."""
        if self._client is None:
            self._client = openai.OpenAI(**self._client_kwargs(openai.OpenAI))
        return self._client

    @client.setter
    def client(self, value):
        self._client = value

    @property
    def aclient(self):
        """Return the async SDK client, constructing it on first use."""
        if self._aclient is None:
            self._aclient = openai.AsyncOpenAI(
                **self._client_kwargs(openai.AsyncOpenAI)
            )
        return self._aclient

    @aclient.setter
    def aclient(self, value):
        self._aclient = value

    @property
    def _has_opened_clients(self) -> bool:
        """Return whether this binding currently owns an SDK client object."""
        return self._client is not None or self._aclient is not None

    def _clone_binding(self) -> "AiClient":
        """Create an independent lazy owner with this binding's resolved key."""
        api_key = self._api_key
        if api_key is None:
            for opened_client in (self._client, self._aclient):
                resolved_key = getattr(opened_client, "api_key", None)
                if isinstance(resolved_key, str) and resolved_key:
                    api_key = resolved_key
                    break
        return AiClient(
            api_key=api_key,
            base_url=self.base_url,
            api_key_env=self.api_key_env,
        )

    @property
    def api_key(self) -> Optional[str]:
        return self._api_key if self._api_key is not None else os.getenv("OPENAI_API_KEY")

    @api_key.setter
    def api_key(self, value):
        self._api_key = value
        if self._aclient is not None:
            self._aclient.api_key = value
        if self._client is not None:
            self._client.api_key = value

    def upload_file(self, file_path: str, purpose: str = "assistants") -> str:
        """Upload a local file via the OpenAI Files API (synchronous).

        Returns the ``file_id`` string from the created file object.
        """
        with open(file_path, "rb") as file_handle:
            result = self.client.files.create(file=file_handle, purpose=purpose)
        return result.id

    async def upload_file_async(self, file_path: str, purpose: str = "assistants") -> str:
        """Upload a local file via the OpenAI Files API (asynchronous).

        Returns the ``file_id`` string from the created file object.
        """
        with open(file_path, "rb") as file_handle:
            result = await self.aclient.files.create(file=file_handle, purpose=purpose)
        return result.id

    async def download_container_file_async(self, container_id: str, file_id: str) -> bytes:
        """Download bytes from one authenticated code interpreter container file."""
        result = await self.aclient.containers.files.content.retrieve(
            file_id,
            container_id=container_id,
        )
        content = getattr(result, "content", None)
        if isinstance(content, (bytes, bytearray)):
            return bytes(content)
        reader = getattr(result, "read", None)
        if callable(reader):
            content = reader()
            if inspect.isawaitable(content):
                content = await content
            if isinstance(content, (bytes, bytearray)):
                return bytes(content)
        raise TypeError("Container file download did not return bytes.")

    @staticmethod
    def _supports_responses_endpoint(client_or_class) -> bool:
        responses = getattr(client_or_class, "responses", None)
        create = getattr(responses, "create", None) if responses is not None else None
        return callable(create) or hasattr(responses, "__get__")

    def ensure_responses_support(self) -> None:
        """Check the Responses SDK surface without opening lazy clients."""
        sync_target = self._client if self._client is not None else openai.OpenAI
        async_target = self._aclient if self._aclient is not None else openai.AsyncOpenAI
        sync_supported = self._supports_responses_endpoint(sync_target)
        async_supported = self._supports_responses_endpoint(async_target)
        if sync_supported and async_supported:
            return

        missing = []
        if not sync_supported:
            missing.append("client.responses.create")
        if not async_supported:
            missing.append("aclient.responses.create")

        raise RuntimeError(
            "Responses runtime requires OpenAI clients with Responses endpoints. Missing: "
            + ", ".join(missing)
            + ". Upgrade the `openai` package to >=3.5.0 and/or inject compatible clients."
        )

    def close(self) -> None:
        """Close any SDK clients that were opened."""
        if self._aclient is not None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                pass
            else:
                raise RuntimeError("Use await close_a() inside an event loop.")
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._aclient is not None:
            result = self._aclient.close()
            if inspect.isawaitable(result):
                asyncio.run(result)
            self._aclient = None

    async def close_a(self) -> None:
        """Close any opened sync and async SDK clients from async code."""
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._aclient is not None:
            result = self._aclient.close()
            if inspect.isawaitable(result):
                await result
            self._aclient = None
