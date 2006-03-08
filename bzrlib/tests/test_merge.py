import os
from StringIO import StringIO

from bzrlib.branch import Branch
from bzrlib.builtins import merge
from bzrlib.commit import commit
from bzrlib.errors import UnrelatedBranches, NoCommits, BzrCommandError
from bzrlib.merge import transform_tree, merge_inner
from bzrlib.osutils import pathjoin
from bzrlib.revision import common_ancestor
from bzrlib.tests import TestCaseWithTransport
from bzrlib.trace import (enable_test_log, disable_test_log)
from bzrlib.workingtree import WorkingTree


class TestMerge(TestCaseWithTransport):
    """Test appending more than one revision"""

    def test_pending(self):
        wt = self.make_branch_and_tree('.')
        wt.commit("lala!")
        self.assertEquals(len(wt.pending_merges()), 0)
        merge([u'.', -1], [None, None])
        self.assertEquals(len(wt.pending_merges()), 0)

    def test_nocommits(self):
        self.test_pending()
        wt2 = self.make_branch_and_tree('branch2')
        self.assertRaises(NoCommits, merge, ['branch2', -1], 
                          [None, None])
        return wt2

    def test_unrelated(self):
        wt2 = self.test_nocommits()
        wt2.commit("blah")
        self.assertRaises(UnrelatedBranches, merge, ['branch2', -1], 
                          [None, None])
        return wt2

    def test_pending_with_null(self):
        """When base is forced to revno 0, pending_merges is set"""
        wt2 = self.test_unrelated()
        wt1 = WorkingTree.open('.')
        br1 = wt1.branch
        br1.fetch(wt2.branch)
        # merge all of branch 2 into branch 1 even though they 
        # are not related.
        self.assertRaises(BzrCommandError, merge, ['branch2', -1], 
                          ['branch2', 0], reprocess=True, show_base=True)
        merge(['branch2', -1], ['branch2', 0], reprocess=True)
        self.assertEquals(len(wt1.pending_merges()), 1)
        return (wt1, wt2.branch)

    def test_two_roots(self):
        """Merge base is sane when two unrelated branches are merged"""
        wt1, br2 = self.test_pending_with_null()
        wt1.commit("blah")
        last = wt1.branch.last_revision()
        self.assertEquals(common_ancestor(last, last, wt1.branch.repository), last)

    def test_create_rename(self):
        """Rename an inventory entry while creating the file"""
        tree =self.make_branch_and_tree('.')
        file('name1', 'wb').write('Hello')
        tree.add('name1')
        tree.commit(message="hello")
        tree.rename_one('name1', 'name2')
        os.unlink('name2')
        transform_tree(tree, tree.branch.basis_tree())

    def test_layered_rename(self):
        """Rename both child and parent at same time"""
        tree =self.make_branch_and_tree('.')
        os.mkdir('dirname1')
        tree.add('dirname1')
        filename = pathjoin('dirname1', 'name1')
        file(filename, 'wb').write('Hello')
        tree.add(filename)
        tree.commit(message="hello")
        filename2 = pathjoin('dirname1', 'name2')
        tree.rename_one(filename, filename2)
        tree.rename_one('dirname1', 'dirname2')
        transform_tree(tree, tree.branch.basis_tree())

    def test_ignore_zero_merge_inner(self):
        # Test that merge_inner's ignore zero paramter is effective
        tree_a =self.make_branch_and_tree('a')
        tree_a.commit(message="hello")
        dir_b = tree_a.bzrdir.sprout('b')
        tree_b = dir_b.open_workingtree()
        tree_a.commit(message="hello again")
        log = StringIO()
        merge_inner(tree_b.branch, tree_a, tree_b.basis_tree(), 
                    this_tree=tree_b, ignore_zero=True)
        lines = self._get_log().splitlines(True)[-1]
        self.failUnless('All changes applied successfully.\n' not in lines)
        tree_b.revert([])
        merge_inner(tree_b.branch, tree_a, tree_b.basis_tree(), 
                    this_tree=tree_b, ignore_zero=False)
        lines = self._get_log().splitlines(True)[-1]
        self.failUnless('All changes applied successfully.\n' in lines)
