# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests for the InterTree.compare() function."""

import os
import shutil

from bzrlib import (
    errors,
    mutabletree,
    tests,
    )
from bzrlib.osutils import has_symlinks
from bzrlib.tests.per_intertree import TestCaseWithTwoTrees
from bzrlib.tests import (
    features,
    )

# TODO: test the include_root option.
# TODO: test that renaming a directory x->y does not emit a rename for the
#       child x/a->y/a.
# TODO: test that renaming a directory x-> does not emit a rename for the child
#        x/a -> y/a when a supplied_files argument gives either 'x/' or 'y/a'
#        -> that is, when the renamed parent is not processed by the function.
# TODO: test items are only emitted once when a specific_files list names a dir
#       whose parent is now a child.
# TODO: test comparisons between trees with different root ids. mbp 20070301
#
# TODO: More comparisons between trees with subtrees in different states.
#
# TODO: Many tests start out by setting the tree roots ids the same, maybe
#       that should just be the default for these tests, by changing
#       make_branch_and_tree.  mbp 20070307

class TestCompare(TestCaseWithTwoTrees):

    def test_compare_empty_trees(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_empty_to_abc_content(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([('a', 'a-id', 'file'),
                          ('b', 'b-id', 'directory'),
                          ('b/c', 'c-id', 'file'),
                         ], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_dangling(self):
        # This test depends on the ability for some trees to have a difference
        # between a 'versioned present' and 'versioned not present' (aka
        # dangling) file. In this test there are two trees each with a separate
        # dangling file, and the dangling files should be considered absent for
        # the test.
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['2/a'])
        tree2.add('a')
        os.unlink('2/a')
        self.build_tree(['1/b'])
        tree1.add('b')
        os.unlink('1/b')
        # the conversion to test trees here will leave the trees intact for the
        # default intertree, but may perform a commit for other tree types,
        # which may reduce the validity of the test. XXX: Think about how to
        # address this.
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_abc_content_to_empty(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([('a', 'a-id', 'file'),
                          ('b', 'b-id', 'directory'),
                          ('b/c', 'c-id', 'file'),
                         ], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_content_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_2(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([('a', 'a-id', 'file', True, False)], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_3(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([('b/c', 'c-id', 'file', False, True)], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_file_rename(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_4(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('a', 'd', 'a-id', 'file', False, False)], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_file_rename_and_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_5(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('a', 'd', 'a-id', 'file', True, False)], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_file_rename_and_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_6(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('b/c', 'e', 'c-id', 'file', False, True)], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_empty_to_abc_content_a_only(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(specific_files=['a'])
        self.assertEqual([('a', 'a-id', 'file')], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_empty_to_abc_content_a_and_c_only(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(
            specific_files=['a', 'b/c'])
        self.assertEqual(
            [('a', 'a-id', 'file'),  (u'b', 'b-id', 'directory'),
             ('b/c', 'c-id', 'file')],
            d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_empty_to_abc_content_c_only(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(
            specific_files=['b/c'])
        self.assertEqual(
            [(u'b', 'b-id', 'directory'), ('b/c', 'c-id', 'file')], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_empty_to_abc_content_b_only(self):
        """Restricting to a dir matches the children of the dir."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(specific_files=['b'])
        self.assertEqual(
            [('b', 'b-id', 'directory'), ('b/c', 'c-id', 'file')],
            d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_unchanged_with_renames_and_modifications(self):
        """want_unchanged should generate a list of unchanged entries."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_5(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(want_unchanged=True)
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([('a', 'd', 'a-id', 'file', True, False)], d.renamed)
        self.assertEqual(
            [(u'b', 'b-id', 'directory'), (u'b/c', 'c-id', 'file')],
            d.unchanged)

    def test_extra_trees_finds_ids(self):
        """Ask for a delta between two trees with a path present in a third."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_3(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare(specific_files=['b'])
        # the type of tree-3 does not matter - it is used as a lookup, not
        # a dispatch. XXX: For dirstate it does speak to the optimisability of
        # the lookup, in merged trees it can be fast-pathed. We probably want
        # two tests: one as is, and one with it as a pending merge.
        tree3 = self.make_branch_and_tree('3')
        tree3 = self.get_tree_no_parents_abc_content_6(tree3)
        tree3.lock_read()
        self.addCleanup(tree3.unlock)
        # tree 3 has 'e' which is 'c-id'. Tree 1 has c-id at b/c, and Tree 2
        # has c-id at b/c with its exec flag toggled.
        # without extra_trees, we should get no modifications from this
        # so do one, to be sure the test is valid.
        d = self.intertree_class(tree1, tree2).compare(
            specific_files=['e'])
        self.assertEqual([], d.modified)
        # now give it an additional lookup:
        d = self.intertree_class(tree1, tree2).compare(
            specific_files=['e'], extra_trees=[tree3])
        self.assertEqual([], d.added)
        self.assertEqual([('b/c', 'c-id', 'file', False, True)], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)

    def test_require_versioned(self):
        # this does not quite robustly test, as it is passing in missing paths
        # rather than present-but-not-versioned paths. At the moment there is
        # no mechanism for managing the test trees (which are readonly) to
        # get present-but-not-versioned files for trees that can do that.
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        self.assertRaises(errors.PathsNotVersionedError,
            self.intertree_class(tree1, tree2).compare,
            specific_files=['d'],
            require_versioned=True)

    def test_default_ignores_unversioned_files(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/a', 'tree1/c',
                         'tree2/a', 'tree2/b', 'tree2/c'])
        tree1.add(['a', 'c'], ['a-id', 'c-id'])
        tree2.add(['a', 'c'], ['a-id', 'c-id'])

        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        d = self.intertree_class(tree1, tree2).compare()
        self.assertEqual([], d.added)
        self.assertEqual([(u'a', 'a-id', 'file', True, False),
            (u'c', 'c-id', 'file', True, False)], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)
        self.assertEqual([], d.unversioned)

    def test_unversioned_paths_in_tree(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree2/file', 'tree2/dir/'])
        if has_symlinks():
            os.symlink('target', 'tree2/link')
            links_supported = True
        else:
            links_supported = False
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        self.not_applicable_if_cannot_represent_unversioned(tree2)
        d = self.intertree_class(tree1, tree2).compare(want_unversioned=True)
        self.assertEqual([], d.added)
        self.assertEqual([], d.modified)
        self.assertEqual([], d.removed)
        self.assertEqual([], d.renamed)
        self.assertEqual([], d.unchanged)
        expected_unversioned = [(u'dir', None, 'directory'),
                                (u'file', None, 'file')]
        if links_supported:
            expected_unversioned.append((u'link', None, 'symlink'))
        self.assertEqual(expected_unversioned, d.unversioned)


class TestIterChanges(TestCaseWithTwoTrees):
    """Test the comparison iterator"""

    def assertEqualIterChanges(self, left_changes, right_changes):
        """Assert that left_changes == right_changes.

        :param left_changes: A list of the output from iter_changes.
        :param right_changes: A list of the output from iter_changes.
        """
        left_changes = sorted(left_changes)
        right_changes = sorted(right_changes)
        if left_changes == right_changes:
            return
        # setify to get item by item differences, but we can only do this
        # when all the ids are unique on both sides.
        left_dict = dict((item[0], item) for item in left_changes)
        right_dict = dict((item[0], item) for item in right_changes)
        if (len(left_dict) != len(left_changes) or
            len(right_dict) != len(right_changes)):
            # Can't do a direct comparison. We could do a sequence diff, but
            # for now just do a regular assertEqual for now.
            self.assertEqual(left_changes, right_changes)
        keys = set(left_dict).union(set(right_dict))
        different = []
        same = []
        for key in keys:
            left_item = left_dict.get(key)
            right_item = right_dict.get(key)
            if left_item == right_item:
                same.append(str(left_item))
            else:
                different.append(" %s\n %s" % (left_item, right_item))
        self.fail("iter_changes output different. Unchanged items:\n" +
            "\n".join(same) + "\nChanged items:\n" + "\n".join(different))

    def do_iter_changes(self, tree1, tree2, **extra_args):
        """Helper to run iter_changes from tree1 to tree2.

        :param tree1, tree2:  The source and target trees. These will be locked
            automatically.
        :param **extra_args: Extra args to pass to iter_changes. This is not
            inspected by this test helper.
        """
        tree1.lock_read()
        tree2.lock_read()
        try:
            # sort order of output is not strictly defined
            return sorted(self.intertree_class(tree1, tree2)
                .iter_changes(**extra_args))
        finally:
            tree1.unlock()
            tree2.unlock()

    def check_has_changes(self, expected, tree1, tree2):
        # has_changes is defined for mutable trees only
        if not isinstance(tree2, mutabletree.MutableTree):
            if isinstance(tree1, mutabletree.MutableTree):
                # Let's switch the trees since has_changes() is commutative
                # (where we can apply it)
                tree2, tree1 = tree1, tree2
            else:
                # Neither tree can be used
                return
        tree1.lock_read()
        try:
            tree2.lock_read()
            try:
                return tree2.has_changes(tree1)
            finally:
                tree2.unlock()
        finally:
            tree1.unlock()

    def mutable_trees_to_locked_test_trees(self, tree1, tree2):
        """Convert the working trees into test trees.

        Read lock them, and add the unlock to the cleanup.
        """
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        tree1.lock_read()
        self.addCleanup(tree1.unlock)
        tree2.lock_read()
        self.addCleanup(tree2.unlock)
        return tree1, tree2

    def make_tree_with_special_names(self):
        """Create a tree with filenames chosen to exercise the walk order."""
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        paths, path_ids = self._create_special_names(tree2, 'tree2')
        tree2.commit('initial', rev_id='rev-1')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        return (tree1, tree2, paths, path_ids)

    def make_trees_with_special_names(self):
        """Both trees will use the special names.

        But the contents will differ for each file.
        """
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        paths, path_ids = self._create_special_names(tree1, 'tree1')
        paths, path_ids = self._create_special_names(tree2, 'tree2')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        return (tree1, tree2, paths, path_ids)

    def _create_special_names(self, tree, base_path):
        """Create a tree with paths that expose differences in sort orders."""
        # Each directory will have a single file named 'f' inside
        dirs = ['a',
                'a-a',
                'a/a',
                'a/a-a',
                'a/a/a',
                'a/a/a-a',
                'a/a/a/a',
                'a/a/a/a-a',
                'a/a/a/a/a',
               ]
        with_slashes = []
        paths = []
        path_ids = []
        for d in dirs:
            with_slashes.append(base_path + '/' + d + '/')
            with_slashes.append(base_path + '/' + d + '/f')
            paths.append(d)
            paths.append(d+'/f')
            path_ids.append(d.replace('/', '_') + '-id')
            path_ids.append(d.replace('/', '_') + '_f-id')
        self.build_tree(with_slashes)
        tree.add(paths, path_ids)
        return paths, path_ids

    def test_compare_empty_trees(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        self.assertEqual([], self.do_iter_changes(tree1, tree2))
        self.check_has_changes(False, tree1, tree2)

    def added(self, tree, file_id):
        path, entry = self.get_path_entry(tree, file_id)
        return (file_id, (None, path), True, (False, True), (None, entry.parent_id),
                (None, entry.name), (None, entry.kind),
                (None, entry.executable))

    @staticmethod
    def get_path_entry(tree, file_id):
        iterator = tree.iter_entries_by_dir(specific_file_ids=[file_id])
        return iterator.next()

    def content_changed(self, tree, file_id):
        path, entry = self.get_path_entry(tree, file_id)
        return (file_id, (path, path), True, (True, True),
                (entry.parent_id, entry.parent_id),
                (entry.name, entry.name), (entry.kind, entry.kind),
                (entry.executable, entry.executable))

    def kind_changed(self, from_tree, to_tree, file_id):
        from_path, old_entry = self.get_path_entry(from_tree, file_id)
        path, new_entry = self.get_path_entry(to_tree, file_id)
        return (file_id, (from_path, path), True, (True, True),
                (old_entry.parent_id, new_entry.parent_id),
                (old_entry.name, new_entry.name),
                (old_entry.kind, new_entry.kind),
                (old_entry.executable, new_entry.executable))

    def missing(self, file_id, from_path, to_path, parent_id, kind):
        _, from_basename = os.path.split(from_path)
        _, to_basename = os.path.split(to_path)
        # missing files have both paths, but no kind.
        return (file_id, (from_path, to_path), True, (True, True),
            (parent_id, parent_id),
            (from_basename, to_basename), (kind, None), (False, False))

    def deleted(self, tree, file_id):
        entry = tree.root_inventory[file_id]
        path = tree.id2path(file_id)
        return (file_id, (path, None), True, (True, False), (entry.parent_id, None),
                (entry.name, None), (entry.kind, None),
                (entry.executable, None))

    def renamed(self, from_tree, to_tree, file_id, content_changed):
        from_path, from_entry = self.get_path_entry(from_tree, file_id)
        to_path, to_entry = self.get_path_entry(to_tree, file_id)
        return (file_id, (from_path, to_path), content_changed, (True, True),
            (from_entry.parent_id, to_entry.parent_id),
            (from_entry.name, to_entry.name),
            (from_entry.kind, to_entry.kind),
            (from_entry.executable, to_entry.executable))

    def unchanged(self, tree, file_id):
        path, entry = self.get_path_entry(tree, file_id)
        parent = entry.parent_id
        name = entry.name
        kind = entry.kind
        executable = entry.executable
        return (file_id, (path, path), False, (True, True),
               (parent, parent), (name, name), (kind, kind),
               (executable, executable))

    def unversioned(self, tree, path):
        """Create an unversioned result."""
        _, basename = os.path.split(path)
        kind = tree._comparison_data(None, path)[0]
        return (None, (None, path), True, (False, False), (None, None),
                (None, basename), (None, kind),
                (None, False))

    def test_empty_to_abc_content(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        expected_results = sorted([
            self.added(tree2, 'root-id'),
            self.added(tree2, 'a-id'),
            self.added(tree2, 'b-id'),
            self.added(tree2, 'c-id'),
            self.deleted(tree1, 'empty-root-id')])
        self.assertEqual(expected_results, self.do_iter_changes(tree1, tree2))
        self.check_has_changes(True, tree1, tree2)

    def test_empty_specific_files(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.assertEqual([],
            self.do_iter_changes(tree1, tree2, specific_files=[]))

    def test_no_specific_files(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        expected_results = sorted([
            self.added(tree2, 'root-id'),
            self.added(tree2, 'a-id'),
            self.added(tree2, 'b-id'),
            self.added(tree2, 'c-id'),
            self.deleted(tree1, 'empty-root-id')])
        self.assertEqual(expected_results, self.do_iter_changes(tree1, tree2))
        self.check_has_changes(True, tree1, tree2)

    def test_empty_to_abc_content_a_only(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.assertEqual(
            sorted([self.added(tree2, 'root-id'),
             self.added(tree2, 'a-id'),
             self.deleted(tree1, 'empty-root-id')]),
            self.do_iter_changes(tree1, tree2, specific_files=['a']))

    def test_abc_content_to_empty_a_only(self):
        # For deletes we don't need to pickup parents.
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.assertEqual(
            [self.deleted(tree1, 'a-id')],
            self.do_iter_changes(tree1, tree2, specific_files=['a']))

    def test_abc_content_to_empty_b_only(self):
        # When b stops being a directory we have to pick up b/c as well.
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.assertEqual(
            [self.deleted(tree1, 'b-id'), self.deleted(tree1, 'c-id')],
            self.do_iter_changes(tree1, tree2, specific_files=['b']))

    def test_empty_to_abc_content_a_and_c_only(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_no_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        expected_result = sorted([self.added(tree2, 'root-id'),
            self.added(tree2, 'a-id'), self.added(tree2, 'b-id'),
            self.added(tree2, 'c-id'), self.deleted(tree1, 'empty-root-id')])
        self.assertEqual(expected_result,
            self.do_iter_changes(tree1, tree2, specific_files=['a', 'b/c']))

    def test_abc_content_to_empty(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_no_content(tree2)
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        expected_results = sorted([
            self.added(tree2, 'empty-root-id'),
            self.deleted(tree1, 'root-id'), self.deleted(tree1, 'a-id'),
            self.deleted(tree1, 'b-id'), self.deleted(tree1, 'c-id')])
        self.assertEqual(
            expected_results,
            self.do_iter_changes(tree1, tree2))
        self.check_has_changes(True, tree1, tree2)

    def test_content_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_2(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        root_id = tree1.path2id('')
        self.assertEqual([('a-id', ('a', 'a'), True, (True, True),
                           (root_id, root_id), ('a', 'a'),
                           ('file', 'file'), (False, False))],
                         self.do_iter_changes(tree1, tree2))
        self.check_has_changes(True, tree1, tree2)

    def test_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_3(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        self.assertEqual([('c-id', ('b/c', 'b/c'), False, (True, True),
                           ('b-id', 'b-id'), ('c', 'c'), ('file', 'file'),
                          (False, True))],
                         self.do_iter_changes(tree1, tree2))

    def test_empty_dir(self):
        """an empty dir should not cause glitches to surrounding files."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        # the pathname is chosen to fall between 'a' and 'b'.
        self.build_tree(['1/a-empty/', '2/a-empty/'])
        tree1.add(['a-empty'], ['a-empty'])
        tree2.add(['a-empty'], ['a-empty'])
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        expected = []
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

    def test_file_rename(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_4(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        root_id = tree1.path2id('')
        self.assertEqual([('a-id', ('a', 'd'), False, (True, True),
                           (root_id, root_id), ('a', 'd'), ('file', 'file'),
                           (False, False))],
                         self.do_iter_changes(tree1, tree2))

    def test_file_rename_and_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_5(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        root_id = tree1.path2id('')
        self.assertEqual([('a-id', ('a', 'd'), True, (True, True),
                           (root_id, root_id), ('a', 'd'), ('file', 'file'),
                           (False, False))],
                         self.do_iter_changes(tree1, tree2))

    def test_specific_content_modification_grabs_parents(self):
        # WHen the only direct change to a specified file is a content change,
        # and its in a reparented subtree, the parents are grabbed.
        tree1 = self.make_branch_and_tree('1')
        tree1.mkdir('changing', 'parent-id')
        tree1.mkdir('changing/unchanging', 'mid-id')
        tree1.add(['changing/unchanging/file'], ['file-id'], ['file'])
        tree1.put_file_bytes_non_atomic('file-id', 'a file')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree2.mkdir('changed', 'parent-id')
        tree2.mkdir('changed/unchanging', 'mid-id')
        tree2.add(['changed/unchanging/file'], ['file-id'], ['file'])
        tree2.put_file_bytes_non_atomic('file-id', 'changed content')
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        # parent-id has changed, as has file-id
        root_id = tree1.path2id('')
        self.assertEqualIterChanges(
            [self.renamed(tree1, tree2, 'parent-id', False),
             self.renamed(tree1, tree2, 'file-id', True)],
             self.do_iter_changes(tree1, tree2,
             specific_files=['changed/unchanging/file']))

    def test_specific_content_modification_grabs_parents_root_changes(self):
        # WHen the only direct change to a specified file is a content change,
        # and its in a reparented subtree, the parents are grabbed, even if
        # that includes the root.
        tree1 = self.make_branch_and_tree('1')
        tree1.set_root_id('old')
        tree1.mkdir('changed', 'parent-id')
        tree1.mkdir('changed/unchanging', 'mid-id')
        tree1.add(['changed/unchanging/file'], ['file-id'], ['file'])
        tree1.put_file_bytes_non_atomic('file-id', 'a file')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id('new')
        tree2.mkdir('changed', 'parent-id')
        tree2.mkdir('changed/unchanging', 'mid-id')
        tree2.add(['changed/unchanging/file'], ['file-id'], ['file'])
        tree2.put_file_bytes_non_atomic('file-id', 'changed content')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        # old is gone, new is added, parent-id has changed(reparented), as has
        # file-id(content)
        root_id = tree1.path2id('')
        self.assertEqualIterChanges(
            [self.renamed(tree1, tree2, 'parent-id', False),
             self.added(tree2, 'new'),
             self.deleted(tree1, 'old'),
             self.renamed(tree1, tree2, 'file-id', True)],
             self.do_iter_changes(tree1, tree2,
             specific_files=['changed/unchanging/file']))

    def test_specific_with_rename_under_new_dir_reports_new_dir(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_7(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        # d(d-id) is new, e is b-id renamed. 
        root_id = tree1.path2id('')
        self.assertEqualIterChanges(
            [self.renamed(tree1, tree2, 'b-id', False),
             self.added(tree2, 'd-id')],
             self.do_iter_changes(tree1, tree2, specific_files=['d/e']))

    def test_specific_with_rename_under_dir_under_new_dir_reports_new_dir(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_7(tree2)
        tree2.rename_one('a', 'd/e/a')
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        # d is new, d/e is b-id renamed, d/e/a is a-id renamed 
        root_id = tree1.path2id('')
        self.assertEqualIterChanges(
            [self.renamed(tree1, tree2, 'b-id', False),
             self.added(tree2, 'd-id'),
             self.renamed(tree1, tree2, 'a-id', False)],
             self.do_iter_changes(tree1, tree2, specific_files=['d/e/a']))

    def test_specific_old_parent_same_path_new_parent(self):
        # when a parent is new at its path, if the path was used in the source
        # it must be emitted as a change.
        tree1 = self.make_branch_and_tree('1')
        tree1.add(['a'], ['a-id'], ['file'])
        tree1.put_file_bytes_non_atomic('a-id', 'a file')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree2.mkdir('a', 'b-id')
        tree2.add(['a/c'], ['c-id'], ['file'])
        tree2.put_file_bytes_non_atomic('c-id', 'another file')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        # a-id is gone, b-id and c-id are added.
        self.assertEqualIterChanges(
            [self.deleted(tree1, 'a-id'),
             self.added(tree2, 'b-id'),
             self.added(tree2, 'c-id')],
             self.do_iter_changes(tree1, tree2, specific_files=['a/c']))

    def test_specific_old_parent_becomes_file(self):
        # When an old parent included because of a path conflict becomes a
        # non-directory, its children have to be all included in the delta.
        tree1 = self.make_branch_and_tree('1')
        tree1.mkdir('a', 'a-old-id')
        tree1.mkdir('a/reparented', 'reparented-id')
        tree1.mkdir('a/deleted', 'deleted-id')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree2.mkdir('a', 'a-new-id')
        tree2.mkdir('a/reparented', 'reparented-id')
        tree2.add(['b'], ['a-old-id'], ['file'])
        tree2.put_file_bytes_non_atomic('a-old-id', '')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        # a-old-id is kind-changed, a-new-id is added, reparented-id is renamed,
        # deleted-id is gone
        self.assertEqualIterChanges(
            [self.kind_changed(tree1, tree2, 'a-old-id'),
             self.added(tree2, 'a-new-id'),
             self.renamed(tree1, tree2, 'reparented-id', False),
             self.deleted(tree1, 'deleted-id')],
             self.do_iter_changes(tree1, tree2,
                specific_files=['a/reparented']))

    def test_specific_old_parent_is_deleted(self):
        # When an old parent included because of a path conflict is removed,
        # its children have to be all included in the delta.
        tree1 = self.make_branch_and_tree('1')
        tree1.mkdir('a', 'a-old-id')
        tree1.mkdir('a/reparented', 'reparented-id')
        tree1.mkdir('a/deleted', 'deleted-id')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree2.mkdir('a', 'a-new-id')
        tree2.mkdir('a/reparented', 'reparented-id')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        # a-old-id is gone, a-new-id is added, reparented-id is renamed,
        # deleted-id is gone
        self.assertEqualIterChanges(
            [self.deleted(tree1, 'a-old-id'),
             self.added(tree2, 'a-new-id'),
             self.renamed(tree1, tree2, 'reparented-id', False),
             self.deleted(tree1, 'deleted-id')],
             self.do_iter_changes(tree1, tree2,
                specific_files=['a/reparented']))

    def test_specific_old_parent_child_collides_with_unselected_new(self):
        # When the child of an old parent because of a path conflict becomes a
        # path conflict with some unselected item in the source, that item also
        # needs to be included (because otherwise the output of applying the
        # delta to the source would have two items at that path).
        tree1 = self.make_branch_and_tree('1')
        tree1.mkdir('a', 'a-old-id')
        tree1.mkdir('a/reparented', 'reparented-id')
        tree1.mkdir('collides', 'collides-id')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree2.mkdir('a', 'a-new-id')
        tree2.mkdir('a/selected', 'selected-id')
        tree2.mkdir('collides', 'reparented-id')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        # a-old-id is one, a-new-id is added, reparented-id is renamed,
        # collides-id is gone, selected-id is new.
        self.assertEqualIterChanges(
            [self.deleted(tree1, 'a-old-id'),
             self.added(tree2, 'a-new-id'),
             self.renamed(tree1, tree2, 'reparented-id', False),
             self.deleted(tree1, 'collides-id'),
             self.added(tree2, 'selected-id')],
             self.do_iter_changes(tree1, tree2,
                specific_files=['a/selected']))

    def test_specific_old_parent_child_dir_stops_being_dir(self):
        # When the child of an old parent also stops being a directory, its
        # children must also be included. This test checks that downward
        # recursion is done appropriately by starting at a child of the root of
        # a deleted subtree (a/reparented), and checking that a sibling
        # directory (a/deleted) has its children included in the delta.
        tree1 = self.make_branch_and_tree('1')
        tree1.mkdir('a', 'a-old-id')
        tree1.mkdir('a/reparented', 'reparented-id-1')
        tree1.mkdir('a/deleted', 'deleted-id-1')
        tree1.mkdir('a/deleted/reparented', 'reparented-id-2')
        tree1.mkdir('a/deleted/deleted', 'deleted-id-2')
        tree2 = self.make_to_branch_and_tree('2')
        tree2.set_root_id(tree1.get_root_id())
        tree2.mkdir('a', 'a-new-id')
        tree2.mkdir('a/reparented', 'reparented-id-1')
        tree2.mkdir('reparented', 'reparented-id-2')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        # a-old-id is gone, a-new-id is added, reparented-id-1, -2 are renamed,
        # deleted-id-1 and -2 are gone.
        self.assertEqualIterChanges(
            [self.deleted(tree1, 'a-old-id'),
             self.added(tree2, 'a-new-id'),
             self.renamed(tree1, tree2, 'reparented-id-1', False),
             self.renamed(tree1, tree2, 'reparented-id-2', False),
             self.deleted(tree1, 'deleted-id-1'),
             self.deleted(tree1, 'deleted-id-2')],
             self.do_iter_changes(tree1, tree2,
                specific_files=['a/reparented']))

    def test_file_rename_and_meta_modification(self):
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_6(tree2)
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        root_id = tree1.path2id('')
        self.assertEqual([('c-id', ('b/c', 'e'), False, (True, True),
                           ('b-id', root_id), ('c', 'e'), ('file', 'file'),
                           (False, True))],
                         self.do_iter_changes(tree1, tree2))

    def test_file_becomes_unversionable_bug_438569(self):
        # This isn't strictly a intertree problem, but its the intertree code
        # path that triggers all stat cache updates on both xml and dirstate
        # trees.
        # In bug 438569, a file becoming a fifo causes an assert. Fifo's are
        # not versionable or diffable. For now, we simply stop cold when they
        # are detected (because we don't know how far through the code the 
        # assumption 'fifo's do not exist' goes). In future we could report 
        # the kind change and have commit refuse to go futher, or something
        # similar. One particular reason for choosing this approach is that
        # there is no minikind for 'fifo' in dirstate today, so we can't 
        # actually update records that way.
        # To add confusion, the totally generic code path works - but it
        # doesn't update persistent metadata. So this test permits InterTrees
        # to either work, or fail with BadFileKindError.
        self.requireFeature(features.OsFifoFeature)
        tree1 = self.make_branch_and_tree('1')
        self.build_tree(['1/a'])
        tree1.set_root_id('root-id')
        tree1.add(['a'], ['a-id'])
        tree2 = self.make_branch_and_tree('2')
        os.mkfifo('2/a')
        tree2.add(['a'], ['a-id'], ['file'])
        try:
            tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        except (KeyError,):
            raise tests.TestNotApplicable(
                "Cannot represent a FIFO in this case %s" % self.id())
        try:
            self.do_iter_changes(tree1, tree2)
        except errors.BadFileKindError:
            pass

    def test_missing_in_target(self):
        """Test with the target files versioned but absent from disk."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content(tree2)
        os.unlink('2/a')
        shutil.rmtree('2/b')
        # TODO ? have a symlink here?
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        self.not_applicable_if_missing_in('a', tree2)
        self.not_applicable_if_missing_in('b', tree2)
        root_id = tree1.path2id('')
        expected = sorted([
            self.missing('a-id', 'a', 'a', root_id, 'file'),
            self.missing('b-id', 'b', 'b', root_id, 'directory'),
            self.missing('c-id', 'b/c', 'b/c', 'b-id', 'file'),
            ])
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

    def test_missing_and_renamed(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/file'])
        tree1.add(['file'], ['file-id'])
        self.build_tree(['tree2/directory/'])
        tree2.add(['directory'], ['file-id'])
        os.rmdir('tree2/directory')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_missing_in('directory', tree2)

        root_id = tree1.path2id('')
        expected = sorted([
            self.missing('file-id', 'file', 'directory', root_id, 'file'),
            ])
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

    def test_only_in_source_and_missing(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/file'])
        tree1.add(['file'], ['file-id'])
        os.unlink('tree1/file')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_missing_in('file', tree1)
        root_id = tree1.path2id('')
        expected = [('file-id', ('file', None), False, (True, False),
            (root_id, None), ('file', None), (None, None), (False, None))]
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

    def test_only_in_target_and_missing(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree2/file'])
        tree2.add(['file'], ['file-id'])
        os.unlink('tree2/file')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_missing_in('file', tree2)
        root_id = tree1.path2id('')
        expected = [('file-id', (None, 'file'), False, (False, True),
            (None, root_id), (None, 'file'), (None, None), (None, False))]
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))

    def test_only_in_target_missing_subtree_specific_bug_367632(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree2/a-dir/', 'tree2/a-dir/a-file'])
        tree2.add(['a-dir', 'a-dir/a-file'], ['dir-id', 'file-id'])
        os.unlink('tree2/a-dir/a-file')
        os.rmdir('tree2/a-dir')
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_missing_in('a-dir', tree2)
        root_id = tree1.path2id('')
        expected = [
            ('dir-id', (None, 'a-dir'), False, (False, True),
            (None, root_id), (None, 'a-dir'), (None, None), (None, False)),
            ('file-id', (None, 'a-dir/a-file'), False, (False, True),
            (None, 'dir-id'), (None, 'a-file'), (None, None), (None, False))
            ]
        # bug 367632 showed that specifying the root broke some code paths,
        # so we check this contract with and without it.
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))
        self.assertEqual(expected,
            self.do_iter_changes(tree1, tree2, specific_files=['']))

    def test_unchanged_with_renames_and_modifications(self):
        """want_unchanged should generate a list of unchanged entries."""
        tree1 = self.make_branch_and_tree('1')
        tree2 = self.make_to_branch_and_tree('2')
        tree1 = self.get_tree_no_parents_abc_content(tree1)
        tree2 = self.get_tree_no_parents_abc_content_5(tree2)
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        root_id = tree1.path2id('')
        self.assertEqual(sorted([self.unchanged(tree1, root_id),
            self.unchanged(tree1, 'b-id'),
            ('a-id', ('a', 'd'), True, (True, True),
             (root_id, root_id), ('a', 'd'), ('file', 'file'),
            (False, False)), self.unchanged(tree1, 'c-id')]),
            self.do_iter_changes(tree1, tree2, include_unchanged=True))

    def test_compare_subtrees(self):
        tree1 = self.make_branch_and_tree('1')
        if not tree1.supports_tree_reference():
            return
        tree1.set_root_id('root-id')
        subtree1 = self.make_branch_and_tree('1/sub')
        subtree1.set_root_id('subtree-id')
        tree1.add_reference(subtree1)

        tree2 = self.make_to_branch_and_tree('2')
        if not tree2.supports_tree_reference():
            return
        tree2.set_root_id('root-id')
        subtree2 = self.make_to_branch_and_tree('2/sub')
        subtree2.set_root_id('subtree-id')
        tree2.add_reference(subtree2)
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)

        self.assertEqual([], list(tree2.iter_changes(tree1)))
        subtree1.commit('commit', rev_id='commit-a')
        self.assertEqual([
            ('root-id',
             (u'', u''),
             False,
             (True, True),
             (None, None),
             (u'', u''),
             ('directory', 'directory'),
             (False, False)),
            ('subtree-id',
             ('sub', 'sub',),
             False,
             (True, True),
             ('root-id', 'root-id'),
             ('sub', 'sub'),
             ('tree-reference', 'tree-reference'),
             (False, False))],
                         list(tree2.iter_changes(tree1,
                             include_unchanged=True)))

    def test_disk_in_subtrees_skipped(self):
        """subtrees are considered not-in-the-current-tree.

        This test tests the trivial case, where the basis has no paths in the
        current trees subtree.
        """
        tree1 = self.make_branch_and_tree('1')
        tree1.set_root_id('root-id')
        tree2 = self.make_to_branch_and_tree('2')
        if not tree2.supports_tree_reference():
            return
        tree2.set_root_id('root-id')
        subtree2 = self.make_to_branch_and_tree('2/sub')
        subtree2.set_root_id('subtree-id')
        tree2.add_reference(subtree2)
        self.build_tree(['2/sub/file'])
        subtree2.add(['file'])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        # this should filter correctly from above
        self.assertEqual([self.added(tree2, 'subtree-id')],
            self.do_iter_changes(tree1, tree2, want_unversioned=True))
        # and when the path is named
        self.assertEqual([self.added(tree2, 'subtree-id')],
            self.do_iter_changes(tree1, tree2, specific_files=['sub'],
                want_unversioned=True))

    def test_default_ignores_unversioned_files(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/a', 'tree1/c',
                         'tree2/a', 'tree2/b', 'tree2/c'])
        tree1.add(['a', 'c'], ['a-id', 'c-id'])
        tree2.add(['a', 'c'], ['a-id', 'c-id'])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)

        # We should ignore the fact that 'b' exists in tree-2
        # because the want_unversioned parameter was not given.
        expected = sorted([
            self.content_changed(tree2, 'a-id'),
            self.content_changed(tree2, 'c-id'),
            ])
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))
        self.check_has_changes(True, tree1, tree2)

    def test_unversioned_paths_in_tree(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree2/file', 'tree2/dir/'])
        if has_symlinks():
            os.symlink('target', 'tree2/link')
            links_supported = True
        else:
            links_supported = False
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_cannot_represent_unversioned(tree2)
        expected = [
            self.unversioned(tree2, 'file'),
            self.unversioned(tree2, 'dir'),
            ]
        if links_supported:
            expected.append(self.unversioned(tree2, 'link'))
        expected = sorted(expected)
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            want_unversioned=True))

    def test_unversioned_paths_in_tree_specific_files(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        self.build_tree(['tree2/file', 'tree2/dir/'])
        if has_symlinks():
            os.symlink('target', 'tree2/link')
            links_supported = True
        else:
            links_supported = False
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_cannot_represent_unversioned(tree2)
        expected = [
            self.unversioned(tree2, 'file'),
            self.unversioned(tree2, 'dir'),
            ]
        specific_files=['file', 'dir']
        if links_supported:
            expected.append(self.unversioned(tree2, 'link'))
            specific_files.append('link')
        expected = sorted(expected)
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            specific_files=specific_files, require_versioned=False,
            want_unversioned=True))

    def test_unversioned_paths_in_target_matching_source_old_names(self):
        # its likely that naive implementations of unversioned file support
        # will fail if the path was versioned, but is not any more,
        # due to a rename, not due to unversioning it.
        # That is, if the old tree has a versioned file 'foo', and
        # the new tree has the same file but versioned as 'bar', and also
        # has an unknown file 'foo', we should get back output for
        # both foo and bar.
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree2/file', 'tree2/dir/',
            'tree1/file', 'tree2/movedfile',
            'tree1/dir/', 'tree2/moveddir/'])
        if has_symlinks():
            os.symlink('target', 'tree1/link')
            os.symlink('target', 'tree2/link')
            os.symlink('target', 'tree2/movedlink')
            links_supported = True
        else:
            links_supported = False
        tree1.add(['file', 'dir'], ['file-id', 'dir-id'])
        tree2.add(['movedfile', 'moveddir'], ['file-id', 'dir-id'])
        if links_supported:
            tree1.add(['link'], ['link-id'])
            tree2.add(['movedlink'], ['link-id'])
        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_cannot_represent_unversioned(tree2)
        root_id = tree1.path2id('')
        expected = [
            self.renamed(tree1, tree2, 'dir-id', False),
            self.renamed(tree1, tree2, 'file-id', True),
            self.unversioned(tree2, 'file'),
            self.unversioned(tree2, 'dir'),
            ]
        specific_files=['file', 'dir']
        if links_supported:
            expected.append(self.renamed(tree1, tree2, 'link-id', False))
            expected.append(self.unversioned(tree2, 'link'))
            specific_files.append('link')
        expected = sorted(expected)
        # run once with, and once without specific files, to catch
        # potentially different code paths.
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            require_versioned=False,
            want_unversioned=True))
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            specific_files=specific_files, require_versioned=False,
            want_unversioned=True))

    def test_similar_filenames(self):
        """Test when we have a few files with similar names."""
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())

        # The trees are actually identical, but they happen to contain
        # similarly named files.
        self.build_tree(['tree1/a/',
                         'tree1/a/b/',
                         'tree1/a/b/c/',
                         'tree1/a/b/c/d/',
                         'tree1/a-c/',
                         'tree1/a-c/e/',
                         'tree2/a/',
                         'tree2/a/b/',
                         'tree2/a/b/c/',
                         'tree2/a/b/c/d/',
                         'tree2/a-c/',
                         'tree2/a-c/e/',
                        ])
        tree1.add(['a', 'a/b', 'a/b/c', 'a/b/c/d', 'a-c', 'a-c/e'],
                  ['a-id', 'b-id', 'c-id', 'd-id', 'a-c-id', 'e-id'])
        tree2.add(['a', 'a/b', 'a/b/c', 'a/b/c/d', 'a-c', 'a-c/e'],
                  ['a-id', 'b-id', 'c-id', 'd-id', 'a-c-id', 'e-id'])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_cannot_represent_unversioned(tree2)

        self.assertEqual([], self.do_iter_changes(tree1, tree2,
                                                  want_unversioned=True))
        expected = sorted([
            self.unchanged(tree2, tree2.get_root_id()),
            self.unchanged(tree2, 'a-id'),
            self.unchanged(tree2, 'b-id'),
            self.unchanged(tree2, 'c-id'),
            self.unchanged(tree2, 'd-id'),
            self.unchanged(tree2, 'a-c-id'),
            self.unchanged(tree2, 'e-id'),
            ])
        self.assertEqual(expected,
                         self.do_iter_changes(tree1, tree2,
                                              want_unversioned=True,
                                              include_unchanged=True))


    def test_unversioned_subtree_only_emits_root(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree2/dir/', 'tree2/dir/file'])
        tree1, tree2 = self.mutable_trees_to_test_trees(self, tree1, tree2)
        self.not_applicable_if_cannot_represent_unversioned(tree2)
        expected = [
            self.unversioned(tree2, 'dir'),
            ]
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            want_unversioned=True))

    def make_trees_with_symlinks(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/fromfile', 'tree1/fromdir/'])
        self.build_tree(['tree2/tofile', 'tree2/todir/', 'tree2/unknown'])
        os.symlink('original', 'tree1/changed')
        os.symlink('original', 'tree1/removed')
        os.symlink('original', 'tree1/tofile')
        os.symlink('original', 'tree1/todir')
        # we make the unchanged link point at unknown to catch incorrect
        # symlink-following code in the specified_files test.
        os.symlink('unknown', 'tree1/unchanged')
        os.symlink('new',      'tree2/added')
        os.symlink('new',      'tree2/changed')
        os.symlink('new',      'tree2/fromfile')
        os.symlink('new',      'tree2/fromdir')
        os.symlink('unknown', 'tree2/unchanged')
        from_paths_and_ids = [
            'fromdir',
            'fromfile',
            'changed',
            'removed',
            'todir',
            'tofile',
            'unchanged',
            ]
        to_paths_and_ids = [
            'added',
            'fromdir',
            'fromfile',
            'changed',
            'todir',
            'tofile',
            'unchanged',
            ]
        tree1.add(from_paths_and_ids, from_paths_and_ids)
        tree2.add(to_paths_and_ids, to_paths_and_ids)
        return self.mutable_trees_to_locked_test_trees(tree1, tree2)

    def test_versioned_symlinks(self):
        self.requireFeature(features.SymlinkFeature)
        tree1, tree2 = self.make_trees_with_symlinks()
        self.not_applicable_if_cannot_represent_unversioned(tree2)
        root_id = tree1.path2id('')
        expected = [
            self.unchanged(tree1, tree1.path2id('')),
            self.added(tree2, 'added'),
            self.content_changed(tree2, 'changed'),
            self.kind_changed(tree1, tree2, 'fromdir'),
            self.kind_changed(tree1, tree2, 'fromfile'),
            self.deleted(tree1, 'removed'),
            self.unchanged(tree2, 'unchanged'),
            self.unversioned(tree2, 'unknown'),
            self.kind_changed(tree1, tree2, 'todir'),
            self.kind_changed(tree1, tree2, 'tofile'),
            ]
        expected = sorted(expected)
        self.assertEqual(expected,
            self.do_iter_changes(tree1, tree2, include_unchanged=True,
                want_unversioned=True))
        self.check_has_changes(True, tree1, tree2)

    def test_versioned_symlinks_specific_files(self):
        self.requireFeature(features.SymlinkFeature)
        tree1, tree2 = self.make_trees_with_symlinks()
        root_id = tree1.path2id('')
        expected = [
            self.added(tree2, 'added'),
            self.content_changed(tree2, 'changed'),
            self.kind_changed(tree1, tree2, 'fromdir'),
            self.kind_changed(tree1, tree2, 'fromfile'),
            self.deleted(tree1, 'removed'),
            self.kind_changed(tree1, tree2, 'todir'),
            self.kind_changed(tree1, tree2, 'tofile'),
            ]
        expected = sorted(expected)
        # we should get back just the changed links. We pass in 'unchanged' to
        # make sure that it is correctly not returned - and neither is the
        # unknown path 'unknown' which it points at.
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2,
            specific_files=['added', 'changed', 'fromdir', 'fromfile',
            'removed', 'unchanged', 'todir', 'tofile']))
        self.check_has_changes(True, tree1, tree2)

    def test_tree_with_special_names(self):
        tree1, tree2, paths, path_ids = self.make_tree_with_special_names()
        expected = sorted(self.added(tree2, f_id) for f_id in path_ids)
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))
        self.check_has_changes(True, tree1, tree2)

    def test_trees_with_special_names(self):
        tree1, tree2, paths, path_ids = self.make_trees_with_special_names()
        expected = sorted(self.content_changed(tree2, f_id) for f_id in path_ids
                          if f_id.endswith('_f-id'))
        self.assertEqual(expected, self.do_iter_changes(tree1, tree2))
        self.check_has_changes(True, tree1, tree2)

    def test_trees_with_deleted_dir(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        tree2.set_root_id(tree1.get_root_id())
        self.build_tree(['tree1/a', 'tree1/b/', 'tree1/b/c',
                         'tree1/b/d/', 'tree1/b/d/e', 'tree1/f/', 'tree1/f/g',
                         'tree2/a', 'tree2/f/', 'tree2/f/g'])
        tree1.add(['a', 'b', 'b/c', 'b/d/', 'b/d/e', 'f', 'f/g'],
                  ['a-id', 'b-id', 'c-id', 'd-id', 'e-id', 'f-id', 'g-id'])
        tree2.add(['a', 'f', 'f/g'], ['a-id', 'f-id', 'g-id'])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        # We should notice that 'b' and all its children are deleted
        expected = [
            self.content_changed(tree2, 'a-id'),
            self.content_changed(tree2, 'g-id'),
            self.deleted(tree1, 'b-id'),
            self.deleted(tree1, 'c-id'),
            self.deleted(tree1, 'd-id'),
            self.deleted(tree1, 'e-id'),
            ]
        self.assertEqualIterChanges(expected,
            self.do_iter_changes(tree1, tree2))
        self.check_has_changes(True, tree1, tree2)

    def test_added_unicode(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)

        # u'\u03b1' == GREEK SMALL LETTER ALPHA
        # u'\u03c9' == GREEK SMALL LETTER OMEGA
        a_id = u'\u03b1-id'.encode('utf8')
        added_id = u'\u03c9_added_id'.encode('utf8')
        try:
            self.build_tree([u'tree1/\u03b1/',
                             u'tree2/\u03b1/',
                             u'tree2/\u03b1/\u03c9-added',
                            ])
        except UnicodeError:
            raise tests.TestSkipped("Could not create Unicode files.")
        tree1.add([u'\u03b1'], [a_id])
        tree2.add([u'\u03b1', u'\u03b1/\u03c9-added'], [a_id, added_id])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)

        self.assertEqual([self.added(tree2, added_id)],
                         self.do_iter_changes(tree1, tree2))
        self.assertEqual([self.added(tree2, added_id)],
                         self.do_iter_changes(tree1, tree2,
                                              specific_files=[u'\u03b1']))
        self.check_has_changes(True, tree1, tree2)

    def test_deleted_unicode(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)

        # u'\u03b1' == GREEK SMALL LETTER ALPHA
        # u'\u03c9' == GREEK SMALL LETTER OMEGA
        a_id = u'\u03b1-id'.encode('utf8')
        deleted_id = u'\u03c9_deleted_id'.encode('utf8')
        try:
            self.build_tree([u'tree1/\u03b1/',
                             u'tree1/\u03b1/\u03c9-deleted',
                             u'tree2/\u03b1/',
                            ])
        except UnicodeError:
            raise tests.TestSkipped("Could not create Unicode files.")
        tree1.add([u'\u03b1', u'\u03b1/\u03c9-deleted'], [a_id, deleted_id])
        tree2.add([u'\u03b1'], [a_id])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)

        self.assertEqual([self.deleted(tree1, deleted_id)],
                         self.do_iter_changes(tree1, tree2))
        self.assertEqual([self.deleted(tree1, deleted_id)],
                         self.do_iter_changes(tree1, tree2,
                                              specific_files=[u'\u03b1']))
        self.check_has_changes(True, tree1, tree2)

    def test_modified_unicode(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)

        # u'\u03b1' == GREEK SMALL LETTER ALPHA
        # u'\u03c9' == GREEK SMALL LETTER OMEGA
        a_id = u'\u03b1-id'.encode('utf8')
        mod_id = u'\u03c9_mod_id'.encode('utf8')
        try:
            self.build_tree([u'tree1/\u03b1/',
                             u'tree1/\u03b1/\u03c9-modified',
                             u'tree2/\u03b1/',
                             u'tree2/\u03b1/\u03c9-modified',
                            ])
        except UnicodeError:
            raise tests.TestSkipped("Could not create Unicode files.")
        tree1.add([u'\u03b1', u'\u03b1/\u03c9-modified'], [a_id, mod_id])
        tree2.add([u'\u03b1', u'\u03b1/\u03c9-modified'], [a_id, mod_id])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)

        self.assertEqual([self.content_changed(tree1, mod_id)],
                         self.do_iter_changes(tree1, tree2))
        self.assertEqual([self.content_changed(tree1, mod_id)],
                         self.do_iter_changes(tree1, tree2,
                                              specific_files=[u'\u03b1']))
        self.check_has_changes(True, tree1, tree2)

    def test_renamed_unicode(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)

        # u'\u03b1' == GREEK SMALL LETTER ALPHA
        # u'\u03c9' == GREEK SMALL LETTER OMEGA
        a_id = u'\u03b1-id'.encode('utf8')
        rename_id = u'\u03c9_rename_id'.encode('utf8')
        try:
            self.build_tree([u'tree1/\u03b1/',
                             u'tree2/\u03b1/',
                            ])
        except UnicodeError:
            raise tests.TestSkipped("Could not create Unicode files.")
        self.build_tree_contents([(u'tree1/\u03c9-source', 'contents\n'),
                                  (u'tree2/\u03b1/\u03c9-target', 'contents\n'),
                                 ])
        tree1.add([u'\u03b1', u'\u03c9-source'], [a_id, rename_id])
        tree2.add([u'\u03b1', u'\u03b1/\u03c9-target'], [a_id, rename_id])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)

        self.assertEqual([self.renamed(tree1, tree2, rename_id, False)],
                         self.do_iter_changes(tree1, tree2))
        self.assertEqualIterChanges(
            [self.renamed(tree1, tree2, rename_id, False)],
            self.do_iter_changes(tree1, tree2, specific_files=[u'\u03b1']))
        self.check_has_changes(True, tree1, tree2)

    def test_unchanged_unicode(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)
        # u'\u03b1' == GREEK SMALL LETTER ALPHA
        # u'\u03c9' == GREEK SMALL LETTER OMEGA
        a_id = u'\u03b1-id'.encode('utf8')
        subfile_id = u'\u03c9-subfile-id'.encode('utf8')
        rootfile_id = u'\u03c9-root-id'.encode('utf8')
        try:
            self.build_tree([u'tree1/\u03b1/',
                             u'tree2/\u03b1/',
                            ])
        except UnicodeError:
            raise tests.TestSkipped("Could not create Unicode files.")
        self.build_tree_contents([
            (u'tree1/\u03b1/\u03c9-subfile', 'sub contents\n'),
            (u'tree2/\u03b1/\u03c9-subfile', 'sub contents\n'),
            (u'tree1/\u03c9-rootfile', 'root contents\n'),
            (u'tree2/\u03c9-rootfile', 'root contents\n'),
            ])
        tree1.add([u'\u03b1', u'\u03b1/\u03c9-subfile', u'\u03c9-rootfile'],
                  [a_id, subfile_id, rootfile_id])
        tree2.add([u'\u03b1', u'\u03b1/\u03c9-subfile', u'\u03c9-rootfile'],
                  [a_id, subfile_id, rootfile_id])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)

        expected = sorted([
            self.unchanged(tree1, root_id),
            self.unchanged(tree1, a_id),
            self.unchanged(tree1, subfile_id),
            self.unchanged(tree1, rootfile_id),
            ])
        self.assertEqual(expected,
                         self.do_iter_changes(tree1, tree2,
                                              include_unchanged=True))

        # We should also be able to select just a subset
        expected = sorted([
            self.unchanged(tree1, a_id),
            self.unchanged(tree1, subfile_id),
            ])
        self.assertEqual(expected,
            self.do_iter_changes(tree1, tree2, specific_files=[u'\u03b1'],
                include_unchanged=True))

    def test_unknown_unicode(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)
        # u'\u03b1' == GREEK SMALL LETTER ALPHA
        # u'\u03c9' == GREEK SMALL LETTER OMEGA
        a_id = u'\u03b1-id'.encode('utf8')
        try:
            self.build_tree([u'tree1/\u03b1/',
                             u'tree2/\u03b1/',
                             u'tree2/\u03b1/unknown_dir/',
                             u'tree2/\u03b1/unknown_file',
                             u'tree2/\u03b1/unknown_dir/file',
                             u'tree2/\u03c9-unknown_root_file',
                            ])
        except UnicodeError:
            raise tests.TestSkipped("Could not create Unicode files.")
        tree1.add([u'\u03b1'], [a_id])
        tree2.add([u'\u03b1'], [a_id])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_cannot_represent_unversioned(tree2)

        expected = sorted([
            self.unversioned(tree2, u'\u03b1/unknown_dir'),
            self.unversioned(tree2, u'\u03b1/unknown_file'),
            self.unversioned(tree2, u'\u03c9-unknown_root_file'),
            # a/unknown_dir/file should not be included because we should not
            # recurse into unknown_dir
            # self.unversioned(tree2, 'a/unknown_dir/file'),
            ])
        self.assertEqual(expected,
                         self.do_iter_changes(tree1, tree2,
                                              require_versioned=False,
                                              want_unversioned=True))
        self.assertEqual([], # Without want_unversioned we should get nothing
                         self.do_iter_changes(tree1, tree2))
        self.check_has_changes(False, tree1, tree2)

        # We should also be able to select just a subset
        expected = sorted([
            self.unversioned(tree2, u'\u03b1/unknown_dir'),
            self.unversioned(tree2, u'\u03b1/unknown_file'),
            ])
        self.assertEqual(expected,
                         self.do_iter_changes(tree1, tree2,
                                              specific_files=[u'\u03b1'],
                                              require_versioned=False,
                                              want_unversioned=True))
        self.assertEqual([], # Without want_unversioned we should get nothing
                         self.do_iter_changes(tree1, tree2,
                                              specific_files=[u'\u03b1']))

    def test_unknown_empty_dir(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)

        # Start with 2 identical trees
        self.build_tree(['tree1/a/', 'tree1/b/',
                         'tree2/a/', 'tree2/b/'])
        self.build_tree_contents([('tree1/b/file', 'contents\n'),
                                  ('tree2/b/file', 'contents\n')])
        tree1.add(['a', 'b', 'b/file'], ['a-id', 'b-id', 'b-file-id'])
        tree2.add(['a', 'b', 'b/file'], ['a-id', 'b-id', 'b-file-id'])

        # Now create some unknowns in tree2
        # We should find both a/file and a/dir as unknown, but we shouldn't
        # recurse into a/dir to find that a/dir/subfile is also unknown.
        self.build_tree(['tree2/a/file', 'tree2/a/dir/', 'tree2/a/dir/subfile'])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_cannot_represent_unversioned(tree2)

        expected = sorted([
            self.unversioned(tree2, u'a/file'),
            self.unversioned(tree2, u'a/dir'),
            ])
        self.assertEqual(expected,
                         self.do_iter_changes(tree1, tree2,
                                              require_versioned=False,
                                              want_unversioned=True))

    def test_rename_over_deleted(self):
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)

        # The final changes should be:
        #   touch a b c d
        #   add a b c d
        #   commit
        #   rm a d
        #   mv b a
        #   mv c d
        self.build_tree_contents([
            ('tree1/a', 'a contents\n'),
            ('tree1/b', 'b contents\n'),
            ('tree1/c', 'c contents\n'),
            ('tree1/d', 'd contents\n'),
            ('tree2/a', 'b contents\n'),
            ('tree2/d', 'c contents\n'),
            ])
        tree1.add(['a', 'b', 'c', 'd'], ['a-id', 'b-id', 'c-id', 'd-id'])
        tree2.add(['a', 'd'], ['b-id', 'c-id'])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)

        expected = sorted([
            self.deleted(tree1, 'a-id'),
            self.deleted(tree1, 'd-id'),
            self.renamed(tree1, tree2, 'b-id', False),
            self.renamed(tree1, tree2, 'c-id', False),
            ])
        self.assertEqual(expected,
                         self.do_iter_changes(tree1, tree2))
        self.check_has_changes(True, tree1, tree2)

    def test_deleted_and_unknown(self):
        """Test a file marked removed, but still present on disk."""
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)

        # The final changes should be:
        # bzr add a b c
        # bzr rm --keep b
        self.build_tree_contents([
            ('tree1/a', 'a contents\n'),
            ('tree1/b', 'b contents\n'),
            ('tree1/c', 'c contents\n'),
            ('tree2/a', 'a contents\n'),
            ('tree2/b', 'b contents\n'),
            ('tree2/c', 'c contents\n'),
            ])
        tree1.add(['a', 'b', 'c'], ['a-id', 'b-id', 'c-id'])
        tree2.add(['a', 'c'], ['a-id', 'c-id'])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_cannot_represent_unversioned(tree2)

        expected = sorted([
            self.deleted(tree1, 'b-id'),
            self.unversioned(tree2, 'b'),
            ])
        self.assertEqual(expected,
                         self.do_iter_changes(tree1, tree2,
                                              want_unversioned=True))
        expected = sorted([
            self.deleted(tree1, 'b-id'),
            ])
        self.assertEqual(expected,
                         self.do_iter_changes(tree1, tree2,
                                              want_unversioned=False))

    def test_renamed_and_added(self):
        """Test when we have renamed a file, and put another in its place."""
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)

        # The final changes are:
        # bzr add b c
        # bzr mv b a
        # bzr mv c d
        # bzr add b c

        self.build_tree_contents([
            ('tree1/b', 'b contents\n'),
            ('tree1/c', 'c contents\n'),
            ('tree2/a', 'b contents\n'),
            ('tree2/b', 'new b contents\n'),
            ('tree2/c', 'new c contents\n'),
            ('tree2/d', 'c contents\n'),
            ])
        tree1.add(['b', 'c'], ['b1-id', 'c1-id'])
        tree2.add(['a', 'b', 'c', 'd'], ['b1-id', 'b2-id', 'c2-id', 'c1-id'])

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)

        expected = sorted([
            self.renamed(tree1, tree2, 'b1-id', False),
            self.renamed(tree1, tree2, 'c1-id', False),
            self.added(tree2, 'b2-id'),
            self.added(tree2, 'c2-id'),
            ])
        self.assertEqual(expected,
                         self.do_iter_changes(tree1, tree2,
                                              want_unversioned=True))

    def test_renamed_and_unknown(self):
        """A file was moved on the filesystem, but not in bzr."""
        tree1 = self.make_branch_and_tree('tree1')
        tree2 = self.make_to_branch_and_tree('tree2')
        root_id = tree1.get_root_id()
        tree2.set_root_id(root_id)

        # The final changes are:
        # bzr add a b
        # mv a a2

        self.build_tree_contents([
            ('tree1/a', 'a contents\n'),
            ('tree1/b', 'b contents\n'),
            ('tree2/a', 'a contents\n'),
            ('tree2/b', 'b contents\n'),
            ])
        tree1.add(['a', 'b'], ['a-id', 'b-id'])
        tree2.add(['a', 'b'], ['a-id', 'b-id'])
        os.rename('tree2/a', 'tree2/a2')

        tree1, tree2 = self.mutable_trees_to_locked_test_trees(tree1, tree2)
        self.not_applicable_if_missing_in('a', tree2)

        expected = sorted([
            self.missing('a-id', 'a', 'a', tree2.get_root_id(), 'file'),
            self.unversioned(tree2, 'a2'),
            ])
        self.assertEqual(expected,
                         self.do_iter_changes(tree1, tree2,
                                              want_unversioned=True))
