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
from bzrlib.branch import Branch, copy_branch



class TestParent(TestCaseInTempDir):
    def test_no_default_parent(self):
        """Branches should have no parent by default"""
        b = Branch('.', init=True)
        self.assertEquals(b.get_parent(), None)
        
    
    def test_set_get_parent(self):
        """Set and then re-get the parent"""
        b = Branch('.', init=True)
        url = 'http://bazaar-ng.org/bzr/bzr.dev'
        b.set_parent(url)
        self.assertEquals(b.get_parent(), url)

    def test_branch_sets_parent(self):
        """The branch command should set the new branch's parent"""
        from bzrlib.commands import run_bzr

        os.mkdir('from')
        branch_from = Branch('from', init=True)
        file('from/foo', 'wt').write('contents of foo')
        branch_from.add('foo')
        branch_from.commit('initial commit')
        
        os.mkdir('to')
        copy_branch(branch_from, 'to', None)

        branch_to = Branch('to')
        abspath = os.path.abspath('from')
        self.assertEquals(branch_to.get_parent(), abspath)
        

