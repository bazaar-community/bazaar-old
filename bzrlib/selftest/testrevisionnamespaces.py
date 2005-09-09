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

import os
from bzrlib.selftest import TestCaseInTempDir

class TestRevisionNamespaces(TestCaseInTempDir):
    def test_revision_namespaces(self):
        """Functional tests for hashcache"""
        from bzrlib.errors import NoSuchRevision
        from bzrlib.branch import Branch
        from bzrlib.revisionspec import RevisionSpec

        b = Branch.initialize('.')

        b.commit('Commit one', rev_id='a@r-0-1')
        b.commit('Commit two', rev_id='a@r-0-2')
        b.commit('Commit three', rev_id='a@r-0-3')

        self.assertEquals(RevisionSpec(b, None), (0, None))
        self.assertEquals(RevisionSpec(b, 1), (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec(b, 'revno:1'), (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec(b, 'revid:a@r-0-1'), (1, 'a@r-0-1'))
        self.assertRaises(NoSuchRevision, RevisionSpec, b, 'revid:a@r-0-0')
        self.assertRaises(TypeError, RevisionSpec, b, object)

        self.assertEquals(RevisionSpec(b, 'date:-tomorrow'), (3, 'a@r-0-3'))
        self.assertEquals(RevisionSpec(b, 'date:+today'), (1, 'a@r-0-1'))

        self.assertEquals(RevisionSpec(b, 'last:1'), (3, 'a@r-0-3'))
        self.assertEquals(RevisionSpec(b, '-1'), (3, 'a@r-0-3'))
