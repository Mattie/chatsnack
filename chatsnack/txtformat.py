from typing import Dict

from snapclass import formatters


class TxtStrFormat(formatters.FileFormatter):
    """Formatter for raw .txt prompt assets edited directly on disk."""

    extensions = {".txt"}

    @classmethod
    def dumps(cls, data: Dict) -> str:
        # Support only strings
        _supported_types = [str]
        # Convert `data` to a string
        output = ""
        for k, v in data.items():
            if type(v) in _supported_types:
                output += str(v)
            else:
                raise ValueError("Unsupported type: {}".format(type(v)))
        return output

    @classmethod
    def loads(cls, text: str) -> Dict:
        return {"content": text}

    @classmethod
    def serialize(cls, data: Dict) -> str:
        return cls.dumps(data)

    @classmethod
    def deserialize(cls, file_object) -> Dict:
        return cls.loads(file_object.read())

def register_txt_datafiles():
    """Compatibility no-op; snapclass formatters are attached per model."""
    return None
