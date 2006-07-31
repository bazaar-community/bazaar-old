# Copyright (C) 2006 by Canonical Ltd
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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Tests for the update command of bzr."""


from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.workingtree import WorkingTree


class TestUpdate(ExternalBase):

    def test_update_standalone_trivial(self):
        self.runbzr("init")
        out, err = self.runbzr('update')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_standalone_trivial_with_alias_up(self):
        self.runbzr("init")
        out, err = self.runbzr('up')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_up_to_date_light_checkout(self):
        self.make_branch_and_tree('branch')
        self.runbzr('checkout --lightweight branch checkout')
        out, err = self.runbzr('update checkout')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_up_to_date_checkout(self):
        self.make_branch_and_tree('branch')
        self.run_bzr('checkout', 'branch', 'checkout')
        out, err = self.run_bzr('update', 'checkout')
        self.assertEqual('Tree is up to date at revision 0.\n', err)
        self.assertEqual('', out)

    def test_update_out_of_date_standalone_tree(self):
        # FIXME the default format has to change for this to pass
        # because it currently uses the branch last-revision marker.
        self.make_branch_and_tree('branch')
        # make a checkout
        self.runbzr('checkout --lightweight branch checkout')
        self.build_tree(['checkout/file'])
        self.runbzr('add checkout/file')
        self.runbzr('commit -m add-file checkout')
        # now branch should be out of date
        out,err = self.runbzr('update branch')
        self.assertEqual('', out)
        self.assertEqual('All changes applied successfully.\n'
                         'Updated to revision 1.\n', err)
        self.failUnlessExists('branch/file')

    def test_update_out_of_date_light_checkout(self):
        self.make_branch_and_tree('branch')
        # make two checkouts
        self.runbzr('checkout --lightweight branch checkout')
        self.runbzr('checkout --lightweight branch checkout2')
        self.build_tree(['checkout/file'])
        self.runbzr('add checkout/file')
        self.runbzr('commit -m add-file checkout')
        # now checkout2 should be out of date
        out,err = self.runbzr('update checkout2')
        self.assertEqual('All changes applied successfully.\n'
                         'Updated to revision 1.\n',
                         err)
        self.assertEqual('', out)

    def test_update_conflicts_returns_2(self):
        self.make_branch_and_tree('branch')
        # make two checkouts
        self.runbzr('checkout --lightweight branch checkout')
        self.build_tree(['checkout/file'])
        self.runbzr('add checkout/file')
        self.runbzr('commit -m add-file checkout')
        self.runbzr('checkout --lightweight branch checkout2')
        # now alter file in checkout
        a_file = file('checkout/file', 'wt')
        a_file.write('Foo')
        a_file.close()
        self.runbzr('commit -m checnge-file checkout')
        # now checkout2 should be out of date
        # make a local change to file
        a_file = file('checkout2/file', 'wt')
        a_file.write('Bar')
        a_file.close()
        out,err = self.runbzr('update checkout2', retcode=1)
        self.assertEqual(['1 conflicts encountered.',
                          'Updated to revision 2.'],
                         err.split('\n')[1:3])
        self.assertContainsRe(err, 'Text conflict in file\n')
        self.assertEqual('', out)

    def test_smoke_update_checkout_bound_branch_local_commits(self):
        # smoke test for doing an update of a checkout of a bound
        # branch with local commits.
        self.make_branch_and_tree('master')
        # make a bound branch
        self.run_bzr('checkout', 'master', 'child')
        # check that out
        self.run_bzr('checkout', '--lightweight', 'child', 'checkout')
        # change master
        a_file = file('master/file', 'wt')
        a_file.write('Foo')
        a_file.close()
        self.run_bzr('add', 'master')
        self.run_bzr('commit', '-m', 'add file', 'master')
        # change child
        a_file = file('child/file_b', 'wt')
        a_file.write('Foo')
        a_file.close()
        self.run_bzr('add', 'child')
        self.run_bzr('commit', '--local', '-m', 'add file_b', 'child')
        # check checkout
        a_file = file('checkout/file_c', 'wt')
        a_file.write('Foo')
        a_file.close()
        self.run_bzr('add', 'checkout')

        # now, update checkout ->
        # get all three files and a pending merge.
        self.run_bzr('update', 'checkout')
        wt = WorkingTree.open('checkout')
        self.assertNotEqual([], wt.pending_merges())
        self.failUnlessExists('checkout/file')
        self.failUnlessExists('checkout/file_b')
        self.failUnlessExists('checkout/file_c')
        self.assertTrue(wt.has_filename('file_c'))
