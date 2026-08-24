import os

import pytest

from chatsnack import Chat, utensil


_RUN_LIVE = os.environ.get("CHATSNACK_RUN_LIVE_TESTS", "").lower() in {"1", "true", "yes"}


@pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None or not _RUN_LIVE,
    reason="Live OpenAI tests require OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1",
)
def test_live_code_interpreter_generated_file_surfaces_on_chat_files(tmp_path, monkeypatch):
    """A real container file citation is captured before the chat returns."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path / "chatsnack-data"))
    analyst = Chat(
        "Always use code interpreter to create requested files.",
        model="gpt-5.4",
        utensils=[utensil.code_interpreter],
    )

    try:
        report = analyst.chat(
            "Create a CSV file named live_snack_inventory.csv with columns snack and score, "
            "containing popcorn,9 and pretzels,8. Provide the CSV as a downloadable file."
        )
        csv_file = next(item for item in report.files if item.filename == "live_snack_inventory.csv")

        assert csv_file.captured
        assert csv_file.path.is_file()
        assert "files:" in report.yaml
        assert b"popcorn" in csv_file.read_bytes().lower()
        assert b"pretzels" in csv_file.read_bytes().lower()
    finally:
        analyst.close_session()


@pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None or not _RUN_LIVE,
    reason="Live OpenAI tests require OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1",
)
def test_live_gpt_image_2_surfaces_on_chat_images(tmp_path, monkeypatch):
    """A real GPT Image 2 result becomes one local ChatFile."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path / "chatsnack-data"))
    artist = Chat(
        "Always use image generation for image requests.",
        model="gpt-5.4",
        utensils=[utensil.image_generation(model="gpt-image-2", quality="low")],
    )

    try:
        drawing = artist.chat("Draw a tiny smiling red apple on a plain cream background.")
        image = drawing.images[0]

        assert image.captured
        assert image.filename.endswith((".png", ".jpg", ".webp"))
        assert image.read_bytes()
        assert drawing.files == drawing.images
        assert "asset:" in drawing.yaml
    finally:
        artist.close_session()
