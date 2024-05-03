# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
from typing import Any, Final, Tuple


from parso.tree import NodeOrLeaf, Node, Leaf, BaseNode
from parso.python.tree import ExprStmt

from mutmut.context import ALL, Context, RelativeMutationID
from mutmut.mutations import has_children, is_name_node, is_operator, mutations_by_type
from mutmut.parse import parse
from mutmut.setup_logging import configure_logger

# mutmut_config es la configuracion en forma de archivo python que define el usuario
mutmut_config: Any

if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())
try:
    import mutmut_config  # type: ignore  [import-not-found, no-redef]
except ImportError:
    mutmut_config = None

logger = configure_logger(__name__)

# We have a global whitelist for constants of the pattern __all__, __version__, etc

dunder_whitelist: Final[list[str]] = [
    'all',
    'version',
    'title',
    'package_name',
    'author',
    'description',
    'email',
    'version',
    'license',
    'copyright',
]


def mutate(context: Context) -> Tuple[str, int]:
    """
    :return: tuple of mutated source code and number of mutations performed
    """
    try:
        result = parse(context.source, error_recovery=False)
    except Exception:
        print('Failed to parse {}. Internal error from parso follows.'.format(context.filename))
        print('----------------------------------')
        raise
    mutate_list_of_nodes(result, context=context)
    mutated_source: str = result.get_code().replace(' not not ', ' ')
    if context.remove_newline_at_end:
        assert mutated_source[-1] == '\n'
        mutated_source = mutated_source[:-1]

    # If we said we mutated the code, check that it has actually changed
    if context.performed_mutation_ids:
        if context.source == mutated_source:
            raise RuntimeError(
                "Mutation context states that a mutation occurred but the "
                "mutated source remains the same as original")
    context.mutated_source = mutated_source
    return mutated_source, len(context.performed_mutation_ids)


def mutate_node(node: NodeOrLeaf, context: Context) -> None:
    assert isinstance(node, NodeOrLeaf)
    context.stack.append(node)
    try:
        if node.type in ('tfpdef', 'import_from', 'import_name'):
            return

        if node.type == 'atom_expr':
            assert isinstance(node, Node)
            if node.children:
                first_child = node.children[0]
                if is_name_node(first_child):
                    if first_child.value == '__import__':
                        return

        if node.start_pos[0] - 1 != context.current_line_index:
            context.current_line_index = node.start_pos[0] - 1
            context.index = 0  # indexes are unique per line, so start over here!

        if node.type == 'expr_stmt':
            assert isinstance(node, ExprStmt)
            if node.children:
                first_child = node.children[0]
                if is_name_node(first_child):
                    if first_child.value.startswith('__') and first_child.value.endswith('__') and first_child.value[2:-2] in dunder_whitelist:
                        return

        # Avoid mutating pure annotations
        if node.type == 'annassign':
            assert has_children(node)
            if len(node.children) == 2:
                return

        if has_children(node):
            mutate_list_of_nodes(node, context=context)

            # this is just an optimization to stop early
            if context.performed_mutation_ids and context.mutation_id != ALL:
                return

        mutation = mutations_by_type.get(node.type)

        if mutation is None:
            return

        for key, value in sorted(mutation.items()):
            old = getattr(node, key)
            if context.exclude_line():
                continue

            new = value(
                context=context,
                node=node,
                value=getattr(node, 'value', None),
                children=getattr(node, 'children', None),
            )

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
                    if hasattr(mutmut_config, 'pre_mutation_ast'):
                        mutmut_config.pre_mutation_ast(context=context)
                    if context.should_mutate(node):
                        context.performed_mutation_ids.append(context.mutation_id_of_current_index)
                        setattr(node, key, new)
                    context.index += 1
                # this is just an optimization to stop early
                if context.performed_mutation_ids and context.mutation_id != ALL:
                    return
    finally:
        context.stack.pop()


def mutate_list_of_nodes(node: BaseNode, context: Context) -> None:
    assert isinstance(node, BaseNode)
    return_annotation_started = False

    for child_node in node.children:
        if is_operator(child_node) and child_node.value == '->':
            return_annotation_started = True

        if return_annotation_started and is_operator(child_node) and child_node.value == ':':
            return_annotation_started = False

        if return_annotation_started:
            continue

        mutate_node(child_node, context=context)

        # this is just an optimization to stop early
        if context.performed_mutation_ids and context.mutation_id != ALL:
            return


def list_mutations(context: Context) -> list[RelativeMutationID]:
    assert context.mutation_id == ALL
    mutate(context)
    return context.performed_mutation_ids
