# (C) 2005 Canonical Ltd
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


import os
import warnings

from bzrlib import (
    revision,
    )
from bzrlib.branch import Branch
from bzrlib.errors import NoSuchRevision
from bzrlib.graph import Graph
from bzrlib.revision import (find_present_ancestors, combined_graph,
                             common_ancestor,
                             is_ancestor, MultipleRevisionSources,
                             NULL_REVISION)
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.trace import mutter
from bzrlib.workingtree import WorkingTree

# We're allowed to test deprecated interfaces
warnings.filterwarnings('ignore',
        '.*get_intervening_revisions was deprecated',
        DeprecationWarning,
        r'bzrlib\.tests\.test_revision')

# XXX: Make this a method of a merge base case
def make_branches(self):
    """Create two branches

    branch 1 has 6 commits, branch 2 has 3 commits
    commit 10 is a ghosted merge merge from branch 1

    the object graph is
    B:     A:
    a..0   a..0 
    a..1   a..1
    a..2   a..2
    b..3   a..3 merges b..4
    b..4   a..4
    b..5   a..5 merges b..5
    b..6 merges a4

    so A is missing b6 at the start
    and B is missing a3, a4, a5
    """
    tree1 = self.make_branch_and_tree("branch1")
    br1 = tree1.branch
    
    tree1.commit("Commit one", rev_id="a@u-0-0")
    tree1.commit("Commit two", rev_id="a@u-0-1")
    tree1.commit("Commit three", rev_id="a@u-0-2")

    tree2 = tree1.bzrdir.clone("branch2").open_workingtree()
    br2 = tree2.branch
    tree2.commit("Commit four", rev_id="b@u-0-3")
    tree2.commit("Commit five", rev_id="b@u-0-4")
    revisions_2 = br2.revision_history()
    
    br1.fetch(br2)
    tree1.add_pending_merge(revisions_2[4])
    self.assertEquals(revisions_2[4], 'b@u-0-4')
    tree1.commit("Commit six", rev_id="a@u-0-3")
    tree1.commit("Commit seven", rev_id="a@u-0-4")
    tree2.commit("Commit eight", rev_id="b@u-0-5")
    
    br1.fetch(br2)
    tree1.add_pending_merge(br2.revision_history()[5])
    tree1.commit("Commit nine", rev_id="a@u-0-5")
    # DO NOT FETCH HERE - we WANT a GHOST.
    # br2.fetch(br1)
    tree2.add_pending_merge(br1.revision_history()[4])
    tree2.commit("Commit ten - ghost merge", rev_id="b@u-0-6")
    
    return br1, br2


class TestIsAncestor(TestCaseWithTransport):

    def test_recorded_ancestry(self):
        """Test that commit records all ancestors"""
        br1, br2 = make_branches(self)
        d = [('a@u-0-0', ['a@u-0-0']),
             ('a@u-0-1', ['a@u-0-0', 'a@u-0-1']),
             ('a@u-0-2', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2']),
             ('b@u-0-3', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3']),
             ('b@u-0-4', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3',
                          'b@u-0-4']),
             ('a@u-0-3', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3', 'b@u-0-4',
                          'a@u-0-3']),
             ('a@u-0-4', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3', 'b@u-0-4',
                          'a@u-0-3', 'a@u-0-4']),
             ('b@u-0-5', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'b@u-0-3', 'b@u-0-4',
                          'b@u-0-5']),
             ('a@u-0-5', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2', 'a@u-0-3', 'a@u-0-4',
                          'b@u-0-3', 'b@u-0-4',
                          'b@u-0-5', 'a@u-0-5']),
             ('b@u-0-6', ['a@u-0-0', 'a@u-0-1', 'a@u-0-2',
                          'b@u-0-3', 'b@u-0-4',
                          'b@u-0-5', 'b@u-0-6']),
             ]
        br1_only = ('a@u-0-3', 'a@u-0-4', 'a@u-0-5')
        br2_only = ('b@u-0-6',)
        for branch in br1, br2:
            for rev_id, anc in d:
                if rev_id in br1_only and not branch is br1:
                    continue
                if rev_id in br2_only and not branch is br2:
                    continue
                mutter('ancestry of {%s}: %r',
                       rev_id, branch.repository.get_ancestry(rev_id))
                result = sorted(branch.repository.get_ancestry(rev_id))
                self.assertEquals(result, [None] + sorted(anc))
    
    
    def test_is_ancestor(self):
        """Test checking whether a revision is an ancestor of another revision"""
        br1, br2 = make_branches(self)
        revisions = br1.revision_history()
        revisions_2 = br2.revision_history()
        sources = br1

        self.assert_(is_ancestor(revisions[0], revisions[0], br1))
        self.assert_(is_ancestor(revisions[1], revisions[0], sources))
        self.assert_(not is_ancestor(revisions[0], revisions[1], sources))
        self.assert_(is_ancestor(revisions_2[3], revisions[0], sources))
        # disabled mbp 20050914, doesn't seem to happen anymore
        ## self.assertRaises(NoSuchRevision, is_ancestor, revisions_2[3],
        ##                  revisions[0], br1)        
        self.assert_(is_ancestor(revisions[3], revisions_2[4], sources))
        self.assert_(is_ancestor(revisions[3], revisions_2[4], br1))
        self.assert_(is_ancestor(revisions[3], revisions_2[3], sources))
        ## self.assert_(not is_ancestor(revisions[3], revisions_2[3], br1))


