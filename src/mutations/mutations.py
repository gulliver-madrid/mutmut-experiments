# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from types import NoneType
from typing import Final, Literal, Mapping, Tuple, TypeGuard
from typing_extensions import Protocol

from parso.python.tree import (
    Name,
    Number,
    Keyword,
    FStringStart,
    FStringEnd,
    Operator,
)
from parso.tree import Node, BaseNode, Leaf, NodeOrLeaf

from src.context import Context
from src.setup_logging import configure_logger

from .ast_pattern import ASTPattern, is_name_node

logger = configure_logger(__name__)


def is_operator(node: NodeOrLeaf) -> TypeGuard[Operator]:
    return node.type == "operator"


class SkipException(Exception):
    pass


def number_mutation(*, value: str) -> str:
    assert isinstance(value, str)
    suffix = ""
    if value.upper().endswith("L"):  # pragma: no cover (python 2 specific)
        suffix = value[-1]
        value = value[:-1]

    if value.upper().endswith("J"):
        suffix = value[-1]
        value = value[:-1]

    if value.startswith("0o"):
        base = 8
        value = value[2:]
    elif value.startswith("0x"):
        base = 16
        value = value[2:]
    elif value.startswith("0b"):
        base = 2
        value = value[2:]
    elif (
        value.startswith("0") and len(value) > 1 and value[1] != "."
    ):  # pragma: no cover (python 2 specific)
        base = 8
        value = value[1:]
    else:
        base = 10

    parsed: float | int
    try:
        parsed = int(value, base=base)
        result = repr(parsed + 1)
    except ValueError:
        # Since it wasn't an int, it must be a float
        parsed = float(value)
        # This avoids all very small numbers becoming 1.0, and very
        # large numbers not changing at all
        if (1e-5 < abs(parsed) < 1e5) or (parsed == 0.0):
            result = repr(parsed + 1)
        else:
            result = repr(parsed * 2)

    if not result.endswith(suffix):
        result += suffix
    return result


def string_mutation(*, value: str) -> str:
    assert isinstance(value, str)
    prefix = value[: min(x for x in [value.find('"'), value.find("'")] if x != -1)]
    value = value[len(prefix) :]

    if value.startswith('"""') or value.startswith("'''"):
        # We assume here that triple-quoted stuff are docs or other things
        # that mutation is meaningless for
        return prefix + value
    return prefix + value[0] + "XX" + value[1:-1] + "XX" + value[-1]


def fstring_mutation(*, children: list[NodeOrLeaf]) -> list[NodeOrLeaf]:
    fstring_start = children[0]
    fstring_end = children[-1]
    assert isinstance(fstring_start, FStringStart)
    assert isinstance(fstring_end, FStringEnd)

    # we need to copy the list here, to not get in place mutation on the next line!
    children = children[:]

    children[0] = FStringStart(
        fstring_start.value + "XX",
        start_pos=fstring_start.start_pos,
        prefix=fstring_start.prefix,
    )

    children[-1] = FStringEnd(
        "XX" + fstring_end.value,
        start_pos=fstring_end.start_pos,
        prefix=fstring_end.prefix,
    )

    return children


def partition_node_list(
    nodes: list[NodeOrLeaf], value: str | None
) -> Tuple[list[NodeOrLeaf], Leaf, list[NodeOrLeaf]]:
    assert isinstance(value, (str, NoneType))
    for i, n in enumerate(nodes):
        assert isinstance(n, NodeOrLeaf)
        if hasattr(n, "value"):
            assert isinstance(n, Leaf)
            if n.value == value:
                return nodes[:i], n, nodes[i + 1 :]

    assert False, "didn't find node to split on"


def lambda_mutation(children: list[NodeOrLeaf]) -> list[NodeOrLeaf]:
    pre, op, post = partition_node_list(children, value=":")

    if len(post) == 1 and getattr(post[0], "value", None) == "None":
        return pre + [op] + [Number(value=" 0", start_pos=post[0].start_pos)]
    else:
        return pre + [op] + [Keyword(value=" None", start_pos=post[0].start_pos)]


