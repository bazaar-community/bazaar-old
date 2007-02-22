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

"""Tests for WorkingTree.paths2ids.

This API probably needs to be exposed as a tree implementation test, but these
initial tests are for the specific cases being refactored from
find_ids_across_trees.
"""

from operator import attrgetter

from bzrlib import errors
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


# TODO: This needs an additional test: do a merge, then do a
# paths2id(trees=left parent only), and also with (trees=all parents) to check
# that only the requested trees are considered - i.e. have an unversioned path
# in the unlisted tree, or an extra file that moves into the selected path but
# should not be returned

# TODO: test that supplying paths with duplication - i.e. foo, foo, foo/bar -
# does not result in garbage out.


class TestPaths2Ids(TestCaseWithWorkingTree):

    def assertExpectedIds(self, ids, tree, paths, trees=None,
        require_versioned=True):
        """Run paths2ids for tree, and check the result."""
        tree.lock_read()
        if trees:
            map(apply, map(attrgetter('lock_read'), trees))
            result = tree.paths2ids(paths, trees,
                require_versioned=require_versioned)
            map(apply, map(attrgetter('unlock'), trees))
        else:
            result = tree.paths2ids(paths,
                require_versioned=require_versioned)
        self.assertEqual(set(ids), result)
        tree.unlock()

    def test_find_single_root(self):
        tree = self.make_branch_and_tree('tree')
        self.assertExpectedIds([tree.path2id('')], tree, [''])

    def test_find_tree_and_clone_roots(self):
        tree = self.make_branch_and_tree('tree')
        clone = tree.bzrdir.clone('clone').open_workingtree()
        clone.lock_tree_write()
        clone_root_id = 'new-id'
        clone.set_root_id(clone_root_id)
        tree_root_id = tree.path2id('')
        clone.unlock()
        self.assertExpectedIds([tree_root_id, clone_root_id], tree, [''], [clone])

    def test_find_tree_basis_roots(self):
        tree = self.make_branch_and_tree('tree')
        tree.commit('basis')
        basis = tree.basis_tree()
        basis_root_id = basis.path2id('')
        tree.lock_tree_write()
        tree_root_id = 'new-id'
        tree.set_root_id(tree_root_id)
        tree.unlock()
        self.assertExpectedIds([tree_root_id, basis_root_id], tree, [''], [basis])

    def test_find_children_of_moved_directories(self):
        """Check the basic nasty corner case that path2ids should handle.

        This is the following situation:
        basis: 
          / ROOT
          /dir dir
          /dir/child-moves child-moves
          /dir/child-stays child-stays
          /dir/child-goes  child-goes

        current tree:
          / ROOT
          /child-moves child-moves
          /newdir newdir
          /newdir/dir  dir
          /newdir/dir/child-stays child-stays
          /newdir/dir/new-child   new-child

        In english: we move a directory under a directory that was a sibling,
        and at the same time remove, or move out of the directory, some of its
        children, and give it a new child previous absent or a sibling.

        current_tree.path2ids(['newdir'], [basis]) is meant to handle this
        correctly: that is it should return the ids:
          newdir because it was provided
          dir, because its under newdir in current
          child-moves because its under dir in old
          child-stays either because its under newdir/dir in current, or under dir in old
          child-goes because its under dir in old.
          new-child because its under dir in new
        
        Symmetrically, current_tree.path2ids(['dir'], [basis]) is meant to show
        new-child, even though its not under the path 'dir' in current, because
        its under a path selected by 'dir' in basis:
          dir because its selected in basis.
          child-moves because its under dir in old
          child-stays either because its under newdir/dir in current, or under dir in old
          child-goes because its under dir in old.
          new-child because its under dir in new.
        """
        tree = self.make_branch_and_tree('tree')
        self.build_tree(
            ['tree/dir/', 'tree/dir/child-moves', 'tree/dir/child-stays',
             'tree/dir/child-goes'])
        tree.add(['dir', 'dir/child-moves', 'dir/child-stays', 'dir/child-goes'],
                 ['dir', 'child-moves', 'child-stays', 'child-goes'])
        tree.commit('create basis')
        basis = tree.basis_tree()
        tree.unversion(['child-goes'])
        tree.rename_one('dir/child-moves', 'child-moves')
        self.build_tree(['tree/newdir/'])
        tree.add(['newdir'], ['newdir'])
        tree.rename_one('dir/child-stays', 'child-stays')
        tree.rename_one('dir', 'newdir/dir')
        tree.rename_one('child-stays', 'newdir/dir/child-stays')
        self.build_tree(['tree/newdir/dir/new-child'])
        tree.add(['newdir/dir/new-child'], ['new-child'])
        self.assertExpectedIds(
            ['newdir', 'dir', 'child-moves', 'child-stays', 'child-goes',
             'new-child'], tree, ['newdir'], [basis])
        self.assertExpectedIds(
            ['dir', 'child-moves', 'child-stays', 'child-goes', 'new-child'],
            tree, ['dir'], [basis])

    def test_unversioned_one_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/unversioned'])
        self.assertExpectedIds([], tree, ['unversioned'], require_versioned=False)
        tree.lock_read()
        self.assertRaises(errors.PathsNotVersionedError, tree.paths2ids, ['unversioned'])
        tree.unlock()

    def test_unversioned_multiple_trees(self):
        # in this test, the path is unversioned in only one tree, but it should
        # still raise an error.
        tree = self.make_branch_and_tree('tree')
        tree.commit('make basis')
        basis = tree.basis_tree()
        self.build_tree(['tree/unversioned'])
        self.assertExpectedIds([], tree, ['unversioned'], [basis],
            require_versioned=False)
        tree.lock_read()
        basis.lock_read()
        self.assertRaises(errors.PathsNotVersionedError, tree.paths2ids,
            ['unversioned'], [basis])
        self.assertRaises(errors.PathsNotVersionedError, basis.paths2ids,
            ['unversioned'], [tree])
        basis.unlock()
        tree.unlock()
