import json
from pathlib import Path

from snapclass import Stash


def _stash_for_path(path):
    if path is None:
        return None
    return Stash(Path(path).parent)


def _set_lookup_stash(owner, path):
    stash = _stash_for_path(path)
    if stash is not None:
        owner._snapshot_lookup_stash = stash


def _set_lookup_stash_from_snapshot(owner, snapshot=None, path=None):
    if path is not None:
        _set_lookup_stash(owner, path)
        return
    snapshot = snapshot or getattr(owner, "snapshot", None)
    snapshot_path = getattr(snapshot, "path", None) if snapshot is not None else None
    if snapshot_path is not None:
        _set_lookup_stash(owner, snapshot_path)


def _refresh_after_snapshot_load(owner):
    # Loading YAML replaces persisted fields such as params/messages. Chat also
    # has live state derived from those fields (runtime, reset baselines, tools),
    # so every explicit load path needs a post-load refresh.
    refresh = getattr(owner, "_refresh_after_snapshot_load", None)
    if refresh is None:
        refresh = getattr(owner, "_after_legacy_autoload", None)
    if refresh is not None:
        refresh()


def _refresh_snapshot_stash(owner):
    snapshot = getattr(owner, "snapshot", None)
    if snapshot is None:
        return
    stash = snapshot.stash
    if stash is not None:
        # snapclass stashes cache their resolved path. chatsnack's default root
        # is intentionally cwd-relative, so refresh before path-sensitive work
        # to preserve import-then-chdir notebook/test workflows.
        snapshot._stash = stash.refresh()


def refresh_snapclass_config_stash(cls):
    """Refresh a model stash before snapclass resolves a new snapshot path."""
    config = getattr(cls, "__snapclass_config__", None)
    stash = getattr(config, "stash", None)
    if stash is not None:
        # snapclass 0.1.2 rejects lifecycle hooks that change snapshot paths.
        # Refresh env/cwd-sensitive stashes before object construction or
        # explicit save/load instead of doing it inside ready/loaded hooks.
        config.stash = stash.refresh()


class DatafileProxy:
    """Compatibility wrapper exposing the old datafiles-style object API."""

    def __init__(self, owner):
        self._owner = owner

    @property
    def _snapshot(self):
        return self._owner.snapshot

    @property
    def path(self):
        return self._snapshot.path

    @path.setter
    def path(self, value):
        self._snapshot.path = Path(value)
        _set_lookup_stash(self._owner, value)

    @property
    def relpath(self):
        return self._snapshot.relpath

    @property
    def text(self):
        return self._snapshot.text

    @text.setter
    def text(self, value):
        self._snapshot.text = value

    @property
    def exists(self):
        return self._snapshot.exists

    @property
    def modified(self):
        return self._snapshot.modified

    def save(self, path=None):
        _refresh_snapshot_stash(self._owner)
        _set_lookup_stash(self._owner, path)
        self._snapshot.save(path)
        _set_lookup_stash_from_snapshot(self._owner)

    def load(self, path=None):
        _refresh_snapshot_stash(self._owner)
        _set_lookup_stash(self._owner, path)
        self._snapshot.load(path)

class DatafileMixin:
    @property
    def datafile(self):
        return DatafileProxy(self)

    @property
    def snapshot_lookup_stash(self):
        _refresh_snapshot_stash(self)
        stash = getattr(self, "_snapshot_lookup_stash", None)
        if stash is not None:
            return stash
        snapshot = getattr(self, "snapshot", None)
        snapshot_path = getattr(snapshot, "path", None) if snapshot is not None else None
        if snapshot_path is not None:
            return _stash_for_path(snapshot_path)
        return snapshot.stash if snapshot is not None else None

    def __snapclass_ready__(self, *, snapshot):
        """Refresh path-sensitive live state after snapclass attaches a snapshot."""
        _set_lookup_stash_from_snapshot(self, snapshot)
        ready = getattr(self, "_ready_after_snapshot_attached", None)
        if ready is not None:
            ready()

    def __snapclass_loaded__(self, *, snapshot, path):
        """Refresh compatibility and live state after snapclass applies file data."""
        _set_lookup_stash_from_snapshot(self, snapshot, path)
        _refresh_after_snapshot_load(self)

    def _install_snapshot_compat_hooks(self):
        # snapclass 0.1.2 owns snapshot lifecycle hooks. This method remains so
        # older chatsnack internals can call it without reintroducing monkey
        # patching around snapshot.load().
        return None

    def _refresh_snapshot_stash(self):
        _refresh_snapshot_stash(self)

    def save(self, path: str = None):
        """Persist the current snapshot-backed object to disk."""
        _refresh_snapshot_stash(self)
        _set_lookup_stash(self, path)
        self.snapshot.save(path)
        _set_lookup_stash_from_snapshot(self)

    def load(self, path: str = None):
        """Load the object from disk, optionally from an explicit path."""
        _refresh_snapshot_stash(self)
        _set_lookup_stash(self, path)
        self.snapshot.load(path)

# Define the Data Serialization mixin
class ChatSerializationMixin(DatafileMixin):
    @property
    def json(self) -> str:
        """Return the expanded chat messages as JSON for API submission."""
        return json.dumps(self.get_messages())
    
    @property
    def json_unexpanded(self) -> str:
        """Return the chat messages as JSON before include expansion."""
        return json.dumps(self.get_messages(includes_expanded=False))

    @property
    def yaml(self) -> str:
        """ Returns the chat prompt as a yaml string ⭐"""
        return self.snapshot.text
    
    # def _messages_to_yaml(self, messages, expand_includes=True):
    #     """Converts messages to a list for YAML serialization"""
    #     result = []
        
    #     for message in messages:
    #         # Each message is a dict with a single key (the role)
    #         for role, content in message.items():
    #             if role == "include" and expand_includes:
    #                 # This is a reference to another named file, we need to load it
    #                 include_chat = self.objects.get_or_none(content)
    #                 if include_chat is None:
    #                     # Can't expand, just add as is
    #                     result.append({role: content})
    #                 else:
    #                     # We got a chat object, add all its messages
    #                     result.extend(include_chat._messages_to_yaml(include_chat.messages))
    #             elif role == "assistant" and isinstance(content, dict) and "tool_calls" in content:
    #                 # Format tool calls for YAML serialization
    #                 result.append({
    #                     role: {
    #                         "tool_calls": [
    #                             {
    #                                 "name": tool_call.get("name", ""),
    #                                 "arguments": tool_call.get("arguments", {})
    #                             }
    #                             for tool_call in content["tool_calls"]
    #                         ]
    #                     }
    #                 })
    #             else:
    #                 # Add the message as is
    #                 result.append({role: content})
        
    #     return result
    
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

