
import re 
from typing import Optional, List

from datafiles import datafile


@datafile
class ChatParams:
    """
    Engine/query parameters for the chat prompt. See OpenAI documentation for most of these. ⭐
    """
    engine: str = "gpt-3.5-turbo"  #: The engine to use for generating responses, typically 'gpt-3.5-turbo' or 'gpt-4'.
    temperature: Optional[float] = None  #: Controls randomness in response generation. Higher values (e.g., 1.0) yield more random responses, lower values (e.g., 0) make the output deterministic.
    top_p: Optional[float] = None  #: Controls the proportion of tokens considered for response generation. A value of 1.0 considers all tokens, lower values (e.g., 0.9) restrict the token set.
    n: Optional[int] = None  #: Number of responses to generate for each prompt.
    stream: Optional[bool] = None  #: If True, responses are streamed as they are generated. (not implemented yet)
    stop: Optional[List[str]] = None  #: List of strings that, if encountered, stop the generation of a response.
    max_tokens: Optional[int] = None  #: Maximum number of tokens allowed in a generated response.
    presence_penalty: Optional[float] = None  #: Penalty applied to tokens based on presence in the input.
    frequency_penalty: Optional[float] = None  #: Penalty applied to tokens based on their frequency in the response.

    # Azure-specific parameters
    deployment: Optional[str] = None  #: The deployment ID to use for this request (e.g. for Azure)
    api_type: Optional[str] = None  #: The API type to use for this request (e.g. 'azure' or 'azure_ad')
    api_base: Optional[str] = None  #: The base URL to use for this request (e.g. for Azure)
    api_version: Optional[str] = None  #: The API version to use for this request (e.g. for Azure)
    api_key_env: Optional[str] = None  #: The environment variable name to use for the API key (e.g. for Azure)
    
    response_pattern: Optional[str] = None # regex pattern to capture subset of response to return (ignore the rest)

    def _get_non_none_params(self):
        """ Returns a dictionary of non-None parameters for the OpenAI API"""
        # get a list of dataclass fields
        fields = [field.name for field in self.__dataclass_fields__.values()]
        out = {field: getattr(self, field) for field in fields if getattr(self, field) is not None}
        if "engine" not in out or len(out["engine"]) < 2:
            out["engine"] = "gpt-3.5-turbo"
        # TODO response_pattern maybe should live elsewhere but for now just exclude it for the API
        if "response_pattern" in out:
            del out["response_pattern"]
        return out


# Define the Chat Configuration mixin
class ChatParamsMixin:
    # make an engine property that allows set/get
    @property
    def engine(self):
        """
        Returns the engine for this chat prompt, typically 'gpt-3.5-turbo'
         or 'gpt-4'. ⭐
        """
        if self.params is None:
            self.params = ChatParams()
        return self.params.engine
    @engine.setter
    def engine(self, value):
        if self.params is None:
            self.params = ChatParams()
        self.params.engine = value
    @property
    def temperature(self):
        if self.params is None:
            self.params = ChatParams()
        return self.params.temperature
    @temperature.setter
    def temperature(self, value):
        if self.params is None:
            self.params = ChatParams()
        self.params.temperature = value
    @property
    def pattern(self):
        # if no pattern, return None
        if self.params is None:
            return None
        return self.params.response_pattern
    @pattern.setter
    def pattern(self, value):
        if self.params is None:
            self.params = ChatParams()
        self.params.response_pattern = value
    # same thing for streaming
    @property
    def stream(self):
        if self.params is None:
            return False # default to False
        else:
            return self.params.stream
    @stream.setter
    def stream(self, value: bool):
        if self.params is None:
            self.params = ChatParams()
        self.params.stream = value
    def set_response_filter(self, prefix: Optional[str] = None, suffix: Optional[str] = None, pattern: Optional[str] = None):
        """ Filters the response given prefix and suffix or pattern. If suffix is None, it is set to the same as prefix. 
         Note that this overwrites any existing regex pattern. ⭐ """
        # if pattern is set then fail if they provided prefix or suffix
        if pattern:
            if prefix or suffix:
                raise ValueError("Cannot set both pattern and prefix/suffix")
            self.pattern = pattern
            return
        self.pattern = ChatParamsMixin._generate_pattern_from_separator(prefix, suffix)
    def _generate_pattern_from_separator(prefix: str, suffix: Optional[str] = None) -> str:
        # Escape special characters in prefix and suffix
        prefix = re.escape(prefix)
        if suffix:
            suffix = re.escape(suffix)
        else:
            suffix = prefix
        # Generate regex pattern
        pattern = rf"{prefix}(.*?)(?:{suffix}|$)"
        return pattern
    def filter_by_pattern(self, text: str) -> Optional[str]:
        """ Filters the response given a regex pattern.  """
        if self.pattern is None:
            return text
        return ChatParamsMixin._search_pattern(self.pattern, text)
    def _search_pattern(pattern: str, text: str) -> Optional[str]:
        matches = re.finditer(pattern, text, re.DOTALL)

        try:
            first_match = next(matches)
        except StopIteration:
            return None

        if len(first_match.groups()) > 0:
            return first_match.group(1)  # Return the first capturing group
        else:
            return first_match.group()  # Return the full matched text


