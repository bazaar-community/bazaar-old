# Copyright (C) 2010 Canonical Ltd
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


"""Black-box tests for bzr rmbranch."""

from bzrlib import (
    bzrdir,
    )
from bzrlib.tests import (
    TestCaseWithTransport,
    )


class TestRemoveBranch(TestCaseWithTransport):

    def example_branch(self, path='.'):
        tree = self.make_branch_and_tree(path)
        self.build_tree_contents([(path + '/hello', 'foo')])
        tree.add('hello')
        tree.commit(message='setup')
        self.build_tree_contents([(path + '/goodbye', 'baz')])
        tree.add('goodbye')
        tree.commit(message='setup')

    def test_remove_local(self):
        # Remove a local branch.
        self.example_branch('a')
        self.run_bzr('rmbranch a')
        dir = bzrdir.BzrDir.open('a')
        self.assertFalse(dir.has_branch())
        self.assertPathExists('a/hello')
        self.assertPathExists('a/goodbye')

    def test_no_branch(self):
        # No branch in the current directory. 
        self.make_repository('a')
        self.run_bzr_error(['Not a branch'],
            'rmbranch a')

    def test_no_arg(self):
        # location argument defaults to current directory
        self.example_branch('a')
        self.run_bzr('rmbranch', working_dir='a')
        dir = bzrdir.BzrDir.open('a')
        self.assertFalse(dir.has_branch())


class TestSmartServerRemoveBranch(TestCaseWithTransport):

    def test_simple_remove_branch(self):
        self.setup_smart_server_with_call_log()
        self.make_branch('branch')
        self.reset_smart_call_log()
        out, err = self.run_bzr(['rmbranch', self.get_url('branch')])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(18, self.hpss_calls)
