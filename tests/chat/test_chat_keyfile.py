"""Chat: reading the Azure key from a file such as an RTF note (rgv_flood/chat/keyfile.py).

Every file here is made up in a temporary folder. The real key file is never touched by a test.
"""

import logging

import pytest

from rgv_flood.chat import keyfile
from rgv_flood.chat.keyfile import KeyFileError, pick_key, read_key_file, rtf_to_text
from rgv_flood.settings import Settings

FAKE = "FAKEKEY-abc123_XYZ.789~qwerty-0123456789-ABCDEFGH"  # 49 made-up characters with symbols


def rtf(body: str) -> str:
    return "{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0\\fswiss Arial;}}{\\colortbl;\\red0\\green0\\blue0;}\\f0\\fs24 " + body + "}"


# ---- turning RTF into text ----

def test_plain_text_passes_through():
    assert rtf_to_text("just a line\nanother") == "just a line\nanother"


def test_paragraphs_and_lines_become_newlines_and_formatting_is_dropped():
    text = rtf_to_text(rtf("\\b Key 1:\\b0  abc\\par second\\line third"))

    assert text.splitlines() == ["Key 1: abc", "second", "third"]


def test_font_and_color_tables_and_starred_groups_are_skipped():
    text = rtf_to_text(rtf("hello{\\*\\generator Msftedit 5.41;} world"))

    assert text.strip() == "hello world" and "Arial" not in text and "Msftedit" not in text


@pytest.mark.parametrize("source, expected", [
    ("a\\\\b", "a\\b"), ("a\\{b\\}", "a{b}"), ("caf\\'e9", "café"), ("\\u233?t", "ét"), ("a\\~b", "a b"),
    ("a\\_b", "a-b"), ("a\\-b", "ab"), ("tab\\tab x", "tab\tx"),
])
def test_escapes(source, expected):
    assert rtf_to_text(rtf(source)).strip() == expected


def test_a_hyperlink_keeps_its_visible_text():
    text = rtf_to_text(rtf('{\\field{\\*\\fldinst HYPERLINK "https://x.test"}{\\fldrslt visible}}'))

    assert text.strip() == "visible"


# ---- choosing the key out of the text ----

def test_a_lone_value_is_the_key():
    assert pick_key(FAKE + "\n") == FAKE


def test_a_labelled_key():
    assert pick_key(f"Key 1: {FAKE}") == FAKE
    assert pick_key(f"API key = {FAKE}") == FAKE


def test_endpoint_and_other_lines_are_not_mistaken_for_the_key():
    text = f"Endpoint: https://thing.cognitiveservices.azure.com/\nRegion: southcentralus\nKey 1: {FAKE}\nDeployment: gpt-4.1"

    assert pick_key(text) == FAKE


def test_key_1_is_taken_when_azure_gives_two_keys():
    """Azure issues two interchangeable keys; Key 1 is the one to use."""
    text = f"Key 2: OTHER{FAKE}\nKey 1: {FAKE}"

    assert pick_key(text) == FAKE
    assert pick_key(text, label="key 2") == "OTHER" + FAKE  # unless a label says otherwise


def test_two_unrelated_keys_need_a_label_to_choose():
    text = f"Azure OpenAI key: {FAKE}\nSpeech service key: OTHER{FAKE}"

    with pytest.raises(KeyFileError, match="more than one"):
        pick_key(text)
    assert pick_key(text, label="speech service KEY") == "OTHER" + FAKE
    assert pick_key(text, label=" Azure OpenAI key ") == FAKE


def test_a_label_that_is_not_there_is_an_error():
    with pytest.raises(KeyFileError, match="label"):
        pick_key(f"Key 1: {FAKE}", label="nope")


def test_quotes_and_spaces_around_the_value_are_removed():
    assert pick_key(f'Key 1: "{FAKE}" ') == FAKE
    assert pick_key(f"api key:  `{FAKE}`") == FAKE


def test_nothing_that_looks_like_a_key():
    for text in ("", "   \n  ", "Endpoint: https://x.test", "short"):
        with pytest.raises(KeyFileError):
            pick_key(text)


def test_error_messages_never_contain_the_text_of_the_file():
    secret_text = f"Azure OpenAI key: {FAKE}\nSpeech service key: {FAKE}Z\nNotes: private words"

    with pytest.raises(KeyFileError) as raised:
        pick_key(secret_text)

    shown = str(raised.value)
    assert FAKE not in shown and "private words" not in shown and "Notes" not in shown and "Speech" not in shown


# ---- reading a file ----

def test_reads_an_rtf_file(tmp_path):
    path = tmp_path / "azure.rtf"
    path.write_text(rtf(f"\\b Key 1:\\b0  {FAKE}\\par"), encoding="ascii")

    assert read_key_file(path) == FAKE


