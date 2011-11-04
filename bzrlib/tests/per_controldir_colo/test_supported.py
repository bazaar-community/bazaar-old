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

"""Tests for bzr directories that support colocated branches."""

from bzrlib.branch import Branch
from bzrlib import (
    errors,
    tests,
    )
from bzrlib.tests import (
    per_controldir,
    )


class TestColocatedBranchSupport(per_controldir.TestCaseWithControlDir):

    def test_destroy_colocated_branch(self):
        branch = self.make_branch('branch')
        bzrdir = branch.bzrdir
        colo_branch = bzrdir.create_branch('colo')
        try:
            bzrdir.destroy_branch("colo")
        except (errors.UnsupportedOperation, errors.TransportNotPossible):
            raise tests.TestNotApplicable('Format does not support destroying branch')
        self.assertRaises(errors.NotBranchError, bzrdir.open_branch,
                          "colo")

    def test_create_colo_branch(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable('Control dir format not supported')
        t = self.get_transport()
        try:
            made_control = self.bzrdir_format.initialize(t.base)
        except errors.UninitializableFormat:
            raise tests.TestNotApplicable(
                'Control dir does not support creating new branches.')
        made_control.create_repository()
        made_branch = made_control.create_branch("colo")
        self.assertIsInstance(made_branch, Branch)
        self.assertEquals("colo", made_branch.name)
        self.assertEqual(made_control, made_branch.bzrdir)

    def test_open_by_url(self):
        # a bzrdir can construct a branch and repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            raise tests.TestNotApplicable('Control dir format not supported')
        t = self.get_transport()
        try:
            made_control = self.bzrdir_format.initialize(t.base)
        except errors.UninitializableFormat:
            raise tests.TestNotApplicable(
                'Control dir does not support creating new branches.')
        made_control.create_repository()
        made_branch = made_control.create_branch(name="colo")
        other_branch = made_control.create_branch(name="othercolo")
        self.assertIsInstance(made_branch, Branch)
        self.assertEqual(made_control, made_branch.bzrdir)
        self.assertNotEqual(made_branch.user_url, other_branch.user_url)
        self.assertNotEqual(made_branch.control_url, other_branch.control_url)
        re_made_branch = Branch.open(made_branch.user_url)
        self.assertEquals(re_made_branch.name, "colo")
        self.assertEqual(made_branch.control_url, re_made_branch.control_url)
        self.assertEqual(made_branch.user_url, re_made_branch.user_url)
