# Copyright (C) 2006 Canonical Ltd
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

"""Tests for WorkingTree.flush."""

import sys
from bzrlib import errors, inventory
from bzrlib.tests import TestSkipped
from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree


class TestFlush(TestCaseWithWorkingTree):

    def test_flush_fresh_tree(self):
        tree = self.make_branch_and_tree('t1')
        tree.lock_write()
        try:
            tree.flush()
        finally:
            tree.unlock()

    def test_flush_when_inventory_is_modified(self):
        if sys.platform == "win32":
            raise TestSkipped("don't use oslocks on win32 in unix manner")
        # This takes a write lock on the source tree, then opens a second copy
        # and tries to grab a read lock. This works on Unix and is a reasonable
        # way to detect when the file is actually written to, but it won't work
        # (as a test) on Windows. It might be nice to instead stub out the
        # functions used to write and that way do both less work and also be
        # able to execute on Windows.
        self.thisFailsStrictLockCheck()
        # when doing a flush the inventory should be written if needed.
        # we test that by changing the inventory (using
        # _set_inventory for now until add etc have lazy writes of
        # the inventory on unlock).
        tree = self.make_branch_and_tree('tree')
        # prepare for a series of changes that will modify the
        # inventory
        tree.lock_write()
        try:
            old_root = tree.get_root_id()
            tree.set_root_id('new-root')
            # to detect that the inventory is written by flush, we
            # first check that it was not written yet.
            reference_tree = tree.bzrdir.open_workingtree()
            self.assertEqual(old_root, reference_tree.get_root_id())
            # now flush the tree which should write the inventory.
            tree.flush()
            # and check it was written using another reference tree
            reference_tree = tree.bzrdir.open_workingtree()
            self.assertEqual('new-root', reference_tree.get_root_id())
        finally:
            tree.unlock()

    def test_flush_with_read_lock_fails(self):
        """Flush cannot be used during a read lock."""
        tree = self.make_branch_and_tree('t1')
        tree.lock_read()
        try:
            self.assertRaises(errors.NotWriteLocked, tree.flush)
        finally:
            tree.unlock()

    def test_flush_with_no_lock_fails(self):
        tree = self.make_branch_and_tree('t1')
        self.assertRaises(errors.NotWriteLocked, tree.flush)
