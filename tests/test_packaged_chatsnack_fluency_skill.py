from importlib.resources import files

from chatsnack.packs.snackpacks import ChatsnackHelper_default_system_message


def test_packaged_chatsnack_fluency_skill_resource_exists():
    skill_file = files("chatsnack.skills").joinpath(
        "chatsnack-fluency",
        "SKILL.md",
    )

    assert skill_file.is_file()
    text = skill_file.read_text(encoding="utf-8")
    assert "name: chatsnack-fluency" in text
    assert "YAML-first" in text


def test_packaged_chatsnack_fluency_atlas_resource_exists():
    atlas_file = files("chatsnack.skills").joinpath(
        "chatsnack-fluency",
        "references",
        "pattern-atlas.md",
    )

    assert atlas_file.is_file()
    text = atlas_file.read_text(encoding="utf-8")
    assert "Agentic Coding Prompt Builder" in text
    assert "Custom Agentic DM" in text


def test_chatsnack_help_includes_escaped_fluency_guidance():
    message = ChatsnackHelper_default_system_message

    assert "Chatsnack fluency guidance:" in message
    assert "chatsnack-fluency" in message
    assert "{{text.System}}" in message
    assert "{{chat.SceneSeed}}" in message
