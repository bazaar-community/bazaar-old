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

"""Tests for WorkingTree.check_state."""

from bzrlib import (
    tests,
    )
from bzrlib.tests.per_workingtree import TestCaseWithWorkingTree


class TestCheckState(TestCaseWithWorkingTree):

    def test_check_state(self):
        tree = self.make_branch_and_tree('tree')
        # Everything should be fine with an unmodified tree, no exception
        # should be raised.
        tree.check_state()
