# Copyright (C) 2005, 2006, 2007, 2009, 2011, 2012, 2016 Canonical Ltd
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

from bzrlib import tests
from bzrlib.tests.matchers import ContainsNoVfsCalls


class TestRevno(tests.TestCaseWithTransport):

    def test_revno(self):

        def bzr(*args, **kwargs):
            return self.run_bzr(*args, **kwargs)[0]

        os.mkdir('a')
        os.chdir('a')
        bzr('init')
        self.assertEqual(int(bzr('revno')), 0)

        with open('foo', 'wb') as f: f.write('foo\n')
        bzr('add foo')
        bzr('commit -m foo')
        self.assertEqual(int(bzr('revno')), 1)

        os.mkdir('baz')
        bzr('add baz')
        bzr('commit -m baz')
        self.assertEqual(int(bzr('revno')), 2)

        os.chdir('..')
        self.assertEqual(int(bzr('revno a')), 2)
        self.assertEqual(int(bzr('revno a/baz')), 2)

    def test_revno_tree(self):
        # Make branch and checkout
        wt = self.make_branch_and_tree('branch')
        checkout = wt.branch.create_checkout('checkout', lightweight=True)

        # Get the checkout out of date
        self.build_tree(['branch/file'])
        wt.add(['file'])
        wt.commit('mkfile')

        # Make sure revno says we're on 1
        out,err = self.run_bzr('revno checkout')
        self.assertEqual('', err)
        self.assertEqual('1\n', out)

        # Make sure --tree knows it's still on 0
        out,err = self.run_bzr('revno --tree checkout')
        self.assertEqual('', err)
        self.assertEqual('0\n', out)

    def test_revno_tree_no_tree(self):
        # Make treeless branch
        b = self.make_branch('branch')

        # Try getting it's --tree revno
        out,err = self.run_bzr('revno --tree branch', retcode=3)
        self.assertEqual('', out)
        self.assertEqual('bzr: ERROR: No WorkingTree exists for "branch".\n',
            err)

    def test_dotted_revno_tree(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'content\n'))])
        builder.build_snapshot('B-id', ['A-id'], [])
        builder.build_snapshot('C-id', ['A-id', 'B-id'], [])
        builder.finish_series()
        b = builder.get_branch()
        co_b = b.create_checkout('checkout_b', lightweight=True,
                                 revision_id='B-id')
        out, err = self.run_bzr('revno checkout_b')
        self.assertEqual('', err)
        self.assertEqual('2\n', out)
        out, err = self.run_bzr('revno --tree checkout_b')
        self.assertEqual('', err)
        self.assertEqual('1.1.1\n', out)

    def test_stale_revno_tree(self):
        builder = self.make_branch_builder('branch')
        builder.start_series()
        builder.build_snapshot('A-id', None, [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'content\n'))])
        builder.build_snapshot('B-id', ['A-id'], [])
        builder.build_snapshot('C-id', ['A-id'], [])
        builder.finish_series()
        b = builder.get_branch()
        # The branch is now at "C-id", but the checkout is still at "B-id"
        # which is no longer in the history
        co_b = b.create_checkout('checkout_b', lightweight=True,
                                 revision_id='B-id')
        out, err = self.run_bzr('revno checkout_b')
        self.assertEqual('', err)
        self.assertEqual('2\n', out)
        out, err = self.run_bzr('revno --tree checkout_b')
        self.assertEqual('', err)
        self.assertEqual('???\n', out)

    def test_revno_with_revision(self):
        wt = self.make_branch_and_tree('.')
        revid1 = wt.commit('rev1')
        revid2 = wt.commit('rev2')

        out, err = self.run_bzr('revno -r-2 .')
        self.assertEqual('1\n', out)

        out, err = self.run_bzr('revno -rrevid:%s .' % revid1)
        self.assertEqual('1\n', out)

    def test_revno_and_tree_mutually_exclusive(self):
        wt = self.make_branch_and_tree('.')
        out, err = self.run_bzr('revno -r-2 --tree .', retcode=3)
        self.assertEqual('', out)
        self.assertEqual(
            'bzr: ERROR: --tree and --revision can not be used together\n',
            err)


class TestSmartServerRevno(tests.TestCaseWithTransport):

    def test_simple_branch_revno(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/foo', 'thecontents')])
        t.add("foo")
        revid = t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(['revno', self.get_url('branch')])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
        self.assertLength(1, self.hpss_connections)
        self.assertLength(6, self.hpss_calls)

    def test_simple_branch_revno_lookup(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/foo', 'thecontents')])
        t.add("foo")
        revid1 = t.commit("message")
        revid2 = t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(['revno', '-rrevid:' + revid1,
            self.get_url('branch')])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(5, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
