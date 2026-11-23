"""Chat: the skill playbooks (markdown files the model loads by name) and their loader."""

import pytest
from database import TABLES

from rgv_flood.chat.skills import BODY_MAX, USE_WHEN_MAX, Skill, SkillError, load_skills

FIRST_SKILLS = {"claims", "rain_vs_claims", "news", "flood_events"}
GOOD = "---\nname: {name}\nuse_when: {use_when}\ntools: [find_place, query_database]\ntables: [nfip_claims]\n---\n{body}\n"


def write(folder, name, use_when="Claims questions.", body="## How to answer\nCall the tool."):
    (folder / f"{name}.md").write_text(GOOD.format(name=name, use_when=use_when, body=body), encoding="utf-8")


def test_all_skill_files_load():
    skills = load_skills()
    assert set(skills) == FIRST_SKILLS
    assert all(isinstance(s, Skill) for s in skills.values())


def test_skill_fields_parse(tmp_path):
    write(tmp_path, "claims")
    s = load_skills(tmp_path)["claims"]
    assert s == Skill("claims", "Claims questions.", ("find_place", "query_database"), ("nfip_claims",),
                      "## How to answer\nCall the tool.")


def test_skills_name_only_real_tools():
    from rgv_flood.chat.prompt import TOOLS

    names = {t["function"]["name"] for t in TOOLS}
    for s in load_skills().values():
        assert set(s.tools) <= names, s.name


def test_skills_name_only_real_tables():
    for s in load_skills().values():
        assert set(s.tables) <= set(TABLES), s.name


def test_playbooks_have_the_three_sections():
    for s in load_skills().values():
        for heading in ("## How to answer", "## Traps", "## Good answer"):
            assert heading in s.body, (s.name, heading)


def test_limits(tmp_path):
    assert USE_WHEN_MAX == 150 and BODY_MAX == 3000
    write(tmp_path, "long", use_when="x" * 151)
    with pytest.raises(SkillError, match="use_when"):
        load_skills(tmp_path)
    (tmp_path / "long.md").unlink()
    write(tmp_path, "big", body="x" * 3001)
    with pytest.raises(SkillError, match="3000"):
        load_skills(tmp_path)


def test_missing_field(tmp_path):
    (tmp_path / "bad.md").write_text("---\nname: bad\ntools: []\ntables: []\n---\nbody\n", encoding="utf-8")
    with pytest.raises(SkillError, match="use_when"):
        load_skills(tmp_path)


def test_no_front_matter(tmp_path):
    (tmp_path / "bad.md").write_text("just text\n", encoding="utf-8")
    with pytest.raises(SkillError, match="front matter"):
        load_skills(tmp_path)


def test_name_must_match_file(tmp_path):
    write(tmp_path, "claims")
    (tmp_path / "claims.md").rename(tmp_path / "other.md")
    with pytest.raises(SkillError, match="other.md"):
        load_skills(tmp_path)


def test_skill_body_is_plain_text():
    for s in load_skills().values():
        assert "```" not in s.body, s.name  # the bot answers in plain text; a playbook must not model markup
