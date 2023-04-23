# Cataclysm Note: Replaces the default datafiles YAML formatter with our own version, this
# is solely for a cleaner yaml file format for source code with the "key: |" format

# Yaml format class is taken from https://github.com/jacebrowning/datafiles  formats.py
# The MIT License (MIT)
# Copyright © 2018, Jace Browning
# Permission is hereby granted, free of charge, to any person obtaining a copy of this 
# software and associated documentation files (the "Software"), to deal in the Software 
# without restriction, including without limitation the rights to use, copy, modify, 
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to 
# permit persons to whom the Software is furnished to do so, subject to the following conditions:
# The above copyright notice and this permission notice shall be included in all copies or 
# substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY 
# OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF 
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL 
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, 
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION 
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
from io import StringIO
import log
from typing import IO, Dict, List, Union
import dataclasses
from datafiles import formats, types
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
from ruamel.yaml import YAML as _YAML

class YAML(formats.Formatter):
    """Formatter for (round-trip) YAML Ain't Markup Language."""

    @classmethod
    def extensions(cls):
        return {"", ".yml", ".yaml"}

    @classmethod
    def deserialize(cls, file_object):
        from ruamel.yaml import YAML as _YAML

        yaml = _YAML()
        yaml.preserve_quotes = True  # type: ignore
        try:
            return yaml.load(file_object)
        except NotImplementedError as e:
            log.error(str(e))
            return {}

    @classmethod
    def serialize(cls, data):
        # HACK: to remove None values from the data and make the yaml file cleaner
        def filter_none_values(data: Union[Dict, List]):
            if isinstance(data, dict):
                # this code worked for None values, but not really for optional default values like I want :()
                return {k: filter_none_values(v) for k, v in data.items() if v is not None}
            elif isinstance(data, list):
                return [filter_none_values(v) for v in data]
            else:
                return data
        data = filter_none_values(data)

        yaml = _YAML()

        # Define custom string representation function
        def represent_plain_str(dumper, data):
            if "\n" in data or "\r" in data or "#" in data or ":" in data or "'" in data or '"' in data:
                return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='|')
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='')

        # Configure the library to use plain style for dictionary keys
        yaml.representer.add_representer(str, represent_plain_str)


        yaml.default_style = "|"  # support the cleaner multiline format for source code blocks
        yaml.register_class(types.List)
        yaml.register_class(types.Dict)

        yaml.indent(mapping=2, sequence=4, offset=2)

        stream = StringIO()
        yaml.dump(data, stream)
        text = stream.getvalue()

        if text.startswith("  "):
            return text[2:].replace("\n  ", "\n")

        if text == "{}\n":
            return ""

        return text.replace("- \n", "-\n")

def register_yaml_datafiles():
    # replace with our own version of 
    formats.register(".yml", YAML)