#!/usr/bin/env python

import re

__VERSION__ = '0.1'

CRUFT_RES = [re.compile(r'\d{1,2}-\w{3}-\d{2,4}')]


def is_cruft(string):
    """Check if a string should not be used to create a tree node.

    >>> assert is_cruft('25-Apr-2017')
    >>> assert is_cruft('2-dec-17')
    """
    return any(re.match(r, string) for r in CRUFT_RES)


def run_curses():
    """Use curses to view log file"""
    pass


if __name__ == '__main__':
    run_curses()
