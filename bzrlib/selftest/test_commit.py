# Copyright (C) 2005 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import os

from bzrlib.selftest import TestCaseInTempDir
from bzrlib.branch import Branch
from bzrlib.commit import Commit
from bzrlib.errors import PointlessCommit


class TestCommit(TestCaseInTempDir):
    def test_simple_commit(self):
        """Commit and check two versions of a single file."""
        b = Branch('.', init=True)
        file('hello', 'w').write('hello world')
        b.add('hello')
        b.commit(message='add hello')
        file_id = b.working_tree().path2id('hello')

        file('hello', 'w').write('version 2')
        b.commit(message='commit 2')

        eq = self.assertEquals
        eq(b.revno(), 2)
        rh = b.revision_history()
        rev = b.get_revision(rh[0])
        eq(rev.message, 'add hello')

        tree1 = b.revision_tree(rh[0])
        text = tree1.get_file_text(file_id)
        eq(text, 'hello world')

        tree2 = b.revision_tree(rh[1])
        eq(tree2.get_file_text(file_id), 'version 2')


    def test_delete_commit(self):
        """Test a commit with a deleted file"""
        b = Branch('.', init=True)
        file('hello', 'w').write('hello world')
        b.add(['hello'], ['hello-id'])
        b.commit(message='add hello')

        os.remove('hello')
        b.commit('removed hello', rev_id='rev2')

        tree = b.revision_tree('rev2')
        self.assertFalse(tree.has_id('hello-id'))


    def test_pointless_commit(self):
        """Commit refuses unless there are changes or it's forced."""
        b = Branch('.', init=True)
        file('hello', 'w').write('hello')
        b.add(['hello'])
        b.commit(message='add hello')
        self.assertEquals(b.revno(), 1)
        self.assertRaises(PointlessCommit,
                          b.commit,
                          message='fails',
                          allow_pointless=False)
        self.assertEquals(b.revno(), 1)
        


    def test_commit_empty(self):
        """Commiting an empty tree works."""
        b = Branch('.', init=True)
        b.commit(message='empty tree', allow_pointless=True)
        self.assertRaises(PointlessCommit,
                          b.commit,
                          message='empty tree',
                          allow_pointless=False)
        b.commit(message='empty tree', allow_pointless=True)
        self.assertEquals(b.revno(), 2)


    def test_selective_delete(self):
        """Selective commit in tree with deletions"""


    def test_removed_commit(self):
        """Test a commit with a removed file"""
        b = Branch('.', init=True)
        file('hello', 'w').write('hello world')
        b.add(['hello'], ['hello-id'])
        b.commit(message='add hello')

        b.remove('hello')
        b.commit('removed hello', rev_id='rev2')

        tree = b.revision_tree('rev2')
        self.assertFalse(tree.has_id('hello-id'))


if __name__ == '__main__':
    import unittest
    unittest.main()
    
