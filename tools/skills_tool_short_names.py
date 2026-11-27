"""+Human: a plugin's skill also answers to its short name.

A plugin registers its skills as ``plugin:skill`` (``alfred-m365:outlook``) and upstream's ``skill_view`` finds them
under that full name only: a name without the namespace is looked up on disk alone. The skills index shows the full
names, but local models keep dropping the namespace and then report the skill as missing. ``skill_view`` calls
:func:`plugin_skill_by_short_name` once nothing on disk answers to the name it was given (codemod C0192 in
alfred-build), so an on-disk skill always wins.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("tools.skills_tool")


class SkillNotOnDisk(str):
    """The on-disk lookup's plain "not found" failure, told apart from its other failures (an ambiguous name, a
    quarantined skill), which stand as they are. To every other reader it is the same JSON string."""


def plugin_skill_by_short_name(name: str, not_found: str, file_path, task_id, preprocess) -> str:
    """Answer for ``name`` after the on-disk lookup failed with ``not_found``: the one plugin skill with that short
    name, served under its full name; an error that lists the full names when several plugins have one; otherwise
    ``not_found`` with the plugins' skills added under their full names. A name that carries a namespace
    (``m365:outlook``, the plugin's name shortened or misspelled) is never guessed: it gets the list."""
    from agent.skill_utils import AMBIGUOUS_SKILL_PREFIX
    from tools import skills_tool as _st  # late: tests patch its helpers, and it imports this module

    try:
        from hermes_cli.plugins import discover_plugins, get_plugin_manager

        discover_plugins()  # idempotent
        offered = [row["name"] for row in get_plugin_manager().list_plugin_skill_metadata()
                   if _st.skill_matches_platform(row.get("frontmatter") or {})
                   and not _st._is_skill_disabled(row["name"])]
    except Exception:
        logger.debug("Plugin skill lookup by short name failed", exc_info=True)
        return str(not_found)
    matches = [] if ":" in name else [q for q in offered if q.rpartition(":")[2] == name]
    if len(matches) == 1:
        served, _local = _st._resolve_plugin_skill(matches[0], file_path, task_id, preprocess)
        if served is not None:
            return served
    elif matches:
        # upstream's shape for a name collision (prefix + load_names), so preload and cron say why too
        return _st._fail(
            f"{AMBIGUOUS_SKILL_PREFIX}'{name}': use one of {', '.join(matches)}. "
            f"{len(matches)} plugins provide a skill of this name.",
            matches=matches, load_names=matches, hint="Pass the full name (plugin:skill).")
    if not offered:
        return str(not_found)
    payload = json.loads(not_found)
    payload["plugin_skills"] = offered
    payload["hint"] = "Plugin skills load by their full name (plugin:skill). " + str(payload.get("hint") or "")
    return _st._json(payload)
