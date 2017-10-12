#!/usr/bin/env python

from __future__ import print_function

try:
    from urllib.request import urlopen
except ImportError:
    from urllib2 import urlopen

import os
import sys
import argparse
import logging
import re
import itertools
import time
import tempfile
import subprocess
import curses
import curses.panel

__VERSION__ = '0.1'

INDENT = '    '

MAX_LAYERS_COUNT = 10
# Create new node only if it has some not too few log line. Prevent
# creation of many small nodes.
MIN_LINES_COUNT = 5
# Dont create too many subnodes. Tree becomes difficult to navigate
# otherwise. Small children are eliminated first.
MAX_CHILDREN_COUNT = 200
MAX_VALUE_LENGTH = 80

KEYWORD_SEPARATOR_RE = re.compile(r'\s')
CRUFT_RES = re.compile(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ip
                       r'|(\d{4}/\d{2}/\d{2})'                 # date
                       r'|(\d{1,2}-\w{3}-\d{2,4})'             # date
                       r'|(\d{1,4}-\d{1,2}-\d{1,4})'           # date
                       r'|(\d{2}:\d{2}:\d{2})'                 # time
                       r'|(\d{1,2}m)'                          # time
                       r'|(\d{1,2}s)'                          # time
                       r'|(\d{1,2}\.\d{1,2}s)')                # time


class LogTreeNode(object):
    """Store log lines in a tree structure."""

    def __init__(self, lines_data, value=None, depth=0, key_depth=0):
        self._logger = logging.getLogger(__name__)
        self._depth = depth
        self._value = value if value else ''
        self._lines = [l for _, l in lines_data]
        self._children = []
        if len(self._value) > MAX_VALUE_LENGTH:
            self._value = self._value[:MAX_VALUE_LENGTH]
            return
        if depth < MAX_LAYERS_COUNT:
            self._build_children(key_depth, lines_data)
            self._children.sort(key=lambda c: c.value)

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

    @property
    def log_length(self):
        """Get log length"""
        return len(self._lines)

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
        keywords = {}
        has_final_lines = False
        for keys, line in lines_data:
            assert len(keys) >= key_depth
            if len(keys) == key_depth:
                has_final_lines = True
                continue
            key = keys[key_depth]
            if key in keywords:
                keywords[key].append((keys, line))
            else:
                keywords[key] = [(keys, line)]
        # don't create child objects that hold identical log lines,
        # don't merge if some lines
        if len(keywords) == 1 and not has_final_lines:
            if self._value:
                self._value += ' ' + ''.join(keywords)
            else:
                self._value = ''.join(keywords)
            if len(self._value) > MAX_VALUE_LENGTH:
                self._value = self._value[:MAX_VALUE_LENGTH]
            else:
                self._build_children(key_depth + 1, lines_data)
            return
        large_enough_children = False
        min_child_line_count = MIN_LINES_COUNT
        while not large_enough_children:
            keywords = {k:v for k, v in keywords.items()
                        if len(v) >= min_child_line_count}
            large_enough_children = len(keywords) <= MAX_CHILDREN_COUNT
            min_child_line_count *= 2
        for keyword, lines in keywords.items():
            self._children.append(LogTreeNode(lines, keyword,
                                              self._depth + 1, key_depth + 1))


