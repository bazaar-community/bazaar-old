# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests for bzrlib.switch."""


import os

from bzrlib import (
    branch,
    errors,
    merge as _mod_merge,
    switch,
    tests,
)


class TestSwitch(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestSwitch, self).setUp()
        self.lightweight = True

    def _setup_tree(self):
        tree = self.make_branch_and_tree('branch-1')
        self.build_tree(['branch-1/file-1'])
        tree.add('file-1')
        tree.commit('rev1')
        return tree

    def test_switch_updates(self):
        """Test switch updates tree and keeps uncommitted changes."""
        tree = self._setup_tree()
        to_branch = tree.bzrdir.sprout('branch-2').open_branch()
        self.build_tree(['branch-1/file-2'])
        tree.add('file-2')
        tree.remove('file-1')
        tree.commit('rev2')
        checkout = tree.branch.create_checkout('checkout',
            lightweight=self.lightweight)
        self.build_tree(['checkout/file-3'])
        checkout.add('file-3')
        self.failIfExists('checkout/file-1')
        self.failUnlessExists('checkout/file-2')
        switch.switch(checkout.bzrdir, to_branch)
        self.failUnlessExists('checkout/file-1')
        self.failIfExists('checkout/file-2')
        self.failUnlessExists('checkout/file-3')

    def test_switch_after_branch_moved(self):
        """Test switch after the branch is moved."""
        tree = self._setup_tree()
        checkout = tree.branch.create_checkout('checkout',
            lightweight=self.lightweight)
        self.build_tree(['branch-1/file-2'])
        tree.add('file-2')
        tree.remove('file-1')
        tree.commit('rev2')
        self.build_tree(['checkout/file-3'])
        checkout.add('file-3')
        checkout_dir = checkout.bzrdir
        # rename the branch on disk, the checkout object is now invalid.
        os.rename('branch-1', 'branch-2')
        to_branch = branch.Branch.open('branch-2')
        # Check fails without --force
        err = self.assertRaises(
            (errors.BzrCommandError, errors.NotBranchError),
            switch.switch, checkout.bzrdir, to_branch)
        if isinstance(err, errors.BzrCommandError):
            self.assertContainsRe(str(err),
                'Unable to connect to current master branch .*'
                'To switch anyway, use --force.')
        switch.switch(checkout.bzrdir, to_branch, force=True)
        self.failIfExists('checkout/file-1')
        self.failUnlessExists('checkout/file-2')
        self.failUnlessExists('checkout/file-3')

    def test_switch_when_pending_merges(self):
        """Test graceful failure if pending merges are outstanding."""
        # Create 2 branches and a checkout
        tree = self._setup_tree()
        tree2 = tree.bzrdir.sprout('branch-2').open_workingtree()
        checkout = tree.branch.create_checkout('checkout',
            lightweight=self.lightweight)
        # Change tree2 and merge it into the checkout without committing
        self.build_tree(['branch-2/file-2'])
        tree2.add('file-2')
        tree2.commit('rev2')
        checkout.merge_from_branch(tree2.branch)
        # Check the error reporting is as expected
        err = self.assertRaises(errors.BzrCommandError,
            switch.switch, checkout.bzrdir, tree2.branch)
        self.assertContainsRe(str(err),
            "Pending merges must be committed or reverted before using switch")

    def test_switch_with_revision(self):
        """Test switch when a revision is given."""
        # Create a tree with 2 revisions
        tree = self.make_branch_and_tree('branch-1')
        self.build_tree(['branch-1/file-1'])
        tree.add('file-1')
        tree.commit(rev_id='rev1', message='rev1')
        self.build_tree(['branch-1/file-2'])
        tree.add('file-2')
        tree.commit(rev_id='rev2', message='rev2')
        # Check it out and switch to revision 1
        checkout = tree.branch.create_checkout('checkout',
            lightweight=self.lightweight)
        switch.switch(checkout.bzrdir, tree.branch, revision_id="rev1")
        self.failUnlessExists('checkout/file-1')
        self.failIfExists('checkout/file-2')

    def test_switch_changing_root_id(self):
        tree = self._setup_tree()
        tree2 = self.make_branch_and_tree('tree-2')
        tree2.set_root_id('custom-root-id')
        self.build_tree(['tree-2/file-2'])
        tree2.add(['file-2'])
        tree2.commit('rev1b')
        checkout = tree.branch.create_checkout('checkout',
            lightweight=self.lightweight)
        switch.switch(checkout.bzrdir, tree2.branch)
        self.assertEqual('custom-root-id', tree2.get_root_id())

    def test_switch_configurable_file_merger(self):
        class DummyMerger(_mod_merge.ConfigurableFileMerger):
            name_prefix = 'file'

        _mod_merge.Merger.hooks.install_named_hook(
            'merge_file_content', DummyMerger,
            'test factory')
        foo = self.make_branch('foo')
        checkout = foo.create_checkout('checkout', lightweight=True)
        self.build_tree_contents([('checkout/file', 'a')])
        checkout.add('file')
        checkout.commit('a')
        bar = foo.bzrdir.sprout('bar').open_workingtree()
        self.build_tree_contents([('bar/file', 'b')])
        bar.commit('b')
        self.build_tree_contents([('checkout/file', 'c')])
        switch.switch(checkout.bzrdir, bar.branch)


class TestSwitchHeavyweight(TestSwitch):

    def setUp(self):
        super(TestSwitchHeavyweight, self).setUp()
        self.lightweight = False

    def test_switch_with_local_commits(self):
        """Test switch complains about local commits unless --force given."""
        tree = self._setup_tree()
        to_branch = tree.bzrdir.sprout('branch-2').open_branch()
        self.build_tree(['branch-1/file-2'])
        tree.add('file-2')
        tree.remove('file-1')
        tree.commit('rev2')
        checkout = tree.branch.create_checkout('checkout')
        self.build_tree(['checkout/file-3'])
        checkout.add('file-3')
        checkout.commit(message='local only commit', local=True)
        self.build_tree(['checkout/file-4'])
        # Check the error reporting is as expected
        err = self.assertRaises(errors.BzrCommandError,
            switch.switch, checkout.bzrdir, to_branch)
        self.assertContainsRe(str(err),
            'Cannot switch as local commits found in the checkout.')
        # Check all is ok when force is given
        self.failIfExists('checkout/file-1')
        self.failUnlessExists('checkout/file-2')
        switch.switch(checkout.bzrdir, to_branch, force=True)
        self.failUnlessExists('checkout/file-1')
        self.failIfExists('checkout/file-2')
        self.failIfExists('checkout/file-3')
        self.failUnlessExists('checkout/file-4')
        # Check that the checkout is a true mirror of the bound branch
        self.assertEqual(to_branch.last_revision_info(),
                         checkout.branch.last_revision_info())
