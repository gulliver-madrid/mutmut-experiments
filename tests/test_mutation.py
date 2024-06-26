# -*- coding: utf-8 -*-

import pytest


from src.context import ALL, Context, RelativeMutationID
from src.mutate import mutate_from_context, list_mutations
from src.mutations import (
    array_subscript_pattern,
    function_call_pattern,
    ASTPattern,
)
from src.parse import parse_source
from src.utils import SequenceStr, split_lines


def test_matches_py3() -> None:
    node = (
        parse_source("a: Optional[int] = 7\n")
        .children[0]
        .children[0]
        .children[1]
        .children[1]
        .children[1]
        .children[1]
    )
    assert not array_subscript_pattern.matches(node=node)


def test_matches() -> None:
    node = parse_source("from foo import bar").children[0]
    assert not array_subscript_pattern.matches(node=node)
    assert not function_call_pattern.matches(node=node)
    assert not array_subscript_pattern.matches(node=node)
    assert not function_call_pattern.matches(node=node)

    node = parse_source("foo[bar]\n").children[0].children[0].children[1].children[1]
    assert array_subscript_pattern.matches(node=node)

    node = parse_source("foo(bar)\n").children[0].children[0].children[1].children[1]
    assert function_call_pattern.matches(node=node)


def test_ast_pattern_for_loop() -> None:
    p = ASTPattern(
        """
for x in y:
#   ^ n  ^ match
    pass
    # ^ x
""",
        x=dict(
            of_type="simple_stmt",
            marker_type="any",
        ),
        n=dict(
            marker_type="name",
        ),
        match=dict(
            marker_type="any",
        ),
    )

    n = (
        parse_source(
            """for a in [1, 2, 3]:
    if foo:
        continue
"""
        )
        .children[0]
        .children[3]
    )
    assert p.matches(node=n)

    n = (
        parse_source(
            """for a, b in [1, 2, 3]:
    if foo:
        continue
"""
        )
        .children[0]
        .children[3]
    )
    assert p.matches(node=n)


@pytest.mark.parametrize(
    "original, expected",
    [
        ("lambda: 0", "lambda: None"),
        ("a(b)", "a(None)"),
        ("a[b]", "a[None]"),
        ("1 in (1, 2)", "2 not in (2, 3)"),
        ("1+1", "2-2"),
        ("1", "2"),
        ("1-1", "2+2"),
        ("1*1", "2/2"),
        ("1/1", "2*2"),
        # ('1.0', '1.0000000000000002'),  # using numpy features
        ("1.0", "2.0"),
        ("0.1", "1.1"),
        ("1e-3", "1.001"),
        ("1e16", "2e+16"),
        ("True", "False"),
        ("False", "True"),
        ('"foo"', '"XXfooXX"'),
        ("'foo'", "'XXfooXX'"),
        ("u'foo'", "u'XXfooXX'"),
        ("f'foo'", "f'XXfooXX'"),
        ("f'foo'", "f'XXfooXX'"),
        ('f"foo"', 'f"XXfooXX"'),
        ("f'''foo'''", "f'''XXfooXX'''"),
        ("f'{foo}'", "f'XX{foo}XX'"),
        ('f"""fo\no"""', 'f"""XXfo\noXX"""'),
        ("fr'foo'", "fr'XXfooXX'"),
        ("rf'foo'", "rf'XXfooXX'"),
        ("return f'foo'", "return f'XXfooXX'"),
        ("foo(f'foo', abcd)", "foo(f'XXfooXX', abcd)"),
        ("0", "1"),
        ("0o0", "1"),
        ("0.", "1.0"),
        ("0x0", "1"),
        ("0b0", "1"),
        ("1<2", "2<=3"),
        ("(1, 2)", "(2, 3)"),
        (
            "1 not in (1, 2)",
            "2  in (2, 3)",
        ),  # two spaces here because "not in" is two words
        ("foo is foo", "foo is not foo"),
        ("foo is not foo", "foo is  foo"),
        ("x if a else b", "x if a else b"),
        ("a or b", "a and b"),
        ("a and b", "a or b"),
        ("a = b", "a = None"),
        ("a = b = c = x", "a = b = c = None"),
        ("s[0]", "s[1]"),
        ("s[0] = a", "s[1] = None"),
        ("s[x]", "s[None]"),
        ("s[1:]", "s[2:]"),
        ("1j", "2j"),
        ("1.0j", "2.0j"),
        ("0o1", "2"),
        ("1.0e10", "20000000000.0"),
        ("1.1e-16", "2.2e-16"),
        ("dict(a=b)", "dict(aXX=b)"),
        ("Struct(a=b)", "Struct(aXX=b)"),
        ("FooBarDict(a=b)", "FooBarDict(aXX=b)"),
        (
            "lambda **kwargs: Variable.integer(**setdefaults(kwargs, dict(show=False)))",
            "lambda **kwargs: None",
        ),
        ("a = {x for x in y}", "a = None"),
        ("break", "continue"),
    ],
)
def test_basic_mutations(original: str, expected: str) -> None:
    actual, number_of_performed_mutations = mutate_from_context(
        Context(
            source=original, mutation_id=ALL, dict_synonyms=["Struct", "FooBarDict"]
        )
    )
    assert actual == expected, 'Performed {} mutations for original "{}"'.format(
        number_of_performed_mutations, original
    )


