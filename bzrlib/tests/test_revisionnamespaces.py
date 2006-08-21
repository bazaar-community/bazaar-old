# Copyright (C) 2004, 2005, 2006 by Canonical Ltd
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
import time

from bzrlib import (
    errors,
    )
from bzrlib.builtins import merge
from bzrlib.branch import Branch
from bzrlib.tests import TestCaseWithTransport
from bzrlib.errors import NoCommonAncestor, NoCommits
from bzrlib.revisionspec import RevisionSpec


class TestRevisionNamespaces(TestCaseWithTransport):

    def test_revno_n_path(self):
        """Test revision specifiers.

        These identify revisions by date, etc."""
        wta = self.make_branch_and_tree('a')
        ba = wta.branch
        
        wta.commit('Commit one', rev_id='a@r-0-1')
        wta.commit('Commit two', rev_id='a@r-0-2')
        wta.commit('Commit three', rev_id='a@r-0-3')

        wtb = self.make_branch_and_tree('b')
        bb = wtb.branch

        wtb.commit('Commit one', rev_id='b@r-0-1')
        wtb.commit('Commit two', rev_id='b@r-0-2')
        wtb.commit('Commit three', rev_id='b@r-0-3')

        self.assertEquals(RevisionSpec('revno:1:a/').in_history(ba),
                          (1, 'a@r-0-1'))
        # The argument of in_history should be ignored since it is
        # redundant with the path in the spec.
        self.assertEquals(RevisionSpec('revno:1:a/').in_history(None),
                          (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('revno:1:a/').in_history(bb),
                          (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('revno:2:b/').in_history(None),
                          (2, 'b@r-0-2'))


    def test_revision_namespaces(self):
        """Test revision specifiers.

        These identify revisions by date, etc."""
        wt = self.make_branch_and_tree('.')
        b = wt.branch

        wt.commit('Commit one', rev_id='a@r-0-1', timestamp=time.time() - 60*60*24)
        wt.commit('Commit two', rev_id='a@r-0-2')
        wt.commit('Commit three', rev_id='a@r-0-3')

        self.assertEquals(RevisionSpec(None).in_history(b), (0, None))
        self.assertEquals(RevisionSpec(1).in_history(b), (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('revno:1').in_history(b),
                          (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('revid:a@r-0-1').in_history(b),
                          (1, 'a@r-0-1'))
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('revid:a@r-0-0').in_history, b)
        self.assertRaises(TypeError, RevisionSpec, object)

        self.assertEquals(RevisionSpec('date:today').in_history(b),
                          (2, 'a@r-0-2'))
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('date:tomorrow').in_history, b)
        self.assertEquals(RevisionSpec('date:yesterday').in_history(b),
                          (1, 'a@r-0-1'))
        self.assertEquals(RevisionSpec('before:date:today').in_history(b),
                          (1, 'a@r-0-1'))

        self.assertEquals(RevisionSpec('last:1').in_history(b),
                          (3, 'a@r-0-3'))
        self.assertEquals(RevisionSpec('-1').in_history(b), (3, 'a@r-0-3'))
#        self.assertEquals(b.get_revision_info('last:1'), (3, 'a@r-0-3'))
#        self.assertEquals(b.get_revision_info('-1'), (3, 'a@r-0-3'))

        self.assertEquals(RevisionSpec('ancestor:.').in_history(b).rev_id,
                          'a@r-0-3')

        os.mkdir('newbranch')
        wt2 = self.make_branch_and_tree('newbranch')
        b2 = wt2.branch
        self.assertRaises(NoCommits, RevisionSpec('ancestor:.').in_history, b2)

        d3 = b.bzrdir.sprout('copy')
        b3 = d3.open_branch()
        wt3 = d3.open_workingtree()
        wt3.commit('Commit four', rev_id='b@r-0-4')
        self.assertEquals(RevisionSpec('ancestor:.').in_history(b3).rev_id,
                          'a@r-0-3')
        merge(['copy', -1], [None, None])
        wt.commit('Commit five', rev_id='a@r-0-4')
        self.assertEquals(RevisionSpec('ancestor:copy').in_history(b).rev_id,
                          'b@r-0-4')
        self.assertEquals(RevisionSpec('ancestor:.').in_history(b3).rev_id,
                          'b@r-0-4')

        # This should be in the revision store, but not in revision-history
        self.assertEquals((None, 'b@r-0-4'),
                RevisionSpec('revid:b@r-0-4').in_history(b))

    def test_branch_namespace(self):
        """Ensure that the branch namespace pulls in the requisite content."""
        self.build_tree(['branch1/', 'branch1/file', 'branch2/'])
        wt = self.make_branch_and_tree('branch1')
        branch = wt.branch
        wt.add(['file'])
        wt.commit('add file')
        d2 = branch.bzrdir.sprout('branch2')
        print >> open('branch2/file', 'w'), 'new content'
        branch2 = d2.open_branch()
        d2.open_workingtree().commit('update file', rev_id='A')
        spec = RevisionSpec('branch:./branch2/.bzr/../')
        rev_info = spec.in_history(branch)
        self.assertEqual(rev_info, (None, 'A'))

    def test_invalid_revno(self):
        self.build_tree(['branch1/', 'branch1/file'])
        wt = self.make_branch_and_tree('branch1')
        wt.add('file')
        wt.commit('first commit', rev_id='r1')
        wt.commit('second commit', rev_id='r2')

        # In the future -20 will probably just fall back to 0
        # but for now, we want to make sure it raises the right error
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('-20').in_history, wt.branch)
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('10').in_history, wt.branch)

        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('revno:-20').in_history, wt.branch)
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('revno:10').in_history, wt.branch)
        self.assertRaises(errors.InvalidRevisionSpec,
                          RevisionSpec('revno:a').in_history, wt.branch)
