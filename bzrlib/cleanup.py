# Copyright (C) 2009 Canonical Ltd
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

"""Helpers for managing cleanup functions and the errors they might raise.

The usual way to run cleanup code in Python is::

    try:
        do_something()
    finally:
        cleanup_something()

However if both `do_something` and `cleanup_something` raise an exception
Python will forget the original exception and propagate the one from
cleanup_something.  Unfortunately, this is almost always much less useful than
the original exception.

If you want to be certain that the first, and only the first, error is raised,
then use::

    do_with_cleanups(do_something, cleanups)

This is more inconvenient (because you need to make every try block a
function), but will ensure that the first error encountered is the one raised,
while also ensuring all cleanups are run.
"""


import sys
from bzrlib import (
    debug,
    trace,
    )

def _log_cleanup_error(exc):
    trace.mutter('Cleanup failed:')
    trace.log_exception_quietly()
    if 'cleanup' in debug.debug_flags:
        trace.warning('bzr: warning: Cleanup failed: %s', exc)


def _run_cleanup(func, *args, **kwargs):
    """Run func(*args, **kwargs), logging but not propagating any error it
    raises.

    :returns: True if func raised no errors, else False.
    """
    try:
        func(*args, **kwargs)
    except KeyboardInterrupt:
        raise
    except Exception, exc:
        _log_cleanup_error(exc)
        return False
    return True


def _run_cleanup_reporting_errors(func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except KeyboardInterrupt:
        raise
    except Exception, exc:
        trace.mutter('Cleanup failed:')
        trace.log_exception_quietly()
        trace.warning('Cleanup failed: %s', exc)
        return False
    return True


def _run_cleanups(funcs, on_error='log'):
    """Run a series of cleanup functions.

    :param errors: One of 'log', 'warn first', 'warn all'
    """
    seen_error = False
    for func in funcs:
        if on_error == 'log' or (on_error == 'warn first' and seen_error):
            seen_error |= _run_cleanup(func)
        else:
            seen_error |= _run_cleanup_reporting_errors(func)


class OperationWithCleanups(object):
    """A helper for using do_with_cleanups with a dynamic cleanup list.

    This provides a way to add cleanups while the function-with-cleanups is
    running.

    Typical use::

        operation = OperationWithCleanups(some_func)
        operation.run(args...)

    where `some_func` is::

        def some_func(operation, args, ...)
            do_something()
            operation.add_cleanup(something)
            # etc
    """

    def __init__(self, func):
        self.func = func
        self.cleanups = []

    def add_cleanup(self, cleanup_func):
        """Add a cleanup to run.  Cleanups will be executed in LIFO order."""
        self.cleanups.insert(0, cleanup_func)

    def run(self, *args, **kwargs):
        func = lambda: self.func(self, *args, **kwargs)
        return do_with_cleanups(func, self.cleanups)


def do_with_cleanups(func, cleanup_funcs):
    """Run `func`, then call all the cleanup_funcs.

    All the cleanup_funcs are guaranteed to be run.  The first exception raised
    by func or any of the cleanup_funcs is the one that will be propagted by
    this function (subsequent errors are caught and logged).

    Conceptually similar to::

        try:
            return func()
        finally:
            for cleanup in cleanup_funcs:
                cleanup()

    It avoids several problems with using try/finally directly:
     * an exception from func will not be obscured by a subsequent exception
       from a cleanup.
     * an exception from a cleanup will not prevent other cleanups from
       running (but the first exception encountered is still the one
       propagated).

    Unike `_run_cleanup`, `do_with_cleanups` can propagate an exception from a
    cleanup, but only if there is no exception from func.
    """
    # As correct as Python 2.4 allows.
    try:
        result = func()
    except:
        # We have an exception from func already, so suppress cleanup errors.
        _run_cleanups(cleanup_funcs)
        raise
    else:
        # No exception from func, so allow the first exception from
        # cleanup_funcs to propagate if one occurs (but only after running all
        # of them).
        exc_info = None
        for cleanup in cleanup_funcs:
            # XXX: Hmm, if KeyboardInterrupt arrives at exactly this line, we
            # won't run all cleanups... perhaps we should temporarily install a
            # SIGINT handler?
            if exc_info is None:
                try:
                    cleanup()
                except:
                    # This is the first cleanup to fail, so remember its
                    # details.
                    exc_info = sys.exc_info()
            else:
                # We already have an exception to propagate, so log any errors
                # but don't propagate them.
                _run_cleanup(cleanup)
        if exc_info is not None:
            raise exc_info[0], exc_info[1], exc_info[2]
        # No error, so we can return the result
        return result


