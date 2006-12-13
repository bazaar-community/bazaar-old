# Copyright (C) 2006 Canonical Ltd
# Authors: Aaron Bentley
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


import os
from StringIO import StringIO

from bzrlib.bundle.serializer import read_bundle
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import TestCaseInTempDir


class TestBundle(TestCaseInTempDir):

    def make_trees(self):
        grandparent_tree = BzrDir.create_standalone_workingtree('grandparent')
        grandparent_tree.commit('initial commit', rev_id='revision1')
        parent_bzrdir = grandparent_tree.bzrdir.sprout('parent')
        parent_tree = parent_bzrdir.open_workingtree()
        parent_tree.commit('next commit', rev_id='revision2')
        branch_tree = parent_tree.bzrdir.sprout('branch').open_workingtree()
        branch_tree.commit('last commit', rev_id='revision3')

    def test_uses_parent(self):
        """Parent location is used as a basis by default"""
        self.make_trees()        
        os.chdir('grandparent')
        errmsg = self.run_bzr('bundle', retcode=3)[1]
        self.assertContainsRe(errmsg, 'No base branch known or specified')
        os.chdir('../branch')
        stdout, stderr = self.run_bzr('bundle')
        self.assertEqual(stderr.count('Using saved location'), 1)
        br = read_bundle(StringIO(stdout))
        self.assertRevisions(br, ['revision3'])

    def assertRevisions(self, bi, expected):
        self.assertEqual([r.revision_id for r in bi.revisions], expected)

    def test_uses_submit(self):
        """Submit location can be used and set"""
        self.make_trees()        
        os.chdir('branch')
        br = read_bundle(StringIO(self.run_bzr('bundle')[0]))
        self.assertRevisions(br, ['revision3'])
        br = read_bundle(StringIO(self.run_bzr('bundle', '../grandparent')[0]))
        self.assertRevisions(br, ['revision3', 'revision2'])
        # submit location should be auto-remembered
        br = read_bundle(StringIO(self.run_bzr('bundle')[0]))
        self.assertRevisions(br, ['revision3', 'revision2'])
        self.run_bzr('bundle', '../parent')
        br = read_bundle(StringIO(self.run_bzr('bundle')[0]))
        self.assertRevisions(br, ['revision3', 'revision2'])
        self.run_bzr('bundle', '../parent', '--remember')
        br = read_bundle(StringIO(self.run_bzr('bundle')[0]))
        self.assertRevisions(br, ['revision3'])
        err = self.run_bzr('bundle', '--remember', retcode=3)[1]
        self.assertContainsRe(err, 
                              '--remember requires a branch to be specified.')

    def test_revision_branch_interaction(self):
        self.make_trees()        
        os.chdir('branch')
        bi = read_bundle(StringIO(self.run_bzr('bundle', '../grandparent')[0]))
        self.assertRevisions(bi, ['revision3', 'revision2'])
        out = StringIO(self.run_bzr('bundle', '../grandparent', '-r', '-2')[0])
        bi = read_bundle(out)
        self.assertRevisions(bi, ['revision2'])
        bi = read_bundle(StringIO(self.run_bzr('bundle', '-r', '-2..-1')[0]))
        self.assertRevisions(bi, ['revision3'])
        self.run_bzr('bundle', '../grandparent', '-r', '-2..-1', retcode=3)

    def test_output(self):
        # check output for consistency
        # win32 stdout convert LF to CRLF and this is break created bundle
        self.make_trees()        
        os.chdir('branch')
        stdout = self.run_bzr_subprocess('bundle')[0]
        br = read_bundle(StringIO(stdout))
        self.assertRevisions(br, ['revision3'])
