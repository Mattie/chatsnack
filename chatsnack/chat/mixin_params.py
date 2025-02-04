import re
from typing import Optional, List
from datafiles import datafile


@datafile
class ChatParams:
    """
    Engine/query parameters for the chat prompt. See OpenAI documentation for most of these. ⭐
    """
    model: str = "gpt-4-turbo"  #: The engine to use for generating responses, typically 'gpt-3.5-turbo', 'gpt-4', or 'gpt-4o'.
    engine: Optional[str] = None   #: Deprecated, use model instead
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stream: Optional[bool] = None
    stop: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    seed: Optional[int] = None
    n: Optional[int] = None

    # Azure-specific parameters
    deployment: Optional[str] = None
    api_type: Optional[str] = None
    api_base: Optional[str] = None
    api_version: Optional[str] = None
    api_key_env: Optional[str] = None

    response_pattern: Optional[str] = None  # internal usage, not passed to the API


    """
    Here is a comparison of the parameters supported by different models: (Bless your heart, OpenAI)
    | Parameter                  | o3-mini | o1  | o1-preview | o1-mini | gpt-4o/mini | gpt-4-turbo | gpt-4o-audio | chatgpt-4o |
    |---------------------------|---------|-----|------------|---------|-------------|-------------|--------------|------------|
    | messages/system *         | Yes     | Yes | No         | No      | Yes         | Yes         | Yes          | Yes        |
    | messages/developer *      | Yes     | Yes | No         | No      | Yes         | Yes         | Yes          | Yes        |
    | messages/user-images      | No      | Yes | No         | No      | Yes         | Yes         | No           | Yes        |
    | `tools` (as functions)    | Yes     | Yes | No         | No      | Yes         | Yes         | Yes          | No         |
    | `functions` (legacy)      | Yes     | Yes | No         | No      | Yes         | Yes         | Yes          | No         |
    | `response_format`-object  | Yes     | Yes | No         | No      | Yes         | Yes         | No           | Yes        |
    | `response_format`-schema  | Yes     | Yes | No         | No      | Yes         | No          | No           | No         |
    | `reasoning_effort`        | Yes     | Yes | No         | No      | No          | No          | No           | No         |
    | `max_tokens`              | No      | No  | No         | No      | Yes         | Yes         | Yes          | Yes        |
    | `max_completion_tokens`*  | Yes     | Yes | Yes        | Yes     | Yes         | Yes         | Yes          | Yes        |
    | `temperature` & `top_p`   | No      | No  | No         | No      | Yes         | Yes         | Yes          | Yes        |
    | `logprobs`                | No      | No  | No         | No      | Yes         | Yes         | No           | Yes        |
    | `xxx_penalty`             | No      | No  | No         | No      | Yes         | Yes         | Yes          | Yes        |
    | `logit_bias` (broken!)    | No      | No  | No         | No      | Yes         | Yes         | ?            | Yes        |
    | `prediction`              | No      | No  | No         | No      | Yes         | No          | No           | No         |
    | `streaming:True`          | Yes     | No  | Yes        | Yes     | Yes         | Yes         | Yes          | Yes        |
    | Cache discount            | Yes     | Yes | Yes        | Yes     | Yes         | No          | No           | No         |
    |---------------------------|---------|-----|------------|---------|-------------|-------------|--------------|------------|
    """
    def _supports_developer_messages(self) -> bool:
        """Returns True if current model supports developer messages."""
        return not ("o1-preview" in self.model or "o1-mini" in self.model)

    def _supports_system_messages(self) -> bool:
        """Returns True if current model supports system messages."""
        return not ("o1" in self.model or "o1-preview" in self.model or "o1-mini" in self.model)

    def _supports_temperature(self) -> bool:
        """Returns True if current model supports temperature."""
        return "gpt-4o" in self.model or "gpt-4-turbo" in self.model

    def _get_non_none_params(self) -> dict:
        """
        Returns a dictionary of non-None parameters to send to the ChatCompletion API.
        Converts old usage (engine, max_tokens) to new fields (model, max_completion_tokens)
        automatically for reasoning models, so clients don't have to change code.
        """
        # Gather all fields of the dataclass
        fields = [field.name for field in self.__dataclass_fields__.values()]
        out = {field: getattr(self, field) for field in fields if getattr(self, field) is not None}

        # Ensure `model` is set, falling back to `engine` if needed
        if "model" not in out or not out["model"].strip():
            if "engine" in out:  
                out["model"] = out["engine"]
            else:
                out["model"] = "chatgpt-4o-latest"

        # engine is deprecated; remove it from the final dict
        if "engine" in out:
            del out["engine"]

        # max_tokens is deprecated
        if "max_tokens" in out:
            out["max_completion_tokens"] = out["max_tokens"]
            del out["max_tokens"]


        # If model supports temperatures, remove it to avoid breakage
        if not self._supports_temperature():
            if "temperature" in out:
                out["temperature"] = None
                del out["temperature"]
        else:
            # For older GPT-3.5 or GPT-4, we keep max_tokens as-is 
            pass

        # response_pattern is for internal usage only; remove it
        if "response_pattern" in out:
            del out["response_pattern"]

        return out


