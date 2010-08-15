# Copyright (C) 2005, 2009 Canonical Ltd
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
import shutil
from StringIO import StringIO
import types

from bzrlib import tests, ui
from bzrlib.bzrdir import (
    BzrDir,
    )
from bzrlib.clean_tree import (
    clean_tree,
    delete_items,
    iter_deletables,
    )
from bzrlib.osutils import (
    has_symlinks,
    )
from bzrlib.tests import (
    TestCaseInTempDir,
    )


class TestCleanTree(TestCaseInTempDir):

    def test_symlinks(self):
        if has_symlinks() is False:
            return
        os.mkdir('branch')
        BzrDir.create_standalone_workingtree('branch')
        os.symlink(os.path.realpath('no-die-please'), 'branch/die-please')
        os.mkdir('no-die-please')
        self.failUnlessExists('branch/die-please')
        os.mkdir('no-die-please/child')

        clean_tree('branch', unknown=True, no_prompt=True)
        self.failUnlessExists('no-die-please')
        self.failUnlessExists('no-die-please/child')

    def test_iter_deletable(self):
        """Files are selected for deletion appropriately"""
        os.mkdir('branch')
        tree = BzrDir.create_standalone_workingtree('branch')
        transport = tree.bzrdir.root_transport
        transport.put_bytes('.bzrignore', '*~\n*.pyc\n.bzrignore\n')
        transport.put_bytes('file.BASE', 'contents')
        tree.lock_write()
        try:
            self.assertEqual(len(list(iter_deletables(tree, unknown=True))), 1)
            transport.put_bytes('file', 'contents')
            transport.put_bytes('file~', 'contents')
            transport.put_bytes('file.pyc', 'contents')
            dels = sorted([r for a,r in iter_deletables(tree, unknown=True)])
            self.assertEqual(['file', 'file.BASE'], dels)

            dels = [r for a,r in iter_deletables(tree, detritus=True)]
            self.assertEqual(sorted(['file~', 'file.BASE']), dels)

            dels = [r for a,r in iter_deletables(tree, ignored=True)]
            self.assertEqual(sorted(['file~', 'file.pyc', '.bzrignore']),
                             dels)

            dels = [r for a,r in iter_deletables(tree, unknown=False)]
            self.assertEqual([], dels)
        finally:
            tree.unlock()

    def test_delete_items_warnings(self):
        """Ensure delete_items issues warnings on OSError. (bug #430785)
        """
        def _dummy_unlink(path):
            if path.endswith('0foo'):
                # simulate error.
                raise OSError

        def _dummy_rmtree(path, ignore_errors=False, onerror=None):
            self.assertTrue(onerror, types.FunctionType)
            # ensure onerror params and call with 0foo to
            # indicate failure in removing 0rmtree_error
            onerror(function=None, path="0rmtree_error", excinfo=None)

        self.overrideAttr(os, 'unlink', _dummy_unlink)
        self.overrideAttr(shutil, 'rmtree', _dummy_rmtree)
        stdout = tests.StringIOWrapper()
        stderr = tests.StringIOWrapper()
        ui.ui_factory = tests.TestUIFactory(stdout=stdout, stderr=stderr)
        os.mkdir('branch')
        BzrDir.create_standalone_workingtree('branch')
        files = ['0foo', '1bar', '2baz']
        os.chdir('branch')
        for f in files:
            open(f, 'w').close()
        os.mkdir('subdir')
        clean_tree('.', unknown=True, no_prompt=True)
        self.assertContainsRe(stderr.getvalue(),
            'bzr: warning: unable to remove.*branch/0foo')
        self.assertContainsRe(stderr.getvalue(),
            'bzr: warning: unable to remove.*0rmtree_error')
