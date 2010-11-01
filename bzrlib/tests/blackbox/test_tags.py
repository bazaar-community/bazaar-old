# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests for commands related to tags"""

from bzrlib import (
    branchbuilder,
    bzrdir,
    tag,
    )
from bzrlib.branch import (
    Branch,
    )
from bzrlib.bzrdir import BzrDir
from bzrlib.tests import (
    script,
    TestCaseWithTransport,
    )
from bzrlib.repository import (
    Repository,
    )
from bzrlib.workingtree import WorkingTree


class TestTagging(TestCaseWithTransport):

    def test_tag_command_help(self):
        out, err = self.run_bzr('help tag')
        self.assertContainsRe(out, 'Create, remove or modify a tag')

    def test_cannot_tag_range(self):
        out, err = self.run_bzr('tag -r1..10 name', retcode=3)
        self.assertContainsRe(err,
            "Tags can only be placed on a single revision")

    def test_no_tag_name(self):
        out, err = self.run_bzr('tag -d branch', retcode=3)
        self.assertContainsRe(err, 'Please specify a tag name.')

    def test_automatic_tag_name(self):
        def get_tag_name(branch, revid):
            return "mytag"
        Branch.hooks.install_named_hook('automatic_tag_name',
            get_tag_name, 'get tag name')
        out, err = self.run_bzr('tag -d branch')
        self.assertContainsRe(out, 'Created tag mytag.')

    def test_tag_current_rev(self):
        t = self.make_branch_and_tree('branch')
        t.commit(allow_pointless=True, message='initial commit',
            rev_id='first-revid')
        # make a tag through the command line
        out, err = self.run_bzr('tag -d branch NEWTAG')
        self.assertContainsRe(out, 'Created tag NEWTAG.')
        # tag should be observable through the api
        self.assertEquals(t.branch.tags.get_tag_dict(),
                dict(NEWTAG='first-revid'))
        # can also create tags using -r
        self.run_bzr('tag -d branch tag2 -r1')
        self.assertEquals(t.branch.tags.lookup_tag('tag2'), 'first-revid')
        # regression test: make sure a unicode revision from the user
        # gets turned into a str object properly. The use of a unicode
        # object for the revid is intentional.
        self.run_bzr(['tag', '-d', 'branch', 'tag3', u'-rrevid:first-revid'])
        self.assertEquals(t.branch.tags.lookup_tag('tag3'), 'first-revid')
        # can also delete an existing tag
        out, err = self.run_bzr('tag --delete -d branch tag2')
        # cannot replace an existing tag normally
        out, err = self.run_bzr('tag -d branch NEWTAG', retcode=3)
        self.assertContainsRe(err, 'Tag NEWTAG already exists\\.')
        # ... but can if you use --force
        out, err = self.run_bzr('tag -d branch NEWTAG --force')

    def test_tag_delete_requires_name(self):
        out, err = self.run_bzr('tag -d branch', retcode=3)
        self.assertContainsRe(err, 'Please specify a tag name\\.')

    def test_branch_push_pull_merge_copies_tags(self):
        t = self.make_branch_and_tree('branch1')
        t.commit(allow_pointless=True, message='initial commit',
            rev_id='first-revid')
        b1 = t.branch
        b1.tags.set_tag('tag1', 'first-revid')
        # branching copies the tag across
        self.run_bzr('branch branch1 branch2')
        b2 = Branch.open('branch2')
        self.assertEquals(b2.tags.lookup_tag('tag1'), 'first-revid')
        # make a new tag and pull it
        b1.tags.set_tag('tag2', 'twa')
        self.run_bzr('pull -d branch2 branch1')
        self.assertEquals(b2.tags.lookup_tag('tag2'), 'twa')
        # make a new tag and push it
        b1.tags.set_tag('tag3', 'san')
        self.run_bzr('push -d branch1 branch2')
        self.assertEquals(b2.tags.lookup_tag('tag3'), 'san')
        # make a new tag and merge it
        t.commit(allow_pointless=True, message='second commit',
            rev_id='second-revid')
        t2 = WorkingTree.open('branch2')
        t2.commit(allow_pointless=True, message='commit in second')
        b1.tags.set_tag('tag4', 'second-revid')
        self.run_bzr('merge -d branch2 branch1')
        self.assertEquals(b2.tags.lookup_tag('tag4'), 'second-revid')
        # pushing to a new location copies the tag across
        self.run_bzr('push -d branch1 branch3')
        b3 = Branch.open('branch3')
        self.assertEquals(b3.tags.lookup_tag('tag1'), 'first-revid')

    def make_master_and_checkout(self):
        builder = self.make_branch_builder('master')
        builder.build_commit(message='Initial commit.', rev_id='rev-1')
        master = builder.get_branch()
        child = master.create_checkout(self.get_url('child'))
        return master, child

    def make_fork(self, branch):
        fork = branch.create_clone_on_transport(self.get_transport('fork'))
        builder = branchbuilder.BranchBuilder(branch=fork)
        builder.build_commit(message='Commit in fork.', rev_id='fork-1')
        return fork

    def test_commit_in_heavyweight_checkout_copies_tags_to_master(self):
        master, child = self.make_master_and_checkout()
        fork = self.make_fork(master)
        fork.tags.set_tag('new-tag', fork.last_revision())
        script.run_script(self, """
            $ cd child
            $ bzr merge ../fork
            $ bzr commit -m "Merge fork."
            2>Committing to: .../master/
            2>Committed revision 2.
            """)
        # Merge copied the tag to child and commit propagated it to master
        self.assertEqual(
            {'new-tag': fork.last_revision()}, child.branch.tags.get_tag_dict())
        self.assertEqual(
            {'new-tag': fork.last_revision()}, master.tags.get_tag_dict())

    def test_commit_in_heavyweight_checkout_reports_tag_conflict(self):
        master, child = self.make_master_and_checkout()
        fork = self.make_fork(master)
        fork.tags.set_tag('new-tag', fork.last_revision())
        master_r1 = master.last_revision()
        master.tags.set_tag('new-tag', master_r1)
        script.run_script(self, """
            $ cd child
            $ bzr merge ../fork
            $ bzr commit -m "Merge fork."
            2>Committing to: .../master/
            2>Conflicting tags in bound branch:
            2>    new-tag
            2>Committed revision 2.
            """)
        # Merge copied the tag to child.  master's conflicting tag is unchanged.
        self.assertEqual(
            {'new-tag': fork.last_revision()}, child.branch.tags.get_tag_dict())
        self.assertEqual(
            {'new-tag': master_r1}, master.tags.get_tag_dict())

    def test_list_tags(self):
        tree1 = self.make_branch_and_tree('branch1')
        tree1.commit(allow_pointless=True, message='revision 1',
                rev_id='revid-1', timestamp=10)
        tree1.commit(allow_pointless=True, message='revision 2',
                rev_id='revid-2', timestamp=15)

        b1 = tree1.branch
        # note how the tag for revid-1 sorts after the one for revid-2
        b1.tags.set_tag(u'tagA\u30d0', 'revid-2')
        b1.tags.set_tag(u'tagB\u30d0', 'missing') # not present in repository
        b1.tags.set_tag(u'tagC\u30d0', 'revid-1')

        # lexicographical order
        out, err = self.run_bzr('tags -d branch1', encoding='utf-8')
        self.assertEquals(err, '')
        self.assertContainsRe(out, (u'^tagA\u30d0  *2\ntagB\u30d0  *\\?\n' +
            u'tagC\u30d0 *1\n').encode('utf-8'))

        out, err = self.run_bzr('tags --show-ids -d branch1', encoding='utf-8')
        self.assertEquals(err, '')
        self.assertContainsRe(out, (u'^tagA\u30d0  *revid-2\n' +
            u'tagB\u30d0  *missing\ntagC\u30d0 *revid-1\n').encode('utf-8'))

        # chronological order
        out, err = self.run_bzr('tags --sort=time -d branch1',
                encoding='utf-8')
        self.assertEquals(err, '')
        self.assertContainsRe(out, (u'^tagC\u30d0  *1\ntagA\u30d0  *2\n' +
            u'tagB\u30d0 *\\?\n').encode('utf-8'))

        out, err = self.run_bzr('tags --sort=time --show-ids -d branch1',
                encoding='utf-8')
        self.assertEquals(err, '')
        self.assertContainsRe(out, (u'^tagC\u30d0  *revid-1\n' +
            u'tagA\u30d0  *revid-2\ntagB\u30d0 *missing\n').encode('utf-8'))

        # now test dotted revnos
        tree2 = tree1.bzrdir.sprout('branch2').open_workingtree()
        tree1.commit(allow_pointless=True, message='revision 3 in branch1',
                rev_id='revid-3a')
        tree2.commit(allow_pointless=True, message='revision 3 in branch2',
                rev_id='revid-3b')

        b2 = tree2.branch
        b2.tags.set_tag('tagD', 'revid-3b')
        self.run_bzr('merge -d branch1 branch2')
        tree1.commit('merge', rev_id='revid-4')

        out, err = self.run_bzr('tags -d branch1', encoding='utf-8')
        self.assertEquals(err, '')
        self.assertContainsRe(out, r'tagD  *2\.1\.1\n')
        out, err = self.run_bzr('tags -d branch2', encoding='utf-8')
        self.assertEquals(err, '')
        self.assertContainsRe(out, r'tagD  *3\n')

    def test_list_tags_revision_filtering(self):
        tree1 = self.make_branch_and_tree('.')
        tree1.commit(allow_pointless=True, message='revision 1',
                rev_id='revid-1')
        tree1.commit(allow_pointless=True, message='revision 2',
                rev_id='revid-2')
        tree1.commit(allow_pointless=True, message='revision 3',
                rev_id='revid-3')
        tree1.commit(allow_pointless=True, message='revision 4',
                rev_id='revid-4')
        b1 = tree1.branch
        b1.tags.set_tag(u'tag 1', 'revid-1')
        b1.tags.set_tag(u'tag 2', 'revid-2')
        b1.tags.set_tag(u'tag 3', 'revid-3')
        b1.tags.set_tag(u'tag 4', 'revid-4')
        self._check_tag_filter('', (1, 2, 3, 4))
        self._check_tag_filter('-r ..', (1, 2, 3, 4))
        self._check_tag_filter('-r ..2', (1, 2))
        self._check_tag_filter('-r 2..', (2, 3, 4))
        self._check_tag_filter('-r 2..3', (2, 3))
        self._check_tag_filter('-r 3..2', ())
        self.run_bzr_error(args="tags -r 123",
            error_regexes=["bzr: ERROR: Requested revision: '123' "
                "does not exist in branch:"])
        self.run_bzr_error(args="tags -r ..123",
            error_regexes=["bzr: ERROR: Requested revision: '123' "
                "does not exist in branch:"])
        self.run_bzr_error(args="tags -r 123.123",
            error_regexes=["bzr: ERROR: Requested revision: '123.123' "
                "does not exist in branch:"])

    def _check_tag_filter(self, argstr, expected_revnos):
        #upper bound of laziness
        out, err = self.run_bzr('tags ' + argstr)
        self.assertEquals(err, '')
        self.assertContainsRe(out, "^" + ''.join(["tag %s +%s\n" % (
            revno, revno) for revno in expected_revnos]) + "$")

    def test_conflicting_tags(self):
        # setup two empty branches with different tags
        t1 = self.make_branch_and_tree('one')
        t2 = self.make_branch_and_tree('two')
        b1 = t1.branch
        b2 = t2.branch
        tagname = u'\u30d0zaar'
        b1.tags.set_tag(tagname, 'revid1')
        b2.tags.set_tag(tagname, 'revid2')
        # push should give a warning about the tags
        out, err = self.run_bzr('push -d one two', encoding='utf-8')
        self.assertContainsRe(out,
                'Conflicting tags:\n.*' + tagname.encode('utf-8'))
        # pull should give a warning about the tags
        out, err = self.run_bzr('pull -d one two', encoding='utf-8')
        self.assertContainsRe(out,
                'Conflicting tags:\n.*' + tagname.encode('utf-8'))
        # merge should give a warning about the tags -- not implemented yet
        ## out, err = self.run_bzr('merge -d one two', encoding='utf-8')
        ## self.assertContainsRe(out,
        ##         'Conflicting tags:\n.*' + tagname.encode('utf-8'))
