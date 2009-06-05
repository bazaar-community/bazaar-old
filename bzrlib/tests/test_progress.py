# Copyright (C) 2006, 2007, 2009 Canonical Ltd
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

import os
from StringIO import StringIO

from bzrlib import errors
from bzrlib.progress import (
        DummyProgress,
        ChildProgress,
        TTYProgressBar,
        DotsProgressBar,
        InstrumentedProgress,
        )
from bzrlib.tests import TestCase
from bzrlib.symbol_versioning import (
    deprecated_in,
    )


class FakeStack:

    def __init__(self, top):
        self.__top = top

    def top(self):
        return self.__top


class _TTYStringIO(StringIO):
    """A helper class which makes a StringIO look like a terminal"""

    def isatty(self):
        return True


class _NonTTYStringIO(StringIO):
    """Helper that implements isatty() but returns False"""

    def isatty(self):
        return False


class TestProgress(TestCase):

    def setUp(self):
        TestCase.setUp(self)
        q = DummyProgress()
        self.top = ChildProgress(_stack=FakeStack(q))

    def test_propogation(self):
        self.top.update('foobles', 1, 2)
        self.assertEqual(self.top.message, 'foobles')
        self.assertEqual(self.top.current, 1)
        self.assertEqual(self.top.total, 2)
        self.assertEqual(self.top.child_fraction, 0)
        child = ChildProgress(_stack=FakeStack(self.top))
        child.update('baubles', 2, 4)
        self.assertEqual(self.top.message, 'foobles')
        self.assertEqual(self.top.current, 1)
        self.assertEqual(self.top.total, 2)
        self.assertEqual(self.top.child_fraction, 0.5)
        grandchild = ChildProgress(_stack=FakeStack(child))
        grandchild.update('barbells', 1, 2)
        self.assertEqual(self.top.child_fraction, 0.625)
        self.assertEqual(child.child_fraction, 0.5)
        child.update('baubles', 3, 4)
        self.assertEqual(child.child_fraction, 0)
        self.assertEqual(self.top.child_fraction, 0.75)
        grandchild.update('barbells', 1, 2)
        self.assertEqual(self.top.child_fraction, 0.875)
        grandchild.update('barbells', 2, 2)
        self.assertEqual(self.top.child_fraction, 1)
        child.update('baubles', 4, 4)
        self.assertEqual(self.top.child_fraction, 1)
        #test clamping
        grandchild.update('barbells', 2, 2)
        self.assertEqual(self.top.child_fraction, 1)

    def test_implementations(self):
        for implementation in (TTYProgressBar, DotsProgressBar,
                               DummyProgress):
            self.check_parent_handling(implementation)

    def check_parent_handling(self, parentclass):
        top = parentclass(to_file=StringIO())
        top.update('foobles', 1, 2)
        child = ChildProgress(_stack=FakeStack(top))
        child.update('baubles', 4, 4)
        top.update('lala', 2, 2)
        child.update('baubles', 4, 4)

    def test_throttling(self):
        pb = InstrumentedProgress(to_file=StringIO())
        # instantaneous updates should be squelched
        pb.update('me', 1, 1)
        self.assertTrue(pb.always_throttled)
        pb = InstrumentedProgress(to_file=StringIO())
        # It's like an instant sleep(1)!
        pb.start_time -= 1
        # Updates after a second should not be squelched
        pb.update('me', 1, 1)
        self.assertFalse(pb.always_throttled)

    def test_clear(self):
        sio = StringIO()
        pb = TTYProgressBar(to_file=sio, show_eta=False)
        pb.width = 20 # Just make it easier to test
        # This should not output anything
        pb.clear()
        # These two should not be displayed because
        # of throttling
        pb.update('foo', 1, 3)
        pb.update('bar', 2, 3)
        # So pb.clear() has nothing to do
        pb.clear()

        # Make sure the next update isn't throttled
        pb.start_time -= 1
        pb.update('baz', 3, 3)
        pb.clear()

        self.assertEqual('\r[=========] baz 3/3'
                         '\r                   \r',
                         sio.getvalue())

    def test_no_eta(self):
        # An old version of the progress bar would
        # store every update if show_eta was false
        # because the eta routine was where it was
        # cleaned out
        pb = InstrumentedProgress(to_file=StringIO(), show_eta=False)
        # Just make sure this first few are throttled
        pb.start_time += 5

        # These messages are throttled, and don't contribute
        for count in xrange(100):
            pb.update('x', count, 300)
        self.assertEqual(0, len(pb.last_updates))

        # Unthrottle by time
        pb.start_time -= 10

        # These happen too fast, so only one gets through
        for count in xrange(100):
            pb.update('x', count+100, 200)
        self.assertEqual(1, len(pb.last_updates))

        pb.MIN_PAUSE = 0.0

        # But all of these go through, don't let the
        # last_update list grow without bound
        for count in xrange(100):
            pb.update('x', count+100, 200)

        self.assertEqual(pb._max_last_updates, len(pb.last_updates))
