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

"""Tests for interface conformance of XXX TOADD"""


from cStringIO import StringIO
import os
import time

from bzrlib import (
    errors,
    inventory,
    )
from bzrlib.diff import internal_diff
from bzrlib.osutils import (
    has_symlinks,
    )
from bzrlib.tests import TestCaseWithTransport
from bzrlib.uncommit import uncommit


class TestEntryDiffing(TestCaseWithTransport):

    def setUp(self):
        super(TestEntryDiffing, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        self.branch = self.wt.branch
        print >> open('file', 'wb'), 'foo'
        print >> open('binfile', 'wb'), 'foo'
        self.wt.add(['file'], ['fileid'])
        self.wt.add(['binfile'], ['binfileid'])
        if has_symlinks():
            os.symlink('target1', 'symlink')
            self.wt.add(['symlink'], ['linkid'])
        self.wt.commit('message_1', rev_id = '1')
        print >> open('file', 'wb'), 'bar'
        print >> open('binfile', 'wb'), 'x' * 1023 + '\x00'
        if has_symlinks():
            os.unlink('symlink')
            os.symlink('target2', 'symlink')
        self.tree_1 = self.branch.repository.revision_tree('1')
        self.inv_1 = self.branch.repository.get_inventory('1')
        self.file_1 = self.inv_1['fileid']
        self.file_1b = self.inv_1['binfileid']
        self.tree_2 = self.wt
        self.tree_2.lock_read()
        self.addCleanup(self.tree_2.unlock)
        self.inv_2 = self.tree_2.read_working_inventory()
        self.file_2 = self.inv_2['fileid']
        self.file_2b = self.inv_2['binfileid']
        if has_symlinks():
            self.link_1 = self.inv_1['linkid']
            self.link_2 = self.inv_2['linkid']

    def test_file_diff_deleted(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "old_label", self.tree_1,
                          "/dev/null", None, None,
                          output)
        self.assertEqual(output.getvalue(), "--- old_label\n"
                                            "+++ /dev/null\n"
                                            "@@ -1,1 +0,0 @@\n"
                                            "-foo\n"
                                            "\n")

    def test_file_diff_added(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "new_label", self.tree_1,
                          "/dev/null", None, None,
                          output, reverse=True)
        self.assertEqual(output.getvalue(), "--- /dev/null\n"
                                            "+++ new_label\n"
                                            "@@ -0,0 +1,1 @@\n"
                                            "+foo\n"
                                            "\n")

    def test_file_diff_changed(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "/dev/null", self.tree_1, 
                          "new_label", self.file_2, self.tree_2,
                          output)
        self.assertEqual(output.getvalue(), "--- /dev/null\n"
                                            "+++ new_label\n"
                                            "@@ -1,1 +1,1 @@\n"
                                            "-foo\n"
                                            "+bar\n"
                                            "\n")
        
    def test_file_diff_binary(self):
        output = StringIO()
        self.file_1.diff(internal_diff, 
                          "/dev/null", self.tree_1, 
                          "new_label", self.file_2b, self.tree_2,
                          output)
        self.assertEqual(output.getvalue(), 
                         "Binary files /dev/null and new_label differ\n")
    def test_link_diff_deleted(self):
        if not has_symlinks():
            return
        output = StringIO()
        self.link_1.diff(internal_diff, 
                          "old_label", self.tree_1,
                          "/dev/null", None, None,
                          output)
        self.assertEqual(output.getvalue(),
                         "=== target was 'target1'\n")

    def test_link_diff_added(self):
        if not has_symlinks():
            return
        output = StringIO()
        self.link_1.diff(internal_diff, 
                          "new_label", self.tree_1,
                          "/dev/null", None, None,
                          output, reverse=True)
        self.assertEqual(output.getvalue(),
                         "=== target is 'target1'\n")

    def test_link_diff_changed(self):
        if not has_symlinks():
            return
        output = StringIO()
        self.link_1.diff(internal_diff, 
                          "/dev/null", self.tree_1, 
                          "new_label", self.link_2, self.tree_2,
                          output)
        self.assertEqual(output.getvalue(),
                         "=== target changed 'target1' => 'target2'\n")


class TestRevert(TestCaseWithTransport):

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
        wt.revert([])
        self.assertEqual(len(wt.inventory), 1)


class TestPreviousHeads(TestCaseWithTransport):

    def setUp(self):
        # we want several inventories, that respectively
        # give use the following scenarios:
        # A) fileid not in any inventory (A),
        # B) fileid present in one inventory (B) and (A,B)
        # C) fileid present in two inventories, and they
        #   are not mutual descendents (B, C)
        # D) fileid present in two inventories and one is
        #   a descendent of the other. (B, D)
        super(TestPreviousHeads, self).setUp()
        self.wt = self.make_branch_and_tree('.')
        self.branch = self.wt.branch
        self.build_tree(['file'])
        self.wt.commit('new branch', allow_pointless=True, rev_id='A')
        self.inv_A = self.branch.repository.get_inventory('A')
        self.wt.add(['file'], ['fileid'])
        self.wt.commit('add file', rev_id='B')
        self.inv_B = self.branch.repository.get_inventory('B')
        uncommit(self.branch, tree=self.wt)
        self.assertEqual(self.branch.revision_history(), ['A'])
        self.wt.commit('another add of file', rev_id='C')
        self.inv_C = self.branch.repository.get_inventory('C')
        self.wt.add_parent_tree_id('B')
        self.wt.commit('merge in B', rev_id='D')
        self.inv_D = self.branch.repository.get_inventory('D')
        self.wt.lock_read()
        self.addCleanup(self.wt.unlock)
        self.file_active = self.wt.inventory['fileid']
        self.weave = self.branch.repository.weave_store.get_weave('fileid',
            self.branch.repository.get_transaction())
        
    def get_previous_heads(self, inventories):
        return self.file_active.find_previous_heads(
            inventories, 
            self.branch.repository.weave_store,
            self.branch.repository.get_transaction())
        
    def test_fileid_in_no_inventory(self):
        self.assertEqual({}, self.get_previous_heads([self.inv_A]))

    def test_fileid_in_one_inventory(self):
        self.assertEqual({'B':self.inv_B['fileid']},
                         self.get_previous_heads([self.inv_B]))
        self.assertEqual({'B':self.inv_B['fileid']},
                         self.get_previous_heads([self.inv_A, self.inv_B]))
        self.assertEqual({'B':self.inv_B['fileid']},
                         self.get_previous_heads([self.inv_B, self.inv_A]))

    def test_fileid_in_two_inventories_gives_both_entries(self):
        self.assertEqual({'B':self.inv_B['fileid'],
                          'C':self.inv_C['fileid']},
                          self.get_previous_heads([self.inv_B, self.inv_C]))
        self.assertEqual({'B':self.inv_B['fileid'],
                          'C':self.inv_C['fileid']},
                          self.get_previous_heads([self.inv_C, self.inv_B]))

    def test_fileid_in_two_inventories_already_merged_gives_head(self):
        self.assertEqual({'D':self.inv_D['fileid']},
                         self.get_previous_heads([self.inv_B, self.inv_D]))
        self.assertEqual({'D':self.inv_D['fileid']},
                         self.get_previous_heads([self.inv_D, self.inv_B]))

    # TODO: test two inventories with the same file revision 


class TestSnapshot(TestCaseWithTransport):

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
        if has_symlinks():
            pass
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
            self.branch.get_transaction()).get_lines('2')
        self.assertEqual(lines, ['contents of subdir/file\n'])

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

    def test_snapshot_changed(self):
        # This tests that a commit with one different parent results in a new
        # revision id in the entry.
        self.wt.rename_one('subdir/file', 'subdir/newname')
        self.file_active = self.wt.inventory['fileid']
        self.file_active.snapshot('2', 'subdir/newname', {'1':self.file_1}, 
                                  self.wt, self.builder)
        # expected outcome - file_1 has a revision id of '2'
        self.assertEqual(self.file_active.revision, '2')
