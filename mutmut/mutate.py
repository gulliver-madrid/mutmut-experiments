# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
from types import NoneType
from typing import Any, Final, NewType, Tuple, TYPE_CHECKING

from parso.tree import NodeOrLeaf, Node, BaseNode
from parso.python.tree import ExprStmt

from mutmut.context import ALL, Context, RelativeMutationID
from mutmut.mutations import has_children, is_name_node, is_operator, mutations_by_type
from mutmut.parse import parse_source
from mutmut.setup_logging import configure_logger


MUTMUT_CONFIG_NOT_DEFINED = 'Mutmut Config Not Defined'

_cached_mutmut_config: Any = MUTMUT_CONFIG_NOT_DEFINED
_cached_project_path: ProjectPath | None = None

ProjectPath = NewType('ProjectPath', Path)


def get_project_path() -> ProjectPath | None:
    '''It could to be None. In that case, calling code probably should use os.getcwd().'''
    return _cached_project_path


def set_project_path(project: str | Path | None = None) -> None:
    global _cached_project_path
    if isinstance(project, str):
        project = Path(project)
    project_path = ProjectPath(project.resolve()) if project is not None else None
    if project_path is not None:
        assert project_path.exists()
    _cached_project_path = project_path


def clear_mutmut_config_cache() -> None:
    global _cached_mutmut_config
    _cached_mutmut_config = MUTMUT_CONFIG_NOT_DEFINED


def get_mutmut_config(project: ProjectPath | None = None) -> Any:
    global _cached_mutmut_config
    # mutmut_config es la configuracion en forma de archivo python que define el usuario
    if _cached_mutmut_config != MUTMUT_CONFIG_NOT_DEFINED:
        return _cached_mutmut_config

    if project is not None:
        set_project_path(project)

    project = get_project_path()

    prev_path = sys.path[:]

    current_project_path_as_str = str(project) if project is not None else os.getcwd()
    assert Path(current_project_path_as_str).exists()

    if current_project_path_as_str not in sys.path:
        sys.path.insert(0, current_project_path_as_str)

    need_reload = "mutmut_config" in sys.modules

    if TYPE_CHECKING:
        mutmut_config: Any

    try:
        import mutmut_config  # type: ignore [import-not-found, no-redef]
    except ImportError:
        mutmut_config = None

    if mutmut_config and need_reload:
        try:
            importlib.reload(mutmut_config)
        except ImportError:
            mutmut_config = None

    _cached_mutmut_config = mutmut_config
    sys.path = prev_path
    return mutmut_config


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


def is_dunder_name(name: str) -> bool:
    return name.startswith('__') and name.endswith('__') and name[2:-2] in dunder_whitelist


def parse_checking_errors(source: str, filename: str | None) -> Any:
    try:
        result = parse_source(source, error_recovery=False)
    except Exception:
        print('Failed to parse {}. Internal error from parso follows.'.format(filename))
        print('----------------------------------')
        raise
    return result


def mutate_from_context(context: Context) -> Tuple[str, int]:
    """
    :return: tuple of mutated source code and number of mutations performed
    """
    result = parse_checking_errors(context.source, context.filename)
    _mutate_list_of_nodes(result, context=context)
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


def _mutate_node(node: NodeOrLeaf, context: Context) -> None:
    assert isinstance(node, NodeOrLeaf)
    mutmut_config = get_mutmut_config()
    context.stack.append(node)
    try:
        if node.type in ('tfpdef', 'import_from', 'import_name'):
            return

        if node.type == 'atom_expr':
            assert isinstance(node, Node)
            if node.children:
                first = node.children[0]
                if is_name_node(first) and first.value == '__import__':
                    return

        if node.start_pos[0] - 1 != context.current_line_index:
            context.current_line_index = node.start_pos[0] - 1
            context.index = 0  # indexes are unique per line, so start over here!

        if node.type == 'expr_stmt':
            assert isinstance(node, ExprStmt)
            if node.children:
                first = node.children[0]
                if is_name_node(first) and is_dunder_name(first.value):
                    return

        # Avoid mutating pure annotations
        if node.type == 'annassign':
            assert has_children(node)
            if len(node.children) == 2:
                return

        if has_children(node):
            _mutate_list_of_nodes(node, context=context)

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

            new: object = value(
                context=context,
                node=node,
                value=getattr(node, 'value', None),
                children=getattr(node, 'children', None),
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



def _mutate_list_of_nodes(node: BaseNode, context: Context) -> None:
    assert isinstance(node, BaseNode)
    return_annotation_started = False

    for child_node in node.children:
        if is_operator(child_node) and child_node.value == '->':
            return_annotation_started = True

        if return_annotation_started and is_operator(child_node) and child_node.value == ':':
            return_annotation_started = False

        if return_annotation_started:
            continue

        _mutate_node(child_node, context=context)

        # this is just an optimization to stop early
        if context.performed_mutation_ids and context.mutation_id != ALL:
            return


def list_mutations(context: Context) -> list[RelativeMutationID]:
    assert context.mutation_id == ALL
    mutate_from_context(context)
    return context.performed_mutation_ids
