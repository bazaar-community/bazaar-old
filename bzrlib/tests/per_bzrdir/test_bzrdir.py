# Copyright (C) 2006-2010 Canonical Ltd
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

"""Tests for bzrdir implementations - tests a bzrdir format."""

import errno
from stat import S_ISDIR

import bzrlib.branch
from bzrlib import (
    errors,
    revision as _mod_revision,
    )

from bzrlib.tests.per_bzrdir import TestCaseWithBzrDir


class TestBzrDir(TestCaseWithBzrDir):

    # Many of these tests test for disk equality rather than checking
    # for semantic equivalence. This works well for some tests but
    # is not good at handling changes in representation or the addition
    # or removal of control data. It would be nice to for instance:
    # sprout a new branch, check that the nickname has been reset by hand
    # and then set the nickname to match the source branch, at which point
    # a semantic equivalence should pass

    def assertDirectoriesEqual(self, source, target, ignore_list=[]):
        """Assert that the content of source and target are identical.

        paths in ignore list will be completely ignored.

        We ignore paths that represent data which is allowed to change during
        a clone or sprout: for instance, inventory.knit contains gzip fragements
        which have timestamps in them, and as we have read the inventory from
        the source knit, the already-read data is recompressed rather than
        reading it again, which leads to changed timestamps. This is ok though,
        because the inventory.kndx file is not ignored, and the integrity of
        knit joins is tested by test_knit and test_versionedfile.

        :seealso: Additionally, assertRepositoryHasSameItems provides value
            rather than representation checking of repositories for
            equivalence.
        """
        files = []
        directories = ['.']
        while directories:
            dir = directories.pop()
            for path in set(source.list_dir(dir) + target.list_dir(dir)):
                path = dir + '/' + path
                if path in ignore_list:
                    continue
                try:
                    stat = source.stat(path)
                except errors.NoSuchFile:
                    self.fail('%s not in source' % path)
                if S_ISDIR(stat.st_mode):
                    self.assertTrue(S_ISDIR(target.stat(path).st_mode))
                    directories.append(path)
                else:
                    self.assertEqualDiff(source.get(path).read(),
                                         target.get(path).read(),
                                         "text for file %r differs:\n" % path)

    def assertRepositoryHasSameItems(self, left_repo, right_repo):
        """require left_repo and right_repo to contain the same data."""
        # XXX: TODO: Doesn't work yet, because we need to be able to compare
        # local repositories to remote ones...  but this is an as-yet unsolved
        # aspect of format management and the Remote protocols...
        # self.assertEqual(left_repo._format.__class__,
        #     right_repo._format.__class__)
        left_repo.lock_read()
        try:
            right_repo.lock_read()
            try:
                # revs
                all_revs = left_repo.all_revision_ids()
                self.assertEqual(left_repo.all_revision_ids(),
                    right_repo.all_revision_ids())
                for rev_id in left_repo.all_revision_ids():
                    self.assertEqual(left_repo.get_revision(rev_id),
                        right_repo.get_revision(rev_id))
                # Assert the revision trees (and thus the inventories) are equal
                sort_key = lambda rev_tree: rev_tree.get_revision_id()
                rev_trees_a = sorted(
                    left_repo.revision_trees(all_revs), key=sort_key)
                rev_trees_b = sorted(
                    right_repo.revision_trees(all_revs), key=sort_key)
                for tree_a, tree_b in zip(rev_trees_a, rev_trees_b):
                    self.assertEqual([], list(tree_a.iter_changes(tree_b)))
                # texts
                text_index = left_repo._generate_text_key_index()
                self.assertEqual(text_index,
                    right_repo._generate_text_key_index())
                desired_files = []
                for file_id, revision_id in text_index.iterkeys():
                    desired_files.append(
                        (file_id, revision_id, (file_id, revision_id)))
                left_texts = list(left_repo.iter_files_bytes(desired_files))
                right_texts = list(right_repo.iter_files_bytes(desired_files))
                left_texts.sort()
                right_texts.sort()
                self.assertEqual(left_texts, right_texts)
                # signatures
                for rev_id in all_revs:
                    try:
                        left_text = left_repo.get_signature_text(rev_id)
                    except errors.NoSuchRevision:
                        continue
                    right_text = right_repo.get_signature_text(rev_id)
                    self.assertEqual(left_text, right_text)
            finally:
                right_repo.unlock()
        finally:
            left_repo.unlock()

    def test_clone_bzrdir_repository_under_shared_force_new_repo(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        repo.fetch(tree.branch.repository)
        self.assertTrue(repo.has_revision('1'))
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        target = dir.clone(self.get_url('target/child'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository, repo)

    def test_clone_bzrdir_branch_and_repo(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.branch.copy_content_into(source)
        dir = source.bzrdir
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    [
                                     './.bzr/basis-inventory-cache',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/merge-hashes',
                                     './.bzr/repository',
                                     './.bzr/stat-cache',
                                    ])
        self.assertRepositoryHasSameItems(
            tree.branch.repository, target.open_repository())

    def test_clone_on_transport(self):
        a_dir = self.make_bzrdir('source')
        target_transport = a_dir.root_transport.clone('..').clone('target')
        target = a_dir.clone_on_transport(target_transport)
        self.assertNotEqual(a_dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(a_dir.root_transport, target.root_transport,
                                    ['./.bzr/merge-hashes'])

    def test_clone_bzrdir_empty(self):
        dir = self.make_bzrdir('source')
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/merge-hashes'])

    def test_clone_bzrdir_empty_force_new_ignored(self):
        # the force_new_repo parameter should have no effect on an empty
        # bzrdir's clone logic
        dir = self.make_bzrdir('source')
        target = dir.clone(self.get_url('target'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/merge-hashes'])

    def test_clone_bzrdir_repository(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        repo.fetch(tree.branch.repository)
        self.assertTrue(repo.has_revision('1'))
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    [
                                     './.bzr/merge-hashes',
                                     './.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository,
            target.open_repository())

    def test_clone_bzrdir_tree_branch_repo(self):
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        dir = tree.bzrdir
        target = dir.clone(self.get_url('target'))
        self.skipIfNoWorkingTree(target)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache',
                                     './.bzr/checkout/dirstate',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/checkout/merge-hashes',
                                     './.bzr/merge-hashes',
                                     './.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository,
            target.open_repository())
        target.open_workingtree().revert()

    def test_revert_inventory(self):
        tree = self.make_branch_and_tree('source')
        self.build_tree(['source/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        dir = tree.bzrdir
        target = dir.clone(self.get_url('target'))
        self.skipIfNoWorkingTree(target)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache',
                                     './.bzr/checkout/dirstate',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/checkout/merge-hashes',
                                     './.bzr/merge-hashes',
                                     './.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository,
            target.open_repository())

        target.open_workingtree().revert()
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache',
                                     './.bzr/checkout/dirstate',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/checkout/merge-hashes',
                                     './.bzr/merge-hashes',
                                     './.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository,
            target.open_repository())

    def test_clone_bzrdir_tree_branch_reference(self):
        # a tree with a branch reference (aka a checkout)
        # should stay a checkout on clone.
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                target_branch=referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        self.createWorkingTreeOrSkip(dir)
        target = dir.clone(self.get_url('target'))
        self.skipIfNoWorkingTree(target)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/stat-cache',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/checkout/merge-hashes',
                                     './.bzr/merge-hashes',
                                     './.bzr/repository/inventory.knit',
                                     ])

    def test_clone_bzrdir_branch_and_repo_into_shared_repo_force_new_repo(self):
        # by default cloning into a shared repo uses the shared repo.
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.branch.copy_content_into(source)
        try:
            self.make_repository('target', shared=True)
        except errors.IncompatibleFormat:
            return
        dir = source.bzrdir
        target = dir.clone(self.get_url('target/child'), force_new_repo=True)
        self.assertNotEqual(dir.transport.base, target.transport.base)
        repo = target.open_repository()
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    ['./.bzr/repository',
                                     ])
        self.assertRepositoryHasSameItems(tree.branch.repository, repo)

    def test_clone_bzrdir_branch_reference(self):
        # cloning should preserve the reference status of the branch in a bzrdir
        referenced_branch = self.make_branch('referencced')
        dir = self.make_bzrdir('source')
        try:
            reference = bzrlib.branch.BranchReferenceFormat().initialize(dir,
                target_branch=referenced_branch)
        except errors.IncompatibleFormat:
            # this is ok too, not all formats have to support references.
            return
        target = dir.clone(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport)

    def test_sprout_bzrdir_repository(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1', rev_id='1')
        dir = self.make_bzrdir('source')
        repo = dir.create_repository()
        repo.fetch(tree.branch.repository)
        self.assertTrue(repo.has_revision('1'))
        try:
            self.assertTrue(
                _mod_revision.is_null(_mod_revision.ensure_null(
                dir.open_branch().last_revision())))
        except errors.NotBranchError:
            pass
        target = dir.sprout(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        # testing inventory isn't reasonable for repositories
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    [
                                     './.bzr/branch',
                                     './.bzr/checkout',
                                     './.bzr/inventory',
                                     './.bzr/parent',
                                     './.bzr/repository/inventory.knit',
                                     ])
        try:
            local_inventory = dir.transport.local_abspath('inventory')
        except errors.NotLocalUrl:
            return
        try:
            # If we happen to have a tree, we'll guarantee everything
            # except for the tree root is the same.
            inventory_f = file(local_inventory, 'rb')
            self.addCleanup(inventory_f.close)
            self.assertContainsRe(inventory_f.read(),
                                  '<inventory format="5">\n</inventory>\n')
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise

    def test_sprout_bzrdir_branch_and_repo(self):
        tree = self.make_branch_and_tree('commit_tree')
        self.build_tree(['commit_tree/foo'])
        tree.add('foo')
        tree.commit('revision 1')
        source = self.make_branch('source')
        tree.branch.repository.copy_content_into(source.repository)
        tree.bzrdir.open_branch().copy_content_into(source)
        dir = source.bzrdir
        target = dir.sprout(self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        target_repo = target.open_repository()
        self.assertRepositoryHasSameItems(source.repository, target_repo)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    [
                                     './.bzr/basis-inventory-cache',
                                     './.bzr/branch/branch.conf',
                                     './.bzr/branch/parent',
                                     './.bzr/checkout',
                                     './.bzr/checkout/inventory',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/inventory',
                                     './.bzr/parent',
                                     './.bzr/repository',
                                     './.bzr/stat-cache',
                                     './foo',
                                     ])

    def test_sprout_bzrdir_tree_branch_repo(self):
        tree = self.make_branch_and_tree('source')
        self.build_tree(['foo'], transport=tree.bzrdir.transport.clone('..'))
        tree.add('foo')
        tree.commit('revision 1')
        dir = tree.bzrdir
        target = self.sproutOrSkip(dir, self.get_url('target'))
        self.assertNotEqual(dir.transport.base, target.transport.base)
        self.assertDirectoriesEqual(dir.root_transport, target.root_transport,
                                    [
                                     './.bzr/branch/branch.conf',
                                     './.bzr/branch/parent',
                                     './.bzr/checkout/dirstate',
                                     './.bzr/checkout/stat-cache',
                                     './.bzr/checkout/inventory',
                                     './.bzr/inventory',
                                     './.bzr/parent',
                                     './.bzr/repository',
                                     './.bzr/stat-cache',
                                     ])
        self.assertRepositoryHasSameItems(
            tree.branch.repository, target.open_repository())


    def test_retire_bzrdir(self):
        bd = self.make_bzrdir('.')
        transport = bd.root_transport
        # must not overwrite existing directories
        self.build_tree(['.bzr.retired.0/', '.bzr.retired.0/junk',],
            transport=transport)
        self.failUnless(transport.has('.bzr'))
        bd.retire_bzrdir()
        self.failIf(transport.has('.bzr'))
        self.failUnless(transport.has('.bzr.retired.1'))

    def test_retire_bzrdir_limited(self):
        bd = self.make_bzrdir('.')
        transport = bd.root_transport
        # must not overwrite existing directories
        self.build_tree(['.bzr.retired.0/', '.bzr.retired.0/junk',],
            transport=transport)
        self.failUnless(transport.has('.bzr'))
        self.assertRaises((errors.FileExists, errors.DirectoryNotEmpty),
            bd.retire_bzrdir, limit=0)
