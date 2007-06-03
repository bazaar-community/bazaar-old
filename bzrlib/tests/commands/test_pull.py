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


from bzrlib.builtins import cmd_pull
from bzrlib.tests import StringIOWrapper
from bzrlib.tests.TransportUtil import TestCaseWithConnectionHookedTransport

class TestPull(TestCaseWithConnectionHookedTransport):

    def test_pull(self):
        wt1 = self.make_branch_and_tree('branch1')
        tip = wt1.commit('empty commit')
        wt2 = self.make_branch_and_tree('branch2')
        # make_branch_and_tree calls have created connections
        self.reset_connections()

        cmd = cmd_pull()
        # We don't care about the ouput but 'outf' should be defined
        cmd.outf = StringIOWrapper()
        cmd.run(self.get_url() + '/branch1', directory='branch2')
        self.assertEquals(1, len(self.connections))

