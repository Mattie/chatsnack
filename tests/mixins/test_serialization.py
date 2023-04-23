import pytest
from chatsnack import Chat

class TestChatSerializationMixin:
    @pytest.fixture
    def chat(self):
        return Chat()
    
    def test_json(self, chat):
        assert isinstance(chat.json, str)
    
    def test_json_unexpanded(self, chat):
        assert isinstance(chat.json_unexpanded, str)
        
    def test_yaml(self, chat):
        assert isinstance(chat.yaml, str)
        
    def test_generate_markdown(self, chat):
        markdown = chat.generate_markdown()
        assert isinstance(markdown, str)
        assert len(markdown.split('\n')) > 0
