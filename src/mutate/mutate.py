# -*- coding: utf-8 -*-
from __future__ import annotations

from types import NoneType
from typing import Any, Tuple

from parso.tree import NodeOrLeaf, Node, BaseNode, Leaf
from parso.python.tree import ExprStmt

from src.context import ALL, Context, RelativeMutationID
from src.mutations import (
    has_children,
    is_name_node,
    is_operator,
    mutations_by_type,
)
from src.mutations.mutations import LeafMutation, NodeWithChildrenMutation
from src.parse import parse_source
from src.tools import configure_logger
from src.shared import FilenameStr
from src.storage import storage

from .dunder import is_dunder_name


logger = configure_logger(__name__)


def list_mutations(context: Context) -> list[RelativeMutationID]:
    assert context.mutation_id == ALL
    mutate_from_context(context)
    return context.performed_mutation_ids


def mutate_from_context(context: Context) -> Tuple[str, int]:
    """
    :return: tuple of mutated source code and number of mutations performed
    """
    result = _parse_checking_errors(context.source, context.filename)
    _mutate_list_of_nodes(result, context=context)
    mutated_source: str = result.get_code().replace(" not not ", " ")
    if context.remove_newline_at_end:
        assert mutated_source[-1] == "\n"
        mutated_source = mutated_source[:-1]

    # If we said we mutated the code, check that it has actually changed
    if context.performed_mutation_ids:
        if context.source == mutated_source:
            raise RuntimeError(
                "Mutation context states that a mutation occurred but the "
                "mutated source remains the same as original"
            )
    context.mutated_source = mutated_source
    return mutated_source, len(context.performed_mutation_ids)


def _mutate_node(node: NodeOrLeaf, context: Context) -> None:
    assert isinstance(node, NodeOrLeaf)
    dynamic_config = storage.dynamic_config.get_dynamic_config()
    context.stack.append(node)
    try:
        if node.type in ("tfpdef", "import_from", "import_name"):
            return

        if node.type == "atom_expr":
            assert isinstance(node, Node)
            if node.children:
                first = node.children[0]
                if is_name_node(first) and first.value == "__import__":
                    return

        if node.start_pos[0] - 1 != context.current_line_index:
            context.current_line_index = node.start_pos[0] - 1
            context.index = 0  # indexes are unique per line, so start over here!

        if node.type == "expr_stmt":
            assert isinstance(node, ExprStmt)
            if node.children:
                first = node.children[0]
                if is_name_node(first) and is_dunder_name(first.value):
                    return

        # Avoid mutating pure annotations
        if node.type == "annassign":
            assert has_children(node)
            if len(node.children) == 2:
                return

        if has_children(node):
            _mutate_list_of_nodes(node, context=context)

            # this is just an optimization to stop early
            if context.performed_mutation_ids and context.mutation_id != ALL:
                return

        mutation_shape = mutations_by_type.get(node.type)

        if mutation_shape is None:
            return

        assert isinstance(mutation_shape, tuple), mutation_shape
        assert len(mutation_shape) == 2

        input_type, mutation = mutation_shape

        assert callable(mutation)

        old = getattr(node, input_type)
        if context.exclude_line():
            return

        value = getattr(node, "value", None)
        children = getattr(node, "children", None)
        assert value or children
        assert value is None or children is None

        new: object = None
        if value:
            assert isinstance(node, Leaf)
            assert isinstance(node.value, str)
            assert isinstance(mutation, LeafMutation)
            new = mutation(
                context=context,
                node=node,
                value=node.value,
            )
        else:
            assert children
            assert has_children(node)
            assert isinstance(mutation, NodeWithChildrenMutation)
            new = mutation(
                context=context,
                node=node,
                children=node.children,
            )

        assert isinstance(new, (str, list, NoneType))

        if isinstance(new, list) and not isinstance(old, list):
            # multiple mutations
            new_list = new
        else:
            # one mutation
            new_list = [new]

        # go through the alternate mutations in reverse as they may have
        # adverse effects on subsequent mutations, this ensures the last
        # mutation applied is the original/default/legacy mutmut mutation
        for new in reversed(new_list):
            assert not callable(new)
            if new is not None and new != old:
                if hasattr(dynamic_config, "pre_mutation_ast"):
                    dynamic_config.pre_mutation_ast(context=context)
                if context.should_mutate(node):
                    context.performed_mutation_ids.append(
                        context.mutation_id_of_current_index
                    )
                    setattr(node, input_type, new)
                context.index += 1
            # this is just an optimization to stop early
            if context.performed_mutation_ids and context.mutation_id != ALL:
                return
    finally:
        context.stack.pop()


def _parse_checking_errors(source: str, filename: FilenameStr | None) -> Any:
    try:
        result = parse_source(source, error_recovery=False)
    except Exception:
        print("Failed to parse {}. Internal error from parso follows.".format(filename))
        print("----------------------------------")
        raise
    return result


def _mutate_list_of_nodes(node: BaseNode, context: Context) -> None:
    assert isinstance(node, BaseNode)
    return_annotation_started = False

    for child_node in node.children:
        if is_operator(child_node) and child_node.value == "->":
            return_annotation_started = True

        if (
            return_annotation_started
            and is_operator(child_node)
            and child_node.value == ":"
        ):
            return_annotation_started = False

        if return_annotation_started:
            continue

        _mutate_node(child_node, context=context)

        # this is just an optimization to stop early
        if context.performed_mutation_ids and context.mutation_id != ALL:
            return