class ChatParamsMixin:
    params: Optional[ChatParams] = None

    @property
    def engine(self) -> Optional[str]:
        if self.params is None:
            self.params = ChatParams()
        return self.params.engine

    @engine.setter
    def engine(self, value: str):
        if self.params is None:
            self.params = ChatParams()
        self.params.engine = value
        # also sync model to that same value
        if self.model != value:
            self.model = value

    @property
    def model(self) -> str:
        if self.params is None:
            self.params = ChatParams()
        return self.params.model

    @model.setter
    def model(self, value: str):
        if self.params is None:
            self.params = ChatParams()
        self.params.model = value

    @property
    def temperature(self) -> Optional[float]:
        if self.params is None:
            self.params = ChatParams()
        return self.params.temperature

    @temperature.setter
    def temperature(self, value: float):
        if self.params is None:
            self.params = ChatParams()
        self.params.temperature = value

    @property
    def pattern(self) -> Optional[str]:
        if not self.params:
            return None
        return self.params.response_pattern

    @pattern.setter
    def pattern(self, value: str):
        if not self.params:
            self.params = ChatParams()
        self.params.response_pattern = value

    @property
    def stream(self) -> bool:
        if not self.params:
            return False  # default to False
        return bool(self.params.stream)

    @stream.setter
    def stream(self, value: bool):
        if not self.params:
            self.params = ChatParams()
        self.params.stream = value

    def set_response_filter(
        self,
        prefix: Optional[str] = None,
        suffix: Optional[str] = None,
        pattern: Optional[str] = None
    ):
        """
        Filters the response by a given prefix/suffix or regex pattern.
        If suffix is None, it is set to the same as prefix.
        """
        if pattern and (prefix or suffix):
            raise ValueError("Cannot set both pattern and prefix/suffix")
        if pattern:
            self.pattern = pattern
        else:
            self.pattern = self._generate_pattern_from_separator(prefix, suffix)

    @staticmethod
    def _generate_pattern_from_separator(prefix: str, suffix: Optional[str] = None) -> str:
        prefix_escaped = re.escape(prefix)
        if suffix:
            suffix_escaped = re.escape(suffix)
        else:
            suffix_escaped = prefix_escaped
        # Generate a pattern capturing everything between prefix and suffix
        pattern = rf"{prefix_escaped}(.*?)(?:{suffix_escaped}|$)"
        return pattern

    def filter_by_pattern(self, text: str) -> Optional[str]:
        """
        Applies self.pattern if set, returning the first capture group match.
        """
        if not self.pattern:
            return text
        return self._search_pattern(self.pattern, text)

    @staticmethod
    def _search_pattern(pattern: str, text: str) -> Optional[str]:
        matches = re.finditer(pattern, text, re.DOTALL)
        try:
            first_match = next(matches)
        except StopIteration:
            return None
        # Return the first capturing group if present
        if len(first_match.groups()) > 0:
            return first_match.group(1)
        else:
            return first_match.group()