def test_fstring_mutation_fstring_is_mutated_separately_from_other_mutations() -> None:
    # arrange
    original = "f'fo{x == 1}o'"
    expected_mutations = ["f'fo{x != 1}o'", "f'fo{x == 2}o'", "f'XXfo{x == 1}oXX'"]

    # act
    actual_mutations = [
        mutate_from_context(Context(source=original, mutation_id=mutation))[0]
        for mutation in list_mutations(Context(source=original))
    ]

    # assert
    assert actual_mutations == expected_mutations


@pytest.mark.parametrize(
    "original, expected",
    [
        ("x+=1", ["x=1", "x-=1"]),
        ("x-=1", ["x=1", "x+=1"]),
        ("x*=1", ["x=1", "x/=1"]),
        ("x/=1", ["x=1", "x*=1"]),
        ("x//=1", ["x=1", "x/=1"]),
        ("x%=1", ["x=1", "x/=1"]),
        ("x<<=1", ["x=1", "x>>=1"]),
        ("x>>=1", ["x=1", "x<<=1"]),
        ("x&=1", ["x=1", "x|=1"]),
        ("x|=1", ["x=1", "x&=1"]),
        ("x^=1", ["x=1", "x&=1"]),
        ("x**=1", ["x=1", "x*=1"]),
    ],
)
def test_multiple_mutations(original: str, expected: SequenceStr) -> None:
    mutations = list_mutations(Context(source=original))
    assert len(mutations) == 3
    assert mutate_from_context(Context(source=original, mutation_id=mutations[0])) == (
        expected[0],
        1,
    )
    assert mutate_from_context(Context(source=original, mutation_id=mutations[1])) == (
        expected[1],
        1,
    )


@pytest.mark.parametrize(
    "original, expected",
    [
        ("a: int = 1", "a: int = None"),
        ("a: Optional[int] = None", 'a: Optional[int] = ""'),
        ("def foo(s: Int = 1): pass", "def foo(s: Int = 2): pass"),
        ("a = None", 'a = ""'),
        ("lambda **kwargs: None", "lambda **kwargs: 0"),
        ("lambda: None", "lambda: 0"),
    ],
)
def test_basic_mutations_python3(original: str, expected: str) -> None:
    actual = mutate_from_context(
        Context(
            source=original, mutation_id=ALL, dict_synonyms=["Struct", "FooBarDict"]
        )
    )[0]
    assert actual == expected


@pytest.mark.parametrize(
    "original, expected",
    [
        ("a: int = 1", "a: int = None"),
        ("a: Optional[int] = None", 'a: Optional[int] = ""'),
    ],
)
def test_basic_mutations_python36(original: str, expected: str) -> None:
    actual = mutate_from_context(
        Context(
            source=original, mutation_id=ALL, dict_synonyms=["Struct", "FooBarDict"]
        )
    )[0]
    assert actual == expected


