# Copyright (C) 2004, 2005 by Canonical Ltd

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


from bzrlib.selftest import InTempDir, TestBase

class TestRevisionNamespaces(InTempDir):
    """Functional tests for hashcache"""
    def runTest(self):
        from bzrlib.errors import NoSuchRevision
        from bzrlib.branch import Branch
        import os
        import time

        b = Branch('.', init=True)

        b.commit('Commit one', rev_id='a@r-0-1')
        b.commit('Commit two', rev_id='a@r-0-2')
        b.commit('Commit three', rev_id='a@r-0-3')

        self.assertEquals(b.get_revision_info(None), (0, None))
        self.assertEquals(b.get_revision_info(1), (1, 'a@r-0-1'))
        self.assertEquals(b.get_revision_info('revno:1'), (1, 'a@r-0-1'))
        self.assertEquals(b.get_revision_info('revid:a@r-0-1'), (1, 'a@r-0-1'))
        self.assertRaises(NoSuchRevision, b.get_revision_info, 'revid:a@r-0-0')
        self.assertRaises(TypeError, b.get_revision_info, object)

        self.assertEquals(b.get_revision_info('date:-tomorrow'), (3, 'a@r-0-3'))
        self.assertEquals(b.get_revision_info('date:+today'), (1, 'a@r-0-1'))

        self.assertEquals(b.get_revision_info('last:1'), (3, 'a@r-0-3'))

        os.mkdir('newbranch')
        b2 = Branch('newbranch', init=True)
        self.assertEquals(b2.lookup_revision('revid:a@r-0-1'), 'a@r-0-1')

TEST_CLASSES = [
    TestRevisionNamespaces
    ]
