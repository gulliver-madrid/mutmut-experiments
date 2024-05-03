# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from types import NoneType
from typing import Any, Callable, Final, Mapping, Tuple, TypedDict, TypeGuard

from parso.python.tree import Name, Number, Keyword, FStringStart, FStringEnd, Module, Operator, PythonLeaf
from parso.python.prefix import PrefixPart
from parso.tree import Node, BaseNode, Leaf, NodeOrLeaf

from mutmut.context import Context
from mutmut.parse import parse
from mutmut.setup_logging import configure_logger


logger = configure_logger(__name__)


class Marker(TypedDict):
    node: NodeOrLeaf
    marker_type: str | None
    name: str


class InvalidASTPatternException(Exception):
    pass


def is_operator(node: NodeOrLeaf) -> TypeGuard[Operator]:
    return node.type == 'operator'


def is_name_node(node: NodeOrLeaf) -> TypeGuard[Name]:
    return node.type == 'name'


def has_children(node: object) -> TypeGuard[BaseNode]:
    if not hasattr(node, 'children'):
        return False
    assert isinstance(node, BaseNode)
    return True


class ASTPattern:
    def __init__(self, source: str, **definitions: Any):
        source = source.strip()

        self.definitions = definitions

        self.module: Module = parse(source)

        self.markers: list[Marker] = []

        def get_leaf(line: int, column: int, of_type: str | None = None) -> NodeOrLeaf:
            assert isinstance(of_type, (str, NoneType))
            first = self.module.children[0]
            assert isinstance(first, BaseNode)
            node: Any = first.get_leaf_for_position((line, column))  # pyright: ignore [reportUnknownMemberType]
            assert isinstance(node, NodeOrLeaf)
            while of_type is not None and node.type != of_type:
                node = node.parent
                assert node is not None
            assert isinstance(node, NodeOrLeaf)
            return node

        def parse_markers(node: PrefixPart | Module | NodeOrLeaf) -> None:
            assert isinstance(node, (PrefixPart, Module, NodeOrLeaf))
            if hasattr(node, '_split_prefix'):
                # logger.info("slpit prefix:" + str(type(node)))
                assert isinstance(node, PythonLeaf), type(node)
                for x in node._split_prefix():  # pyright: ignore [reportPrivateUsage]
                    parse_markers(x)

            if has_children(node):
                for x in node.children:
                    parse_markers(x)

            if node.type == 'comment':
                line, column = node.start_pos
                assert isinstance(node, PrefixPart), node
                for match in re.finditer(r'\^(?P<value>[^\^]*)', node.value):
                    name = match.groupdict()['value'].strip()
                    d = definitions.get(name, {})
                    assert set(d.keys()) | {'of_type', 'marker_type'} == {'of_type', 'marker_type'}
                    marker_type = d.get('marker_type')
                    assert isinstance(marker_type, (NoneType, str)), type(marker_type)
                    self.markers.append(Marker(
                        node=get_leaf(line - 1, column + match.start(), of_type=d.get('of_type')),
                        marker_type=marker_type,
                        name=name,
                    ))

        parse_markers(self.module)

        pattern_nodes = [x['node'] for x in self.markers if x['name'] == 'match' or x['name'] == '']
        if len(pattern_nodes) != 1:
            raise InvalidASTPatternException("Found more than one match node. Match nodes are nodes with an empty name or with the explicit name 'match'")
        self.pattern = pattern_nodes[0]
        assert isinstance(self.pattern, NodeOrLeaf)  # guess
        self.marker_type_by_id = {id(x['node']): x['marker_type'] for x in self.markers}

    def matches(self, node: NodeOrLeaf, pattern: NodeOrLeaf | None = None, skip_child: NodeOrLeaf | None = None) -> bool:

        assert isinstance(node, NodeOrLeaf)
        assert isinstance(pattern, (NodeOrLeaf, NoneType))
        assert isinstance(skip_child, (NodeOrLeaf, NoneType))
        if pattern is None:
            pattern = self.pattern

        check_value = True
        check_children = True

        assert pattern is not None

        # Match type based on the name, so _keyword matches all keywords.
        # Special case for _all that matches everything
        if (
           is_name_node(pattern)
            and pattern.value.startswith('_') and pattern.value[1:] in ('any', node.type)
           ):
            check_value = False

        # The advanced case where we've explicitly marked up a node with
        # the accepted types
        elif id(pattern) in self.marker_type_by_id:
            if self.marker_type_by_id[id(pattern)] in (pattern.type, 'any'):
                check_value = False
                check_children = False  # TODO: really? or just do this for 'any'?

        # Check node type strictly
        elif pattern.type != node.type:
            return False

        # Match children
        if check_children and has_children(pattern):
            assert isinstance(node, BaseNode)
            if len(pattern.children) != len(node.children):
                return False

            for pattern_child, node_child in zip(pattern.children, node.children):
                if node_child is skip_child:  # prevent infinite recursion
                    continue

                if not self.matches(node=node_child, pattern=pattern_child, skip_child=node_child):
                    return False

        # Node value
        if check_value and hasattr(pattern, 'value'):
            assert isinstance(pattern, Leaf)
            assert isinstance(node, Leaf)
            if pattern.value != node.value:
                return False

        # Parent
        assert pattern.parent is not None
        if pattern.parent.type != 'file_input':  # top level matches nothing
            if skip_child != node:
                assert node.parent is not None
                return self.matches(node=node.parent, pattern=pattern.parent, skip_child=node)

        return True


