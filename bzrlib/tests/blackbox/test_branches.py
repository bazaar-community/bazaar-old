# Copyright (C) 2011 Canonical Ltd
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


"""Black-box tests for bzr branches."""

from bzrlib.branch import BranchReferenceFormat
from bzrlib.tests import TestCaseWithTransport


class TestBranches(TestCaseWithTransport):

    def test_no_colocated_support(self):
        # Listing the branches in a control directory without colocated branch
        # support.
        self.run_bzr('init a')
        out, err = self.run_bzr('branches a')
        self.assertEquals(out, "*(default)\n")

    def test_no_branch(self):
        # Listing the branches in a control directory without branches.
        self.run_bzr('init-repo a')
        out, err = self.run_bzr('branches a')
        self.assertEquals(out, "")

    def test_default_current_dir(self):
        # "bzr branches" list the branches in the current directory
        # if no location was specified.
        self.run_bzr('init-repo a')
        out, err = self.run_bzr('branches', working_dir='a')
        self.assertEquals(out, "")

    def test_recursive_current(self):
        self.run_bzr('init .')
        self.assertEquals(".\n", self.run_bzr('branches --recursive')[0])

    def test_recursive(self):
        self.run_bzr('init source')
        self.run_bzr('init source/subsource')
        self.run_bzr('checkout --lightweight source checkout')
        self.run_bzr('init checkout/subcheckout')
        self.run_bzr('init checkout/.bzr/subcheckout')
        out = self.run_bzr('branches --recursive')[0]
        lines = out.split('\n')
        self.assertIs(True, 'source' in lines, lines)
        self.assertIs(True, 'source/subsource' in lines, lines)
        self.assertIs(True, 'checkout/subcheckout' in lines, lines)
        self.assertIs(True, 'checkout' not in lines, lines)

    def test_indicates_non_branch(self):
        t = self.make_branch_and_tree('a', format='development-colo')
        t.bzrdir.create_branch(name='another')
        t.bzrdir.create_branch(name='colocated')
        out, err = self.run_bzr('branches a')
        self.assertEquals(out, "*(default)\n"
                               " another\n"
                               " colocated\n")

    def test_indicates_branch(self):
        t = self.make_repository('a', format='development-colo')
        t.bzrdir.create_branch(name='another')
        branch = t.bzrdir.create_branch(name='colocated')
        BranchReferenceFormat().initialize(t.bzrdir, target_branch=branch)
        out, err = self.run_bzr('branches a')
        self.assertEquals(out, "*(default)\n"
                               " another\n"
                               "*colocated\n")
