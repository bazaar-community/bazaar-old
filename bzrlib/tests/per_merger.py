# Copyright (C) 2009 Canonical Ltd
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

import os

from bzrlib.conflicts import TextConflict
from bzrlib import (
    errors,
    merge as _mod_merge,
    progress,
    )
from bzrlib.tests import (
    multiply_tests,
    TestCaseWithTransport,
    )
from bzrlib.tests.test_merge_core import MergeBuilder
from bzrlib.transform import TreeTransform



def load_tests(standard_tests, module, loader):
    """Multiply tests for tranport implementations."""
    result = loader.suiteClass()
    merge_types = {
        'merge3': _mod_merge.Merge3Merger,
        'weave': _mod_merge.WeaveMerger,
        'lca': _mod_merge.LCAMerger,
        }
    scenarios = [
        (name, {'merge_type': merger}) for name, merger in merge_types.items()]
    return multiply_tests(standard_tests, scenarios, result)


class TestMergeImplementation(TestCaseWithTransport):

    def do_merge(self, target_tree, source_tree, **kwargs):
        merger = _mod_merge.Merger.from_revision_ids(progress.DummyProgress(),
            target_tree, source_tree.last_revision(),
            other_branch=source_tree.branch)
        merger.merge_type=self.merge_type
        for name, value in kwargs.items():
            setattr(merger, name, value)
        merger.do_merge()

    def test_merge_specific_file(self):
        this_tree = self.make_branch_and_tree('this')
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        self.build_tree_contents([
            ('this/file1', 'a\nb\n'),
            ('this/file2', 'a\nb\n')
        ])
        this_tree.add(['file1', 'file2'])
        this_tree.commit('Added files')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([
            ('other/file1', 'a\nb\nc\n'),
            ('other/file2', 'a\nb\nc\n')
        ])
        other_tree.commit('modified both')
        self.build_tree_contents([
            ('this/file1', 'd\na\nb\n'),
            ('this/file2', 'd\na\nb\n')
        ])
        this_tree.commit('modified both')
        self.do_merge(this_tree, other_tree, interesting_files=['file1'])
        self.assertFileEqual('d\na\nb\nc\n', 'this/file1')
        self.assertFileEqual('d\na\nb\n', 'this/file2')

    def test_merge_move_and_change(self):
        this_tree = self.make_branch_and_tree('this')
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        self.build_tree_contents([
            ('this/file1', 'line 1\nline 2\nline 3\nline 4\n'),
        ])
        this_tree.add('file1',)
        this_tree.commit('Added file')
        other_tree = this_tree.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([
            ('other/file1', 'line 1\nline 2 to 2.1\nline 3\nline 4\n'),
        ])
        other_tree.commit('Changed 2 to 2.1')
        self.build_tree_contents([
            ('this/file1', 'line 1\nline 3\nline 2\nline 4\n'),
        ])
        this_tree.commit('Swapped 2 & 3')
        self.do_merge(this_tree, other_tree)
        if self.merge_type is _mod_merge.LCAMerger:
            self.expectFailure(
                "lca merge doesn't conflict for move and change",
                self.assertFileEqual,
                'line 1\n'
                '<<<<<<< TREE\n'
                'line 3\n'
                'line 2\n'
                '=======\n'
                'line 2 to 2.1\n'
                'line 3\n'
                '>>>>>>> MERGE-SOURCE\n'
                'line 4\n', 'this/file1')
        else:
            self.assertFileEqual('line 1\n'
                '<<<<<<< TREE\n'
                'line 3\n'
                'line 2\n'
                '=======\n'
                'line 2 to 2.1\n'
                'line 3\n'
                '>>>>>>> MERGE-SOURCE\n'
                'line 4\n', 'this/file1')

    def test_modify_conflicts_with_delete(self):
        # If one side deletes a line, and the other modifies that line, then
        # the modification should be considered a conflict
        builder = self.make_branch_builder('test')
        builder.start_series()
        builder.build_snapshot('BASE-id', None,
            [('add', ('', None, 'directory', None)),
             ('add', ('foo', 'foo-id', 'file', 'a\nb\nc\nd\ne\n')),
            ])
        # Delete 'b\n'
        builder.build_snapshot('OTHER-id', ['BASE-id'],
            [('modify', ('foo-id', 'a\nc\nd\ne\n'))])
        # Modify 'b\n', add 'X\n'
        builder.build_snapshot('THIS-id', ['BASE-id'],
            [('modify', ('foo-id', 'a\nb2\nc\nd\nX\ne\n'))])
        builder.finish_series()
        branch = builder.get_branch()
        this_tree = branch.bzrdir.create_workingtree()
        this_tree.lock_write()
        self.addCleanup(this_tree.unlock)
        other_tree = this_tree.bzrdir.sprout('other', 'OTHER-id').open_workingtree()
        self.do_merge(this_tree, other_tree)
        if self.merge_type is _mod_merge.LCAMerger:
            self.expectFailure("lca merge doesn't track deleted lines",
                self.assertFileEqual,
                    'a\n'
                    '<<<<<<< TREE\n'
                    'b2\n'
                    '=======\n'
                    '>>>>>>> MERGE-SOURCE\n'
                    'c\n'
                    'd\n'
                    'X\n'
                    'e\n', 'test/foo')
        else:
            self.assertFileEqual(
                'a\n'
                '<<<<<<< TREE\n'
                'b2\n'
                '=======\n'
                '>>>>>>> MERGE-SOURCE\n'
                'c\n'
                'd\n'
                'X\n'
                'e\n', 'test/foo')

    def get_limbodir_deletiondir(self, wt):
        transform = TreeTransform(wt)
        limbodir = transform._limbodir
        deletiondir = transform._deletiondir
        transform.finalize()
        return (limbodir, deletiondir)
    
    def test_merge_with_existing_limbo(self):
        wt = self.make_branch_and_tree('this')
        (limbodir, deletiondir) =  self.get_limbodir_deletiondir(wt)
        os.mkdir(limbodir)
        self.assertRaises(errors.ExistingLimbo, self.do_merge, wt, wt)
        self.assertRaises(errors.LockError, wt.unlock)

    def test_merge_with_pending_deletion(self):
        wt = self.make_branch_and_tree('this')
        (limbodir, deletiondir) =  self.get_limbodir_deletiondir(wt)
        os.mkdir(deletiondir)
        self.assertRaises(errors.ExistingPendingDeletion, self.do_merge, wt, wt)
        self.assertRaises(errors.LockError, wt.unlock)


