"""Skill playbooks: markdown files in `chat/skills/` the model loads by name with `load_skill`.

Each file starts with front matter:

    ---
    name: claims                      (must match the file name)
    use_when: one line, shown in the system prompt's skill list
    tools: [find_place, claims_summary]
    tables: [nfip_claims]
    ---

and its body (how to answer, traps, a good answer) is what `load_skill` returns. Adding a skill is
adding a file; the tests check every file names only tools and tables that exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"
USE_WHEN_MAX = 150
BODY_MAX = 3000
FIELDS = ("name", "use_when", "tools", "tables")


class SkillError(ValueError):
    """A skill file is malformed. Raised at startup, so a broken file fails the tests, not a visitor."""


@dataclass(frozen=True)
class Skill:
    name: str
    use_when: str
    tools: tuple[str, ...]
    tables: tuple[str, ...]
    body: str


def _value(raw: str) -> str | tuple[str, ...]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return tuple(part.strip() for part in raw[1:-1].split(",") if part.strip())
    return raw


def parse_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise SkillError(f"{path.name}: no front matter (a block between two --- lines)")
    head, body = text[4:].split("\n---\n", 1)
    fields = {}
    for line in head.splitlines():
        if line.strip():
            key, sep, value = line.partition(":")
            if not sep:
                raise SkillError(f"{path.name}: front matter line {line!r} is not 'key: value'")
            fields[key.strip()] = _value(value)
    missing = [f for f in FIELDS if f not in fields]
    if missing:
        raise SkillError(f"{path.name}: front matter is missing {', '.join(missing)}")
    body = body.strip()
    skill = Skill(fields["name"], fields["use_when"], tuple(fields["tools"]), tuple(fields["tables"]), body)
    if skill.name != path.stem:
        raise SkillError(f"{path.name}: name {skill.name!r} must match the file name")
    if not skill.use_when or len(skill.use_when) > USE_WHEN_MAX:
        raise SkillError(f"{path.name}: use_when must be 1 to {USE_WHEN_MAX} characters")
    if not body or len(body) > BODY_MAX:
        raise SkillError(f"{path.name}: the body must be 1 to {BODY_MAX} characters (it is {len(body)})")
    return skill


def load_skills(folder: Path = SKILLS_DIR) -> dict[str, Skill]:
    """Every skill file in `folder`, by name."""
    return {skill.name: skill for skill in (parse_skill(p) for p in sorted(folder.glob("*.md")))}