def argument_mutation(
    *, children: list[NodeOrLeaf], context: Context
) -> list[NodeOrLeaf] | None:
    """Mutate the arguments one by one from dict(a=b) to dict(aXXX=b).

    This is similar to the mutation of dict literals in the form {'a': b}.
    """

    assert all(isinstance(child, NodeOrLeaf) for child in children)
    if len(context.stack) >= 3 and context.stack[-3].type in ("power", "atom_expr"):
        stack_pos_of_power_node = -3
    elif len(context.stack) >= 4 and context.stack[-4].type in ("power", "atom_expr"):
        stack_pos_of_power_node = -4
    else:
        return None

    power_node = context.stack[stack_pos_of_power_node]
    assert isinstance(power_node, BaseNode)
    if (
        is_name_node(power_node.children[0])
        and power_node.children[0].value in context.dict_synonyms
    ):
        c = children[0]
        if is_name_node(c):
            children = children[:]
            children[0] = Name(c.value + "XX", start_pos=c.start_pos, prefix=c.prefix)
            return children
    return None


def keyword_mutation(*, value: str, context: Context) -> str | None:
    if (
        len(context.stack) > 2
        and context.stack[-2].type in ("comp_op", "sync_comp_for")
        and value in ("in", "is")
    ):
        return None

    if len(context.stack) > 1 and context.stack[-2].type == "for_stmt":
        return None

    return {
        # 'not': 'not not',
        "not": "",
        "is": "is not",  # this will cause "is not not" sometimes, so there's a hack to fix that later
        "in": "not in",
        "break": "continue",
        "continue": "break",
        "True": "False",
        "False": "True",
    }.get(value)


import_from_star_pattern = ASTPattern(
    """
from _name import *
#                 ^
"""
)


def operator_mutation(*, value: str, node: Leaf) -> str | list[str] | None:
    assert isinstance(node, Leaf)
    if import_from_star_pattern.matches(node=node):
        return None

    if (
        value in ("*", "**")
        and node.parent  # always true
        and node.parent.type == "param"
    ):
        return None

    if value == "*" and node.parent and node.parent.type == "parameters":  # always true
        return None

    if (
        value in ("*", "**")
        and node.parent  # always true
        and node.parent.type in ("argument", "arglist")
    ):
        return None
    data: Mapping[str, str | list[str]] = {
        "+": "-",
        "-": "+",
        "*": "/",
        "/": "*",
        "//": "/",
        "%": "/",
        "<<": ">>",
        ">>": "<<",
        "&": "|",
        "|": "&",
        "^": "&",
        "**": "*",
        "~": "",
        "+=": ["-=", "="],
        "-=": ["+=", "="],
        "*=": ["/=", "="],
        "/=": ["*=", "="],
        "//=": ["/=", "="],
        "%=": ["/=", "="],
        "<<=": [">>=", "="],
        ">>=": ["<<=", "="],
        "&=": ["|=", "="],
        "|=": ["&=", "="],
        "^=": ["&=", "="],
        "**=": ["*=", "="],
        "~=": "=",
        "<": "<=",
        "<=": "<",
        ">": ">=",
        ">=": ">",
        "==": "!=",
        "!=": "==",
        "<>": "==",
    }
    return data.get(value)


def and_or_test_mutation(*, children: list[NodeOrLeaf], node: Node) -> list[NodeOrLeaf]:
    assert isinstance(node, Node)
    assert all(isinstance(child, NodeOrLeaf) for child in children), children
    children = children[:]
    assert isinstance(children[1], Leaf)
    children[1] = Keyword(
        value={"and": " or", "or": " and"}[children[1].value],
        start_pos=node.start_pos,
    )
    return children


def expression_mutation(*, children: list[NodeOrLeaf]) -> list[NodeOrLeaf]:
    assert all(isinstance(child, NodeOrLeaf) for child in children)

    def handle_assignment(children: list[NodeOrLeaf]) -> list[NodeOrLeaf]:
        mutation_index = -1  # we mutate the last value to handle multiple assignement
        if getattr(children[mutation_index], "value", "---") != "None":
            x = " None"
        else:
            x = ' ""'
        children = children[:]
        children[mutation_index] = Name(
            value=x, start_pos=children[mutation_index].start_pos
        )

        return children

    if is_operator(children[0]) and children[0].value == ":":
        if (
            len(children) > 2
            and is_operator(children[2])  # always true
            and children[2].value == "="
        ):
            # we need to copy the list here, to not get in place mutation on the next line!
            children = children[:]
            children[1:] = handle_assignment(children[1:])
    elif is_operator(children[1]) and children[1].value == "=":
        children = handle_assignment(children)

    return children


def decorator_mutation(*, children: list[NodeOrLeaf]) -> list[NodeOrLeaf]:
    assert all(isinstance(child, NodeOrLeaf) for child in children), children
    assert children[-1].type == "newline"
    return children[-1:]


array_subscript_pattern = ASTPattern(
    """
_name[_any]
#       ^
"""
)