@pytest.mark.parametrize(
    "source",
    [
        "foo(a, *args, **kwargs)",
        "'''foo'''",  # don't mutate things we assume to be docstrings
        "r'''foo'''",  # don't mutate things we assume to be docstrings
        "(x for x in [])",  # don't mutate 'in' in generators
        "NotADictSynonym(a=b)",
        "from foo import *",
        "from .foo import *",
        "import foo",
        "import foo as bar",
        "foo.bar",
        "for x in y: pass",
        "def foo(a, *args, **kwargs): pass",
        "import foo",
    ],
)
def test_do_not_mutate(source: str) -> None:
    actual = mutate_from_context(
        Context(source=source, mutation_id=ALL, dict_synonyms=["Struct", "FooBarDict"])
    )[0]
    assert actual == source


@pytest.mark.parametrize(
    "source",
    [
        "def foo(s: str): pass",
        "def foo(a, *, b): pass",
        "a[None]",
        "a(None)",
    ],
)
def test_do_not_mutate_python3(source: str) -> None:
    actual = mutate_from_context(
        Context(source=source, mutation_id=ALL, dict_synonyms=["Struct", "FooBarDict"])
    )[0]
    assert actual == source


def test_mutate_body_of_function_with_return_type_annotation() -> None:
    source = """
def foo() -> int:
    return 0
    """

    assert mutate_from_context(Context(source=source, mutation_id=ALL))[
        0
    ] == source.replace("0", "1")


def test_mutate_all() -> None:
    assert mutate_from_context(
        Context(source="def foo():\n    return 1+1", mutation_id=ALL)
    ) == ("def foo():\n    return 2-2", 3)


def test_mutate_both() -> None:
    source = "a = b + c"
    mutations = list_mutations(Context(source=source))
    assert len(mutations) == 2
    assert mutate_from_context(Context(source=source, mutation_id=mutations[0])) == (
        "a = b - c",
        1,
    )
    assert mutate_from_context(Context(source=source, mutation_id=mutations[1])) == (
        "a = None",
        1,
    )


def test_perform_one_indexed_mutation() -> None:
    assert mutate_from_context(
        Context(
            source="1+1",
            mutation_id=RelativeMutationID(line="1+1", index=0, line_number=0),
        )
    ) == ("2+1", 1)
    assert mutate_from_context(
        Context(source="1+1", mutation_id=RelativeMutationID("1+1", 1, line_number=0))
    ) == ("1-1", 1)
    assert mutate_from_context(
        Context(source="1+1", mutation_id=RelativeMutationID("1+1", 2, line_number=0))
    ) == ("1+2", 1)

    # TODO: should this case raise an exception?
    # assert mutate(Context(source='def foo():\n    return 1', mutation_id=2)) == ('def foo():\n    return 1\n', 0)


def test_function() -> None:
    source = "def capitalize(s):\n    return s[0].upper() + s[1:] if s else s\n"
    assert mutate_from_context(
        Context(
            source=source,
            mutation_id=RelativeMutationID(split_lines(source)[1], 0, line_number=1),
        )
    ) == ("def capitalize(s):\n    return s[1].upper() + s[1:] if s else s\n", 1)
    assert mutate_from_context(
        Context(
            source=source,
            mutation_id=RelativeMutationID(split_lines(source)[1], 1, line_number=1),
        )
    ) == ("def capitalize(s):\n    return s[0].upper() - s[1:] if s else s\n", 1)
    assert mutate_from_context(
        Context(
            source=source,
            mutation_id=RelativeMutationID(split_lines(source)[1], 2, line_number=1),
        )
    ) == ("def capitalize(s):\n    return s[0].upper() + s[2:] if s else s\n", 1)


def test_function_with_annotation() -> None:
    source = "def capitalize(s : str):\n    return s[0].upper() + s[1:] if s else s\n"
    assert mutate_from_context(
        Context(
            source=source,
            mutation_id=RelativeMutationID(split_lines(source)[1], 0, line_number=1),
        )
    ) == ("def capitalize(s : str):\n    return s[1].upper() + s[1:] if s else s\n", 1)


def test_pragma_no_mutate() -> None:
    source = """def foo():\n    return 1+1  # pragma: no mutate\n"""
    assert mutate_from_context(Context(source=source, mutation_id=ALL)) == (source, 0)


