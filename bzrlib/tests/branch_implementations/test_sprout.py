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

"""Tests for Branch.sprout()"""

from bzrlib import (
    branch as _mod_branch,
    remote,
    revision as _mod_revision,
    tests,
    )
from bzrlib.tests.branch_implementations import TestCaseWithBranch


class TestSprout(TestCaseWithBranch):

    def test_sprout_branch_nickname(self):
        # test the nick name is reset always
        raise tests.TestSkipped('XXX branch sprouting is not yet tested.')

    def test_sprout_branch_parent(self):
        source = self.make_branch('source')
        target = source.bzrdir.sprout(self.get_url('target')).open_branch()
        self.assertEqual(source.bzrdir.root_transport.base, target.get_parent())

    def test_sprout_uses_bzrdir_branch_format(self):
        if isinstance(self.branch_format, _mod_branch.BranchReferenceFormat):
            raise tests.TestNotApplicable('cannot sprout to a reference')
        # Start with a format that is unlikely to be the target format
        source = tests.TestCaseWithTransport.make_branch(self, 'old-branch',
                                                         format='metaweave')
        target_bzrdir = self.make_bzrdir('target')
        target_bzrdir.create_repository()
        target = source.sprout(target_bzrdir)

        self.assertIs(self.branch_format.__class__, target._format.__class__)

    def test_sprout_partial(self):
        # test sprouting with a prefix of the revision-history.
        # also needs not-on-revision-history behaviour defined.
        wt_a = self.make_branch_and_tree('a')
        self.build_tree(['a/one'])
        wt_a.add(['one'])
        wt_a.commit('commit one', rev_id='1')
        self.build_tree(['a/two'])
        wt_a.add(['two'])
        wt_a.commit('commit two', rev_id='2')
        repo_b = self.make_repository('b')
        repo_a = wt_a.branch.repository
        repo_a.copy_content_into(repo_b)
        br_b = wt_a.branch.sprout(repo_b.bzrdir, revision_id='1')
        self.assertEqual('1', br_b.last_revision())

    def test_sprout_partial_not_in_revision_history(self):
        """We should be able to sprout from any revision in ancestry."""
        wt = self.make_branch_and_tree('source')
        self.build_tree(['source/a'])
        wt.add('a')
        wt.commit('rev1', rev_id='rev1')
        wt.commit('rev2-alt', rev_id='rev2-alt')
        wt.set_parent_ids(['rev1'])
        wt.branch.set_last_revision_info(1, 'rev1')
        wt.commit('rev2', rev_id='rev2')
        wt.set_parent_ids(['rev2', 'rev2-alt'])
        wt.commit('rev3', rev_id='rev3')

        repo = self.make_repository('target')
        repo.fetch(wt.branch.repository)
        branch2 = wt.branch.sprout(repo.bzrdir, revision_id='rev2-alt')
        self.assertEqual((2, 'rev2-alt'), branch2.last_revision_info())
        self.assertEqual(['rev1', 'rev2-alt'], branch2.revision_history())

    def test_sprout_from_any_repo_revision(self):
        """We should be able to sprout from any revision."""
        wt = self.make_branch_and_tree('source')
        self.build_tree(['source/a'])
        wt.add('a')
        wt.commit('rev1a', rev_id='rev1a')
        # simulated uncommit
        wt.branch.set_last_revision_info(0, _mod_revision.NULL_REVISION)
        wt.set_last_revision(_mod_revision.NULL_REVISION)
        wt.revert()
        wt.commit('rev1b', rev_id='rev1b')
        wt2 = wt.bzrdir.sprout('target',
            revision_id='rev1a').open_workingtree()
        self.assertEqual('rev1a', wt2.last_revision())
        self.failUnlessExists('target/a')
