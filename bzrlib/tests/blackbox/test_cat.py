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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Black-box tests for bzr cat.
"""

import os

from bzrlib.tests.blackbox import TestCaseWithTransport

class TestCat(TestCaseWithTransport):

    def test_cat(self):

        def bzr(*args, **kwargs):
            return self.run_bzr_subprocess(*args, **kwargs)[0]

        os.mkdir('branch')
        os.chdir('branch')
        bzr('init')
        open('a', 'wb').write('foo\n')
        bzr('add', 'a')

        # 'bzr cat' without an option should cat the last revision
        bzr('cat', 'a', retcode=3)

        bzr('commit', '-m', '1')
        open('a', 'wb').write('baz\n')

        self.assertEquals(bzr('cat', 'a'), 'foo\n')

        bzr('commit', '-m', '2')
        self.assertEquals(bzr('cat', 'a'), 'baz\n')
        self.assertEquals(bzr('cat', 'a', '-r', '1'), 'foo\n')
        self.assertEquals(bzr('cat', 'a', '-r', '-1'), 'baz\n')

        rev_id = bzr('revision-history').strip().split('\n')[-1]

        self.assertEquals(bzr('cat', 'a', '-r', 'revid:%s' % rev_id), 'baz\n')
        
        os.chdir('..')
        
        self.assertEquals(bzr('cat', 'branch/a', '-r', 'revno:1:branch'),
                          'foo\n')
        bzr('cat', 'a', retcode=3)
        bzr('cat', 'a', '-r', 'revno:1:branch-that-does-not-exist', retcode=3)
        
    def test_cat_different_id(self):
        """'cat' works with old and new files"""
        tree = self.make_branch_and_tree('.')
        # the files are named after their path in the revision and
        # current trees later in the test case
        # a-rev-tree is special because it appears in both the revision
        # tree and the working tree
        self.build_tree_contents([('a-rev-tree', 'foo\n'),
            ('c-rev', 'baz\n'), ('d-rev', 'bar\n')])
        tree.lock_write()
        try:
            tree.add(['a-rev-tree', 'c-rev', 'd-rev'])
            tree.commit('add test files')
            # remove currently uses self._write_inventory - 
            # work around that for now.
            tree.flush()
            tree.remove(['d-rev'])
            tree.rename_one('a-rev-tree', 'b-tree')
            tree.rename_one('c-rev', 'a-rev-tree')

            # 'b-tree' is not present in the old tree.
            self.run_bzr_error([], 'cat', 'b-tree', '--name-from-revision')

            # get to the old file automatically
            out, err = self.run_bzr('cat', 'd-rev')
            self.assertEqual('bar\n', out)
            self.assertEqual('', err)

            out, err = self.run_bzr('cat', 'a-rev-tree',
                                    '--name-from-revision')
            self.assertEqual('foo\n', out)
            self.assertEqual('', err)

            out, err = self.run_bzr('cat', 'a-rev-tree')
            self.assertEqual('baz\n', out)
            self.assertEqual('', err)
        finally:
            tree.unlock()

    def test_remote_cat(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['README'])
        wt.add('README')
        wt.commit('Making sure there is a basis_tree available')

        url = self.get_readonly_url() + '/README'
        out, err = self.run_bzr('cat', url)
        self.assertEqual('contents of README\n', out)
