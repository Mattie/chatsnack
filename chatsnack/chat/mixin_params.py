
from typing import Dict, List, Optional

from datafiles import datafile

@datafile
class ChatParams:
    engine: str = "gpt-3.5-turbo"
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = None
    stream: Optional[bool] = None
    stop: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None

    def _get_non_none_params(self):
        """ Returns a dictionary of non-None parameters """
        # get a list of dataclass fields
        fields = [field.name for field in self.__dataclass_fields__.values()]
        out = {field: getattr(self, field) for field in fields if getattr(self, field) is not None}
        if "engine" not in out or len(out["engine"]) < 2:
            out["engine"] = "gpt-3.5-turbo"
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
        print(self.params.temperature)
        return self.params.temperature
    @temperature.setter
    def temperature(self, value):
        if self.params is None:
            self.params = ChatParams()
        self.params.temperature = value

