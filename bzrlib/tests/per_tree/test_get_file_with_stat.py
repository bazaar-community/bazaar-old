# Copyright (C) 2008 Canonical Ltd
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

"""Test that all WorkingTree's implement get_file_with_stat."""

import os
import sys

from bzrlib.tests.per_tree import TestCaseWithTree



class TestGetFileWithStat(TestCaseWithTree):

    # On Windows, 'os.fstat(f.fileno())' will return a value for 'st_ino' but
    # 'os.lstat(filename)' does *not* return a value. As such, we can't just
    # compare all attributes of the stat object to assert that fstat returns
    # identical content to lstat...
    # However, see also bug #478023
    ignore_ino = (sys.platform == 'win32')

    def test_get_file_with_stat_id_only(self):
        work_tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        work_tree.add(['foo'], ['foo-id'])
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        file_obj, statvalue = tree.get_file_with_stat('foo-id')
        try:
            if statvalue is not None:
                expected = os.lstat('foo')
                self.assertEqualStat(expected, statvalue,
                                     ignore_ino=self.ignore_ino)
            self.assertEqual(["contents of foo\n"], file_obj.readlines())
        finally:
            file_obj.close()

    def test_get_file_with_stat_id_and_path(self):
        work_tree = self.make_branch_and_tree('.')
        self.build_tree(['foo'])
        work_tree.add(['foo'], ['foo-id'])
        tree = self._convert_tree(work_tree)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        file_obj, statvalue = tree.get_file_with_stat('foo-id', 'foo')
        try:
            if statvalue is not None:
                expected = os.lstat('foo')
                self.assertEqualStat(expected, statvalue,
                                     ignore_ino=self.ignore_ino)
            self.assertEqual(["contents of foo\n"], file_obj.readlines())
        finally:
            file_obj.close()
