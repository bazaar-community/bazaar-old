# Copyright (C) 2009 Canonical Ltd
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

import os


from bzrlib import (
    export,
    osutils,
    tests,
    )


class TestExport(tests.TestCaseWithTransport):

    def test_dir_export_missing_file(self):
        self.build_tree(['a/', 'a/b', 'a/c'])
        wt = self.make_branch_and_tree('.')
        wt.add(['a', 'a/b', 'a/c'])
        os.unlink('a/c')
        export.export(wt, 'target', format="dir")
        self.failUnlessExists('target/a/b')
        self.failIfExists('target/a/c')

    def test_dir_export_symlink(self):
        if osutils.has_symlinks() is False:
            return
        wt = self.make_branch_and_tree('.')
        os.symlink('source', 'link')
        wt.add(['link'])
        export.export(wt, 'target', format="dir")
        self.failUnlessExists('target/link')