def test_pragma_no_mutate_and_no_cover() -> None:
    source = """def foo():\n    return 1+1  # pragma: no cover, no mutate\n"""
    assert mutate_from_context(Context(source=source, mutation_id=ALL)) == (source, 0)


def test_mutate_decorator() -> None:
    source = """@foo\ndef foo():\n    pass\n"""
    assert mutate_from_context(Context(source=source, mutation_id=ALL)) == (
        source.replace("@foo", ""),
        1,
    )


# TODO: getting this test and the above to both pass is tricky
# def test_mutate_decorator2():
#     source = """\"""foo\"""\n\n@foo\ndef foo():\n    pass\n"""
#     assert mutate(Context(source=source, mutation_id=ALL)) == (source.replace('@foo', ''), 1)


def test_mutate_dict() -> None:
    source = "dict(a=b, c=d)"
    assert mutate_from_context(
        Context(source=source, mutation_id=RelativeMutationID(source, 1, line_number=0))
    ) == ("dict(a=b, cXX=d)", 1)


def test_mutate_dict2() -> None:
    source = "dict(a=b, c=d, e=f, g=h)"
    assert mutate_from_context(
        Context(source=source, mutation_id=RelativeMutationID(source, 3, line_number=0))
    ) == ("dict(a=b, c=d, e=f, gXX=h)", 1)


def test_performed_mutation_ids() -> None:
    source = "dict(a=b, c=d)"
    context = Context(source=source)
    mutate_from_context(context)
    # we found two mutation points: mutate "a" and "c"
    assert context.performed_mutation_ids == [
        RelativeMutationID(source, 0, 0),
        RelativeMutationID(source, 1, 0),
    ]


def test_syntax_error() -> None:
    with pytest.raises(Exception):
        mutate_from_context(Context(source=":!"))


# TODO: this test becomes incorrect with the new mutation_id system, should try to salvage the idea though...
# def test_mutation_index():
#     source = '''
#
# a = b
# b = c + a
# d = 4 - 1
#
#
#     '''.strip()
#     num_mutations = count_mutations(Context(source=source))
#     mutants = [mutate(Context(source=source, mutation_id=i)) for i in range(num_mutations)]
#     assert len(mutants) == len(set(mutants))  # no two mutants should be the same
#
#     # invalid mutation index should not mutate anything
#     mutated_source, count = mutate(Context(source=source, mutation_id=num_mutations + 1))
#     assert mutated_source.strip() == source
#     assert count == 0


def test_bug_github_issue_18() -> None:
    source = """@register.simple_tag(name='icon')
def icon(name):
    if name is None:
        return ''
    tpl = '<span class="glyphicon glyphicon-{}"></span>'
    return format_html(tpl, name)"""
    mutate_from_context(Context(source=source))


def test_bug_github_issue_19() -> None:
    source = """key = lambda a: "foo"
filters = dict((key(field), False) for field in fields)"""
    mutate_from_context(Context(source=source))


def test_bug_github_issue_26() -> None:
    source = """
class ConfigurationOptions(Protocol):
    min_name_length: int
    """
    mutate_from_context(Context(source=source))


def test_bug_github_issue_30() -> None:
    source = """
def from_checker(cls: Type['BaseVisitor'], checker) -> 'BaseVisitor':
    pass
"""
    assert mutate_from_context(Context(source=source)) == (source, 0)


def test_bug_github_issue_77() -> None:
    # Don't crash on this
    Context(source="")


def test_multiline_dunder_whitelist() -> None:
    source = """
__all__ = [
    1,
    2,
    'foo',
    'bar',
]
"""
    assert mutate_from_context(Context(source=source)) == (source, 0)


def test_bug_github_issue_162() -> None:
    source = """
primes: List[int] = []
foo = 'bar'
"""
    assert mutate_from_context(
        Context(source=source, mutation_id=RelativeMutationID("foo = 'bar'", 0, 2))
    ) == (source.replace("'bar'", "'XXbarXX'"), 1)


def test_bad_mutation_str_type_definition() -> None:
    source = """
foo: 'SomeType'
    """
    assert mutate_from_context(Context(source=source)) == (source, 0)