class LogModel(object):
    """Holds log data and update log views.

    Model and controller.
    """

    def __init__(self):
        self._logger = logging.getLogger(__name__)
        self._log_tree = None
        self._current_node = None
        self.tree_view = None
        self.log_view = None
        self._displayed_objects = None
        self._tree_view_data = []

    @property
    def data(self):
        return self._log_tree

    @data.setter
    def data(self, value):
        self._log_tree = value
        self._current_node = self._log_tree
        self._init_tree_view_data()
        if self.tree_view:
            self.tree_view.on_data_changed()
        if self.log_view:
            self.log_view.on_data_changed()

    def get_displayed_log(self):
        """Used to display log in an external program."""
        return self._current_node.log

    def get_view_data(self, view, row, height):
        if view == self.tree_view:
            return self._get_tree_view_data(row, height)
        elif view == self.log_view:
            return self._get_log_view_data(row, height)
        else:
            assert False, 'Unknown view'

    def get_row_count(self, view):
        if view == self.tree_view:
            return self._get_tree_view_row_count()
        elif view == self.log_view:
            return self._get_log_view_row_count()
        else:
            assert False, 'Unknown view'

    def selected(self, view, row):
        """Process cursor moving in tree view."""
        assert view
        if not self.log_view or view != self.tree_view:
            return
        if row >= len(self._displayed_objects):
            return
        self._current_node = self._displayed_objects[row]
        self.log_view.on_data_changed()

    def activated(self, view, row):
        """Change tree view on enter key."""
        if view != self.tree_view:
            return
        if row >= len(self._displayed_objects):
            return
        if row == len(self._displayed_objects) - 1 \
           or self._displayed_objects[row].depth >= \
           self._displayed_objects[row + 1].depth:
            self._insert_children(row)
        else:
            self._remove_children(row)
        self._update_tree_view_data()
        self.tree_view.on_data_changed()

    def _insert_children(self, row):
        for i, child in enumerate(self._displayed_objects[row].children):
            self._displayed_objects.insert(row + 1 + i, child)

    def _remove_children(self, row):
        parent_depth = self._displayed_objects[row].depth
        row += 1
        new_objects = self._displayed_objects[:row]
        while row < len(self._displayed_objects) \
              and self._displayed_objects[row].depth > parent_depth:
            row += 1
        new_objects += self._displayed_objects[row:]
        self._displayed_objects = new_objects

    def _init_tree_view_data(self):
        self._displayed_objects = [self._log_tree]
        self._displayed_objects.extend(self._log_tree.children)
        self._update_tree_view_data()

    def _update_tree_view_data(self):
        data = []
        for obj in  self._displayed_objects:
            prefix = ' +' if obj.children else ' -'
            line = obj.depth * '  ' + prefix + obj.value
            data.append(line)
        self._tree_view_data = data

    def _get_tree_view_data(self, row, height):
        first = min(row, len(self._tree_view_data))
        last = min(row + height, len(self._tree_view_data))
        return self._tree_view_data[first:last]

    def _get_log_view_data(self, row, height):
        first = min(row, len(self._current_node.log))
        last = min(row + height, len(self._current_node.log))
        return self._current_node.log[first:last]

    def _get_tree_view_row_count(self):
        return len(self._tree_view_data)

    def _get_log_view_row_count(self):
        return self._current_node.log_length