class TestHookMergeFileContent(TestCaseWithTransport):
    """Tests that the 'merge_file_content' hook is invoked."""

    def install_hook_noop(self):
        def hook_na(merge_params):
            # This hook unconditionally does nothing.
            return 'not_applicable', None
        _mod_merge.Merger.hooks.install_named_hook(
            'merge_file_content', hook_na, 'test hook (n/a)')

    def install_hook_success(self):
        def hook_success(merge_params):
            if merge_params.file_id == '1':
                return 'success', ['text-merged-by-hook']
            return 'not_applicable', None
        _mod_merge.Merger.hooks.install_named_hook(
            'merge_file_content', hook_success, 'test hook (success)')
        
    def install_hook_conflict(self):
        def hook_conflict(merge_params):
            if merge_params.file_id == '1':
                return 'conflicted', ['text-with-conflict-markers-from-hook']
            return 'not_applicable', None
        _mod_merge.Merger.hooks.install_named_hook(
            'merge_file_content', hook_conflict, 'test hook (delete)')
        
    def install_hook_delete(self):
        def hook_delete(merge_params):
            if merge_params.file_id == '1':
                return 'delete', None
            return 'not_applicable', None
        _mod_merge.Merger.hooks.install_named_hook(
            'merge_file_content', hook_delete, 'test hook (delete)')
        
    def install_hook_log_lines(self):
        """Install a hook that saves the get_lines for the this, base and other
        versions of the file.
        """
        self.hook_log = []
        def hook_log(merge_params):
            merger = merge_params.merger
            self.hook_log.append((
                merger.get_lines(merger.this_tree, merge_params.file_id),
                merger.get_lines(merger.other_tree, merge_params.file_id),
                merger.get_lines(merger.base_tree, merge_params.file_id),
                ))
            # This hook unconditionally does nothing.
            return 'not_applicable', None
        _mod_merge.Merger.hooks.install_named_hook(
            'merge_file_content', hook_log, 'test hook (log)')

    def make_merge_builder(self):
        builder = MergeBuilder(self.test_base_dir)
        self.addCleanup(builder.cleanup)
        return builder

    def test_change_vs_change(self):
        """Hook is used for (changed, changed)"""
        self.install_hook_success()
        builder = self.make_merge_builder()
        builder.add_file("1", builder.tree_root, "name1", "text1", True)
        builder.change_contents("1", other="text4", this="text3")
        conflicts = builder.merge(self.merge_type)
        self.assertEqual(conflicts, [])
        self.assertEqual(
            builder.this.get_file('1').read(), 'text-merged-by-hook')

    def test_change_vs_deleted(self):
        """Hook is used for (changed, deleted)"""
        self.install_hook_success()
        builder = self.make_merge_builder()
        builder.add_file("1", builder.tree_root, "name1", "text1", True)
        builder.change_contents("1", this="text2")
        builder.remove_file("1", other=True)
        conflicts = builder.merge(self.merge_type)
        self.assertEqual(conflicts, [])
        self.assertEqual(
            builder.this.get_file('1').read(), 'text-merged-by-hook')

    def test_result_can_be_delete(self):
        """A hook's result can be the deletion of a file."""
        self.install_hook_delete()
        builder = self.make_merge_builder()
        builder.add_file("1", builder.tree_root, "name1", "text1", True)
        builder.change_contents("1", this="text2", other="text3")
        conflicts = builder.merge(self.merge_type)
        self.assertEqual(conflicts, [])
        self.assertRaises(errors.NoSuchId, builder.this.id2path, '1')

    def test_result_can_be_conflict(self):
        """A hook's result can be a conflict."""
        self.install_hook_conflict()
        builder = self.make_merge_builder()
        builder.add_file("1", builder.tree_root, "name1", "text1", True)
        builder.change_contents("1", this="text2", other="text3")
        conflicts = builder.merge(self.merge_type)
        self.assertEqual(conflicts, [TextConflict('name1', file_id='1')])
        # The hook still gets to set the file contents in this case, so that it
        # can insert custom conflict markers.
        self.assertEqual(
            builder.this.get_file('1').read(),
            'text-with-conflict-markers-from-hook')

    def test_can_access_this_other_and_base_versions(self):
        """The hook function can call params.merger.get_lines to access the
        THIS/OTHER/BASE versions of the file.
        """
        self.install_hook_log_lines()
        builder = self.make_merge_builder()
        builder.add_file("1", builder.tree_root, "name1", "text1", True)
        builder.change_contents("1", this="text2", other="text3")
        conflicts = builder.merge(self.merge_type)
        self.assertEqual(
            [(['text2'], ['text3'], ['text1'])], self.hook_log)

