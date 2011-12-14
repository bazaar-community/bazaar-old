# Copyright (C) 2006-2011 Canonical Ltd
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

"""Black-box tests for repositories with shared branches"""

import os

from bzrlib.bzrdir import BzrDir, BzrDirMetaFormat1
import bzrlib.errors as errors
from bzrlib.tests import TestCaseInTempDir

class TestSharedRepo(TestCaseInTempDir):

    def test_make_repository(self):
        out, err = self.run_bzr("init-repository a")
        self.assertEqual(out,
"""Shared repository with trees (format: 2a)
Location:
  shared repository: a
""")
        self.assertEqual(err, "")
        dir = BzrDir.open('a')
        self.assertIs(dir.open_repository().is_shared(), True)
        self.assertRaises(errors.NotBranchError, dir.open_branch)
        self.assertRaises(errors.NoWorkingTree, dir.open_workingtree)

    def test_make_repository_quiet(self):
        out, err = self.run_bzr("init-repository a -q")
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        dir = BzrDir.open('a')
        self.assertIs(dir.open_repository().is_shared(), True)
        self.assertRaises(errors.NotBranchError, dir.open_branch)
        self.assertRaises(errors.NoWorkingTree, dir.open_workingtree)

    def test_init_repo_existing_dir(self):
        """Make repo in existing directory.

        (Malone #38331)
        """
        out, err = self.run_bzr("init-repository .")
        dir = BzrDir.open('.')
        self.assertTrue(dir.open_repository())

    def test_init(self):
        self.run_bzr("init-repo a")
        self.run_bzr("init --format=default a/b")
        dir = BzrDir.open('a')
        self.assertIs(dir.open_repository().is_shared(), True)
        self.assertRaises(errors.NotBranchError, dir.open_branch)
        self.assertRaises(errors.NoWorkingTree, dir.open_workingtree)
        bdir = BzrDir.open('a/b')
        bdir.open_branch()
        self.assertRaises(errors.NoRepositoryPresent, bdir.open_repository)
        wt = bdir.open_workingtree()

    def test_branch(self):
        self.run_bzr("init-repo a")
        self.run_bzr("init --format=default a/b")
        self.run_bzr('branch a/b a/c')
        cdir = BzrDir.open('a/c')
        cdir.open_branch()
        self.assertRaises(errors.NoRepositoryPresent, cdir.open_repository)
        cdir.open_workingtree()

    def test_branch_tree(self):
        self.run_bzr("init-repo --trees a")
        self.run_bzr("init --format=default b")
        file('b/hello', 'wt').write('bar')
        self.run_bzr("add b/hello")
        self.run_bzr("commit -m bar b/hello")

        self.run_bzr('branch b a/c')
        cdir = BzrDir.open('a/c')
        cdir.open_branch()
        self.assertRaises(errors.NoRepositoryPresent, cdir.open_repository)
        self.assertPathExists('a/c/hello')
        cdir.open_workingtree()

    def test_trees_default(self):
        # 0.15 switched to trees by default
        self.run_bzr("init-repo repo")
        repo = BzrDir.open("repo").open_repository()
        self.assertEqual(True, repo.make_working_trees())

    def test_trees_argument(self):
        # Supplying the --trees argument should be harmless,
        # as it was previously non-default we need to get it right.
        self.run_bzr("init-repo --trees trees")
        repo = BzrDir.open("trees").open_repository()
        self.assertEqual(True, repo.make_working_trees())

    def test_no_trees_argument(self):
        # --no-trees should make it so that there is no working tree
        self.run_bzr("init-repo --no-trees notrees")
        repo = BzrDir.open("notrees").open_repository()
        self.assertEqual(False, repo.make_working_trees())

    def test_init_repo_smart_acceptance(self):
        # The amount of hpss calls made on init-repo to a smart server should
        # be fixed.
        self.setup_smart_server_with_call_log()
        self.run_bzr(['init-repo', self.get_url('repo')])
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(13, self.hpss_calls)

    def test_notification_on_branch_from_repository(self):
        out, err = self.run_bzr("init-repository -q a")
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        dir = BzrDir.open('a')
        dir.open_repository() # there is a repository there
        e = self.assertRaises(errors.NotBranchError, dir.open_branch)
        self.assertContainsRe(str(e), "location is a repository")

    def test_notification_on_branch_from_nonrepository(self):
        fmt = BzrDirMetaFormat1()
        t = self.get_transport()
        t.mkdir('a')
        dir = fmt.initialize_on_transport(t.clone('a'))
        self.assertRaises(errors.NoRepositoryPresent, dir.open_repository)
        e = self.assertRaises(errors.NotBranchError, dir.open_branch)
        self.assertNotContainsRe(str(e), "location is a repository")

    def test_init_repo_with_post_repo_init_hook(self):
        calls = []
        BzrDir.hooks.install_named_hook('post_repo_init', calls.append, None)
        self.assertLength(0, calls)
        self.run_bzr("init-repository a")
        self.assertLength(1, calls)

    def test_init_repo_without_username(self):
        """Ensure init-repo works if username is not set.
        """
        # bzr makes user specified whoami mandatory for operations
        # like commit as whoami is recorded. init-repo however is not so final
        # and uses whoami only in a lock file. Without whoami the login name
        # is used. This test is to ensure that init-repo passes even when whoami
        # is not available.
        self.overrideEnv('EMAIL', None)
        self.overrideEnv('BZR_EMAIL', None)
        out, err = self.run_bzr(['init-repo', 'foo'])
        self.assertEqual(err, '')
        self.assertTrue(os.path.exists('foo'))
