# Copyright (C) 2005-2011 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

from __future__ import absolute_import

"""Tests for weave-era working tree formats."""

import os

from bzrlib import (
    conflicts,
    errors,
    )

from bzrlib.tests import (
    TestCaseWithTransport,
    )

from bzrlib.plugins.weave_fmt.bzrdir import BzrDirFormat6


class TestFormat2WorkingTree(TestCaseWithTransport):
    """Tests that are specific to format 2 trees."""

    def create_format2_tree(self, url):
        return self.make_branch_and_tree(
            url, format=BzrDirFormat6())

    def test_conflicts(self):
        # test backwards compatability
        tree = self.create_format2_tree('.')
        self.assertRaises(errors.UnsupportedOperation, tree.set_conflicts,
                          None)
        file('lala.BASE', 'wb').write('labase')
        expected = conflicts.ContentsConflict('lala')
        self.assertEqual(list(tree.conflicts()), [expected])
        file('lala', 'wb').write('la')
        tree.add('lala', 'lala-id')
        expected = conflicts.ContentsConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])
        file('lala.THIS', 'wb').write('lathis')
        file('lala.OTHER', 'wb').write('laother')
        # When "text conflict"s happen, stem, THIS and OTHER are text
        expected = conflicts.TextConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])
        os.unlink('lala.OTHER')
        os.mkdir('lala.OTHER')
        expected = conflicts.ContentsConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])

    def test_detect_conflicts(self):
        """Conflicts are detected properly"""
        tree = self.create_format2_tree('.')
        self.build_tree_contents([('hello', 'hello world4'),
                                  ('hello.THIS', 'hello world2'),
                                  ('hello.BASE', 'hello world1'),
                                  ('hello.OTHER', 'hello world3'),
                                  ('hello.sploo.BASE', 'yellowworld'),
                                  ('hello.sploo.OTHER', 'yellowworld2'),
                                  ])
        tree.lock_read()
        self.assertLength(6, list(tree.list_files()))
        tree.unlock()
        tree_conflicts = tree.conflicts()
        self.assertLength(2, tree_conflicts)
        self.assertTrue('hello' in tree_conflicts[0].path)
        self.assertTrue('hello.sploo' in tree_conflicts[1].path)
        conflicts.restore('hello')
        conflicts.restore('hello.sploo')
        self.assertLength(0, tree.conflicts())
        self.assertFileEqual('hello world2', 'hello')
        self.assertFalse(os.path.lexists('hello.sploo'))
        self.assertRaises(errors.NotConflicted, conflicts.restore, 'hello')
        self.assertRaises(errors.NotConflicted,
                          conflicts.restore, 'hello.sploo')