class SkipException(Exception):
    pass


def number_mutation(value: str, **_: Any) -> str:
    assert isinstance(value, str)
    suffix = ''
    if value.upper().endswith('L'):  # pragma: no cover (python 2 specific)
        suffix = value[-1]
        value = value[:-1]

    if value.upper().endswith('J'):
        suffix = value[-1]
        value = value[:-1]

    if value.startswith('0o'):
        base = 8
        value = value[2:]
    elif value.startswith('0x'):
        base = 16
        value = value[2:]
    elif value.startswith('0b'):
        base = 2
        value = value[2:]
    elif value.startswith('0') and len(value) > 1 and value[1] != '.':  # pragma: no cover (python 2 specific)
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


def string_mutation(value: str, **_: Any) -> str:
    assert isinstance(value, str)
    prefix = value[:min(x for x in [value.find('"'), value.find("'")] if x != -1)]
    value = value[len(prefix):]

    if value.startswith('"""') or value.startswith("'''"):
        # We assume here that triple-quoted stuff are docs or other things
        # that mutation is meaningless for
        return prefix + value
    return prefix + value[0] + 'XX' + value[1:-1] + 'XX' + value[-1]


def fstring_mutation(children: list[NodeOrLeaf], **_: Any) -> list[NodeOrLeaf]:
    fstring_start = children[0]
    fstring_end = children[-1]
    assert isinstance(fstring_start, FStringStart)
    assert isinstance(fstring_end, FStringEnd)

    children = children[:]  # we need to copy the list here, to not get in place mutation on the next line!

    children[0] = FStringStart(fstring_start.value + 'XX',
                               start_pos=fstring_start.start_pos,
                               prefix=fstring_start.prefix)

    children[-1] = FStringEnd('XX' + fstring_end.value,
                              start_pos=fstring_end.start_pos,
                              prefix=fstring_end.prefix)

    return children


def partition_node_list(nodes: list[NodeOrLeaf], value: str | None) -> Tuple[list[NodeOrLeaf], Leaf, list[NodeOrLeaf]]:
    assert isinstance(value, (str, NoneType))
    for i, n in enumerate(nodes):
        assert isinstance(n, NodeOrLeaf)
        if hasattr(n, 'value'):
            assert isinstance(n, Leaf)
            if n.value == value:
                return nodes[:i], n, nodes[i + 1:]

    assert False, "didn't find node to split on"


def lambda_mutation(children: list[NodeOrLeaf], **_: Any) -> list[NodeOrLeaf]:
    pre, op, post = partition_node_list(children, value=':')

    if len(post) == 1 and getattr(post[0], 'value', None) == 'None':
        return pre + [op] + [Number(value=' 0', start_pos=post[0].start_pos)]
    else:
        return pre + [op] + [Keyword(value=' None', start_pos=post[0].start_pos)]


# unused: NEWLINE = {'formatting': [], 'indent': '', 'type': 'endl', 'value': ''}


def argument_mutation(children: list[NodeOrLeaf], context: Context, **_: Any) -> list[NodeOrLeaf] | None:
    """Mutate the arguments one by one from dict(a=b) to dict(aXXX=b).

    This is similar to the mutation of dict literals in the form {'a': b}.
    """

    assert all(isinstance(child, NodeOrLeaf) for child in children)
    if len(context.stack) >= 3 and context.stack[-3].type in ('power', 'atom_expr'):
        stack_pos_of_power_node = -3
    elif len(context.stack) >= 4 and context.stack[-4].type in ('power', 'atom_expr'):
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
            children[0] = Name(c.value + 'XX', start_pos=c.start_pos, prefix=c.prefix)
            return children
    return None


def keyword_mutation(value: str, context: Context, **_: Any) -> str | None:
    if len(context.stack) > 2 and context.stack[-2].type in ('comp_op', 'sync_comp_for') and value in ('in', 'is'):
        return None

    if len(context.stack) > 1 and context.stack[-2].type == 'for_stmt':
        return None

    return {
        # 'not': 'not not',
        'not': '',
        'is': 'is not',  # this will cause "is not not" sometimes, so there's a hack to fix that later
        'in': 'not in',
        'break': 'continue',
        'continue': 'break',
        'True': 'False',
        'False': 'True',
    }.get(value)


