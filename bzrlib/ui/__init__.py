# Copyright (C) 2005, 2006, 2007, 2008, 2009 Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""UI abstraction.

This tells the library how to display things to the user.  Through this
layer different applications can choose the style of UI.

Several levels are supported, and you can also register new factories such as
for a GUI.

UIFactory
    Semi-abstract base class

SilentUIFactory
    Produces no output and cannot take any input; useful for programs using
    bzrlib in batch mode or for programs such as loggerhead.

TextUIFactory
    Standard text command-line interface, with stdin, stdout, stderr.
    May make more or less advanced use of them, eg in drawing progress bars,
    depending on the detected capabilities of the terminal.
"""

import os
import sys
import warnings

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import getpass

from bzrlib import (
    errors,
    osutils,
    progress,
    trace,
    )
""")


class UIFactory(object):
    """UI abstraction.

    This tells the library how to display things to the user.  Through this
    layer different applications can choose the style of UI.
    """

    def __init__(self):
        self._task_stack = []

    def get_password(self, prompt='', **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.

        :return: The password string, return None if the user canceled the
                 request. Note that we do not touch the encoding, users may
                 have whatever they see fit and the password should be
                 transported as is.
        """
        raise NotImplementedError(self.get_password)

    def nested_progress_bar(self):
        """Return a nested progress bar.

        When the bar has been finished with, it should be released by calling
        bar.finished().
        """
        if self._task_stack:
            t = progress.ProgressTask(self._task_stack[-1], self)
        else:
            t = progress.ProgressTask(None, self)
        self._task_stack.append(t)
        return t

    def _progress_finished(self, task):
        """Called by the ProgressTask when it finishes"""
        if not self._task_stack:
            warnings.warn("%r finished but nothing is active"
                % (task,))
        elif task != self._task_stack[-1]:
            warnings.warn("%r is not the active task %r"
                % (task, self._task_stack[-1]))
        else:
            del self._task_stack[-1]
        if not self._task_stack:
            self._progress_all_finished()

    def _progress_all_finished(self):
        """Called when the top-level progress task finished"""
        pass

    def _progress_updated(self, task):
        """Called by the ProgressTask when it changes.

        Should be specialized to draw the progress.
        """
        pass

    def clear_term(self):
        """Prepare the terminal for output.

        This will, for example, clear text progress bars, and leave the
        cursor at the leftmost position.
        """
        pass

    def get_boolean(self, prompt):
        """Get a boolean question answered from the user.

        :param prompt: a message to prompt the user with. Should be a single
        line without terminating \n.
        :return: True or False for y/yes or n/no.
        """
        raise NotImplementedError(self.get_boolean)

    def make_progress_view(self):
        """Construct a new ProgressView object for this UI.

        Application code should normally not call this but instead
        nested_progress_bar().
        """
        return NullProgressView()

    def recommend_upgrade(self,
        current_format_name,
        basedir):
        # this should perhaps be in the TextUIFactory and the default can do
        # nothing
        trace.warning("%s is deprecated "
            "and a better format is available.\n"
            "It is recommended that you upgrade by "
            "running the command\n"
            "  bzr upgrade %s",
            current_format_name,
            basedir)

    def report_transport_activity(self, transport, byte_count, direction):
        """Called by transports as they do IO.

        This may update a progress bar, spinner, or similar display.
        By default it does nothing.
        """
        pass



class CLIUIFactory(UIFactory):
    """Common behaviour for command line UI factories.

    This is suitable for dumb terminals that can't repaint existing text."""

    def __init__(self, stdin=None, stdout=None, stderr=None):
        UIFactory.__init__(self)
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr

    def get_boolean(self, prompt):
        # FIXME: make a regexp and handle case variations as well.
        while True:
            self.prompt(prompt + "? [y/n]: ")
            line = self.stdin.readline()
            if line in ('y\n', 'yes\n'):
                return True
            if line in ('n\n', 'no\n'):
                return False

    def get_non_echoed_password(self):
        isatty = getattr(self.stdin, 'isatty', None)
        if isatty is not None and isatty():
            # getpass() ensure the password is not echoed and other
            # cross-platform niceties
            password = getpass.getpass('')
        else:
            # echo doesn't make sense without a terminal
            password = self.stdin.readline()
            if not password:
                password = None
            elif password[-1] == '\n':
                password = password[:-1]
        return password

    def get_password(self, prompt='', **kwargs):
        """Prompt the user for a password.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.
        :return: The password string, return None if the user
                 canceled the request.
        """
        prompt += ': '
        self.prompt(prompt, **kwargs)
        # There's currently no way to say 'i decline to enter a password'
        # as opposed to 'my password is empty' -- does it matter?
        return self.get_non_echoed_password()

    def get_username(self, prompt, **kwargs):
        """Prompt the user for a username.

        :param prompt: The prompt to present the user
        :param kwargs: Arguments which will be expanded into the prompt.
                       This lets front ends display different things if
                       they so choose.
        :return: The username string, return None if the user
                 canceled the request.
        """
        prompt += ': '
        self.prompt(prompt, **kwargs)
        username = self.stdin.readline()
        if not username:
            username = None
        elif username[-1] == '\n':
            username = username[:-1]
        return username

    def prompt(self, prompt, **kwargs):
        """Emit prompt on the CLI.
        
        :param kwargs: Dictionary of arguments to insert into the prompt,
            to allow UIs to reformat the prompt.
        """
        if kwargs:
            # See <https://launchpad.net/bugs/365891>
            prompt = prompt % kwargs
        prompt = prompt.encode(osutils.get_terminal_encoding(), 'replace')
        self.clear_term()
        self.stderr.write(prompt)

    def note(self, msg):
        """Write an already-formatted message."""
        self.stdout.write(msg + '\n')


class SilentUIFactory(CLIUIFactory):
    """A UI Factory which never prints anything.

    This is the default UI, if another one is never registered.
    """

    def __init__(self):
        CLIUIFactory.__init__(self)

    def get_password(self, prompt='', **kwargs):
        return None

    def get_username(self, prompt='', **kwargs):
        return None

    def prompt(self, prompt, **kwargs):
        pass

    def note(self, msg):
        pass


def clear_decorator(func, *args, **kwargs):
    """Decorator that clears the term"""
    ui_factory.clear_term()
    func(*args, **kwargs)


ui_factory = SilentUIFactory()
"""IMPORTANT: never import this symbol directly. ONLY ever access it as
ui.ui_factory."""


def make_ui_for_terminal(stdin, stdout, stderr):
    """Construct and return a suitable UIFactory for a text mode program.

    If stdout is a smart terminal, this gets a smart UIFactory with
    progress indicators, etc.  If it's a dumb terminal, just plain text output.
    """
    cls = None
    isatty = getattr(stdin, 'isatty', None)
    if isatty is None:
        cls = CLIUIFactory
    elif not isatty():
        cls = CLIUIFactory
    # The following case also handles Win32 - on that platform $TERM is
    # typically never set, so the case None is treated as a smart terminal,
    # not dumb.  <https://bugs.launchpad.net/bugs/334808>  win32 files do have
    # isatty methods that return true.
    elif os.environ.get('TERM') in ('dumb', ''):
        # e.g. emacs compile window
        cls = CLIUIFactory
    # User may know better, otherwise default to TextUIFactory
    if (os.environ.get('BZR_USE_TEXT_UI', None) is not None
        or cls is None):
        from bzrlib.ui.text import TextUIFactory
        cls = TextUIFactory
    return cls(stdin=stdin, stdout=stdout, stderr=stderr)


class NullProgressView(object):
    """Soak up and ignore progress information."""

    def clear(self):
        pass

    def show_progress(self, task):
        pass

    def show_transport_activity(self, transport, direction, byte_count):
        pass
