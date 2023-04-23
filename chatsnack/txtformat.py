from datafiles import formats
from typing import IO, Dict, List

class TxtStrFormat(formats.Formatter):
    """Special formatter to use with strings and .txt datafiles for a convenient raw text format for easy document editing on disk."""

    @classmethod
    def extensions(cls) -> List[str]:
        return ['.txt']

    @classmethod
    def serialize(cls, data: Dict) -> str:
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
    def deserialize(cls, file_object: IO) -> Dict:
        # Read the entire content of the file
        file_object = open(file_object.name, 'r', encoding='utf-8')
        content = file_object.read()

        # Create an output dictionary with a single key-value pair
        output = {'content': content}
        return output

def register_txt_datafiles():
    # this format class only works with strings
    formats.register('.txt', TxtStrFormat)