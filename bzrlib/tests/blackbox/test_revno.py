# Copyright (C) 2005 Canonical Ltd
# -*- coding: utf-8 -*-
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


"""Black-box tests for bzr revno.
"""

import os

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir

class TestRevno(TestCaseInTempDir):

    def test_revno(self):

        def bzr(*args, **kwargs):
            return self.run_bzr(*args, **kwargs)[0]

        os.mkdir('a')
        os.chdir('a')
        bzr('init')
        self.assertEquals(int(bzr('revno')), 0)

        open('foo', 'wb').write('foo\n')
        bzr('add foo')
        bzr('commit -m foo')
        self.assertEquals(int(bzr('revno')), 1)

        os.mkdir('baz')
        bzr('add baz')
        bzr('commit -m baz')
        self.assertEquals(int(bzr('revno')), 2)

        os.chdir('..')
        self.assertEquals(int(bzr('revno a')), 2)
        self.assertEquals(int(bzr('revno a/baz')), 2)

    def test_revno_tree(self):
        # Make branch and checkout
        os.mkdir('branch')
        self.run_bzr('init branch')
        self.run_bzr('checkout --lightweight branch checkout')

        # Get the checkout out of date
        self.build_tree(['branch/file'])
        self.run_bzr('add branch/file')
        self.run_bzr('commit -m mkfile branch')

        # Make sure revno says we're on 1
        out,err = self.run_bzr('revno checkout')
        self.assertEqual('', err)
        self.assertEqual('1\n', out)

        # Make sure --tree knows it's still on 0
        out,err = self.run_bzr('revno --tree checkout')
        self.assertEqual('', err)
        self.assertEqual('0\n', out)

