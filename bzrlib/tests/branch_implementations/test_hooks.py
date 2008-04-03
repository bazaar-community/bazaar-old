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

"""Tests that branch classes implement hook callouts correctly."""

from bzrlib.branch import Branch
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCaseWithMemoryTransport


class TestSetRevisionHistoryHook(TestCaseWithMemoryTransport):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithMemoryTransport.setUp(self)

    def capture_set_rh_hook(self, branch, rev_history):
        """Capture post set-rh hook calls to self.hook_calls.
        
        The call is logged, as is some state of the branch.
        """
        self.hook_calls.append(
            ('set_rh', branch, rev_history, branch.is_locked()))

    def test_set_rh_empty_history(self):
        branch = self.make_branch('source')
        Branch.hooks.install_hook('set_rh', self.capture_set_rh_hook)
        branch.set_revision_history([])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, [], True)])

    def test_set_rh_nonempty_history(self):
        tree = self.make_branch_and_memory_tree('source')
        tree.lock_write()
        tree.add('')
        tree.commit('another commit', rev_id='f\xc2\xb5')
        tree.commit('empty commit', rev_id='foo')
        tree.unlock()
        branch = tree.branch
        Branch.hooks.install_hook('set_rh', self.capture_set_rh_hook)
        # some branches require that their history be set to a revision in the
        # repository
        branch.set_revision_history(['f\xc2\xb5'])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, ['f\xc2\xb5'], True)])

    def test_set_rh_branch_is_locked(self):
        branch = self.make_branch('source')
        Branch.hooks.install_hook('set_rh', self.capture_set_rh_hook)
        branch.set_revision_history([])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, [], True)])

    def test_set_rh_calls_all_hooks_no_errors(self):
        branch = self.make_branch('source')
        Branch.hooks.install_hook('set_rh', self.capture_set_rh_hook)
        Branch.hooks.install_hook('set_rh', self.capture_set_rh_hook)
        branch.set_revision_history([])
        self.assertEqual(self.hook_calls,
            [('set_rh', branch, [], True),
             ('set_rh', branch, [], True),
            ])


class TestSetLastRevisionInfoHook(TestCaseWithMemoryTransport):

    def setUp(self):
        self.hook_calls = []
        TestCaseWithMemoryTransport.setUp(self)

    def capture_set_last_revision_info_hook(self, branch, revno, revid):
        """Capture set_last_revision_info hook calls to self.hook_calls.

        The call is logged, as is some state of the branch.
        """
        self.hook_calls.append(
            ('set_last_revision_info', branch, revno, revid,
             branch.is_locked()))

    def test_set_last_revision_info_empty_history(self):
        branch = self.make_branch('source')
        Branch.hooks.install_hook('set_last_revision_info',
                                  self.capture_set_last_revision_info_hook)
        branch.set_last_revision_info(0, NULL_REVISION)
        self.assertEqual(self.hook_calls,
            [('set_last_revision_info', branch, 0, NULL_REVISION, True)])

    def test_set_last_revision_info_nonempty_history(self):
        tree = self.make_branch_and_memory_tree('source')
        tree.lock_write()
        tree.add('')
        tree.commit('another commit', rev_id='f\xc2\xb5')
        tree.commit('empty commit', rev_id='foo')
        tree.unlock()
        branch = tree.branch
        Branch.hooks.install_hook('set_last_revision_info',
                                  self.capture_set_last_revision_info_hook)
        # some branches require that their history be set to a revision in the
        # repository
        branch.set_last_revision_info(1, 'f\xc2\xb5')
        self.assertEqual(self.hook_calls,
            [('set_last_revision_info', branch, 1, 'f\xc2\xb5', True)])

    def test_set_last_revision_info_branch_is_locked(self):
        branch = self.make_branch('source')
        Branch.hooks.install_hook('set_last_revision_info',
                                  self.capture_set_last_revision_info_hook)
        branch.set_last_revision_info(0, NULL_REVISION)
        self.assertEqual(self.hook_calls,
            [('set_last_revision_info', branch, 0, NULL_REVISION, True)])

    def test_set_last_revision_info_calls_all_hooks_no_errors(self):
        branch = self.make_branch('source')
        Branch.hooks.install_hook('set_last_revision_info',
                                  self.capture_set_last_revision_info_hook)
        Branch.hooks.install_hook('set_last_revision_info',
                                  self.capture_set_last_revision_info_hook)
        branch.set_last_revision_info(0, NULL_REVISION)
        self.assertEqual(self.hook_calls,
            [('set_last_revision_info', branch, 0, NULL_REVISION, True),
             ('set_last_revision_info', branch, 0, NULL_REVISION, True),
            ])