class TextView(object):
    """Display large text with scrolling."""

    def __init__(self, model, y, x, height, width):
        self._logger = logging.getLogger(__name__)
        self._model = model
        self._has_focus = False
        # store line data for horizontal scrolling
        self._lines = []
        # position inside viewable window
        self._cursor_row = 0
        # top left view corner
        self._row = 0
        self._col = 0
        self._max_col = 0
        self._row_count = 0
        # viewable size, 2 chars for border
        self._height = height - 2
        self._width = width - 2
        # display window
        self._window = curses.newwin(height, width, y, x)
        self._window.keypad(1)
        # input handlers
        self._key_functions = {
            curses.KEY_UP: self._on_key_up,
            curses.KEY_DOWN: self._on_key_down,
            curses.KEY_PPAGE: self._on_key_pgup,
            curses.KEY_NPAGE: self._on_key_pgdown,
            curses.KEY_LEFT: self._on_key_left,
            curses.KEY_RIGHT: self._on_key_right,
            ord('\n'): self._on_key_enter,
            ord('\r'): self._on_key_enter,
        }
        self._key_bindings = [
            ('LEFT', 'left by 5 symbols'),
            ('RIGHT', 'right by 5 symbols'),
            ('UP', 'row up'),
            ('DOWN', 'row down'),
            ('PG UP', 'page up'),
            ('PG DOWN', 'page down'),
            ('ENTER', 'toggle object under cursor')
        ]
        self.refresh()

    def get_key_bindings(self):
        return self._key_bindings

    def getch(self):
        """Getch refreshes the window so it cannot be called with stdscr.

        The work around is to call getch() for an active window.
        """
        c = self._window.getch()
        return c

    def set_focus(self):
        self._has_focus = True
        self.refresh()

    def loose_focus(self):
        self._has_focus = False
        self.refresh()

    def on_data_changed(self):
        """Called by model."""
        self._col = 0
        new_row_count = self._model.get_row_count(self)
        if new_row_count > self._row_count:
            lines_to_show = min(self._height, new_row_count - self._row_count)
            lines_below_cursor = self._height - self._cursor_row - 1
            desired_scroll_up = max(0, lines_to_show - lines_below_cursor)
            scroll_up = min(self._cursor_row, desired_scroll_up)
            self._row += scroll_up
            self._cursor_row -= scroll_up
        else:
            self._row = 0
        self._row_count = new_row_count
        self._update_data()
        self.refresh()

    def _update_data(self):
        """Request current data from model."""
        self._lines = self._model.get_view_data(self, self._row, self._height)
        assert len(self._lines) <= self._height
        max_line_len = max(len(l) for l in self._lines) if self._lines else 0
        self._max_col = max(0, max_line_len - self._width)

    def update_cursor(self):
        if self._has_focus:
            self._window.move(self._cursor_row + 1, 1)

    def refresh(self):
        self._window.erase()
        for row, text in enumerate(self._lines):
            first = min(self._col, len(text))
            self._window.addnstr(row + 1, 1, text[first:], self._width)
        self._window.border()
        self.update_cursor()
        self._window.refresh()

    def process_key(self, key):
        if key not in self._key_functions.keys():
            return
        self._key_functions[key]()

    def _on_key_up(self):
        self._move_cursor_up(1)

    def _on_key_down(self):
        self._move_cursor_down(1)

    def _on_key_pgup(self):
        self._move_cursor_up(self._height - 1)

    def _on_key_pgdown(self):
        self._move_cursor_down(self._height - 1)

    def _on_key_left(self):
        self._col -= 5
        if self._col < 0:
            self._col = 0
        self.refresh()

    def _on_key_right(self):
        self._col += 5
        if self._col >= self._max_col:
            self._col = self._max_col
        self.refresh()

    def _on_key_enter(self):
        self._model.activated(self, self._row + self._cursor_row)

    def _move_cursor_up(self, value):
        assert value >= 0
        old_data_row = self._row + self._cursor_row
        self._cursor_row -= value
        if self._cursor_row < 0:
            self._row = max(0, self._row + self._cursor_row)
            self._cursor_row = 0
            self._update_data()
            self.refresh()
        else:
            self.update_cursor()
        new_data_row = self._row + self._cursor_row
        if new_data_row != old_data_row:
            self._model.selected(self, new_data_row)

    def _move_cursor_down(self, value):
        assert value >= 0
        # to implement correct behaviour the algorithm minimises
        # self._row change
        old_selected_row = self._row + self._cursor_row
        new_selected_row = min(old_selected_row + value,
                               self._model.get_row_count(self) - 1)
        if new_selected_row - self._row < self._height:
            self._cursor_row = new_selected_row - self._row
            self.update_cursor()
        else:
            self._row = max(0, new_selected_row - self._height + 1)
            self._cursor_row = new_selected_row - self._row
            self._update_data()
            self.refresh()
        if new_selected_row != old_selected_row:
            self._model.selected(self, new_selected_row)


class StatusBar(object):
    def __init__(self, width, y, height=1, x=0):
        self._window = curses.newwin(height, width, y, x)
        self._text = ''
        self.refresh()

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = value
        self.refresh()

    def refresh(self):
        self._window.erase()
        self._window.addstr(0, 0, self._text)
        self._window.refresh()


def is_cruft(string):
    """Check if a string should not be used to create a tree node.

    >>> assert is_cruft('25-Apr-2017')
    >>> assert is_cruft('2-dec-17')
    >>> assert is_cruft('11:22:33')
    """
    return re.match(CRUFT_RES, string) is not None

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


def show_tree(_, tree_object):
    """Display log information."""
    print(tree_object)


def show_log(_, tree_object):
    """Display log information."""
    print('\n'.join(tree_object.log))


def create_gui_objects(parent, tree_object):
    """Return tuple of tree and log windows."""
    model = LogModel()
    ysize, xsize = parent.getmaxyx()
    tree_width = int(xsize * 0.3)
    tree_view = TextView(model, 0, 0, ysize - 1, tree_width)
    model.tree_view = tree_view
    log_view = TextView(model, 0, tree_width, ysize - 1 , xsize - tree_width)
    model.log_view = log_view
    model.data = tree_object
    status_bar = StatusBar(xsize, ysize - 1)
    return model, [tree_view, log_view], status_bar


class suspend_curses():
    """Context Manager to temporarily leave curses mode"""

    def __enter__(self):
        curses.endwin()

    def __exit__(self, exc_type, exc_val, exec_tb):
        newscr = curses.initscr()
        newscr.refresh()
        curses.doupdate()


