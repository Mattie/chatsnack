import os
import subprocess
import sys
import textwrap
from uuid import uuid4

import pytest
from snapclass import Stash

from chatsnack import Chat, ChatParams, Text


def test_datafile_proxy_and_objects_manager_preserve_legacy_access(tmp_path):
    text_path = tmp_path / "LegacyText.txt"
    text = Text(name="LegacyText", content="line one\nline two\n")
    text.save(text_path)

    assert text.datafile.path == text_path
    assert text.snapshot.path == text_path
    assert text.datafile.text == "line one\nline two\n"

    loaded_text = Text(name="Other")
    loaded_text.datafile.load(text_path)
    assert loaded_text.content == "line one\nline two\n"

    chat_path = tmp_path / "LegacyChat.yml"
    chat = Chat(name="LegacyChat")
    chat.system("Respond tersely.")
    chat.user("Hello")
    chat.datafile.save(chat_path)

    loaded_chat = Chat(name="LegacyChat")
    loaded_chat.datafile.load(chat_path)
    assert loaded_chat.system_message == "Respond tersely."
    assert loaded_chat.datafile.text == loaded_chat.snapshot.text


def test_objects_manager_returns_initialized_chat(tmp_path):
    chat = Chat(name="ObjectsCompat")
    chat.system("Use the saved prompt.")
    chat.save(tmp_path / "ObjectsCompat.yml")

    loaded = Chat.objects(tmp_path).get("ObjectsCompat")

    assert loaded.system_message == "Use the saved prompt."
    assert hasattr(loaded, "ai")
    assert hasattr(loaded, "runtime")


def test_native_snapshots_return_initialized_chat_when_lifecycle_hooks_are_available(tmp_path):
    chat = Chat(
        name="NativeLifecycle",
        params=ChatParams(runtime="chat_completions"),
    )
    chat.system("Use the saved prompt.")
    chat.save(tmp_path / "NativeLifecycle.yml")

    loaded = Chat.snapshots(Stash(tmp_path)).get("NativeLifecycle")

    assert loaded.system_message == "Use the saved prompt."
    assert hasattr(loaded, "ai")
    assert type(loaded.runtime).__name__ == "ChatCompletionsAdapter"
    loaded.system("Changed")
    loaded.reset()
    assert loaded.system_message == "Use the saved prompt."

    created = Chat.snapshots(Stash(tmp_path)).get_or_create("CreatedLifecycle")
    assert hasattr(created, "ai")
    assert hasattr(created, "runtime")
    created.reset()


def test_named_chat_autoloads_before_applying_live_constructor_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATSNACK_BASE_DIR", os.fspath(tmp_path))

    saved = Chat(
        name="NamedRuntimeCompat",
        params=ChatParams(model="saved-model", runtime="chat_completions"),
    )
    saved.system("Load this from disk.")
    saved.save()

    loaded = Chat(
        name="NamedRuntimeCompat",
        model="override-model",
        runtime="chat_completions",
    )

    assert loaded.system_message == "Load this from disk."
    assert loaded.model == "override-model"
    assert type(loaded.runtime).__name__ == "ChatCompletionsAdapter"
    loaded.reset()
    assert loaded.system_message == "Load this from disk."
    assert loaded.model == "override-model"


def test_explicit_load_refreshes_runtime_from_loaded_params(tmp_path):
    chat_path = tmp_path / "RuntimeCompat.yml"
    chat = Chat(
        name="RuntimeCompat",
        params=ChatParams(runtime="chat_completions"),
    )
    chat.system("Use the runtime in YAML.")
    chat.save(chat_path)

    loaded = Chat(name="RuntimeCompat")
    loaded.load(chat_path)
    assert loaded.params.runtime == "chat_completions"
    assert type(loaded.runtime).__name__ == "ChatCompletionsAdapter"

    datafile_loaded = Chat(name="RuntimeCompat")
    datafile_loaded.datafile.load(chat_path)
    assert datafile_loaded.params.runtime == "chat_completions"
    assert type(datafile_loaded.runtime).__name__ == "ChatCompletionsAdapter"

    snapshot_loaded = Chat(name="RuntimeCompat")
    snapshot_loaded.snapshot.load(chat_path)
    assert snapshot_loaded.params.runtime == "chat_completions"
    assert type(snapshot_loaded.runtime).__name__ == "ChatCompletionsAdapter"

    text_loaded = Chat(name="RuntimeTextCompat")
    text_loaded.datafile.path = tmp_path / "RuntimeTextCompat.yml"
    text_loaded.datafile.text = chat.snapshot.text
    assert text_loaded.params.runtime == "chat_completions"
    assert type(text_loaded.runtime).__name__ == "ChatCompletionsAdapter"


def test_default_base_dir_remains_cwd_relative_after_import(tmp_path):
    text_name = f"CwdText{uuid4().hex}"
    script = textwrap.dedent(
        f"""
        import os
        from pathlib import Path
        from chatsnack import CHATSNACK_BASE_DIR, Text

        original = Path.cwd()
        target = Path({os.fspath(tmp_path)!r})
        os.chdir(target)
        try:
            assert Path(CHATSNACK_BASE_DIR) == Path("datafiles/chatsnack")
            Text(name={text_name!r}, content="from cwd").save()
            assert Path("datafiles/chatsnack/{text_name}.txt").read_text() == "from cwd"
            assert not (original / "datafiles/chatsnack/{text_name}.txt").exists()
            print("ok")
        finally:
            os.chdir(original)
        """
    )

    env = os.environ.copy()
    env.pop("CHATSNACK_BASE_DIR", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=os.getcwd(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.strip() == "ok"


def test_explicit_path_load_resolves_sibling_includes_and_fillings(tmp_path):
    Text(name="SiblingVoice", content="from sibling text").save(tmp_path / "SiblingVoice.txt")
    Chat(name="SiblingInclude").system("from sibling include").save(tmp_path / "SiblingInclude.yml")

    chat_path = tmp_path / "SiblingParent.yml"
    parent = Chat(name="SiblingParent")
    parent.system("{text.SiblingVoice}")
    parent.include("SiblingInclude")
    parent.save(chat_path)

    loaded = Chat(name="SiblingParent")
    loaded.load(chat_path)

    messages = loaded.get_messages()
    assert {"role": "system", "content": "{text.SiblingVoice}"} in messages
    assert {"role": "system", "content": "from sibling include"} in messages
    assert "from sibling text" in loaded._run_sync(loaded._build_final_prompt(), "_build_final_prompt")


def test_chatsnack_base_dir_env_is_resolved_by_stash(tmp_path):
    env = os.environ.copy()
    env["CHATSNACK_BASE_DIR"] = os.fspath(tmp_path)
    script = textwrap.dedent(
        """
        from pathlib import Path
        from chatsnack import CHATSNACK_BASE_DIR, CHATSNACK_PROMPTS, Text

        assert Path(CHATSNACK_BASE_DIR) == Path(CHATSNACK_PROMPTS.path)
        text = Text(name="EnvText", content="from env")
        text.save()
        assert Path(CHATSNACK_BASE_DIR, "EnvText.txt").read_text() == "from env"
        print("ok")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=os.getcwd(),
        check=True,
        text=True,
        capture_output=True,
    )

    assert result.stdout.strip() == "ok"
