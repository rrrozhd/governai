from __future__ import annotations

from governai.skills.base import Skill


class SkillRegistry:
    def __init__(self) -> None:
        """Initialize SkillRegistry."""
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """Register."""
        if skill.name in self._skills:
            raise ValueError(f"Skill already registered: {skill.name}")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        """Get."""
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(f"Unknown skill: {name}") from exc

    def list(self) -> list[Skill]:
        """List."""
        return list(self._skills.values())
