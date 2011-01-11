# Copyright (C) 2005 Canonical Ltd
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

from bzrlib import (
    missing,
    tests,
    )
from bzrlib.missing import (
    iter_log_revisions,
    )
from bzrlib.tests import TestCaseWithTransport


class TestMissing(TestCaseWithTransport):

    def assertUnmerged(self, expected, source, target, restrict='all',
                       backward=False):
        unmerged = missing.find_unmerged(source, target, restrict=restrict,
                                         backward=backward)
        self.assertEqual(expected, unmerged)

    def test_find_unmerged(self):
        original_tree = self.make_branch_and_tree('original')
        original = original_tree.branch
        puller_tree = self.make_branch_and_tree('puller')
        puller = puller_tree.branch
        merger_tree = self.make_branch_and_tree('merger')
        merger = merger_tree.branch
        self.assertUnmerged(([], []), original, puller)
        original_tree.commit('a', rev_id='a')
        self.assertUnmerged(([('1', 'a')], []), original, puller)
        puller_tree.pull(original)
        self.assertUnmerged(([], []), original, puller)
        merger_tree.pull(original)
        original_tree.commit('b', rev_id='b')
        original_tree.commit('c', rev_id='c')
        self.assertUnmerged(([('2', 'b'), ('3', 'c')], []),
                            original, puller)
        self.assertUnmerged(([('3', 'c'), ('2', 'b')], []),
                            original, puller, backward=True)

        puller_tree.pull(original)
        self.assertUnmerged(([], []), original, puller)
        self.assertUnmerged(([('2', 'b'), ('3', 'c')], []),
                            original, merger)
        merger_tree.merge_from_branch(original)
        self.assertUnmerged(([('2', 'b'), ('3', 'c')], []),
                            original, merger)
        merger_tree.commit('d', rev_id='d')
        self.assertUnmerged(([], [('2', 'd')]), original, merger)

    def test_iter_log_revisions(self):
        base_tree = self.make_branch_and_tree('base')
        self.build_tree(['base/a'])
        base_tree.add(['a'], ['a-id'])
        base_tree.commit('add a', rev_id='b-1')

        child_tree = base_tree.bzrdir.sprout('child').open_workingtree()

        self.build_tree(['child/b'])
        child_tree.add(['b'], ['b-id'])
        child_tree.commit('adding b', rev_id='c-2')

        child_tree.remove(['a'])
        child_tree.commit('removing a', rev_id='c-3')

        self.build_tree_contents([('child/b', 'new contents for b\n')])
        child_tree.commit('modifying b', rev_id='c-4')

        child_tree.rename_one('b', 'c')
        child_tree.commit('rename b=>c', rev_id='c-5')

        base_extra, child_extra = missing.find_unmerged(base_tree.branch,
                                                        child_tree.branch)
        results = list(iter_log_revisions(base_extra,
                            base_tree.branch.repository,
                            verbose=True))
        self.assertEqual([], results)

        results = list(iter_log_revisions(child_extra,
                            child_tree.branch.repository,
                            verbose=True))
        self.assertEqual(4, len(results))

        r0,r1,r2,r3 = results

        self.assertEqual([('2', 'c-2'), ('3', 'c-3'),
                          ('4', 'c-4'), ('5', 'c-5'),],
                         [(r.revno, r.rev.revision_id) for r in results])

        delta0 = r0.delta
        self.assertNotEqual(None, delta0)
        self.assertEqual([('b', 'b-id', 'file')], delta0.added)
        self.assertEqual([], delta0.removed)
        self.assertEqual([], delta0.renamed)
        self.assertEqual([], delta0.modified)

        delta1 = r1.delta
        self.assertNotEqual(None, delta1)
        self.assertEqual([], delta1.added)
        self.assertEqual([('a', 'a-id', 'file')], delta1.removed)
        self.assertEqual([], delta1.renamed)
        self.assertEqual([], delta1.modified)

        delta2 = r2.delta
        self.assertNotEqual(None, delta2)
        self.assertEqual([], delta2.added)
        self.assertEqual([], delta2.removed)
        self.assertEqual([], delta2.renamed)
        self.assertEqual([('b', 'b-id', 'file', True, False)], delta2.modified)

        delta3 = r3.delta
        self.assertNotEqual(None, delta3)
        self.assertEqual([], delta3.added)
        self.assertEqual([], delta3.removed)
        self.assertEqual([('b', 'c', 'b-id', 'file', False, False)],
                         delta3.renamed)
        self.assertEqual([], delta3.modified)


