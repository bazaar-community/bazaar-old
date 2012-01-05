# Copyright (C) 2005-2012 Canonical Ltd
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


"""Black-box tests for bzr cat.
"""

from bzrlib import tests
from bzrlib.tests.matchers import ContainsNoVfsCalls
from bzrlib.transport import memory


class TestCat(tests.TestCaseWithTransport):

    def test_cat(self):
        tree = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/a', 'foo\n')])
        tree.add('a')
        # 'bzr cat' without an option should cat the last revision
        self.run_bzr(['cat', 'a'], retcode=3, working_dir='branch')

        tree.commit(message='1')
        self.build_tree_contents([('branch/a', 'baz\n')])

        self.assertEquals('foo\n',
                          self.run_bzr(['cat', 'a'], working_dir='branch')[0])

        # On Windows, we used to have a bug where newlines got changed into
        # crlf, whereas cat ought to write out the file exactly as it's
        # recorded (by default.)  That problem can't be reproduced in-process,
        # so we need just one test here that 
        self.assertEquals('foo\n',
                          self.run_bzr_subprocess(['cat', 'a'],
                                                  working_dir='branch')[0])

        tree.commit(message='2')
        self.assertEquals(
            'baz\n', self.run_bzr(['cat', 'a'], working_dir='branch')[0])
        self.assertEquals(
            'foo\n', self.run_bzr(['cat', 'a', '-r', '1'],
                                  working_dir='branch')[0])
        self.assertEquals(
            'baz\n', self.run_bzr(['cat', 'a', '-r', '-1'],
                                  working_dir='branch')[0])

        rev_id = tree.branch.last_revision()

        self.assertEquals(
            'baz\n', self.run_bzr(['cat', 'a', '-r', 'revid:%s' % rev_id],
                                  working_dir='branch')[0])

        self.assertEquals('foo\n',
                          self.run_bzr(['cat', 'branch/a',
                                        '-r', 'revno:1:branch'])[0])
        self.run_bzr(['cat', 'a'], retcode=3)
        self.run_bzr(['cat', 'a', '-r', 'revno:1:branch-that-does-not-exist'],
                     retcode=3)

    def test_cat_different_id(self):
        """'cat' works with old and new files"""
        self.disable_missing_extensions_warning()
        tree = self.make_branch_and_tree('.')
        # the files are named after their path in the revision and
        # current trees later in the test case
        # a-rev-tree is special because it appears in both the revision
        # tree and the working tree
        self.build_tree_contents([('a-rev-tree', 'foo\n'),
            ('c-rev', 'baz\n'), ('d-rev', 'bar\n'), ('e-rev', 'qux\n')])
        tree.lock_write()
        try:
            tree.add(['a-rev-tree', 'c-rev', 'd-rev', 'e-rev'])
            tree.commit('add test files', rev_id='first')
            # remove currently uses self._write_inventory -
            # work around that for now.
            tree.flush()
            tree.remove(['d-rev'])
            tree.rename_one('a-rev-tree', 'b-tree')
            tree.rename_one('c-rev', 'a-rev-tree')
            tree.rename_one('e-rev', 'old-rev')
            self.build_tree_contents([('e-rev', 'new\n')])
            tree.add(['e-rev'])
        finally:
            # calling bzr as another process require free lock on win32
            tree.unlock()

        # 'b-tree' is not present in the old tree.
        self.run_bzr_error(["^bzr: ERROR: u?'b-tree' "
                            "is not present in revision .+$"],
                           'cat b-tree --name-from-revision')

        # get to the old file automatically
        out, err = self.run_bzr('cat d-rev')
        self.assertEqual('bar\n', out)
        self.assertEqual('', err)

        out, err = \
                self.run_bzr('cat a-rev-tree --name-from-revision')
        self.assertEqual('foo\n', out)
        self.assertEqual('', err)

        out, err = self.run_bzr('cat a-rev-tree')
        self.assertEqual('baz\n', out)
        self.assertEqual('', err)

        # the actual file-id for e-rev doesn't exist in the old tree
        out, err = self.run_bzr('cat e-rev -rrevid:first')
        self.assertEqual('qux\n', out)
        self.assertEqual('', err)

    def test_remote_cat(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['README'])
        wt.add('README')
        wt.commit('Making sure there is a basis_tree available')

        url = self.get_readonly_url() + '/README'
        out, err = self.run_bzr(['cat', url])
        self.assertEqual('contents of README\n', out)

    def test_cat_branch_revspec(self):
        wt = self.make_branch_and_tree('a')
        self.build_tree(['a/README'])
        wt.add('README')
        wt.commit('Making sure there is a basis_tree available')
        wt = self.make_branch_and_tree('b')

        out, err = self.run_bzr(['cat', '-r', 'branch:../a', 'README'],
                                working_dir='b')
        self.assertEqual('contents of a/README\n', out)

    def test_cat_filters(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['README'])
        wt.add('README')
        wt.commit('Making sure there is a basis_tree available')
        url = self.get_readonly_url() + '/README'

        # Test unfiltered output
        out, err = self.run_bzr(['cat', url])
        self.assertEqual('contents of README\n', out)

        # Test --filters option is legal but has no impact if no filters
        out, err = self.run_bzr(['cat', '--filters', url])
        self.assertEqual('contents of README\n', out)

    def test_cat_filters_applied(self):
        # Test filtering applied to output. This is tricky to do in a
        # subprocess because we really need to patch in a plugin that
        # registers the filters. Instead, we patch in a custom
        # filter_stack and use run_bzr() ...
        from cStringIO import StringIO
        from bzrlib.commands import run_bzr
        from bzrlib.tests.test_filters import _stack_2
        from bzrlib.trace import mutter
        from bzrlib.tree import Tree
        wt = self.make_branch_and_tree('.')
        self.build_tree_contents([
            ('README', "junk\nline 1 of README\nline 2 of README\n"),
            ])
        wt.add('README')
        wt.commit('Making sure there is a basis_tree available')
        url = self.get_readonly_url() + '/README'
        real_content_filter_stack = Tree._content_filter_stack
        def _custom_content_filter_stack(tree, path=None, file_id=None):
            return _stack_2
        Tree._content_filter_stack = _custom_content_filter_stack
        try:
            out, err = self.run_bzr(['cat', url, '--filters'])
            # The filter stack will remove the first line and swapcase the rest
            self.assertEqual('LINE 1 OF readme\nLINE 2 OF readme\n', out)
            self.assertEqual('', err)
        finally:
            Tree._content_filter_stack = real_content_filter_stack

    def test_cat_no_working_tree(self):
        wt = self.make_branch_and_tree('.')
        self.build_tree(['README'])
        wt.add('README')
        wt.commit('Making sure there is a basis_tree available')
        wt.branch.bzrdir.destroy_workingtree()

        url = self.get_readonly_url() + '/README'
        out, err = self.run_bzr(['cat', url])
        self.assertEqual('contents of README\n', out)

    def test_cat_nonexistent_branch(self):
        self.vfs_transport_factory = memory.MemoryServer
        self.run_bzr_error(['^bzr: ERROR: Not a branch'],
                           ['cat', self.get_url()])

    def test_cat_directory(self):
        wt = self.make_branch_and_tree('a')
        self.build_tree(['a/README'])
        wt.add('README')
        wt.commit('Making sure there is a basis_tree available')

        out, err = self.run_bzr(['cat', '--directory=a', 'README'])
        self.assertEqual('contents of a/README\n', out)

    def test_cat_remote_directory(self):
        wt = self.make_branch_and_tree('a')
        self.build_tree(['a/README'])
        wt.add('README')
        wt.commit('Making sure there is a basis_tree available')

        url = self.get_readonly_url() + '/a'
        out, err = self.run_bzr(['cat', '-d', url, 'README'])
        self.assertEqual('contents of a/README\n', out)


class TestSmartServerCat(tests.TestCaseWithTransport):

    def test_simple_branch_cat(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('branch')
        self.build_tree_contents([('branch/foo', 'thecontents')])
        t.add("foo")
        t.commit("message")
        self.reset_smart_call_log()
        out, err = self.run_bzr(['cat', "%s/foo" % self.get_url('branch')])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(9, self.hpss_calls)
        self.assertLength(1, self.hpss_connections)
        self.assertThat(self.hpss_calls, ContainsNoVfsCalls)