class TestIntermediateRevisions(TestCaseWithTransport):

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.br1, self.br2 = make_branches(self)
        wt1 = self.br1.bzrdir.open_workingtree()
        wt2 = self.br2.bzrdir.open_workingtree()
        wt2.commit("Commit eleven", rev_id="b@u-0-7")
        wt2.commit("Commit twelve", rev_id="b@u-0-8")
        wt2.commit("Commit thirtteen", rev_id="b@u-0-9")

        self.br1.fetch(self.br2)
        wt1.add_pending_merge(self.br2.revision_history()[6])
        wt1.commit("Commit fourtten", rev_id="a@u-0-6")

        self.br2.fetch(self.br1)
        wt2.add_pending_merge(self.br1.revision_history()[6])
        wt2.commit("Commit fifteen", rev_id="b@u-0-10")

        from bzrlib.revision import MultipleRevisionSources
        self.sources = MultipleRevisionSources(self.br1.repository,
                                               self.br2.repository)



class MockRevisionSource(object):
    """A RevisionSource that takes a pregenerated graph.

    This is useful for testing revision graph algorithms where
    the actual branch existing is irrelevant.
    """

    def __init__(self, full_graph):
        self._full_graph = full_graph

    def get_revision_graph_with_ghosts(self, revision_ids):
        # This is mocked out to just return a constant graph.
        return self._full_graph


class TestCommonAncestor(TestCaseWithTransport):
    """Test checking whether a revision is an ancestor of another revision"""

    def test_common_ancestor(self):
        """Pick a reasonable merge base"""
        br1, br2 = make_branches(self)
        revisions = br1.revision_history()
        revisions_2 = br2.revision_history()
        sources = MultipleRevisionSources(br1.repository, br2.repository)
        expected_ancestors_list = {revisions[3]:(0, 0), 
                                   revisions[2]:(1, 1),
                                   revisions_2[4]:(2, 1), 
                                   revisions[1]:(3, 2),
                                   revisions_2[3]:(4, 2),
                                   revisions[0]:(5, 3) }
        ancestors_list = find_present_ancestors(revisions[3], sources)
        self.assertEquals(len(expected_ancestors_list), len(ancestors_list))
        for key, value in expected_ancestors_list.iteritems():
            self.assertEqual(ancestors_list[key], value, 
                              "key %r, %r != %r" % (key, ancestors_list[key],
                                                    value))
        self.assertEqual(common_ancestor(revisions[0], revisions[0], sources),
                          revisions[0])
        self.assertEqual(common_ancestor(revisions[1], revisions[2], sources),
                          revisions[1])
        self.assertEqual(common_ancestor(revisions[1], revisions[1], sources),
                          revisions[1])
        self.assertEqual(common_ancestor(revisions[2], revisions_2[4], sources),
                          revisions[2])
        self.assertEqual(common_ancestor(revisions[3], revisions_2[4], sources),
                          revisions_2[4])
        self.assertEqual(common_ancestor(revisions[4], revisions_2[5], sources),
                          revisions_2[4])
        self.assertTrue(common_ancestor(revisions[5], revisions_2[6], sources) in
                        (revisions[4], revisions_2[5]))
        self.assertTrue(common_ancestor(revisions_2[6], revisions[5], sources),
                        (revisions[4], revisions_2[5]))
        self.assertEqual(None, common_ancestor(None, revisions[5], sources))
        self.assertEqual(NULL_REVISION,
            common_ancestor(NULL_REVISION, NULL_REVISION, sources))
        self.assertEqual(NULL_REVISION,
            common_ancestor(revisions[0], NULL_REVISION, sources))
        self.assertEqual(NULL_REVISION,
            common_ancestor(NULL_REVISION, revisions[0], sources))

    def test_combined(self):
        """combined_graph
        Ensure it's not order-sensitive
        """
        br1, br2 = make_branches(self)
        source = MultipleRevisionSources(br1.repository, br2.repository)
        combined_1 = combined_graph(br1.last_revision(), 
                                    br2.last_revision(), source)
        combined_2 = combined_graph(br2.last_revision(),
                                    br1.last_revision(), source)
        self.assertEquals(combined_1[1], combined_2[1])
        self.assertEquals(combined_1[2], combined_2[2])
        self.assertEquals(combined_1[3], combined_2[3])
        self.assertEquals(combined_1, combined_2)

    def test_get_history(self):
        # TODO: test ghosts on the left hand branch's impact
        # TODO: test ghosts on all parents, we should get some
        # indicator. i.e. NULL_REVISION
        # RBC 20060608
        tree = self.make_branch_and_tree('.')
        tree.commit('1', rev_id = '1', allow_pointless=True)
        tree.commit('2', rev_id = '2', allow_pointless=True)
        tree.commit('3', rev_id = '3', allow_pointless=True)
        rev = tree.branch.repository.get_revision('1')
        history = rev.get_history(tree.branch.repository)
        self.assertEqual([None, '1'], history)
        rev = tree.branch.repository.get_revision('2')
        history = rev.get_history(tree.branch.repository)
        self.assertEqual([None, '1', '2'], history)
        rev = tree.branch.repository.get_revision('3')
        history = rev.get_history(tree.branch.repository)
        self.assertEqual([None, '1', '2' ,'3'], history)

    def test_common_ancestor_rootless_graph(self):
        # common_ancestor on a graph with no reachable roots - only
        # ghosts - should still return a useful value.
        graph = Graph()
        # add a ghost node which would be a root if it wasn't a ghost.
        graph.add_ghost('a_ghost')
        # add a normal commit on top of that
        graph.add_node('rev1', ['a_ghost'])
        # add a left-branch revision
        graph.add_node('left', ['rev1'])
        # add a right-branch revision
        graph.add_node('right', ['rev1'])
        source = MockRevisionSource(graph)
        self.assertEqual('rev1', common_ancestor('left', 'right', source))


