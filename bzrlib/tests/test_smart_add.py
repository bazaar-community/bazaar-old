# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

from cStringIO import StringIO

from bzrlib import osutils
from bzrlib.add import (
    AddAction,
    AddFromBaseAction,
    )
from bzrlib.tests import TestCase, TestCaseWithTransport
from bzrlib.inventory import Inventory


class AddCustomIDAction(AddAction):

    def __call__(self, inv, parent_ie, path, kind):
        # The first part just logs if appropriate
        # Now generate a custom id
        file_id = osutils.safe_file_id(kind + '-'
                                       + path.raw_path.replace('/', '%'),
                                       warn=False)
        if self.should_print:
            self._to_file.write('added %s with id %s\n'
                                % (path.raw_path, file_id))
        return file_id


class TestAddFrom(TestCaseWithTransport):
    """Tests for AddFromBaseAction"""

    def make_base_tree(self):
        self.base_tree = self.make_branch_and_tree('base')
        self.build_tree(['base/a', 'base/b',
                         'base/dir/', 'base/dir/a',
                         'base/dir/subdir/',
                         'base/dir/subdir/b',
                        ])
        self.base_tree.add(['a', 'b', 'dir', 'dir/a',
                            'dir/subdir', 'dir/subdir/b'])
        self.base_tree.commit('creating initial tree.')

    def add_helper(self, base_tree, base_path, new_tree, file_list,
                   should_print=False):
        to_file = StringIO()
        base_tree.lock_read()
        try:
            new_tree.lock_write()
            try:
                action = AddFromBaseAction(base_tree, base_path,
                                           to_file=to_file,
                                           should_print=should_print)
                new_tree.smart_add(file_list, action=action)
            finally:
                new_tree.unlock()
        finally:
            base_tree.unlock()
        return to_file.getvalue()

    def test_copy_all(self):
        self.make_base_tree()
        new_tree = self.make_branch_and_tree('new')
        files = ['a', 'b',
                 'dir/', 'dir/a',
                 'dir/subdir/',
                 'dir/subdir/b',
                ]
        self.build_tree(['new/' + fn for fn in files])
        self.add_helper(self.base_tree, '', new_tree, ['new'])

        for fn in files:
            base_file_id = self.base_tree.path2id(fn)
            new_file_id = new_tree.path2id(fn)
            self.assertEqual(base_file_id, new_file_id)

    def test_copy_from_dir(self):
        self.make_base_tree()
        new_tree = self.make_branch_and_tree('new')

        self.build_tree(['new/a', 'new/b', 'new/c',
                         'new/subdir/', 'new/subdir/b', 'new/subdir/d'])
        new_tree.set_root_id(self.base_tree.get_root_id())
        self.add_helper(self.base_tree, 'dir', new_tree, ['new'])

        # We know 'a' and 'b' exist in the root, and they are being added
        # in a new 'root'. Since ROOT ids have been set as the same, we will
        # use those ids
        self.assertEqual(self.base_tree.path2id('a'),
                         new_tree.path2id('a'))
        self.assertEqual(self.base_tree.path2id('b'),
                         new_tree.path2id('b'))

        # Because we specified 'dir/' as the base path, and we have
        # nothing named 'subdir' in the base tree, we should grab the
        # ids from there
        self.assertEqual(self.base_tree.path2id('dir/subdir'),
                         new_tree.path2id('subdir'))
        self.assertEqual(self.base_tree.path2id('dir/subdir/b'),
                         new_tree.path2id('subdir/b'))

        # These should get newly generated ids
        c_id = new_tree.path2id('c')
        self.assertNotEqual(None, c_id)
        self.base_tree.lock_read()
        self.addCleanup(self.base_tree.unlock)
        self.failIf(c_id in self.base_tree)

        d_id = new_tree.path2id('subdir/d')
        self.assertNotEqual(None, d_id)
        self.failIf(d_id in self.base_tree)

    def test_copy_existing_dir(self):
        self.make_base_tree()
        new_tree = self.make_branch_and_tree('new')
        self.build_tree(['new/subby/', 'new/subby/a', 'new/subby/b'])

        subdir_file_id = self.base_tree.path2id('dir/subdir')
        new_tree.add(['subby'], [subdir_file_id])
        self.add_helper(self.base_tree, '', new_tree, ['new'])
        # Because 'subby' already points to subdir, we should add
        # 'b' with the same id
        self.assertEqual(self.base_tree.path2id('dir/subdir/b'),
                         new_tree.path2id('subby/b'))

        # 'subby/a' should be added with a new id because there is no
        # matching path or child of 'subby'.
        a_id = new_tree.path2id('subby/a')
        self.assertNotEqual(None, a_id)
        self.base_tree.lock_read()
        self.addCleanup(self.base_tree.unlock)
        self.failIf(a_id in self.base_tree)


class TestAddActions(TestCase):

    def test_quiet(self):
        self.run_action("")

    def test__print(self):
        self.run_action("added path\n")

    def run_action(self, output):
        from bzrlib.add import AddAction
        from bzrlib.mutabletree import FastPath
        inv = Inventory()
        stdout = StringIO()
        action = AddAction(to_file=stdout, should_print=bool(output))

        self.apply_redirected(None, stdout, None, action, inv, None, FastPath('path'), 'file')
        self.assertEqual(stdout.getvalue(), output)
