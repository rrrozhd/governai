from __future__ import annotations

import pytest
from pydantic import BaseModel

from governai import Skill, tool


class InModel(BaseModel):
    x: int


class OutModel(BaseModel):
    y: int


@tool(name="one", input_model=InModel, output_model=OutModel)
async def one(ctx, data: InModel) -> OutModel:
    return OutModel(y=data.x)


@tool(name="two", input_model=InModel, output_model=OutModel)
async def two(ctx, data: InModel) -> OutModel:
    return OutModel(y=data.x)


def test_skill_registration_and_lookup() -> None:
    skill = Skill(name="support", tools=[one, two])
    assert skill.get_tool("one").name == "one"
    assert len(skill.list_tools()) == 2


def test_skill_duplicate_tool_name_rejected() -> None:
    with pytest.raises(ValueError):
        Skill(name="dup", tools=[one, one])


def test_skill_lookup_unknown() -> None:
    skill = Skill(name="support", tools=[one])
    with pytest.raises(KeyError):
        skill.get_tool("missing")