class TestMultipleRevisionSources(TestCaseWithTransport):
    """Tests for the MultipleRevisionSources adapter."""

    def test_get_revision_graph_merges_ghosts(self):
        # when we ask for the revision graph for B, which
        # is in repo 1 with a ghost of A, and which is not
        # in repo 2, which has A, the revision_graph()
        # should return A and B both.
        tree_1 = self.make_branch_and_tree('1')
        tree_1.add_pending_merge('A')
        tree_1.commit('foo', rev_id='B', allow_pointless=True)
        tree_2 = self.make_branch_and_tree('2')
        tree_2.commit('bar', rev_id='A', allow_pointless=True)
        source = MultipleRevisionSources(tree_1.branch.repository,
                                         tree_2.branch.repository)
        self.assertEqual({'B':['A'],
                          'A':[]},
                         source.get_revision_graph('B'))

class TestRevisionAttributes(TestCaseWithTransport):
    """Test that revision attributes are correct."""

    def test_revision_accessors(self):
        """Make sure the values that come out of a revision are the same as the ones that go in.
        """
        tree1 = self.make_branch_and_tree("br1")

        # create a revision
        tree1.commit(message="quux", allow_pointless=True, committer="jaq",
                     revprops={'empty':'',
                               'value':'one',
                               'unicode':'\xb5',
                               'multiline':'foo\nbar\n\n'
                              })
        assert len(tree1.branch.revision_history()) > 0
        rev_a = tree1.branch.repository.get_revision(tree1.branch.last_revision())

        tree2 = self.make_branch_and_tree("br2")
        tree2.commit(message=rev_a.message,
                     timestamp=rev_a.timestamp,
                     timezone=rev_a.timezone,
                     committer=rev_a.committer,
                     rev_id=rev_a.revision_id,
                     revprops=rev_a.properties,
                     allow_pointless=True, # there's nothing in this commit
                     strict=True,
                     verbose=True)
        rev_b = tree2.branch.repository.get_revision(tree2.branch.last_revision())
        
        self.assertEqual(rev_a.message, rev_b.message)
        self.assertEqual(rev_a.timestamp, rev_b.timestamp)
        self.assertEqual(rev_a.timezone, rev_b.timezone)
        self.assertEqual(rev_a.committer, rev_b.committer)
        self.assertEqual(rev_a.revision_id, rev_b.revision_id)
        self.assertEqual(rev_a.properties, rev_b.properties)


class TestRevisionEncodeCache(TestCase):
    
    def setUp(self):
        super(TestRevisionEncodeCache, self).setUp()
        revision.clear_encoding_cache()
        self.addCleanup(revision.clear_encoding_cache)

    def check_one(self, rev_id):
        rev_id_utf8 = rev_id.encode('utf-8')
        self.failIf(rev_id in revision._unicode_to_utf8_map)
        self.failIf(rev_id_utf8 in revision._utf8_to_unicode_map)

        # After a single encode, the mapping should exist for
        # both directions
        self.assertEqual(rev_id_utf8, revision.encode_utf8(rev_id))
        self.failUnless(rev_id in revision._unicode_to_utf8_map)
        self.failUnless(rev_id_utf8 in revision._utf8_to_unicode_map)
        self.assertEqual(rev_id, revision.decode_utf8(rev_id_utf8))

    def test_ascii(self):
        self.check_one(u'all_ascii_characters123123123')

    def test_unicode(self):
        self.check_one(u'some_\xb5_unicode_\xe5_chars')

