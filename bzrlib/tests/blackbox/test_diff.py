# Copyright (C) 2005, 2006 Canonical Ltd
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


"""Black-box tests for bzr diff.
"""

import os
import re

import bzrlib
from bzrlib import workingtree
from bzrlib.branch import Branch
from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase


def subst_dates(string):
    """Replace date strings with constant values."""
    return re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [-\+]\d{4}',
                  'YYYY-MM-DD HH:MM:SS +ZZZZ', string)


class DiffBase(ExternalBase):
    """Base class with common setup method"""

    def make_example_branch(self):
        # FIXME: copied from test_too_much -- share elsewhere?
        tree = self.make_branch_and_tree('.')
        open('hello', 'wb').write('foo\n')
        tree.add(['hello'])
        tree.commit('setup')
        open('goodbye', 'wb').write('baz\n')
        tree.add(['goodbye'])
        tree.commit('setup')


class TestDiff(DiffBase):

    def test_diff(self):
        self.make_example_branch()
        file('hello', 'wt').write('hello world!')
        self.run_bzr('commit -m fixing hello')
        output = self.run_bzr('diff -r 2..3', retcode=1)[0]
        self.assert_('\n+hello world!' in output)
        output = self.run_bzr('diff -r last:3..last:1',
                retcode=1)[0]
        self.assert_('\n+baz' in output)
        self.build_tree(['moo'])
        self.run_bzr('add moo')
        os.unlink('moo')
        self.run_bzr('diff')

    def test_diff_prefix(self):
        """diff --prefix appends to filenames in output"""
        self.make_example_branch()
        file('hello', 'wb').write('hello world!\n')
        out, err = self.run_bzr('diff --prefix old/:new/', retcode=1)
        self.assertEquals(err, '')
        self.assertEqualDiff(subst_dates(out), '''\
=== modified file 'hello'
--- old/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ new/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -1,1 +1,1 @@
-foo
+hello world!

''')

    def test_diff_illegal_prefix_value(self):
        # There was an error in error reporting for this option
        out, err = self.run_bzr('diff --prefix old/', retcode=3)
        self.assertContainsRe(err,
            '--prefix expects two values separated by a colon')

    def test_diff_p1(self):
        """diff -p1 produces lkml-style diffs"""
        self.make_example_branch()
        file('hello', 'wb').write('hello world!\n')
        out, err = self.run_bzr('diff -p1', retcode=1)
        self.assertEquals(err, '')
        self.assertEqualDiff(subst_dates(out), '''\
=== modified file 'hello'
--- old/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ new/hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -1,1 +1,1 @@
-foo
+hello world!

''')

    def test_diff_p0(self):
        """diff -p0 produces diffs with no prefix"""
        self.make_example_branch()
        file('hello', 'wb').write('hello world!\n')
        out, err = self.run_bzr('diff -p0', retcode=1)
        self.assertEquals(err, '')
        self.assertEqualDiff(subst_dates(out), '''\
=== modified file 'hello'
--- hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
+++ hello\tYYYY-MM-DD HH:MM:SS +ZZZZ
@@ -1,1 +1,1 @@
-foo
+hello world!

''')

    def test_diff_nonexistent(self):
        # Get an error from a file that does not exist at all
        # (Malone #3619)
        self.make_example_branch()
        out, err = self.run_bzr('diff does-not-exist', retcode=3)
        self.assertContainsRe(err, 'not versioned.*does-not-exist')

    def test_diff_illegal_revision_specifiers(self):
        out, err = self.run_bzr('diff -r 1..23..123', retcode=3)
        self.assertContainsRe(err, 'one or two revision specifiers')

    def test_diff_unversioned(self):
        # Get an error when diffing a non-versioned file.
        # (Malone #3619)
        self.make_example_branch()
        self.build_tree(['unversioned-file'])
        out, err = self.run_bzr('diff unversioned-file', retcode=3)
        self.assertContainsRe(err, 'not versioned.*unversioned-file')

    # TODO: What should diff say for a file deleted in working tree?

    def example_branches(self):
        self.build_tree(['branch1/', 'branch1/file'], line_endings='binary')
        self.run_bzr(['init', 'branch1'])[0]
        self.run_bzr(['add', 'branch1/file'])[0]
        self.run_bzr(['commit', '-m', 'add file', 'branch1'])
        self.run_bzr(['branch', 'branch1', 'branch2'])[0]
        self.build_tree_contents([('branch2/file', 'new content\n')])
        self.run_bzr(['commit', '-m', 'update file', 'branch2'])

    def test_diff_branches(self):
        self.example_branches()
        # should open branch1 and diff against branch2, 
        out, err = self.run_bzr(['diff', '-r', 'branch:branch2', 
                                          'branch1'],
                                         retcode=1)
        self.assertEquals('', err)
        self.assertEquals("=== modified file 'file'\n"
                          "--- file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                          "+++ file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                          "@@ -1,1 +1,1 @@\n"
                          "-new content\n"
                          "+contents of branch1/file\n"
                          "\n", subst_dates(out))
        out, err = self.run_bzr(['diff', 'branch2', 'branch1'],
                                         retcode=1)
        self.assertEquals('', err)
        self.assertEqualDiff("=== modified file 'file'\n"
                              "--- file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                              "+++ file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                              "@@ -1,1 +1,1 @@\n"
                              "-new content\n"
                              "+contents of branch1/file\n"
                              "\n", subst_dates(out))

    def test_diff_revno_branches(self):
        self.example_branches()
        print >> open('branch2/file', 'wb'), 'even newer content'
        self.run_bzr(['commit', '-m', 
                               'update file once more', 'branch2'])

        out, err = self.run_bzr(['diff', '-r',
                                          'revno:1:branch2..revno:1:branch1'],
                                         retcode=0)
        self.assertEquals('', err)
        self.assertEquals('', out)
        out, err = self.run_bzr(['diff', '-r', 
                                          'revno:2:branch2..revno:1:branch1'],
                                         retcode=1)
        self.assertEquals('', err)
        self.assertEqualDiff("=== modified file 'file'\n"
                              "--- file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                              "+++ file\tYYYY-MM-DD HH:MM:SS +ZZZZ\n"
                              "@@ -1,1 +1,1 @@\n"
                              "-new content\n"
                              "+contents of branch1/file\n"
                              "\n", subst_dates(out))

    def example_branch2(self):
        self.build_tree(['branch1/', 'branch1/file1'], line_endings='binary')
        self.run_bzr(['init', 'branch1'])[0]
        self.run_bzr(['add', 'branch1/file1'])[0]
        print >> open('branch1/file1', 'wb'), 'original line'
        self.run_bzr(['commit', '-m', 'first commit', 'branch1'])
        
        print >> open('branch1/file1', 'wb'), 'repo line'
        self.run_bzr(['commit', '-m', 'second commit', 'branch1'])

    def test_diff_to_working_tree(self):
        self.example_branch2()
        
        print >> open('branch1/file1', 'wb'), 'new line'
        output = self.run_bzr(['diff', '-r', '1..', 'branch1'],
                                       retcode=1)
        self.assertTrue('\n-original line\n+new line\n' in output[0])

    def test_diff_across_rename(self):
        """The working tree path should always be considered for diffing"""
        self.make_example_branch()
        self.run_bzr('diff', '-r', '0..1', 'hello', retcode=1)
        wt = workingtree.WorkingTree.open_containing('.')[0]
        wt.rename_one('hello', 'hello1')
        self.run_bzr('diff', 'hello1', retcode=1)
        self.run_bzr('diff', '-r', '0..1', 'hello1', retcode=1)


