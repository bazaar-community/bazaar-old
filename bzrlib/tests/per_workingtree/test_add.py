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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for interface conformance of 'WorkingTree.add'"""

import os

from bzrlib import (
    errors,
    inventory,
    osutils,
    tests,
    workingtree,
    )
from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree


class TestAdd(TestCaseWithWorkingTree):

    def get_tree_layout(self, tree):
        """Get the (path, file_id) pairs for the current tree."""
        tree.lock_read()
        try:
            return [(path, ie.file_id) for path, ie
                    in tree.iter_entries_by_dir()]
        finally:
            tree.unlock()

    def assertTreeLayout(self, expected, tree):
        """Check that the tree has the correct layout."""
        actual = self.get_tree_layout(tree)
        self.assertEqual(expected, actual)

    def test_add_one(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['one'])
        tree.add('one', 'one-id')
        root_id = tree.get_root_id()

        self.assertTreeLayout([('', root_id), ('one', 'one-id')], tree)

    def test_add_existing_id(self):
        """Adding an entry with a pre-existing id raises DuplicateFileId"""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b'])
        tree.add(['a'], ['an-id'])
        self.assertRaises(errors.DuplicateFileId,
                          tree.add, ['b'], ['an-id'])
        root_id = tree.get_root_id()
        # And the entry should not have been added.
        self.assertTreeLayout([('', root_id), ('a', 'an-id')], tree)

    def test_add_old_id(self):
        """We can add an old id, as long as it doesn't exist now."""
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b'])
        tree.add(['a'], ['an-id'])
        tree.commit('first', rev_id='rev-1')
        root_id = tree.get_root_id()
        # And the entry should not have been added.
        tree.unversion(['an-id'])
        tree.add(['b'], ['an-id'])
        self.assertTreeLayout([('', root_id), ('b', 'an-id')], tree)
        self.assertTreeLayout([('', root_id), ('a', 'an-id')],
                              tree.basis_tree())

    def test_add_one_list(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['one'])
        tree.add(['one'], ['one-id'])
        root_id = tree.get_root_id()

        self.assertTreeLayout([('', root_id), ('one', 'one-id')], tree)

    def test_add_one_new_id(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['one'])
        tree.add(['one'])
        root_id = tree.get_root_id()
        one_id = tree.path2id('one')

        self.assertTreeLayout([('', root_id), ('one', one_id)], tree)

    def test_add_unicode(self):
        tree = self.make_branch_and_tree('.')
        try:
            self.build_tree([u'f\xf6'])
        except UnicodeError:
            raise tests.TestSkipped('Filesystem does not support filename.')
        tree.add([u'f\xf6'])
        root_id = tree.get_root_id()
        foo_id = tree.path2id(u'f\xf6')

        self.assertTreeLayout([('', root_id), (u'f\xf6', foo_id)], tree)

    def test_add_subdir(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/subdir/', 'dir/subdir/foo'])
        tree.add(['dir'], ['dir-id'])
        tree.add(['dir/subdir'], ['subdir-id'])
        tree.add(['dir/subdir/foo'], ['foo-id'])
        root_id = tree.get_root_id()

        self.assertTreeLayout([('', root_id), ('dir', 'dir-id'),
                               ('dir/subdir', 'subdir-id'),
                               ('dir/subdir/foo', 'foo-id')], tree)

    def test_add_multiple(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['a', 'b', 'dir/', 'dir/subdir/', 'dir/subdir/foo'])
        tree.add(['a', 'b', 'dir', 'dir/subdir', 'dir/subdir/foo'],
                 ['a-id', 'b-id', 'dir-id', 'subdir-id', 'foo-id'])
        root_id = tree.get_root_id()

        self.assertTreeLayout([('', root_id), ('a', 'a-id'), ('b', 'b-id'),
                               ('dir', 'dir-id'), ('dir/subdir', 'subdir-id'),
                               ('dir/subdir/foo', 'foo-id')], tree)

    def test_add_invalid(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/subdir/', 'dir/subdir/foo'])
        root_id = tree.get_root_id()

        self.assertRaises(errors.NotVersionedError,
                          tree.add, ['dir/subdir'])
        self.assertTreeLayout([('', root_id)], tree)

    def test_add_after_remove(self):
        tree = self.make_branch_and_tree('.')
        self.build_tree(['dir/', 'dir/subdir/', 'dir/subdir/foo'])
        root_id = tree.get_root_id()
        tree.add(['dir'], ['dir-id'])
        tree.commit('dir', rev_id='rev-1')
        tree.unversion(['dir-id'])
        self.assertRaises(errors.NotVersionedError,
                          tree.add, ['dir/subdir'])

    def test_add_root(self):
        # adding the root should be a no-op, or at least not
        # do anything whacky.
        tree = self.make_branch_and_tree('.')
        tree.lock_write()
        tree.add('')
        self.assertEqual([tree.path2id('')], list(tree))
        # the root should have been changed to be a new unique root.
        self.assertNotEqual(inventory.ROOT_ID, tree.path2id(''))
        tree.unlock()

    def test_add_previously_added(self):
        # adding a path that was previously added should work
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add(['foo'], ['foo-id'])
        tree.unversion(['foo-id'])
        tree.add(['foo'], ['foo-id'])
        self.assertEqual('foo-id', tree.path2id('foo'))

    def test_add_present_in_basis(self):
        # adding a path that was present in the basis should work.
        tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        tree.add(['foo'], ['foo-id'])
        tree.commit('add foo')
        tree.unversion(['foo-id'])
        tree.add(['foo'], ['foo-id'])
        self.assertEqual('foo-id', tree.path2id('foo'))

    def test_add_subdir_file_bug_205636(self):
        """Added file turning into a dir should be detected on add dir/file"""
        if self.workingtree_format.__class__ in (
                workingtree.WorkingTreeFormat2,
                workingtree.WorkingTreeFormat3):
            self.knownFailure("Old workingtree formats raise AttributeError")
        tree = self.make_branch_and_tree(".")
        self.build_tree(["dir"]) # whoops, make a file called dir
        tree.add(["dir"], ["dir-id"])
        os.remove("dir")
        self.build_tree(["dir/", "dir/file"])
        tree.add(["dir/file"], ["file-id"])
        tree.commit("Add file in dir")
        self.addCleanup(tree.lock_read().unlock)
        self.assertEqual([
                (u"dir", "V", "directory", "dir-id"),
                (u"dir/file", "V", "file", "file-id")],
            [t[:4] for t in tree.list_files()])
        self.assertFalse(list(tree.iter_changes(tree.basis_tree())))
