from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import BaseModel, Field, ValidationError

from governai.agents.registry import AgentRegistry
from governai.app.config import (
    DuplicateStepError,
    FlowConfigV1,
    InvalidTransitionError,
    UnknownAgentError,
    UnknownEntryStepError,
    UnknownToolError,
    TransitionConfigV1,
    governed_flow_from_config,
    validate_flow_config,
)
from governai.tools.registry import ToolRegistry


class DSLError(ValueError):
    """Base error for DSL parsing/compilation."""


class DSLSyntaxError(DSLError):
    def __init__(self, message: str, *, line: int | None = None, column: int | None = None) -> None:
        """Initialize syntax error with optional source location."""
        if line is not None and column is not None:
            message = f"{message} (line {line}, column {column})"
        super().__init__(message)
        self.line = line
        self.column = column


class DSLSemanticError(DSLError):
    def __init__(self, message: str, *, line: int | None = None, column: int | None = None) -> None:
        """Initialize semantic error with optional source location."""
        if line is not None and column is not None:
            message = f"{message} (line {line}, column {column})"
        super().__init__(message)
        self.line = line
        self.column = column


class DSLAst(BaseModel):
    flow: FlowConfigV1
    step_locations: dict[str, tuple[int, int]] = Field(default_factory=dict)
    entry_location: tuple[int, int] | None = None


_GRAMMAR = r"""
start: flow

flow: "flow" NAME "{" flow_item* "}"

?flow_item: entry_stmt
          | policy_stmt
          | skill_stmt
          | channel_stmt
          | interrupt_stmt
          | step_stmt

entry_stmt: "entry" ":" step_ref ";"
policy_stmt: "policy" ":" NAME ("," NAME)* ";"
skill_stmt: "skill" ":" NAME ("," NAME)* ";"
channel_stmt: "channel" NAME ["reducer" NAME] ["initial" value] ";"
interrupt_stmt: "interrupts" "ttl" INT "max_pending" INT ";"

step_stmt: "step" NAME ":" executor step_meta* transition ";"
executor: "tool" NAME      -> tool_exec
        | "agent" NAME     -> agent_exec

step_meta: "requires" "[" [NAME ("," NAME)*] "]"  -> requires_meta
         | "emit" NAME                            -> emit_meta
         | "approval" BOOL                        -> approval_meta

transition: "->" step_ref                                 -> then_transition
          | "branch" "router" NAME "mapping" "{" [mapping_item ("," mapping_item)*] "}" -> branch_transition
          | "route_to" "[" [step_ref ("," step_ref)*] "]" -> route_transition

mapping_item: map_key ":" step_ref
map_key: NAME | ESCAPED_STRING

step_ref: NAME | END

?value: object
      | array
      | ESCAPED_STRING   -> string
      | SIGNED_NUMBER    -> number
      | BOOL             -> boolean
      | "null"i          -> null

array : "[" [value ("," value)*] "]"
object: "{" [pair ("," pair)*] "}"
pair  : ESCAPED_STRING ":" value

BOOL: "true"i | "false"i
END: "end"i
INT: /[0-9]+/
NAME: /[A-Za-z_][A-Za-z0-9_.-]*/

%import common.ESCAPED_STRING
%import common.SIGNED_NUMBER
%import common.WS
%ignore WS
%ignore /#[^\n]*/
"""


def _parse_lark_tree(text: str) -> Any:
    """Parse raw DSL text into a Lark parse tree with positions."""
    try:
        from lark import Lark
        from lark.exceptions import UnexpectedInput
    except Exception as exc:  # pragma: no cover - dependency guard
        raise DSLSyntaxError("DSL support requires lark installed") from exc

    parser = Lark(_GRAMMAR, parser="lalr", propagate_positions=True)
    try:
        return parser.parse(text)
    except UnexpectedInput as exc:
        raise DSLSyntaxError("Invalid DSL syntax", line=exc.line, column=exc.column) from exc


def _decode_string(value: Any) -> str:
    """Decode JSON-escaped string tokens from grammar nodes."""
    return json.loads(str(value))


def _decode_number(value: Any) -> int | float:
    """Decode numeric tokens to `int` when possible, otherwise `float`."""
    raw = str(value)
    if "." in raw:
        return float(raw)
    return int(raw)


