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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for interface conformance of 'WorkingTree.remove'"""

from bzrlib.tests.workingtree_implementations import TestCaseWithWorkingTree
from bzrlib import errors, osutils

class TestRemove(TestCaseWithWorkingTree):
    """Tests WorkingTree.remove"""

    files = ['a', 'b/', 'b/c', 'd/']
    rfiles = ['b/c', 'b', 'a', 'd']

    def getTree(self, files):
        tree = self.make_branch_and_tree('.')
        self.build_tree(files)
        self.failUnlessExists(files)
        return tree

    def getCommittedTree(self, files, message="Committing"):
        tree = self.getTree(files)
        tree.add(files)
        tree.commit(message)
        self.assertInWorkingTree(files)
        return tree

    def test_remove_keep(self):
        """Check that files and directories are unversioned but not deleted."""
        tree = self.getTree(TestRemove.files)
        tree.add(TestRemove.files)
        self.assertInWorkingTree(TestRemove.files)

        tree.remove(TestRemove.files)
        self.assertNotInWorkingTree(TestRemove.files)
        self.failUnlessExists(TestRemove.files)

    def test_remove_keep_subtree(self):
        """Check that a directory is unversioned but not deleted."""
        tree = self.make_branch_and_tree('.')
        subtree = self.make_branch_and_tree('subtree')
        tree.add('subtree', 'subtree-id')

        tree.remove('subtree')
        self.assertNotInWorkingTree('subtree')
        self.failUnlessExists('subtree')

    def test_remove_unchanged_files(self):
        """Check that unchanged files are removed and deleted."""
        tree = self.getCommittedTree(TestRemove.files)

        tree.remove(TestRemove.files, keep_files=False)

        self.assertNotInWorkingTree(TestRemove.files)
        self.failIfExists(TestRemove.files)

    def test_remove_added_files(self):
        """Removal of newly added files must fail."""
        tree = self.getTree(TestRemove.files)
        tree.add(TestRemove.files)
        self.assertInWorkingTree(TestRemove.files)
        err = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            TestRemove.files, keep_files=False)
        self.assertContainsRe(err.changes_as_text,
            '(?s)added:.*a.*b/.*b/c.*d/')
        self.assertInWorkingTree(TestRemove.files)
        self.failUnlessExists(TestRemove.files)

    def test_remove_changed_file(self):
        """Removal of a changed files must fail."""
        tree = self.getCommittedTree('a')
        self.build_tree_contents([('a', "some other new content!")])
        self.assertInWorkingTree('a')
        err = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            'a', keep_files=False)
        self.assertContainsRe(err.changes_as_text, '(?s)modified:.*a')
        self.assertInWorkingTree('a')
        self.failUnlessExists('a')

    def test_remove_deleted_files(self):
        """Check that files are removed if they don't exist any more."""
        tree = self.getCommittedTree(TestRemove.files)
        for f in TestRemove.rfiles:
            osutils.delete_any(f)
        self.assertInWorkingTree(TestRemove.files)
        self.failIfExists(TestRemove.files)

        tree.remove(TestRemove.files, keep_files=False)

        self.assertNotInWorkingTree(TestRemove.files)
        self.failIfExists(TestRemove.files)

    def test_remove_renamed_files(self):
        """Check that files are removed even if they are renamed."""
        tree = self.getCommittedTree(TestRemove.files)

        for f in TestRemove.rfiles:
            tree.rename_one(f,f+'x')
        rfilesx = ['bx/cx', 'bx', 'ax', 'dx']
        self.assertInWorkingTree(rfilesx)
        self.failUnlessExists(rfilesx)

        tree.remove(rfilesx, keep_files=False)

        self.assertNotInWorkingTree(rfilesx)
        self.failIfExists(rfilesx)

    def test_remove_renamed_changed_files(self):
        """Check that files are not removed if they are renamed and changed."""
        tree = self.getCommittedTree(TestRemove.files)

        for f in TestRemove.rfiles:
            tree.rename_one(f,f+'x')
        rfilesx = ['bx/cx', 'bx', 'ax', 'dx']
        self.build_tree_contents([('ax','changed and renamed!'),
                                  ('bx/cx','changed and renamed!')])
        self.assertInWorkingTree(rfilesx)
        self.failUnlessExists(rfilesx)

        err = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            rfilesx, keep_files=False)
        self.assertContainsRe(err.changes_as_text,
            '(?s)modified:.*ax.*bx/cx')
        self.assertInWorkingTree(rfilesx)
        self.failUnlessExists(rfilesx)

    def test_force_remove_changed_files(self):
        """Check that changed files are removed and deleted when forced."""
        tree = self.getTree(TestRemove.files)
        tree.add(TestRemove.files)
        self.assertInWorkingTree(TestRemove.files)

        tree.remove(TestRemove.files, keep_files=False, force=True)

        self.assertNotInWorkingTree(TestRemove.files)
        self.failIfExists(TestRemove.files)

    def test_remove_unknown_files(self):
        """Try to delete unknown files."""
        tree = self.getTree(TestRemove.files)
        err = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            TestRemove.files, keep_files=False)
        self.assertContainsRe(err.changes_as_text,
            '(?s)unknown:.*d/.*b/c.*b/.*a.*')

    def test_remove_nonexisting_files(self):
        """Try to delete non-existing files."""
        tree = self.getTree(TestRemove.files)
        tree.remove([''], keep_files=False)
        tree.remove(['xyz', 'abc/def'], keep_files=False)

    def test_remove_nonempty_directory(self):
        """Unchanged directories should be deleted."""
        files = ['b/', 'b/c', 'b/sub_directory/', 'b/sub_directory/with_file']
        tree = self.getCommittedTree(files)
        tree.remove('b', keep_files=False)
        self.assertNotInWorkingTree('b')
        self.failIfExists('b')

    def test_dont_remove_directory_with_unknowns(self):
        """Directories with unknowns should not be deleted."""
        directories = ['a/', 'b/', 'c/', 'c/c/']
        tree = self.getCommittedTree(directories)

        self.build_tree(['a/unknown_file'])
        err = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            'a', keep_files=False)
        self.assertContainsRe(err.changes_as_text,
            '(?s)unknown:.*a/unknown_file')

        self.build_tree(['b/unknown_directory'])
        err = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            'b', keep_files=False)
        self.assertContainsRe(err.changes_as_text,
            '(?s)unknown:.*b/unknown_directory')

        self.build_tree(['c/c/unknown_file'])
        err = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            'c/c', keep_files=False)
        self.assertContainsRe(err.changes_as_text,
            '(?s)unknown:.*c/c/unknown_file')

        self.assertInWorkingTree(directories)
        self.failUnlessExists(directories)

    def test_force_remove_directory_with_unknowns(self):
        """Unchanged non-empty directories should be deleted when forced."""
        files = ['b/', 'b/c']
        tree = self.getCommittedTree(files)

        other_files = ['b/unknown_file', 'b/sub_directory/',
            'b/sub_directory/with_file', 'b/sub_directory/sub_directory/']
        self.build_tree(other_files)

        self.assertInWorkingTree(files)
        self.failUnlessExists(files)

        tree.remove('b', keep_files=False, force=True)

        self.assertNotInWorkingTree(files)
        self.failIfExists(files)
        self.assertNotInWorkingTree(other_files)
        self.failIfExists(other_files)

    def test_remove_directory_with_changed_file(self):
        """Refuse to delete directories with changed files."""
        files = ['b/', 'b/c']
        tree = self.getCommittedTree(files)
        self.build_tree_contents([('b/c', "some other new content!")])

        err = self.assertRaises(errors.BzrRemoveChangedFilesError, tree.remove,
            'b', keep_files=False)
        self.assertContainsRe(err.changes_as_text, '(?s)modified:.*b/c')
        self.assertInWorkingTree(files)
        self.failUnlessExists(files)

        #see if we can force it now..
        tree.remove('b', keep_files=False, force=True)
        self.assertNotInWorkingTree(files)
        self.failIfExists(files)

    def test_remove_directory_with_renames(self):
        """Delete directory with renames in or out."""

        files = ['a/', 'a/file', 'a/directory/', 'b/']
        files_to_move = ['a/file', 'a/directory/']

        tree = self.getCommittedTree(files)
        #move stuff from a=>b
        tree.move(['a/file', 'a/directory'], to_dir='b')

        moved_files = ['b/file', 'b/directory/']
        self.assertNotInWorkingTree(files_to_move)
        self.failIfExists(files_to_move)
        self.assertInWorkingTree(moved_files)
        self.failUnlessExists(moved_files)

        # check if it works with renames out
        tree.remove('a', keep_files=False)
        self.assertNotInWorkingTree(['a/'])
        self.failIfExists(['a/'])

        # check if it works with renames in
        tree.remove('b', keep_files=False)
        self.assertNotInWorkingTree(['b/'])
        self.failIfExists(['b/'])

    def test_non_cwd(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/dir/', 'tree/dir/file'])
        tree.add(['dir', 'dir/file'])
        tree.commit('add file')
        tree.remove('dir/', keep_files=False)
        self.failIfExists('tree/dir/file')
        self.assertNotInWorkingTree('tree/dir/file', 'tree')