import_from_star_pattern = ASTPattern("""
from _name import *
#                 ^
""")


def operator_mutation(value: str, node: Leaf, **_: Any) -> str | list[str] | None:
    assert isinstance(node, Leaf)
    if import_from_star_pattern.matches(node=node):
        return None

    if (
        value in ('*', '**')
        and node.parent  # always true
        and node.parent.type == 'param'
    ):
        return None

    if (
        value == '*'
        and node.parent  # always true
        and node.parent.type == 'parameters'
    ):
        return None

    if (
        value in ('*', '**')
        and node.parent  # always true
        and node.parent.type in ('argument', 'arglist')
    ):
        return None
    data: Mapping[str, str | list[str]] = {
        '+': '-',
        '-': '+',
        '*': '/',
        '/': '*',
        '//': '/',
        '%': '/',
        '<<': '>>',
        '>>': '<<',
        '&': '|',
        '|': '&',
        '^': '&',
        '**': '*',
        '~': '',

        '+=': ['-=', '='],
        '-=': ['+=', '='],
        '*=': ['/=', '='],
        '/=': ['*=', '='],
        '//=': ['/=', '='],
        '%=': ['/=', '='],
        '<<=': ['>>=', '='],
        '>>=': ['<<=', '='],
        '&=': ['|=', '='],
        '|=': ['&=', '='],
        '^=': ['&=', '='],
        '**=': ['*=', '='],
        '~=': '=',

        '<': '<=',
        '<=': '<',
        '>': '>=',
        '>=': '>',
        '==': '!=',
        '!=': '==',
        '<>': '==',
    }
    return data.get(value)


def and_or_test_mutation(children: list[Leaf], node: Node, **_: Any) -> list[Leaf]:
    assert isinstance(node, Node)
    assert all(isinstance(child, Leaf) for child in children)
    children = children[:]
    children[1] = Keyword(
        value={'and': ' or', 'or': ' and'}[children[1].value],
        start_pos=node.start_pos,
    )
    return children


def expression_mutation(children: list[NodeOrLeaf], **_: Any) -> list[NodeOrLeaf]:
    assert all(isinstance(child, NodeOrLeaf) for child in children)

    def handle_assignment(children: list[NodeOrLeaf]) -> list[NodeOrLeaf]:
        mutation_index = -1  # we mutate the last value to handle multiple assignement
        if getattr(children[mutation_index], 'value', '---') != 'None':
            x = ' None'
        else:
            x = ' ""'
        children = children[:]
        children[mutation_index] = Name(value=x, start_pos=children[mutation_index].start_pos)

        return children

    if is_operator(children[0]) and children[0].value == ':':
        if (
            len(children) > 2
            and is_operator(children[2])  # always true
            and children[2].value == '='
        ):
            children = children[:]  # we need to copy the list here, to not get in place mutation on the next line!
            children[1:] = handle_assignment(children[1:])
    elif is_operator(children[1]) and children[1].value == '=':
        children = handle_assignment(children)

    return children


def decorator_mutation(children: list[NodeOrLeaf], **_: Any) -> list[NodeOrLeaf]:
    assert all(isinstance(child, NodeOrLeaf) for child in children), children
    assert children[-1].type == 'newline'
    return children[-1:]


array_subscript_pattern = ASTPattern("""
_name[_any]
#       ^
""")


function_call_pattern = ASTPattern("""
_name(_any)
#       ^
""")


def name_mutation(node: Leaf | None, value: str, **_: Any) -> str | None:
    assert isinstance(value, str)
    assert isinstance(node, (Leaf, NoneType))  # guess
    simple_mutants = {
        'True': 'False',
        'False': 'True',
        'deepcopy': 'copy',
        'None': '""',
        # TODO: probably need to add a lot of things here... some builtins maybe, what more?
    }
    if value in simple_mutants:
        return simple_mutants[value]

    assert node is not None  # guess

    if array_subscript_pattern.matches(node=node):
        return 'None'

    if function_call_pattern.matches(node=node):
        return 'None'

    return None


mutations_by_type: Final[Mapping[str, Mapping[str, Callable[..., Any]]]] = {
    'operator': dict(value=operator_mutation),
    'keyword': dict(value=keyword_mutation),
    'number': dict(value=number_mutation),
    'name': dict(value=name_mutation),
    'string': dict(value=string_mutation),
    'fstring': dict(children=fstring_mutation),
    'argument': dict(children=argument_mutation),
    'or_test': dict(children=and_or_test_mutation),
    'and_test': dict(children=and_or_test_mutation),
    'lambdef': dict(children=lambda_mutation),
    'expr_stmt': dict(children=expression_mutation),
    'decorator': dict(children=decorator_mutation),
    'annassign': dict(children=expression_mutation),
}

# TODO: detect regexes and mutate them in nasty ways? Maybe mutate all strings as if they are regexes
