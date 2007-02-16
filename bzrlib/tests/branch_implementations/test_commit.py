# Copyright (C) 2007 Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the contract of commit on branches."""

from bzrlib.branch import Branch
from bzrlib import errors
from bzrlib.tests.branch_implementations.test_branch import TestCaseWithBranch
from bzrlib.revision import NULL_REVISION
from bzrlib.transport import get_transport


class TestCommit(TestCaseWithBranch):

    def test_commit_nicks(self):
        """Nicknames are committed to the revision"""
        get_transport(self.get_url()).mkdir('bzr.dev')
        wt = self.make_branch_and_tree('bzr.dev')
        branch = wt.branch
        branch.nick = "My happy branch"
        wt.commit('My commit respect da nick.')
        committed = branch.repository.get_revision(branch.last_revision())
        self.assertEqual(committed.properties["branch-nick"], 
                         "My happy branch")


class TestCommitHook(TestCaseWithBranch):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithBranch.setUp(self)

    def capture_post_commit_hook(self, local, master, old_revno,
        old_revid, new_revno, new_revid):
        """Capture post commit hook calls to self.hook_calls.
        
        The call is logged, as is some state of the two branches.
        """
        if local:
            local_locked = local.is_locked()
            local_base = local.base
        else:
            local_locked = None
            local_base = None
        self.hook_calls.append(
            ('post_commit', local_base, master.base, old_revno, old_revid,
             new_revno, new_revid, local_locked, master.is_locked()))

    def test_post_commit_to_origin(self):
        tree = self.make_branch_and_memory_tree('branch')
        Branch.hooks.install_hook('post_commit',
            self.capture_post_commit_hook)
        tree.lock_write()
        tree.add('')
        revid = tree.commit('a revision')
        # should have had one notification, from origin, and
        # have the branch locked at notification time.
        self.assertEqual([
            ('post_commit', None, tree.branch.base, 0, NULL_REVISION, 1, revid,
             None, True)
            ],
            self.hook_calls)
        tree.unlock()

    def test_post_commit_bound(self):
        master = self.make_branch('master')
        tree = self.make_branch_and_memory_tree('local')
        try:
            tree.branch.bind(master)
        except errors.UpgradeRequired:
            # cant bind this format, the test is irrelevant.
            return
        Branch.hooks.install_hook('post_commit',
            self.capture_post_commit_hook)
        tree.lock_write()
        tree.add('')
        revid = tree.commit('a revision')
        # with a bound branch, local is set.
        self.assertEqual([
            ('post_commit', tree.branch.base, master.base, 0, NULL_REVISION,
             1, revid, True, True)
            ],
            self.hook_calls)
        tree.unlock()

    def test_post_commit_not_to_origin(self):
        tree = self.make_branch_and_memory_tree('branch')
        tree.lock_write()
        tree.add('')
        revid = tree.commit('first revision')
        Branch.hooks.install_hook('post_commit',
            self.capture_post_commit_hook)
        revid2 = tree.commit('second revision')
        # having committed from up the branch, we should get the
        # before and after revnos and revids correctly.
        self.assertEqual([
            ('post_commit', None, tree.branch.base, 1, revid, 2, revid2,
             None, True)
            ],
            self.hook_calls)
        tree.unlock()
