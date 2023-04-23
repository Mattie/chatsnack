import pytest
from chatsnack.chat import Text
from chatsnack.txtformat import TxtStrFormat

@pytest.fixture
def empty_text():
    return Text(name="empty-text", content="")

@pytest.fixture
def populated_text():
    return Text(name="populated-text", content="Hello, world!")

def test_create_text(empty_text):
    assert empty_text.name == "empty-text"
    assert empty_text.content == ""

def test_create_populated_text(populated_text):
    assert populated_text.name == "populated-text"
    assert populated_text.content == "Hello, world!"

def test_txt_str_format_serialize():
    data = {"content": "Hello, world!"}
    serialized_data = TxtStrFormat.serialize(data)

    assert serialized_data == "Hello, world!"

def test_txt_str_format_serialize_unsupported_type():
    data = {"content": ["Invalid", "content", "type"]}

    with pytest.raises(ValueError):
        TxtStrFormat.serialize(data)

# def test_txt_str_format_deserialize(populated_text):
#     datafile = DataFile.load(populated_text.datafile.path)
#     deserialized_data = TxtStrFormat.deserialize(datafile.file)

#     assert deserialized_data == {"content": "Hello, world!"}

# def test_txt_str_format_deserialize_empty(empty_text):
#     datafile = DataFile.load(empty_text.datafile.path)
#     deserialized_data = TxtStrFormat.deserialize(datafile.file)

#     assert deserialized_data == {"content": ""}
