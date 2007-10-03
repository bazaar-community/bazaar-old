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

"""Tests for interface conformance of inventories of working trees."""


import os
import time

from bzrlib import (
    errors,
    inventory,
    )
from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree


class TestRevert(TestCaseWithWorkingTree):

    def test_dangling_id(self):
        wt = self.make_branch_and_tree('b1')
        wt.lock_tree_write()
        self.addCleanup(wt.unlock)
        self.assertEqual(len(wt.inventory), 1)
        open('b1/a', 'wb').write('a test\n')
        wt.add('a')
        self.assertEqual(len(wt.inventory), 2)
        wt.flush() # workaround revert doing wt._write_inventory for now.
        os.unlink('b1/a')
        wt.revert()
        self.assertEqual(len(wt.inventory), 1)


class TestSnapshot(TestCaseWithWorkingTree):

    def setUp(self):
        # for full testing we'll need a branch
        # with a subdir to test parent changes.
        # and a file, link and dir under that.
        # but right now I only need one attribute
        # to change, and then test merge patterns
        # with fake parent entries.
        super(TestSnapshot, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        self.branch = self.wt.branch
        self.build_tree(['subdir/', 'subdir/file'], line_endings='binary')
        self.wt.add(['subdir', 'subdir/file'],
                                       ['dirid', 'fileid'])
        self.wt.commit('message_1', rev_id = '1')
        self.tree_1 = self.branch.repository.revision_tree('1')
        self.inv_1 = self.branch.repository.get_inventory('1')
        self.file_1 = self.inv_1['fileid']
        self.wt.lock_write()
        self.addCleanup(self.wt.unlock)
        self.file_active = self.wt.inventory['fileid']
        self.builder = self.branch.get_commit_builder([], timestamp=time.time(), revision_id='2')

    def test_snapshot_new_revision(self):
        # This tests that a simple commit with no parents makes a new
        # revision value in the inventory entry
        self.file_active.snapshot('2', 'subdir/file', {}, self.wt, self.builder)
        # expected outcome - file_1 has a revision id of '2', and we can get
        # its text of 'file contents' out of the weave.
        self.assertEqual(self.file_1.revision, '1')
        self.assertEqual(self.file_active.revision, '2')
        # this should be a separate test probably, but lets check it once..
        lines = self.branch.repository.weave_store.get_weave(
            'fileid', 
            self.branch.repository.get_transaction()).get_lines('2')
        self.assertEqual(lines, ['contents of subdir/file\n'])
        self.wt.branch.repository.commit_write_group()

    def test_snapshot_unchanged(self):
        #This tests that a simple commit does not make a new entry for
        # an unchanged inventory entry
        self.file_active.snapshot('2', 'subdir/file', {'1':self.file_1},
                                  self.wt, self.builder)
        self.assertEqual(self.file_1.revision, '1')
        self.assertEqual(self.file_active.revision, '1')
        vf = self.branch.repository.weave_store.get_weave(
            'fileid', 
            self.branch.repository.get_transaction())
        self.assertRaises(errors.RevisionNotPresent,
                          vf.get_lines,
                          '2')
        self.wt.branch.repository.commit_write_group()

    def test_snapshot_merge_identical_different_revid(self):
        # This tests that a commit with two identical parents, one of which has
        # a different revision id, results in a new revision id in the entry.
        # 1->other, commit a merge of other against 1, results in 2.
        other_ie = inventory.InventoryFile('fileid', 'newname', self.file_1.parent_id)
        other_ie = inventory.InventoryFile('fileid', 'file', self.file_1.parent_id)
        other_ie.revision = '1'
        other_ie.text_sha1 = self.file_1.text_sha1
        other_ie.text_size = self.file_1.text_size
        self.assertEqual(self.file_1, other_ie)
        other_ie.revision = 'other'
        self.assertNotEqual(self.file_1, other_ie)
        versionfile = self.branch.repository.weave_store.get_weave(
            'fileid', self.branch.repository.get_transaction())
        versionfile.clone_text('other', '1', ['1'])
        self.file_active.snapshot('2', 'subdir/file', 
                                  {'1':self.file_1, 'other':other_ie},
                                  self.wt, self.builder)
        self.assertEqual(self.file_active.revision, '2')
        self.wt.branch.repository.commit_write_group()

    def test_snapshot_changed(self):
        # This tests that a commit with one different parent results in a new
        # revision id in the entry.
        self.wt.rename_one('subdir/file', 'subdir/newname')
        self.file_active = self.wt.inventory['fileid']
        self.file_active.snapshot('2', 'subdir/newname', {'1':self.file_1}, 
                                  self.wt, self.builder)
        # expected outcome - file_1 has a revision id of '2'
        self.assertEqual(self.file_active.revision, '2')
        self.wt.branch.repository.commit_write_group()


class TestApplyInventoryDelta(TestCaseWithWorkingTree):

    def test_add(self):
        wt = self.make_branch_and_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        root_id = wt.get_root_id()
        wt.apply_inventory_delta([(None, 'bar/foo', 'foo-id',
            inventory.InventoryFile('foo-id', 'foo', parent_id='bar-id')),
            (None, 'bar', 'bar-id', inventory.InventoryDirectory('bar-id',
            'bar', parent_id=root_id))])
        self.assertEqual('bar/foo', wt.inventory.id2path('foo-id'))
        self.assertEqual('bar', wt.inventory.id2path('bar-id'))

    def test_remove(self):
        wt = self.make_branch_and_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        self.build_tree(['foo/', 'foo/bar'])
        wt.add(['foo', 'foo/bar'], ['foo-id', 'bar-id'])
        wt.apply_inventory_delta([('foo', None, 'foo-id', None),
                                  ('foo/bar', None, 'bar-id', None)])
        self.assertIs(None, wt.path2id('foo'))

    def test_rename_dir_with_children(self):
        wt = self.make_branch_and_tree('.')
        wt.lock_write()
        root_id = wt.get_root_id()
        self.addCleanup(wt.unlock)
        self.build_tree(['foo/', 'foo/bar'])
        wt.add(['foo', 'foo/bar'],
               ['foo-id', 'bar-id'])
        wt.apply_inventory_delta([('foo', 'baz', 'foo-id',
            inventory.InventoryDirectory('foo-id', 'baz', root_id))])
        # foo/bar should have been followed the rename of its parent to baz/bar
        self.assertEqual('baz/bar', wt.id2path('bar-id'))

    def test_rename_dir_with_children_with_children(self):
        wt = self.make_branch_and_tree('.')
        wt.lock_write()
        root_id = wt.get_root_id()
        self.addCleanup(wt.unlock)
        self.build_tree(['foo/', 'foo/bar/', 'foo/bar/baz'])
        wt.add(['foo', 'foo/bar', 'foo/bar/baz'],
               ['foo-id', 'bar-id', 'baz-id'])
        wt.apply_inventory_delta([('foo', 'quux', 'foo-id',
            inventory.InventoryDirectory('foo-id', 'quux', root_id))])
        # foo/bar/baz should have been followed the rename of its parent's
        # parent to quux/bar/baz
        self.assertEqual('quux/bar/baz', wt.id2path('baz-id'))

    def test_rename_file(self):
        wt = self.make_branch_and_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)
        self.build_tree(['foo/', 'foo/bar', 'baz/'])
        wt.add(['foo', 'foo/bar', 'baz'],
               ['foo-id', 'bar-id', 'baz-id'])
        wt.apply_inventory_delta([('foo/bar', 'baz/bar', 'bar-id',
            inventory.InventoryFile('bar-id', 'bar', 'baz-id'))])
        self.assertEqual('baz/bar', wt.id2path('bar-id'))

    def test_rename_swap(self):
        """Test the swap-names edge case.

        foo and bar should swap names, but retain their children.  If this
        works, any simpler rename ought to work.
        """
        wt = self.make_branch_and_tree('.')
        wt.lock_write()
        root_id = wt.get_root_id()
        self.addCleanup(wt.unlock)
        self.build_tree(['foo/', 'foo/bar', 'baz/', 'baz/qux'])
        wt.add(['foo', 'foo/bar', 'baz', 'baz/qux'],
               ['foo-id', 'bar-id', 'baz-id', 'qux-id'])
        wt.apply_inventory_delta([('foo', 'baz', 'foo-id',
            inventory.InventoryDirectory('foo-id', 'baz', root_id)),
            ('baz', 'foo', 'baz-id',
            inventory.InventoryDirectory('baz-id', 'foo', root_id))])
        self.assertEqual('baz/bar', wt.id2path('bar-id'))
        self.assertEqual('foo/qux', wt.id2path('qux-id'))

    def test_child_rename_ordering(self):
        """Test the rename-parent, move child edge case.

        (A naive implementation may move the parent first, and then be
         unable to find the child.)
        """
        wt = self.make_branch_and_tree('.')
        root_id = wt.get_root_id()
        self.build_tree(['dir/', 'dir/child', 'other/'])
        wt.add(['dir', 'dir/child', 'other'],
               ['dir-id', 'child-id', 'other-id'])
        # this delta moves dir-id to dir2 and reparents 
        # child-id to a parent of other-id
        wt.apply_inventory_delta([('dir', 'dir2', 'dir-id',
            inventory.InventoryDirectory('dir-id', 'dir2', root_id)),
            ('dir/child', 'other/child', 'child-id',
             inventory.InventoryFile('child-id', 'child', 'other-id'))])
        self.assertEqual('dir2', wt.id2path('dir-id'))
        self.assertEqual('other/child', wt.id2path('child-id'))

    def test_replace_root(self):
        wt = self.make_branch_and_tree('.')
        wt.lock_write()
        self.addCleanup(wt.unlock)

        root_id = wt.get_root_id()
        wt.apply_inventory_delta([('', None, root_id, None),
            (None, '', 'root-id',
             inventory.InventoryDirectory('root-id', '', None))])
