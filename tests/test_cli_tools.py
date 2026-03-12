from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from governai import CLIToolOutputError, CLIToolProcessError, CLIToolTimeoutError, Tool


class InModel(BaseModel):
    value: int


class OutModel(BaseModel):
    result: int


def write_script(path: Path, body: str) -> None:
    path.write_text(body)


def test_cli_tool_success_path(tmp_path: Path) -> None:
    script = tmp_path / "ok.py"
    write_script(
        script,
        "import json,sys\n"
        "p=json.loads(sys.stdin.read())\n"
        "sys.stdout.write(json.dumps({'result': p['value'] + 1}))\n",
    )
    cli_tool = Tool.from_cli(
        name="cli.ok",
        command=[sys.executable, str(script)],
        input_model=InModel,
        output_model=OutModel,
    )

    async def run() -> None:
        out = await cli_tool.execute(None, {"value": 4})
        assert out.result == 5

    asyncio.run(run())


def test_cli_tool_non_zero_exit(tmp_path: Path) -> None:
    script = tmp_path / "fail.py"
    write_script(script, "import sys\nsys.stderr.write('bad')\nsys.exit(3)\n")
    cli_tool = Tool.from_cli(
        name="cli.fail",
        command=[sys.executable, str(script)],
        input_model=InModel,
        output_model=OutModel,
    )

    async def run() -> None:
        with pytest.raises(CLIToolProcessError):
            await cli_tool.execute(None, {"value": 1})

    asyncio.run(run())


def test_cli_tool_invalid_json_output(tmp_path: Path) -> None:
    script = tmp_path / "invalid.py"
    write_script(script, "import sys\nsys.stdout.write('not-json')\n")
    cli_tool = Tool.from_cli(
        name="cli.invalid",
        command=[sys.executable, str(script)],
        input_model=InModel,
        output_model=OutModel,
    )

    async def run() -> None:
        with pytest.raises(CLIToolOutputError):
            await cli_tool.execute(None, {"value": 1})

    asyncio.run(run())


def test_cli_tool_timeout(tmp_path: Path) -> None:
    script = tmp_path / "slow.py"
    write_script(script, "import time\ntime.sleep(2)\nprint('{\"result\":1}')\n")
    cli_tool = Tool.from_cli(
        name="cli.slow",
        command=[sys.executable, str(script)],
        input_model=InModel,
        output_model=OutModel,
        timeout_seconds=0.1,
    )

    async def run() -> None:
        with pytest.raises(CLIToolTimeoutError):
            await cli_tool.execute(None, {"value": 1})

    asyncio.run(run())
