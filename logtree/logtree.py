#!/usr/bin/env python

from __future__ import print_function

import sys
import argparse
import re
import itertools
import curses
import curses.panel

__VERSION__ = '0.1'

INDENT = '    '

MAX_LAYERS_COUNT = 10
MAX_CHILDREN_COUNT = 50
MAX_VALUE_LENGTH = 80

KEYWORD_SEPARATOR_RE = re.compile(r'\s')
CRUFT_RES = [re.compile(r'\d{1,2}-\w{3}-\d{2,4}'),
             re.compile(r'\d{1,4}-\d{1,2}-\d{1,4}'),
             re.compile(r'\d{2}:\d{2}:\d{2}')]


class LogTreeNode(object):
    """Store log lines in a tree structure."""

    def __init__(self, lines_data, value=None, depth=0, key_depth=0):
        self._depth = depth
        self._value = value if value else ''
        self._lines = [l for _, l in lines_data]
        self._children = []
        if len(self._value) > MAX_VALUE_LENGTH:
            self._value = self._value[:MAX_VALUE_LENGTH]
            return
        if depth < MAX_LAYERS_COUNT:
            self._build_children(key_depth, lines_data)
            self._children.sort(key=lambda c : c.value)

    def __str__(self):
        value = self._depth * INDENT + self._value
        if self._children:
            value += '\n' + '\n'.join(str(c) for c in self._children)
        return value

    @property
    def depth(self):
        """Node depth in the hierarchy."""
        return self._depth

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

    def get_subtree(self, path):
        """Return tree object with given path."""
        if self.value.startswith(path):
            # enables abbreviation of long node names
            return self
        if not path.startswith(self.value):
            return None
        child_path = path[len(self.value):].strip()
        if not child_path:
            return self
        for child in self.children:
            subtree = child.get_subtree(child_path)
            if subtree:
                return subtree
        return None

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
            if len(self._value) > MAX_VALUE_LENGTH:
                self._value = self._value[:MAX_VALUE_LENGTH]
            else:
                self._build_children(key_depth + 1, lines_data)
            return
        for keyword in keywords:
            child_lines = [(k, l) for (k, l) in lines_data
                           if len(k) > key_depth and k[key_depth] == keyword]
            if not child_lines:
                continue
            self._children.append(LogTreeNode(child_lines, keyword,
                                              self._depth + 1, key_depth + 1))


class LogModel(object):
    """Holds log data and update log views.

    Model and controller.
    """

    def __init__(self):
        self._log_tree = None
        self._current_node = None
        self.tree_view = None
        self.log_view = None
        self._displayed_objects = None

    @property
    def data(self):
        return self._log_tree

    @data.setter
    def data(self, value):
        self._log_tree = value
        self._current_node = self._log_tree
        self._init_tree_view_data()
        if self.tree_view:
            self.tree_view.data_changed()
        if self.log_view:
            self.log_view.data_changed()

    def get_view_data(self, view):
        if view == self.tree_view:
            return self._get_tree_view_data()
        elif view == self.log_view:
            return self._get_log_view_data()
        else:
            assert False, 'Unknown view'

    def selected(self, view, row, column):
        """Process cursor moving in tree view."""
        assert view
        if not self.log_view or view != self.tree_view:
            return
        if row >= len(self._displayed_objects):
            return
        self._current_node = self._displayed_objects[row]
        self.log_view.data_changed()

    def activated(self, view, row, column):
        """Change tree view on enter key."""
        assert view
        if view != self.tree_view:
            return
        if row >= len(self._displayed_objects):
            return
        if self._displayed_objects[row].children:
            return

    def _init_tree_view_data(self):
        self._displayed_objects = [self._log_tree]
        for c in self._log_tree.children:
            self._displayed_objects.append(c)

    def _get_tree_view_data(self):
        lines = ['|+' + o.value for o in self._displayed_objects[:-1]]
        lines.append('\-' + self._displayed_objects[-1].value)
        return lines

    def _get_log_view_data(self):
        return self._current_node.log