def test_reads_a_plain_text_file_with_a_byte_order_mark(tmp_path):
    path = tmp_path / "key.txt"
    path.write_bytes(b"\xef\xbb\xbf" + FAKE.encode() + b"\r\n")

    assert read_key_file(path) == FAKE


def test_a_missing_file_is_an_error_that_does_not_echo_the_path(tmp_path):
    with pytest.raises(KeyFileError) as raised:
        read_key_file(tmp_path / "nowhere" / "secret-folder.rtf")

    assert "secret-folder" not in str(raised.value) and "not found" in str(raised.value)


def test_a_huge_file_is_refused(tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("x" * (keyfile.MAX_BYTES + 1))

    with pytest.raises(KeyFileError, match="too large"):
        read_key_file(path)


# ---- the settings use it ----

AZURE = {"azure_openai_endpoint": "https://az.test", "azure_openai_deployment": "d", "session_secret": "s" * 40}


def test_settings_take_the_key_from_the_file(tmp_path):
    path = tmp_path / "azure.rtf"
    path.write_text(rtf(f"Key 1: {FAKE}"), encoding="ascii")

    settings = Settings(**AZURE, azure_openai_api_key_file=path)

    assert settings.azure_openai_api_key.get_secret_value() == FAKE and settings.chat_enabled is True
    assert FAKE not in repr(settings) + str(settings) + repr(settings.model_dump())


def test_the_label_setting_picks_between_keys(tmp_path):
    path = tmp_path / "azure.rtf"
    path.write_text(rtf(f"Key 1: {FAKE}\\par Key 2: SECOND{FAKE}"), encoding="ascii")

    settings = Settings(**AZURE, azure_openai_api_key_file=path, azure_openai_api_key_label="Key 2")

    assert settings.azure_openai_api_key.get_secret_value() == "SECOND" + FAKE


def test_a_key_in_the_environment_beats_the_file(tmp_path):
    path = tmp_path / "azure.rtf"
    path.write_text(rtf(f"Key 1: {FAKE}"), encoding="ascii")

    settings = Settings(**AZURE, azure_openai_api_key="from-the-environment-0123456789", azure_openai_api_key_file=path)

    assert settings.azure_openai_api_key.get_secret_value() == "from-the-environment-0123456789"


def test_a_relative_path_is_from_the_repository_root_not_the_working_folder(tmp_path, monkeypatch):
    (tmp_path / "keys").mkdir()
    (tmp_path / "keys" / "azure.rtf").write_text(rtf(f"Key 1: {FAKE}"), encoding="ascii")
    monkeypatch.setattr("rgv_flood.settings.REPO_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path / "keys")  # somewhere else entirely

    settings = Settings(**AZURE, azure_openai_api_key_file="keys/azure.rtf")

    assert settings.azure_openai_api_key.get_secret_value() == FAKE


def test_a_bad_file_turns_chat_off_but_does_not_stop_the_app(tmp_path, caplog):
    path = tmp_path / "azure.rtf"
    path.write_text(rtf(f"Azure OpenAI key: {FAKE}\\par Speech service key: {FAKE}Z"), encoding="ascii")
    caplog.set_level(logging.WARNING)

    settings = Settings(**AZURE, azure_openai_api_key_file=path)

    assert settings.chat_enabled is False
    assert "more than one" in caplog.text and FAKE not in caplog.text and "Speech" not in caplog.text


def test_a_missing_file_turns_chat_off_with_a_warning(tmp_path, caplog):
    caplog.set_level(logging.WARNING)

    settings = Settings(**AZURE, azure_openai_api_key_file=tmp_path / "gone.rtf")

    assert settings.chat_enabled is False and "key file" in caplog.text.lower()


def test_the_self_check_describes_the_shape_and_never_shows_the_key(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "azure.rtf"
    path.write_text(rtf(f"Key 1: {FAKE}"), encoding="ascii")

    done = subprocess.run([sys.executable, "-m", "rgv_flood.chat.keyfile", str(path)], capture_output=True, text=True, check=False)

    assert done.returncode == 0 and "49 characters" in done.stdout
    assert FAKE not in done.stdout + done.stderr


def test_the_self_check_fails_clearly_for_a_missing_file(tmp_path):
    import subprocess
    import sys

    done = subprocess.run([sys.executable, "-m", "rgv_flood.chat.keyfile", str(tmp_path / "none.rtf")], capture_output=True, text=True, check=False)

    assert done.returncode == 1 and "No key could be read" in done.stdout


def test_no_file_setting_changes_nothing():
    assert Settings(**AZURE).chat_enabled is False
