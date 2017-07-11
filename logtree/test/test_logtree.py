from __future__ import print_function

from logtree.logtree import build_tree


def test_single_line():
    loglines = ['error   25-Apr-2017 20:37:09    [some message] more text']
    tree = build_tree(loglines)
    assert not tree.children
    assert tree.value == 'error some message more text'
    assert tree.log == loglines


def test_merge_identical():
    loglines = ['error some message', 'error some message']
    tree = build_tree(loglines)
    assert not tree.children
    assert tree.value == 'error some message'
    assert tree.log == loglines


def test_prefix_of_other():
    loglines = ['error some message', 'error some message with more text']
    tree = build_tree(loglines)
    assert len(tree.children) == 1
    assert tree.value == 'error some message'
    assert tree.log == loglines
    child = tree.children[0]
    assert not child.children
    assert child.value == 'with more text'
    assert child.log == [loglines[1]]
