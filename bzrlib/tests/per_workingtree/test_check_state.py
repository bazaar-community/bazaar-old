# Copyright (C) 2011 Canonical Ltd
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

"""Tests for WorkingTree.check_state."""

from bzrlib import (
    errors,
    tests,
    )
from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree



class TestCaseWithState(TestCaseWithWorkingTree):

    def make_tree_with_broken_dirstate(self, path):
        tree = self.make_branch_and_tree(path)
        self.break_dirstate(tree)
        return tree

    def break_dirstate(self, tree):
        """Write garbage into the dirstate file."""
        if getattr(tree, 'current_dirstate', None) is None:
            raise tests.TestNotApplicable(
                'Only applies to dirstate-based trees')
        tree.lock_read()
        try:
            dirstate = tree.current_dirstate()
            dirstate_path = dirstate._filename
            self.failUnlessExists(dirstate_path)
        finally:
            tree.unlock()
        # We have to have the tree unlocked at this point, so we can safely
        # mutate the state file on all platforms.
        f = open(dirstate_path, 'ab')
        try:
            f.write('garbage-at-end-of-file\n')
        finally:
            f.close()


class TestCheckState(TestCaseWithState):

    def test_check_state(self):
        tree = self.make_branch_and_tree('tree')
        # Everything should be fine with an unmodified tree, no exception
        # should be raised.
        tree.check_state()

    def test_check_broken_dirstate(self):
        tree = self.make_tree_with_broken_dirstate('tree')
        self.assertRaises(errors.BzrError, tree.check_state)


class TestResetState(TestCaseWithState):

    def test_reset_state_forgets_changes(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/foo', 'tree/dir/', 'tree/dir/bar'])
        tree.add(['foo', 'dir', 'dir/bar'])
        tree.commit('initial')
        foo_id = tree.path2id('foo')
        tree.rename_one('foo', 'baz')
        self.assertEqual(None, tree.path2id('foo'))
        self.assertEqual(foo_id, tree.path2id('baz'))
        tree.reset_state()
        # After reset, we should have forgotten about the rename, but we won't
        # have
        self.assertEqual(foo_id, tree.path2id('foo'))
        self.assertEqual(None, tree.path2id('baz'))
        self.failIfExists('tree/foo')
        self.failUnlessExists('tree/baz')

    def test_reset_state_handles_corrupted_dirstate(self):
        tree = self.make_branch_and_tree('tree')
        self.break_dirstate(tree)
        tree.reset_state()
        tree.check_state()