class TextView(object):
    """Display large text with scrolling."""

    def __init__(self, model, y, x, height, width):
        self._model = model
        self._lines = []
        self._has_focus = False
        # cursor move vertically as usual
        # 0 <= _cursor_row < _pad_height
        # _current_row <= _cursor_row < _current_row + _view_height
        # cursor stays at the left edge of the screen
        # 0 <= _cursor_col <= _pad_width -_view_width
        # _current_col == _cursor_col
        self._cursor_row = None
        self._cursor_col = None
        self._current_row = None
        self._current_col = None
        self._pad_width = None
        self._pad_height = None
        self._view_height = height - 2
        self._view_width = width - 2
        self._pad = None
        self._update_pad()
        # window just to draw border, no need to ever refresh it
        self._window = curses.newwin(height, width, y, x)
        self._window.border()
        self._window.refresh()
        self._pad_region = (y + 1, x + 1, y + height - 2, x + width - 2)
        # input handlers
        self._key_functions = {
            curses.KEY_UP: self._on_key_up,
            curses.KEY_DOWN: self._on_key_down,
            curses.KEY_PPAGE: self._on_key_pgup,
            curses.KEY_NPAGE: self._on_key_pgdown,
            curses.KEY_LEFT: self._on_key_left,
            curses.KEY_RIGHT: self._on_key_right,
            curses.KEY_ENTER: self._on_key_enter,
        }
        self.refresh()

    def getch(self):
        """Getch refreshes the window so it cannot be called with stdscr.

        The work around is to call getch() for an active window.
        """
        return self._pad.getch()

    def set_focus(self):
        self._has_focus = True
        self.refresh()

    def loose_focus(self):
        self._has_focus = False
        self.refresh()

    def data_changed(self):
        self._lines = self._model.get_view_data(self)
        self._update_pad()
        self.refresh()

    def _update_pad(self):
        self._pad_height = max(self._view_height, len(self._lines))
        self._pad_width = 0
        if self._lines:
            self._pad_width = max(len(l) for l in self._lines)
            self._pad_width += 1
        self._pad_width = max(self._view_width, self._pad_width)
        self._pad = curses.newpad(self._pad_height, self._pad_width)
        self._pad.keypad(1)
        for i, l in enumerate(self._lines):
            self._pad.addnstr(i, 0, l, self._pad_width)
        self._cursor_row = 0
        self._cursor_col = 0
        self._current_row = 0
        self._current_col = 0

    def refresh(self):
        if self._has_focus:
            self._pad.move(self._cursor_row, self._cursor_col)
        self._pad.refresh(self._current_row, self._current_col,
                          *self._pad_region)

    def process_key(self, key):
        if key not in self._key_functions.keys():
            return
        if self._key_functions[key]():
            self.refresh()

    def _on_key_up(self):
        self._move_cursor_up(1)
        self._model.selected(self, self._cursor_row, self._cursor_col)
        return True

    def _on_key_down(self):
        self._move_cursor_down(1)
        self._model.selected(self, self._cursor_row, self._cursor_col)
        return True

    def _on_key_pgup(self):
        self._move_cursor_up(self._view_height - 1)
        self._model.selected(self, self._cursor_row, self._cursor_col)
        return True

    def _on_key_pgdown(self):
        self._move_cursor_down(self._view_height - 1)
        self._model.selected(self, self._cursor_row, self._cursor_col)
        return True

    def _on_key_left(self):
        self._cursor_col -= 5
        self._cursor_col = max(self._cursor_col, 0)
        self._current_col = self._cursor_col
        return True

    def _on_key_right(self):
        self._cursor_col += 5
        self._cursor_col = min(self._cursor_col,
                               self._pad_width - self._view_width)
        self._current_col = self._cursor_col
        return True

    def _on_key_enter(self):
        self._model.activated(self, self._cursor_row, self._cursor_col)
        return False

    def _move_cursor_up(self, value):
        assert value >= 0
        self._cursor_row -= value
        self._cursor_row = max(self._cursor_row, 0)
        # ensure: current_row <= cursor_row
        self._current_row = min(self._current_row, self._cursor_row)

    def _move_cursor_down(self, value):
        assert value >= 0
        self._cursor_row += value
        self._cursor_row = min(self._cursor_row, self._pad_height - 1)
        # ensure: current_row + view_height > cursor_row
        self._current_row = max(self._current_row,
                                self._cursor_row - self._view_height + 1)


def is_cruft(string):
    """Check if a string should not be used to create a tree node.

    >>> assert is_cruft('25-Apr-2017')
    >>> assert is_cruft('2-dec-17')
    >>> assert is_cruft('11:22:33')
    """
    return any(re.match(r, string) for r in CRUFT_RES)


def strip_specials(string):
    """Remove spaces and brackets"""
    return string.strip(' \t()[]{}:;.,')


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


def show_tree(tree_object):
    """Display log information."""
    print(tree_object)


def show_log(tree_object):
    """Display log information."""
    print('\n'.join(tree_object.log))


def create_gui_objects(parent, tree_object):
    """Return tuple of tree and log windows."""
    model = LogModel()
    ysize, xsize = parent.getmaxyx()
    tree_width = int(xsize * 0.3)
    tree_view = TextView(model, 0, 0, ysize, tree_width)
    model.tree_view = tree_view
    log_view = TextView(model, 0, tree_width, ysize, xsize - tree_width)
    model.log_view = log_view
    model.data = tree_object
    return model, [tree_view, log_view]


def display_tree(stdscr, tree_object):
    """Use curses to view log file."""
    model, text_views = create_gui_objects(stdscr, tree_object)
    windows = itertools.cycle(text_views)
    active_window = next(windows)
    active_window.set_focus()
    while True:
        key = active_window.getch()
        if key == ord('\t'):
            active_window.loose_focus()
            active_window = next(windows)
            active_window.set_focus()
        elif key == ord('q'):
            break
        elif key == ord('h'):
            break
        else:
            active_window.process_key(key)


def run_curses(tree_object):
    """Run curses wrapper that inits and destroy screen."""
    curses.wrapper(display_tree, tree_object)


COMMAND_HANDLERS = {'tree': show_tree,
                    'log': show_log,
                    'curses': run_curses}


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Access plain log as if it is stored in a tree.')
    parser.add_argument('-c', '--command', choices=COMMAND_HANDLERS.keys(),
                        default='curses',
                        help='command to execute [default: curses]')
    parser.add_argument('-i', '--input', type=argparse.FileType('r'),
                        required=True, help='input file')
    parser.add_argument('-p', '--path', type=str,
                        help='display starting with path')

    return parser.parse_args()


def main():
    """Execute specified command."""
    arguments = parse_args()
    if arguments.command == 'curses':
        # Need to expand tabs because curses pad can not handle
        # strings with multiple tabs. Pad has fixed width and it is
        # expensive to calculate line widths taking tabs into
        # account. If a line is too long it wraps thus end is lost. If
        # the last line is too long then pad throws an exception.
        tree = build_tree(l.strip('\n\r').expandtabs()
                          for l in arguments.input.readlines())
    else:
        # Don't expand tabs to preserve original formating in case
        # this program is used as a filter.
        tree = build_tree(l.strip('\n\r')
                          for l in arguments.input.readlines())
    if arguments.path:
        tree = tree.get_subtree(arguments.path)
        if not tree:
            sys.exit('error: the specified path was not found')
    COMMAND_HANDLERS[arguments.command](tree)


if __name__ == '__main__':
    main()
