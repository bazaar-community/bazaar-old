# Copyright (C) 2008 Canonical Ltd
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

"""Tests for branch implementations - test check() functionality"""

from StringIO import StringIO

from bzrlib import errors, tests, ui
from bzrlib.tests.branch_implementations import TestCaseWithBranch


class TestBranchCheck(TestCaseWithBranch):

    def test_check_detects_invalid_revhistory(self):
        # Different formats have different ways of handling invalid revision
        # histories, so the setup portion is customized
        tree = self.make_branch_and_tree('test')
        r1 = tree.commit('one')
        r2 = tree.commit('two')
        r3 = tree.commit('three')
        r4 = tree.commit('four')
        # create an alternate branch
        tree.set_parent_ids([r1])
        tree.branch.set_last_revision_info(1, r1)
        r2b = tree.commit('two-b')

        # now go back and merge the commit
        tree.set_parent_ids([r4, r2b])
        tree.branch.set_last_revision_info(4, r4)

        r5 = tree.commit('five')
        # Now, try to set an invalid history
        try:
            tree.branch.set_revision_history([r1, r2b, r5])
            if tree.branch.last_revision_info() != (3, r5):
                # RemoteBranch silently corrects an impossible revision
                # history given to set_revision_history.  It can be tricked
                # with set_last_revision_info though.
                tree.branch.set_last_revision_info(3, r5)
        except errors.NotLefthandHistory:
            # Branch5 allows set_revision_history to be wrong
            # Branch6 raises NotLefthandHistory, but we can force bogus stuff
            # with set_last_revision_info
            tree.branch.set_last_revision_info(3, r5)

        tree.lock_read()
        self.addCleanup(tree.unlock)
        refs = self.make_refs(tree.branch)
        result = tree.branch.check(refs)
        ui.ui_factory = tests.TestUIFactory(stdout=StringIO())
        result.report_results(True)
        self.assertContainsRe('revno does not match len',
            ui.ui_factory.stdout.getvalue())

    def test_check_branch_report_results(self):
        """Checking a branch produces results which can be printed"""
        branch = self.make_branch('.')
        branch.lock_read()
        self.addCleanup(branch.unlock)
        result = branch.check(self.make_refs(branch))
        # reports results through logging
        result.report_results(verbose=True)
        result.report_results(verbose=False)

    def test__get_check_refs(self):
        tree = self.make_branch_and_tree('.')
        revid = tree.commit('foo')
        self.assertEqual(
            set([('revision-existence', revid), ('lefthand-distance', revid)]),
            set(tree.branch._get_check_refs()))

    def make_refs(self, branch):
        needed_refs = branch._get_check_refs()
        refs = {}
        distances = set()
        existences = set()
        for ref in needed_refs:
            kind, value = ref
            if kind == 'lefthand-distance':
                distances.add(value)
            elif kind == 'revision-existence':
                existences.add(value)
            else:
                raise AssertionError(
                    'unknown ref kind for ref %s' % ref)
        node_distances = branch.repository.get_graph().find_lefthand_distances(
            distances)
        for key, distance in node_distances.iteritems():
            refs[('lefthand-distance', key)] = distance
            if key in existences and distance > 0:
                refs[('revision-existence', key)] = True
                existences.remove(key)
        parent_map = branch.repository.get_graph().get_parent_map(existences)
        for key in parent_map:
            refs[('revision-existence', key)] = True
            existences.remove(key)
        for key in existences:
            refs[('revision-existence', key)] = False
        return refs
