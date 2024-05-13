# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from types import NoneType
from typing import Any, TypedDict, TypeGuard

from parso.python.tree import (
    Name,
    Module,
    PythonLeaf,
)
from parso.python.prefix import PrefixPart
from parso.tree import BaseNode, Leaf, NodeOrLeaf

from src.parse import parse_source


class InvalidASTPatternException(Exception):
    pass


class Marker(TypedDict):
    node: NodeOrLeaf
    marker_type: str | None
    name: str


def has_children(node: object) -> TypeGuard[BaseNode]:
    if not hasattr(node, "children"):
        return False
    assert isinstance(node, BaseNode)
    return True


def is_name_node(node: NodeOrLeaf) -> TypeGuard[Name]:
    return node.type == "name"


class ASTPattern:
    def __init__(self, source: str, **definitions: Any):
        source = source.strip()

        self.definitions = definitions

        self.module: Module = parse_source(source)

        self.markers: list[Marker] = []

        def get_leaf(line: int, column: int, of_type: str | None = None) -> NodeOrLeaf:
            assert isinstance(of_type, (str, NoneType))
            first = self.module.children[0]
            assert isinstance(first, BaseNode)
            node = first.get_leaf_for_position((line, column))  # type: ignore [no-untyped-call]
            assert isinstance(node, NodeOrLeaf)
            while of_type is not None and node.type != of_type:
                node = node.parent
                assert node is not None
            assert isinstance(node, NodeOrLeaf)
            return node

        def parse_markers(node: PrefixPart | Module | NodeOrLeaf) -> None:
            assert isinstance(node, (PrefixPart, Module, NodeOrLeaf))
            if hasattr(node, "_split_prefix"):
                assert isinstance(node, PythonLeaf), type(node)
                for x in node._split_prefix():  # type: ignore [no-untyped-call]
                    parse_markers(x)

            if has_children(node):
                for x in node.children:
                    parse_markers(x)

            if node.type == "comment":
                line, column = node.start_pos
                assert isinstance(node, PrefixPart), node
                for match in re.finditer(r"\^(?P<value>[^\^]*)", node.value):
                    name = match.groupdict()["value"].strip()
                    d = definitions.get(name, {})
                    assert set(d.keys()) | {"of_type", "marker_type"} == {
                        "of_type",
                        "marker_type",
                    }
                    marker_type = d.get("marker_type")
                    assert isinstance(marker_type, (NoneType, str)), type(marker_type)
                    self.markers.append(
                        Marker(
                            node=get_leaf(
                                line - 1,
                                column + match.start(),
                                of_type=d.get("of_type"),
                            ),
                            marker_type=marker_type,
                            name=name,
                        )
                    )

        parse_markers(self.module)

        pattern_nodes = [
            x["node"] for x in self.markers if x["name"] == "match" or x["name"] == ""
        ]
        if len(pattern_nodes) != 1:
            raise InvalidASTPatternException(
                "Found more than one match node. Match nodes are nodes with an empty name or with the explicit name 'match'"
            )
        self.pattern = pattern_nodes[0]
        assert isinstance(self.pattern, NodeOrLeaf)  # guess
        self.marker_type_by_id = {id(x["node"]): x["marker_type"] for x in self.markers}

    def matches(
        self,
        node: NodeOrLeaf,
        pattern: NodeOrLeaf | None = None,
        skip_child: NodeOrLeaf | None = None,
    ) -> bool:

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
            and pattern.value.startswith("_")
            and pattern.value[1:] in ("any", node.type)
        ):
            check_value = False

        # The advanced case where we've explicitly marked up a node with
        # the accepted types
        elif id(pattern) in self.marker_type_by_id:
            if self.marker_type_by_id[id(pattern)] in (pattern.type, "any"):
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

                if not self.matches(
                    node=node_child, pattern=pattern_child, skip_child=node_child
                ):
                    return False

        # Node value
        if check_value and hasattr(pattern, "value"):
            assert isinstance(pattern, Leaf)
            assert isinstance(node, Leaf)
            if pattern.value != node.value:
                return False

        # Parent
        assert pattern.parent is not None
        if pattern.parent.type != "file_input":  # top level matches nothing
            if skip_child != node:
                assert node.parent is not None
                return self.matches(
                    node=node.parent, pattern=pattern.parent, skip_child=node
                )

        return True