def display_in_less(model):
    tmpfile, tmppath = tempfile.mkstemp()
    newline = bytearray('\n', encoding='utf-8')
    for logline in model.get_displayed_log():
        os.write(tmpfile, bytearray(logline, encoding='utf-8'))
        os.write(tmpfile, newline)
    os.close(tmpfile)
    with suspend_curses():
        subprocess.call(['less', tmppath])
    os.remove(tmppath)


_TOP_KEY_BINDINGS = [
    ('TAB', 'next window'),
    ('q, ESC', 'quit'),
    ('l', 'display current log section in less'),
    ('h', 'display this help')
]

def display_tree(stdscr, source_path, tree_object):
    """Use curses to view log file."""
    model, text_views, status_bar = create_gui_objects(stdscr, tree_object)
    status_bar.text = source_path
    windows = itertools.cycle(text_views)
    active_window = next(windows)
    active_window.set_focus()
    while True:
        key = active_window.getch()
        if status_bar.text != source_path:
            # reset status bar to source path after showing help
            status_bar.text = source_path
        if key == ord('\t'):
            active_window.loose_focus()
            active_window = next(windows)
            active_window.set_focus()
        elif key == ord('q') or key == 27:
            break
        elif key == ord('h') or key == curses.KEY_F1:
            status_bar.text = ('q,ESC: quit; l: view log in less; '
                               'TAB: switch window; ARROWS, PG *: move around; '
                               'ENTER: open/close tree node')
        elif key == ord('l'):
            display_in_less(model)
            for view in text_views:
                view.refresh()
            stdscr.refresh()
        else:
            active_window.process_key(key)
        active_window.update_cursor()


def run_curses(source_path, tree_object):
    """Run curses wrapper that inits and destroy screen."""
    os.environ['ESCDELAY'] = '25'
    curses.wrapper(display_tree, source_path, tree_object)


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
                        required=False, help='input file')
    parser.add_argument('-l', '--link', type=str,
                        required=False, help='link to input file')
    parser.add_argument('-p', '--path', type=str,
                        help='display starting with path')
    parser.add_argument('-d', '--debug', type=argparse.FileType('w'),
                        help='output for log messages')
    parser.add_argument('--profile', action='store_true',
                        help='run profiler on build tree code')

    return parser.parse_args()


def main():
    """Execute specified command."""
    arguments = parse_args()
    logger = None
    if arguments.debug:
        logger = logging.getLogger(__name__)
        logger.addHandler(logging.StreamHandler(arguments.debug))
        logger.setLevel(logging.DEBUG)
    if not arguments.link and not arguments.input:
        sys.exit('please specify either a file name or a link')
    start_ts = time.clock()
    if arguments.link:
        response = urlopen(arguments.link)
        log_lines = (l.decode('latin-1') for l in response.readlines())
        source_path = 'Link: ' + arguments.link
    else:
        log_lines = (l for l in arguments.input.readlines())
        source_path = 'File: ' + arguments.input.name
    if arguments.command == 'curses':
        # Need to expand tabs because curses pad can not handle
        # strings with multiple tabs. Pad has fixed width and it is
        # expensive to calculate line widths taking tabs into
        # account. If a line is too long it wraps thus end is lost. If
        # the last line is too long then pad throws an exception.
        log_lines = (l.strip('\n\r').expandtabs() for l in log_lines)
    else:
        # Don't expand tabs to preserve original formating in case
        # this program is used as a filter.
        log_lines = (l.strip('\n\r') for l in log_lines)
    log_read_ts = time.clock()
    if arguments.profile:
        import cProfile
        cProfile.runctx('build_tree(log_lines)', locals={},
                        globals={'log_lines': log_lines,
                                 'build_tree': build_tree})
        return
    tree = build_tree(log_lines)
    tree_built_ts = time.clock()
    if logger:
        logger.info('Data read time: %s s', str(log_read_ts - start_ts))
        logger.info('Tree build time: %s s', str(tree_built_ts - log_read_ts))
    if arguments.path:
        tree = tree.get_subtree(arguments.path)
        if not tree:
            sys.exit('error: the specified path was not found')
    COMMAND_HANDLERS[arguments.command](source_path, tree)


if __name__ == '__main__':
    main()