def _extract_value(node: Any) -> Any:
    """Convert a parse node into a plain Python value."""
    from lark import Token, Tree

    if isinstance(node, Token):
        if node.type == "ESCAPED_STRING":
            return _decode_string(node)
        if node.type == "SIGNED_NUMBER":
            return _decode_number(node)
        if node.type == "BOOL":
            return str(node).lower() == "true"
        if node.type == "NAME":
            return str(node)
        if node.type == "END":
            return "end"
        if node.type == "INT":
            return int(str(node))
    if not isinstance(node, Tree):
        return node

    if node.data == "string":
        return _decode_string(node.children[0])
    if node.data == "number":
        return _decode_number(node.children[0])
    if node.data == "boolean":
        return str(node.children[0]).lower() == "true"
    if node.data == "null":
        return None
    if node.data == "array":
        return [_extract_value(child) for child in node.children]
    if node.data == "pair":
        key = _decode_string(node.children[0])
        val = _extract_value(node.children[1])
        return key, val
    if node.data == "object":
        out: dict[str, Any] = {}
        for child in node.children:
            key, val = _extract_value(child)
            out[key] = val
        return out
    if node.data == "step_ref":
        return _extract_value(node.children[0])
    if node.data == "map_key":
        child = node.children[0]
        if isinstance(child, Token) and child.type == "ESCAPED_STRING":
            return _decode_string(child)
        return str(child)
    return [_extract_value(child) for child in node.children]


def _find_node(tree: Any, name: str) -> Any:
    """Return first direct child subtree matching `name`."""
    from lark import Tree

    for child in tree.children:
        if isinstance(child, Tree) and child.data == name:
            return child
    return None


def _build_ast(tree: Any) -> DSLAst:
    """Build validated DSL AST and corresponding `FlowConfigV1` payload."""
    from lark import Tree, Token

    flow_tree = _find_node(tree, "flow")
    if flow_tree is None:
        raise DSLSemanticError("Missing flow definition")

    flow_name_token = flow_tree.children[0]
    flow_name = str(flow_name_token)
    config_payload: dict[str, Any] = {
        "version": "v1",
        "name": flow_name,
        "steps": [],
        "policies": [],
        "skills": [],
        "channels": [],
        "interrupts": {"ttl_seconds": 1800, "max_pending": 1},
    }
    step_locations: dict[str, tuple[int, int]] = {}
    entry_location: tuple[int, int] | None = None

    # Walk each flow item and progressively materialize config payload fields.
    for item in flow_tree.children[1:]:
        if not isinstance(item, Tree):
            continue
        if item.data == "entry_stmt":
            entry = _extract_value(item.children[0])
            config_payload["entry_step"] = entry
            entry_location = (item.meta.line, item.meta.column)
            continue
        if item.data == "policy_stmt":
            config_payload["policies"].extend(str(child) for child in item.children)
            continue
        if item.data == "skill_stmt":
            config_payload["skills"].extend(str(child) for child in item.children)
            continue
        if item.data == "interrupt_stmt":
            config_payload["interrupts"] = {
                "ttl_seconds": int(str(item.children[0])),
                "max_pending": int(str(item.children[1])),
            }
            continue
        if item.data == "channel_stmt":
            channel_name = str(item.children[0])
            reducer = "replace"
            initial: Any = None
            remainder = item.children[1:]
            if remainder:
                first = remainder[0]
                if isinstance(first, Token) and first.type == "NAME":
                    reducer = str(first)
                    if len(remainder) > 1:
                        initial = _extract_value(remainder[1])
                else:
                    initial = _extract_value(first)
            config_payload["channels"].append(
                {
                    "name": channel_name,
                    "reducer": reducer,
                    "initial": initial,
                }
            )
            continue
        if item.data != "step_stmt":
            continue

        step_name = str(item.children[0])
        if step_name in step_locations:
            line, column = item.meta.line, item.meta.column
            raise DSLSemanticError(f"Duplicate step name: {step_name}", line=line, column=column)
        step_locations[step_name] = (item.meta.line, item.meta.column)

        executor_tree = item.children[1]
        if not isinstance(executor_tree, Tree):
            raise DSLSemanticError(
                f"Invalid executor declaration for step {step_name}",
                line=item.meta.line,
                column=item.meta.column,
            )
        executor_kind = "tool" if executor_tree.data == "tool_exec" else "agent"
        executor_name = str(executor_tree.children[0])

        required_artifacts: list[str] = []
        emitted_artifact: str | None = None
        approval_override: bool | None = None
        transition_payload: TransitionConfigV1 | None = None

        for child in item.children[2:]:
            if not isinstance(child, Tree):
                continue
            if child.data == "requires_meta":
                required_artifacts = [str(node) for node in child.children]
                continue
            if child.data == "emit_meta":
                emitted_artifact = str(child.children[0])
                continue
            if child.data == "approval_meta":
                approval_override = str(child.children[0]).lower() == "true"
                continue
            if child.data == "then_transition":
                next_step = _extract_value(child.children[0])
                if str(next_step).lower() == "end":
                    transition_payload = TransitionConfigV1(kind="end")
                else:
                    transition_payload = TransitionConfigV1(kind="then", next_step=str(next_step))
                continue
            if child.data == "branch_transition":
                router = str(child.children[0])
                mapping: dict[str, str] = {}
                for mapping_item in child.children[1:]:
                    if not isinstance(mapping_item, Tree) or mapping_item.data != "mapping_item":
                        continue
                    key = _extract_value(mapping_item.children[0])
                    target = _extract_value(mapping_item.children[1])
                    mapping[str(key)] = str(target)
                transition_payload = TransitionConfigV1(kind="branch", router=router, mapping=mapping)
                continue
            if child.data == "route_transition":
                allowed = [str(_extract_value(node)) for node in child.children]
                transition_payload = TransitionConfigV1(kind="route_to", allowed=allowed)
                continue

        if transition_payload is None:
            line, column = step_locations[step_name]
            raise DSLSemanticError(
                f"Step {step_name} is missing transition declaration",
                line=line,
                column=column,
            )

        step_payload = {
            "name": step_name,
            executor_kind: executor_name,
            "required_artifacts": required_artifacts,
            "emitted_artifact": emitted_artifact,
            "approval_override": approval_override,
            "transition": transition_payload.model_dump(mode="json"),
        }
        config_payload["steps"].append(step_payload)

    try:
        config = FlowConfigV1.model_validate(config_payload)
    except ValidationError as exc:
        raise DSLSemanticError(str(exc)) from exc

    try:
        validate_flow_config(config)
    except InvalidTransitionError as exc:
        line, column = step_locations.get(exc.step_name, (None, None))
        raise DSLSemanticError(str(exc), line=line, column=column) from exc
    except DuplicateStepError as exc:
        line, column = step_locations.get(exc.step_name, (None, None))
        raise DSLSemanticError(str(exc), line=line, column=column) from exc
    except UnknownEntryStepError as exc:
        line = entry_location[0] if entry_location else None
        column = entry_location[1] if entry_location else None
        raise DSLSemanticError(str(exc), line=line, column=column) from exc

    return DSLAst(flow=config, step_locations=step_locations, entry_location=entry_location)