class TestFindUnmerged(tests.TestCaseWithTransport):

    def assertUnmerged(self, local, remote, local_branch, remote_branch,
            restrict='all', include_merges=False, backward=False,
            local_revid_range=None, remote_revid_range=None):
        """Check the output of find_unmerged_mainline_revisions"""
        local_extra, remote_extra = missing.find_unmerged(
            local_branch, remote_branch, restrict,
            include_merges=include_merges, backward=backward,
            local_revid_range=local_revid_range,
            remote_revid_range=remote_revid_range)
        self.assertEqual(local, local_extra)
        self.assertEqual(remote, remote_extra)

    def test_same_branch(self):
        tree = self.make_branch_and_tree('tree')
        rev1 = tree.commit('one')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertUnmerged([], [], tree.branch, tree.branch)
        self.assertUnmerged([], [], tree.branch, tree.branch,
            local_revid_range=(rev1, rev1))

    def test_one_ahead(self):
        tree = self.make_branch_and_tree('tree')
        rev1 = tree.commit('one')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        rev2 = tree2.commit('two')
        self.assertUnmerged([], [('2', rev2)], tree.branch, tree2.branch)
        self.assertUnmerged([('2', rev2)], [], tree2.branch, tree.branch)

    def test_restrict(self):
        tree = self.make_branch_and_tree('tree')
        rev1 = tree.commit('one')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        rev2 = tree2.commit('two')
        self.assertUnmerged([], [('2', rev2)], tree.branch, tree2.branch)
        self.assertUnmerged([], None, tree.branch, tree2.branch, 'local')
        self.assertUnmerged(None, [('2', rev2)], tree.branch, tree2.branch,
                                               'remote')

    def test_merged(self):
        tree = self.make_branch_and_tree('tree')
        rev1 = tree.commit('one')
        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        rev2 = tree2.commit('two')
        rev3 = tree2.commit('three')
        tree.merge_from_branch(tree2.branch)
        rev4 = tree.commit('four')

        self.assertUnmerged([('2', rev4)], [], tree.branch, tree2.branch)
        self.assertUnmerged([('2', rev4)], [], tree.branch, tree2.branch,
            local_revid_range=(rev4, rev4))
        self.assertUnmerged([], [], tree.branch, tree2.branch,
            local_revid_range=(rev1, rev1))

    def test_include_merges(self):
        tree = self.make_branch_and_tree('tree')
        rev1 = tree.commit('one', rev_id='rev1')

        tree2 = tree.bzrdir.sprout('tree2').open_workingtree()
        rev2 = tree2.commit('two', rev_id='rev2')
        rev3 = tree2.commit('three', rev_id='rev3')

        tree3 = tree2.bzrdir.sprout('tree3').open_workingtree()
        rev4 = tree3.commit('four', rev_id='rev4')
        rev5 = tree3.commit('five', rev_id='rev5')

        tree2.merge_from_branch(tree3.branch)
        rev6 = tree2.commit('six', rev_id='rev6')

        self.assertUnmerged([], [('2', 'rev2', 0), ('3', 'rev3', 0),
                                 ('4', 'rev6', 0),
                                 ('3.1.1', 'rev4', 1), ('3.1.2', 'rev5', 1),
                                 ],
                            tree.branch, tree2.branch,
                            include_merges=True)

        self.assertUnmerged([], [('4', 'rev6', 0),
                                 ('3.1.2', 'rev5', 1), ('3.1.1', 'rev4', 1),
                                 ('3', 'rev3', 0), ('2', 'rev2', 0),
                                 ],
                            tree.branch, tree2.branch,
                            include_merges=True,
                            backward=True)

        self.assertUnmerged([], [('4', 'rev6', 0)],
            tree.branch, tree2.branch,
            include_merges=True, remote_revid_range=(rev6, rev6))

        self.assertUnmerged([], [('3', 'rev3', 0), ('3.1.1', 'rev4', 1)],
                    tree.branch, tree2.branch,
                    include_merges=True, remote_revid_range=(rev3, rev4))

        self.assertUnmerged([], [('4', 'rev6', 0), ('3.1.2', 'rev5', 1)],
                    tree.branch, tree2.branch,
                    include_merges=True, remote_revid_range=(rev5, rev6))

    def test_revision_range(self):
        local = self.make_branch_and_tree('local')
        lrevid1 = local.commit('one')
        remote = local.bzrdir.sprout('remote').open_workingtree()
        rrevid2 = remote.commit('two')
        rrevid3 = remote.commit('three')
        rrevid4 = remote.commit('four')
        lrevid2 = local.commit('two')
        lrevid3 = local.commit('three')
        lrevid4 = local.commit('four')
        local_extra = [('2', lrevid2), ('3', lrevid3), ('4', lrevid4)]
        remote_extra = [('2', rrevid2), ('3', rrevid3), ('4', rrevid4)]

        # control
        self.assertUnmerged(local_extra, remote_extra,
            local.branch, remote.branch)
        self.assertUnmerged(local_extra, remote_extra,
            local.branch, remote.branch, local_revid_range=(None, None),
            remote_revid_range=(None, None))

        # exclude local revisions
        self.assertUnmerged([('2', lrevid2)], remote_extra,
            local.branch, remote.branch, local_revid_range=(lrevid2, lrevid2))
        self.assertUnmerged([('2', lrevid2), ('3', lrevid3)], remote_extra,
            local.branch, remote.branch, local_revid_range=(lrevid2, lrevid3))
        self.assertUnmerged([('2', lrevid2), ('3', lrevid3)], None,
            local.branch, remote.branch, 'local',
            local_revid_range=(lrevid2, lrevid3))

        # exclude remote revisions
        self.assertUnmerged(local_extra, [('2', rrevid2)],
            local.branch, remote.branch, remote_revid_range=(None, rrevid2))
        self.assertUnmerged(local_extra, [('2', rrevid2)],
            local.branch, remote.branch, remote_revid_range=(lrevid1, rrevid2))
        self.assertUnmerged(local_extra, [('2', rrevid2)],
            local.branch, remote.branch, remote_revid_range=(rrevid2, rrevid2))
        self.assertUnmerged(local_extra, [('2', rrevid2), ('3', rrevid3)],
            local.branch, remote.branch, remote_revid_range=(None, rrevid3))
        self.assertUnmerged(local_extra, [('2', rrevid2), ('3', rrevid3)],
            local.branch, remote.branch, remote_revid_range=(rrevid2, rrevid3))
        self.assertUnmerged(local_extra, [('3', rrevid3)],
            local.branch, remote.branch, remote_revid_range=(rrevid3, rrevid3))
        self.assertUnmerged(None, [('2', rrevid2), ('3', rrevid3)],
            local.branch, remote.branch, 'remote',
            remote_revid_range=(rrevid2, rrevid3))

        # exclude local and remote revisions
        self.assertUnmerged([('3', lrevid3)], [('3', rrevid3)],
            local.branch, remote.branch, local_revid_range=(lrevid3, lrevid3),
            remote_revid_range=(rrevid3, rrevid3))
