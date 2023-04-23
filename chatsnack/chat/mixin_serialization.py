import json
from pathlib import Path

class DatafileMixin:
    def save(self, path: str = None):
        """ Saves the text to disk """
        # path is a cached property so we're going to delete it so it'll get recalculated
        del self.datafile.path
        if path is not None:
            self.datafile.path = Path(path)
        self.datafile.save()
    def load(self, path: str = None):
        """ Loads the chat prompt from a file, can load from a new path but it won't work with snack expansion/vending """
        # path is a cached property so we're going to delete it so it'll get recalculated
        del self.datafile.path
        if path is not None:
            self.datafile.path = Path(path)
        self.datafile.load()

# Define the Data Serialization mixin
class ChatSerializationMixin(DatafileMixin):
    @property
    def json(self) -> str:
        """ Returns the flattened JSON for use in the API"""
        return json.dumps(self.get_messages())
    
    @property
    def json_unexpanded(self) -> str:
        """ Returns the unflattened JSON for use in the API"""
        return json.dumps(self.get_messages(includes_expanded=False))

    @property
    def yaml(self) -> str:
        """ Returns the chat prompt as a yaml string ⭐"""
        return self.datafile.text

    def generate_markdown(self, wrap=80) -> str:
        """ Returns the chat prompt as a markdown string ⭐"""
        # TODO convert this to a template file so people can change it
        # convert the chat conversation to markdown
        markdown_lines = []
        def md_quote_text(text, wrap=wrap):
            import textwrap
            if text is None:
                return ">  "            
            text = text.strip()
            # no line in the text should be longer than 80 characters
            for i, line in enumerate(text.splitlines()):
               if len(line) > wrap:
                   text = text.replace(line, textwrap.fill(line, wrap))
            # we want the text in a blockquote, including empty lines
            text = textwrap.indent(text, "> ")
            # append "  " to the end of each line so they show up in markdown
            # replace empty lines with '> \n' so they show up in markdown
            text = text.replace("\n\n", "\n> \n")
            text = text.replace("\n", "  \n")
            return text
        system_message = self.system_message
        markdown_lines.append(f"# Bot Chat Log")
        markdown_lines.append(f"## Bot Information")
        markdown_lines.append(f"**Name**: {self.name}")
        markdown_lines.append(f"**Engine**: {self.engine}")
        markdown_lines.append(f"**Primary Directive**:")
        markdown_lines.append(md_quote_text(system_message))
        markdown_lines.append(f"## Conversation")
        for _message in self.messages:
            message = self._msg_dict(_message)
            for role, text in message.items():
                if role == "system":
                    continue
                text = md_quote_text(text)
                emoji = "🤖" if role == "assistant" else "👤"
                markdown_lines.append(f"{emoji} **{role.capitalize()}:**\n{text}")
        markdown_text = "\n\n".join(markdown_lines)
        return markdown_text

