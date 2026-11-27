"""+Human: skill_view finds a plugin's skill by its short name (overlay from alfred-build, codemod C0192)."""

import json

import pytest


@pytest.fixture
def skills(tmp_path, monkeypatch):
    """Fresh plugin manager and an empty on-disk skills dir; returns (register_plugin_skill, write_disk_skill)."""
    from hermes_cli import plugins as plugins_mod
    from hermes_cli.plugins import PluginManager

    pm = PluginManager()
    monkeypatch.setattr(plugins_mod, "_plugin_manager", pm)
    home = tmp_path / ".hermes"
    disk = home / "skills"
    disk.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr("tools.skills_tool.SKILLS_DIR", disk)

    def register(plugin, name):
        skill_dir = tmp_path / "plugins" / plugin / "skills" / name
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text(f"---\nname: {name}\ndescription: {name} of {plugin}\n---\n\nbody of {plugin}:{name}\n",
                      encoding="utf-8")
        pm._plugin_skills[f"{plugin}:{name}"] = {"path": md, "plugin": plugin, "bare_name": name, "description": ""}

    def on_disk(name):
        (disk / name).mkdir()
        (disk / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: local {name}\n---\n\nbody of the local {name}\n", encoding="utf-8")

    return register, on_disk


def _view(name):
    from tools.skills_tool import skill_view

    return json.loads(skill_view(name))


def test_short_name_serves_the_one_plugin_skill_under_its_full_name(skills):
    register, _on_disk = skills
    register("foo", "outlook")
    register("foo", "calendar")
    result = _view("outlook")
    assert result["success"] is True
    assert result["name"] == "foo:outlook"
    assert "body of foo:outlook" in result["content"]


def test_full_name_still_works(skills):
    register, _on_disk = skills
    register("foo", "outlook")
    assert _view("foo:outlook")["name"] == "foo:outlook"


def test_short_name_of_two_plugins_is_ambiguous_and_lists_both(skills):
    register, _on_disk = skills
    register("foo", "outlook")
    register("bar", "outlook")
    result = _view("outlook")
    assert result["success"] is False
    assert result["matches"] == ["bar:outlook", "foo:outlook"]
    assert "bar:outlook" in result["error"] and "foo:outlook" in result["error"]
    # upstream's shape for a name collision: what preload and cron read to say why
    from agent.skill_commands import ambiguous_skill_label

    assert ambiguous_skill_label("outlook", result) == "Ambiguous skill name outlook: use one of bar:outlook, foo:outlook"


def test_a_wrong_namespace_is_not_guessed_but_gets_the_full_names(skills):
    register, _on_disk = skills
    register("alfred-m365", "outlook")
    for asked in ("m365:outlook", "alfred_m365:outlook"):
        result = _view(asked)
        assert result["success"] is False
        assert result["error"] == f"Skill '{asked}' not found."
        assert result["plugin_skills"] == ["alfred-m365:outlook"]


def test_a_skill_on_disk_wins_over_a_plugin_skill_of_the_same_name(skills):
    register, on_disk = skills
    register("foo", "outlook")
    on_disk("outlook")
    result = _view("outlook")
    assert result["success"] is True
    assert result["name"] == "outlook"
    assert "body of the local outlook" in result["content"]


def test_not_found_lists_plugin_skills_by_full_name(skills):
    register, on_disk = skills
    register("foo", "outlook")
    on_disk("notes")
    result = _view("teams")
    assert result["success"] is False
    assert result["error"] == "Skill 'teams' not found."
    assert result["plugin_skills"] == ["foo:outlook"]
    assert "notes" in result["available_skills"]
    assert "plugin:skill" in result["hint"]


def test_not_found_is_unchanged_without_plugin_skills(skills):
    result = _view("teams")
    assert result["success"] is False
    assert result["error"] == "Skill 'teams' not found."
    assert "plugin_skills" not in result


def test_a_disabled_plugin_skill_is_not_offered_by_short_name(skills, monkeypatch):
    register, _on_disk = skills
    register("foo", "outlook")
    monkeypatch.setattr("tools.skills_tool._is_skill_disabled", lambda *names, **_kw: "foo:outlook" in names)
    result = _view("outlook")
    assert result["success"] is False
    assert result["error"] == "Skill 'outlook' not found."
    assert "plugin_skills" not in result
