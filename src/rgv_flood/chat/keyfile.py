"""Read the Azure key from a file (such as a note saved as RTF) instead of from the environment.

The file's text is secret. Nothing here ever puts it, its labels or the path into an
error message or a log line: errors say only what kind of problem there was.
"""

from __future__ import annotations

import re
from pathlib import Path

MAX_BYTES = 200_000
MIN_KEY_LENGTH = 20  # a real key is longer; this keeps "Region: eastus"-style values out

# Lines whose label says they are not the key.
_NOT_A_KEY_LABEL = re.compile(r"endpoint|url|uri|region|location|name|resource|deployment|version|model|subscription|tenant|id\b", re.IGNORECASE)
_KEY_LABEL = re.compile(r"key|secret|token", re.IGNORECASE)
_PREFERRED = re.compile(r"\bkey\s*1\b|api[\s_-]*key", re.IGNORECASE)
# RTF groups whose contents are formatting or metadata, not the document's text.
_SKIPPED_DESTINATIONS = frozenset({
    "fonttbl", "colortbl", "stylesheet", "info", "header", "footer", "pict", "object", "themedata", "colorschememapping",
    "latentstyles", "datastore", "rsidtbl", "listtable", "listoverridetable", "generator", "fldinst", "xmlnstbl",
})


class KeyFileError(Exception):
    """The key could not be found in the file. The message is safe to log."""


def rtf_to_text(raw: str) -> str:
    """The plain text of an RTF document (or `raw` itself if it is not RTF)."""
    if not raw.lstrip().startswith("{\\rtf"):
        return raw
    out: list[str] = []
    stack: list[tuple[bool, int]] = []  # (skipping this group?, how many characters follow a \uN)
    skipping, unicode_skip, i, n = False, 1, 0, len(raw)
    pending_skip = 0  # characters still to drop after a \uN
    first_group = True
    while i < n:
        char = raw[i]
        if char == "{":
            stack.append((skipping, unicode_skip))
            i += 1
            if raw.startswith("\\*", i):  # an optional destination: drop it, as readers that don't know it do
                skipping = True
            first_group = False
        elif char == "}":
            skipping, unicode_skip = stack.pop() if stack else (False, 1)
            i += 1
        elif char == "\\":
            i += 1
            if i >= n:
                break
            nxt = raw[i]
            if nxt in "\\{}":
                if not skipping and pending_skip == 0:
                    out.append(nxt)
                pending_skip = max(0, pending_skip - 1) if pending_skip else 0
                i += 1
            elif nxt == "'":
                digits = raw[i + 1 : i + 3]
                i += 3
                if pending_skip:
                    pending_skip -= 1
                elif not skipping:
                    try:
                        out.append(bytes([int(digits, 16)]).decode("cp1252", "replace"))
                    except ValueError:
                        pass
            elif nxt == "~":
                out.append("" if skipping else " ")
                i += 1
            elif nxt == "_":
                out.append("" if skipping else "-")
                i += 1
            elif nxt in "-|:":
                i += 1
            elif nxt == "\n" or nxt == "\r":
                out.append("" if skipping else "\n")
                i += 1
            elif nxt.isalpha():
                j = i
                while j < n and raw[j].isalpha():
                    j += 1
                word = raw[i:j]
                k = j
                if k < n and raw[k] in "-0123456789":
                    k += 1
                    while k < n and raw[k].isdigit():
                        k += 1
                parameter = raw[j:k]
                i = k + 1 if k < n and raw[k] == " " else k  # one space ends a control word
                if word in _SKIPPED_DESTINATIONS:
                    skipping = True
                elif word in ("par", "line", "sect", "page") and not skipping:
                    out.append("\n")
                elif word == "tab" and not skipping:
                    out.append("\t")
                elif word == "uc" and parameter.lstrip("-").isdigit():
                    unicode_skip = int(parameter)
                elif word == "u" and parameter.lstrip("-").isdigit() and not skipping:
                    code = int(parameter)
                    out.append(chr(code + 65536 if code < 0 else code))
                    pending_skip = unicode_skip
            else:
                i += 1
        elif char in "\r\n":
            i += 1
        else:
            if pending_skip:
                pending_skip -= 1
            elif not skipping:
                out.append(char)
            i += 1
    del first_group
    return "".join(out)


def _clean(value: str) -> str:
    value = value.strip().strip("\"'`“”‘’").strip()
    return value


def pick_key(text: str, label: str = "") -> str:
    """The key in `text`: a lone value, or the value on a "Key 1: ..." style line. Several candidates
    need `label` (the text before the colon of the right line) to choose between them."""
    candidates: list[tuple[str, str]] = []  # (label, value)
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        head, separator, tail = re.split(r"\s*([:=])\s*", line, maxsplit=1) if re.search(r"[:=]", line) else (line, "", "")
        value = _clean(tail if separator else head)
        name = head.strip() if separator else ""
        if len(value) < MIN_KEY_LENGTH or " " in value or value.lower().startswith(("http://", "https://")):
            continue
        if name and _NOT_A_KEY_LABEL.search(name) and not _KEY_LABEL.search(name):
            continue
        candidates.append((name, value))
    if label.strip():
        wanted = " ".join(label.lower().split())
        matches = [value for name, value in candidates if " ".join(name.lower().split()) == wanted]
        if len(matches) != 1:
            raise KeyFileError("The key file has no single line with the label you set (RGV_AZURE_OPENAI_API_KEY_LABEL).")
        return matches[0]
    if not candidates:
        raise KeyFileError("No value that looks like a key was found in the key file.")
    if len(candidates) == 1:
        return candidates[0][1]
    labelled = [value for name, value in candidates if _PREFERRED.search(name)]
    if len(labelled) == 1:
        return labelled[0]
    raise KeyFileError(
        f"The key file has more than one value that could be the key ({len(candidates)}); "
        "set RGV_AZURE_OPENAI_API_KEY_LABEL to the text before the colon on the right line."
    )


def read_key_file(path: Path, label: str = "") -> str:
    """The key stored in the file at `path` (RTF or plain text)."""
    try:
        size = path.stat().st_size
        if size > MAX_BYTES:
            raise KeyFileError("The key file is too large to be a key.")
        raw = path.read_bytes().decode("utf-8-sig", "replace")
    except FileNotFoundError:
        raise KeyFileError("The key file was not found.") from None
    except OSError:
        raise KeyFileError("The key file could not be read.") from None
    return pick_key(rtf_to_text(raw), label)


def describe(key: str) -> str:
    """What kind of value this is, without showing it: its length and what kinds of characters it has."""
    kinds = {
        "letters": sum(c.isalpha() for c in key), "digits": sum(c.isdigit() for c in key),
        "symbols": sum(not c.isalnum() for c in key),
    }
    return f"{len(key)} characters: " + ", ".join(f"{n} {kind}" for kind, n in kinds.items())


if __name__ == "__main__":  # uv run python -m rgv_flood.chat.keyfile keys/azure.rtf ["label"]
    import sys

    from rgv_flood.settings import REPO_ROOT

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("keys/azure.rtf")
    target = target if target.is_absolute() else REPO_ROOT / target
    try:
        print("A key was found.", describe(read_key_file(target, sys.argv[2] if len(sys.argv) > 2 else "")))
        print("Its text is not shown. Azure resource keys are usually 32 hex characters or about 84 letters and digits.")
    except KeyFileError as error:
        print("No key could be read:", error)
        raise SystemExit(1) from None