class TestCheckoutDiff(TestDiff):

    def make_example_branch(self):
        super(TestCheckoutDiff, self).make_example_branch()
        self.run_bzr('checkout . checkout')
        os.chdir('checkout')

    def example_branch2(self):
        super(TestCheckoutDiff, self).example_branch2()
        os.mkdir('checkouts')
        self.run_bzr('checkout branch1 checkouts/branch1')
        os.chdir('checkouts')

    def example_branches(self):
        super(TestCheckoutDiff, self).example_branches()
        os.mkdir('checkouts')
        self.run_bzr('checkout branch1 checkouts/branch1')
        self.run_bzr('checkout branch2 checkouts/branch2')
        os.chdir('checkouts')


class TestDiffLabels(DiffBase):

    def test_diff_label_removed(self):
        super(TestDiffLabels, self).make_example_branch()
        self.run_bzr('remove hello')
        diff = self.run_bzr(['diff'], retcode=1)
        self.assertTrue("=== removed file 'hello'" in diff[0])

    def test_diff_label_added(self):
        super(TestDiffLabels, self).make_example_branch()
        file('barbar', 'wt').write('barbar')
        self.run_bzr('add barbar')
        diff = self.run_bzr(['diff'], retcode=1)
        self.assertTrue("=== added file 'barbar'" in diff[0])

    def test_diff_label_modified(self):
        super(TestDiffLabels, self).make_example_branch()
        file('hello', 'wt').write('barbar')
        diff = self.run_bzr(['diff'], retcode=1)
        self.assertTrue("=== modified file 'hello'" in diff[0])

    def test_diff_label_renamed(self):
        super(TestDiffLabels, self).make_example_branch()
        self.run_bzr('rename hello gruezi')
        diff = self.run_bzr(['diff'], retcode=1)
        self.assertTrue("=== renamed file 'hello' => 'gruezi'" in diff[0])


class TestExternalDiff(DiffBase):

    def test_external_diff(self):
        """Test that we can spawn an external diff process"""
        # We have to use run_bzr_subprocess, because we need to
        # test writing directly to stdout, (there was a bug in
        # subprocess.py that we had to workaround).
        # However, if 'diff' may not be available
        self.make_example_branch()
        orig_progress = os.environ.get('BZR_PROGRESS_BAR')
        try:
            os.environ['BZR_PROGRESS_BAR'] = 'none'
            out, err = self.run_bzr_subprocess('diff', '-r', '1',
                                               '--diff-options', '-ub',
                                               universal_newlines=True,
                                               retcode=None)
        finally:
            if orig_progress is None:
                del os.environ['BZR_PROGRESS_BAR']
            else:
                os.environ['BZR_PROGRESS_BAR'] = orig_progress
            
        if 'Diff is not installed on this machine' in err:
            raise TestSkipped("No external 'diff' is available")
        self.assertEqual('', err)
        # We have to skip the stuff in the middle, because it depends
        # on time.time()
        self.assertStartsWith(out, "=== added file 'goodbye'\n"
                                   "--- goodbye\t1970-01-01 00:00:00 +0000\n"
                                   "+++ goodbye\t")
        self.assertEndsWith(out, "\n@@ -0,0 +1 @@\n"
                                 "+baz\n\n")


class TestDiffOutput(DiffBase):

    def test_diff_output(self):
        # check that output doesn't mangle line-endings
        self.make_example_branch()
        file('hello', 'wb').write('hello world!\n')
        output = self.run_bzr_subprocess('diff', retcode=1)[0]
        self.assert_('\n+hello world!\n' in output)