function_call_pattern = ASTPattern(
    """
_name(_any)
#       ^
"""
)


def name_mutation(*, node: Leaf | None, value: str) -> str | None:
    assert isinstance(value, str)
    assert isinstance(node, (Leaf, NoneType))  # guess
    simple_mutants = {
        "True": "False",
        "False": "True",
        "deepcopy": "copy",
        "None": '""',
        # TODO: probably need to add a lot of things here... some builtins maybe, what more?
    }
    if value in simple_mutants:
        return simple_mutants[value]

    assert node is not None  # guess

    if array_subscript_pattern.matches(node=node):
        return "None"

    if function_call_pattern.matches(node=node):
        return "None"

    return None


MutationInputType = Literal["value", "children"]


class LeafMutation(ABC):
    @abstractmethod
    def __call__(
        self,
        *,
        node: Leaf | None,
        context: Context,
        value: str,
    ) -> str | list[str] | None:
        pass


class NodeWithChildrenMutation(ABC):
    @abstractmethod
    def __call__(
        self,
        *,
        node: BaseNode,
        context: Context,
        children: list[NodeOrLeaf],
    ) -> list[NodeOrLeaf] | None:
        pass


class OperatorMutation(LeafMutation):
    def __call__(
        self,
        *,
        node: Leaf | None,
        context: Context,
        value: str,
    ) -> str | list[str] | None:
        assert node is not None
        return operator_mutation(value=value, node=node)


class KeywordMutation(LeafMutation):
    def __call__(
        self,
        *,
        node: Leaf | None,
        context: Context,
        value: str,
    ) -> str | list[str] | None:
        return keyword_mutation(value=value, context=context)


class NumberMutation(LeafMutation):
    def __call__(
        self,
        *,
        node: Leaf | None,
        context: Context,
        value: str,
    ) -> str | list[str] | None:
        return number_mutation(value=value)


class NameMutation(LeafMutation):
    def __call__(
        self,
        *,
        node: Leaf | None,
        context: Context,
        value: str,
    ) -> str | list[str] | None:
        return name_mutation(node=node, value=value)


class StringMutation(LeafMutation):
    def __call__(
        self,
        *,
        node: Leaf | None,
        context: Context,
        value: str,
    ) -> str | list[str] | None:
        return string_mutation(value=value)


class ArgumentMutation(NodeWithChildrenMutation):
    def __call__(
        self,
        *,
        node: BaseNode,
        context: Context,
        children: list[NodeOrLeaf],
    ) -> list[NodeOrLeaf] | None:
        return argument_mutation(children=children, context=context)


class AndOrTestMutation(NodeWithChildrenMutation):
    def __call__(
        self,
        *,
        node: BaseNode,
        context: Context,
        children: list[NodeOrLeaf],
    ) -> list[NodeOrLeaf] | None:
        assert isinstance(node, Node)
        return and_or_test_mutation(children=children, node=node)


class _GetChildrenMutation(Protocol):
    def __call__(
        self,
        *,
        children: list[NodeOrLeaf],
    ) -> list[NodeOrLeaf]: ...


class GetChildrenMutation(NodeWithChildrenMutation):
    def __init__(self, mutation_func: _GetChildrenMutation):
        self._mutation_func = mutation_func

    def __call__(
        self,
        *,
        node: BaseNode,
        context: Context,
        children: list[NodeOrLeaf],
    ) -> list[NodeOrLeaf] | None:
        return self._mutation_func(children=children)


Mutation = LeafMutation | NodeWithChildrenMutation


mutations_by_type: Final[Mapping[str, tuple[MutationInputType, Mutation]]] = {
    "operator": ("value", OperatorMutation()),
    "keyword": ("value", KeywordMutation()),
    "number": ("value", NumberMutation()),
    "name": ("value", NameMutation()),
    "string": ("value", StringMutation()),
    "fstring": ("children", GetChildrenMutation(fstring_mutation)),
    "argument": ("children", ArgumentMutation()),
    "or_test": ("children", AndOrTestMutation()),
    "and_test": ("children", AndOrTestMutation()),
    "lambdef": ("children", GetChildrenMutation(lambda_mutation)),
    "expr_stmt": ("children", GetChildrenMutation(expression_mutation)),
    "decorator": ("children", GetChildrenMutation(decorator_mutation)),
    "annassign": ("children", GetChildrenMutation(expression_mutation)),
}

# TODO: detect regexes and mutate them in nasty ways? Maybe mutate all strings as if they are regexes
