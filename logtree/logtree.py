#!/usr/bin/env python

from __future__ import print_function

import re


__VERSION__ = '0.1'

INDENT = '    '

MAX_LAYERS_COUNT = 10
MAX_CHILDREN_COUNT = 50

KEYWORD_SEPARATOR_RE = re.compile(r'\s')
CRUFT_RES = [re.compile(r'\d{1,2}-\w{3}-\d{2,4}'),
             re.compile(r'\d{1,4}-\d{1,2}-\d{1,4}'),
             re.compile(r'\d{2}:\d{2}:\d{2}')]


class LogTreeNode:
    """Store log lines in a tree structure."""

    def __init__(self, lines_data, value=None, depth=0, key_depth=0):
        self._depth = depth
        self._value = value if value else ''
        self._lines = [l for _, l in lines_data]
        self._children = []
        if depth < MAX_LAYERS_COUNT:
            self._build_children(key_depth, lines_data)

    def __str__(self):
        indent = self._depth * INDENT
        children_str = '\n'.join(str(c) for c in self._children)
        return indent + self._value + '\n' + children_str

    def _build_children(self, key_depth, lines_data):
        """Create children if therea are not too many or too few."""

        keywords = set(k[key_depth] for k, _ in lines_data if len(k) > key_depth)
        if len(keywords) >= MAX_CHILDREN_COUNT:
            return
        # don't create child objects that hold identical log lines
        if len(keywords) == 1 and all(len(k) > key_depth for k, _ in lines_data):
            if self._value:
                self._value += ' ' + ''.join(keywords)
            else:
                self._value = ''.join(keywords)
            self._build_children(key_depth + 1, lines_data)
            return
        for keyword in keywords:
            child_lines = [(k, l) for (k, l) in lines_data
                           if len(k) > key_depth and k[key_depth] == keyword]
            if not child_lines:
                continue
            self._children.append(LogTreeNode(child_lines, keyword,
                                              self._depth + 1, key_depth + 1))

    @property
    def value(self):
        """Get log keyword associates with the node"""
        return self._value

    @property
    def children(self):
        """Get node children"""
        return self._children

    @property
    def log(self):
        """Get log lines associated with the node"""
        return self._lines


def is_cruft(string):
    """Check if a string should not be used to create a tree node.

    >>> assert is_cruft('25-Apr-2017')
    >>> assert is_cruft('2-dec-17')
    >>> assert is_cruft('11:22:33')
    """
    return any(re.match(r, string) for r in CRUFT_RES)


def strip_specials(string):
    """Remove spaces and brackets"""
    return string.strip(' \t()[]{}:')


def get_keywords(logline):
    """Convert a log line into keywords.

    >>> get_keywords('error   {25-Apr-2017}\t(something]')
    ['error', 'something']
    """
    return [s for s in
            (strip_specials(p) for p in re.split(KEYWORD_SEPARATOR_RE, logline))
            if s and not is_cruft(s)]


def build_tree(loglines):
    """Place log lines into tree structure."""
    return LogTreeNode([(get_keywords(l), l) for l in loglines])


def run_cmd():
    """Display log information"""
    pass


def run_curses():
    """Use curses to view log file"""
    pass


if __name__ == '__main__':
    run_cmd()