def parse_dsl(text: str) -> DSLAst:
    """Parse DSL text into a validated AST with location metadata."""
    tree = _parse_lark_tree(text)
    return _build_ast(tree)


def dsl_to_flow_config(text: str) -> FlowConfigV1:
    """Compile DSL text directly into `FlowConfigV1`."""
    return parse_dsl(text).flow


def governed_flow_from_dsl(
    text: str,
    *,
    tool_registry: ToolRegistry,
    agent_registry: AgentRegistry,
    policy_registry: Mapping[str, Any] | None = None,
    skill_registry: Mapping[str, Any] | None = None,
    runtime_overrides: Mapping[str, Any] | None = None,
    containment_mode: str = "local_dev",
    remote_execution_adapter: Any = None,
    interrupt_store: Any = None,
):
    """Compile DSL text into an executable governed flow instance."""
    ast = parse_dsl(text)
    config = ast.flow
    try:
        return governed_flow_from_config(
            config,
            tool_registry=tool_registry,
            agent_registry=agent_registry,
            policy_registry=policy_registry,
            skill_registry=skill_registry,
            runtime_overrides=runtime_overrides,
            containment_mode=containment_mode,
            remote_execution_adapter=remote_execution_adapter,
            interrupt_store=interrupt_store,
        )
    except UnknownToolError as exc:
        for step in config.steps:
            if step.tool == exc.tool_name:
                line, column = ast.step_locations.get(step.name, (None, None))
                raise DSLSemanticError(str(exc), line=line, column=column) from exc
        raise DSLSemanticError(str(exc)) from exc
    except UnknownAgentError as exc:
        for step in config.steps:
            if step.agent == exc.agent_name:
                line, column = ast.step_locations.get(step.name, (None, None))
                raise DSLSemanticError(str(exc), line=line, column=column) from exc
        raise DSLSemanticError(str(exc)) from exc
