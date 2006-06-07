# Copyright (C) 2006 by Canonical Ltd
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Tests for the info command of bzr."""


import bzrlib


from bzrlib.osutils import format_date
from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase


class TestInfo(ExternalBase):

    def test_info_non_existing(self):
        out, err = self.runbzr('info /i/do/not/exist/', retcode=3)
        self.assertEqual(out, '')
        self.assertEqual(err, 'bzr: ERROR: Not a branch: /i/do/not/exist/\n')

    def test_info_standalone(self):
        transport = self.get_transport()

        # Create initial standalone branch
        old_format = bzrlib.bzrdir.BzrDirFormat.get_default_format()
        bzrlib.bzrdir.BzrDirFormat.set_default_format(bzrlib.bzrdir.BzrDirFormat6())
        tree1 = self.make_branch_and_tree('standalone')
        bzrlib.bzrdir.BzrDirFormat.set_default_format(old_format)
        self.build_tree(['standalone/a'])
        tree1.add('a')
        branch1 = tree1.branch
        out, err = self.runbzr('info standalone')
        self.assertEqualDiff(
"""Location:
  branch root: %s

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: Weave repository format 6

In the working tree:
         0 unchanged
         0 modified
         1 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % branch1.bzrdir.root_transport.base, out)
        self.assertEqual('', err)
        tree1.commit('commit one')
        rev = branch1.repository.get_revision(branch1.revision_history()[0])
        datestring_first = format_date(rev.timestamp, rev.timezone)

        # Branch standalone with push location
        branch2 = branch1.bzrdir.sprout('branch').open_branch()
        branch2.set_push_location(branch1.bzrdir.root_transport.base)
        out, err = self.runbzr('info branch --verbose')
        self.assertEqualDiff(
"""Location:
  branch root: %s

Related branches:
      parent branch: %s
  publish to branch: %s

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: Weave repository format 6

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         %d KiB
""" % (branch2.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       branch2.repository._revision_store.total_size(
        branch2.repository.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Branch and bind to standalone, needs upgrade to metadir
        # (creates backup as unknown)
        branch1.bzrdir.sprout('bound')
        bzrlib.upgrade.upgrade('bound', bzrlib.bzrdir.BzrDirMetaFormat1())
        branch3 = bzrlib.bzrdir.BzrDir.open('bound').open_branch()
        branch3.bind(branch1)
        out, err = self.runbzr('info bound')
        self.assertEqualDiff(
"""Location:
       checkout root: %s
  checkout of branch: %s

Related branches:
  parent branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         1 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         %d KiB
""" % (branch3.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       branch3.repository._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       branch3.repository._revision_store.total_size(
        branch3.repository.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Checkout standalone (same as above, but does not have parent set)
        old_format = bzrlib.bzrdir.BzrDirFormat.get_default_format()
        bzrlib.bzrdir.BzrDirFormat.set_default_format(bzrlib.bzrdir.BzrDirMetaFormat1())
        branch4 = bzrlib.bzrdir.BzrDir.create_branch_convenience('checkout')
        bzrlib.bzrdir.BzrDirFormat.set_default_format(old_format)
        branch4.bind(branch1)
        branch4.bzrdir.open_workingtree().update()
        out, err = self.runbzr('info checkout --verbose')
        self.assertEqualDiff(
"""Location:
       checkout root: %s
  checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         %d KiB
""" % (branch4.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       branch4.repository._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       branch4.repository._revision_store.total_size(
        branch4.repository.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Lightweight checkout (same as above, different branch and repository)
        old_format = bzrlib.bzrdir.BzrDirFormat.get_default_format()
        bzrlib.bzrdir.BzrDirFormat.set_default_format(bzrlib.bzrdir.BzrDirMetaFormat1())
        transport.mkdir('lightcheckout')
        dir5 = bzrlib.bzrdir.BzrDirMetaFormat1().initialize('lightcheckout')
        bzrlib.branch.BranchReferenceFormat().initialize(dir5, branch1)
        dir5.create_workingtree()
        tree5 = dir5.open_workingtree()
        bzrlib.bzrdir.BzrDirFormat.set_default_format(old_format)
        branch5 = tree5.branch
        out, err = self.runbzr('info lightcheckout')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
   checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 4
    repository: Weave repository format 6

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 KiB
""" % (tree5.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Update initial standalone branch
        self.build_tree(['standalone/b'])
        tree1.add('b')
        tree1.commit('commit two')
        rev = branch1.repository.get_revision(branch1.revision_history()[-1])
        datestring_last = format_date(rev.timestamp, rev.timezone)

        # Out of date branched standalone branch will not be detected
        out, err = self.runbzr('info branch')
        self.assertEqualDiff(
"""Location:
  branch root: %s

Related branches:
      parent branch: %s
  publish to branch: %s

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: Weave repository format 6

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         0 KiB
""" % (branch2.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       datestring_first, datestring_first,
       ), out)
        self.assertEqual('', err)

        # Out of date bound branch
        out, err = self.runbzr('info bound')
        self.assertEqualDiff(
"""Location:
       checkout root: %s
  checkout of branch: %s

Related branches:
  parent branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Branch is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         1 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         %d KiB
""" % (branch3.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       branch3.repository._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       branch3.repository._revision_store.total_size(
        branch3.repository.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Out of date checkout
        out, err = self.runbzr('info checkout')
        self.assertEqualDiff(
"""Location:
       checkout root: %s
  checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Branch is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         %d KiB
""" % (branch4.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       branch4.repository._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       branch4.repository._revision_store.total_size(
        branch4.repository.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Out of date lightweight checkout
        out, err = self.runbzr('info lightcheckout --verbose')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
   checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 4
    repository: Weave repository format 6

Working tree is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         2 revisions
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         2 revisions
         0 KiB
""" % (tree5.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       datestring_first, datestring_last,
       ), out)
        self.assertEqual('', err)

    def test_info_standalone_no_tree(self):
        # create standalone branch without a working tree
        branch = self.make_branch('branch')
        repo = branch.repository
        out, err = self.runbzr('info branch')
        self.assertEqualDiff(
"""Location:
  branch root: %s

Format:
       control: Meta directory format 1
        branch: Branch format 5
    repository: %s

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (branch.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       ), out)
        self.assertEqual('', err)

    def test_info_shared_repository(self):
        old_format = bzrlib.bzrdir.BzrDirFormat.get_default_format()
        bzrlib.bzrdir.BzrDirFormat.set_default_format(bzrlib.bzrdir.BzrDirMetaFormat1())
        transport = self.get_transport()

        # Create shared repository
        repo = self.make_repository('repo', shared=True)
        repo.set_make_working_trees(False)
        out, err = self.runbzr('info repo')
        self.assertEqualDiff(
"""Location:
  shared repository: %s

Format:
       control: Meta directory format 1
    repository: %s

Revision store:
         0 revisions
         0 KiB
""" % (repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create branch inside shared repository
        repo.bzrdir.root_transport.mkdir('branch')
        branch1 = repo.bzrdir.create_branch_convenience('repo/branch')
        out, err = self.runbzr('info repo/branch')
        self.assertEqualDiff(
"""Location:
  shared repository: %s
  repository branch: branch

Format:
       control: Meta directory format 1
        branch: Branch format 5
    repository: %s

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create lightweight checkout
        transport.mkdir('tree')
        transport.mkdir('tree/lightcheckout')
        dir2 = bzrlib.bzrdir.BzrDirMetaFormat1().initialize('tree/lightcheckout')
        bzrlib.branch.BranchReferenceFormat().initialize(dir2, branch1)
        dir2.create_workingtree()
        tree2 = dir2.open_workingtree()
        branch2 = tree2.branch
        out, err = self.runbzr('info tree/lightcheckout')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
    shared repository: %s
    repository branch: branch

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (tree2.bzrdir.root_transport.base,
       repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create normal checkout
        tree3 = bzrlib.bzrdir.BzrDir.create_checkout_convenience(
            'tree/checkout', branch1)
        branch3 = tree3.branch
        assert tree3.basis_tree().inventory.root is not None
        assert tree3.inventory.root is not None 
        out, err = self.runbzr('info tree/checkout --verbose')
        self.assertEqualDiff(
"""Location:
       checkout root: %s
  checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
         0 committers

Revision store:
         0 revisions
         0 KiB
""" % (branch3.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Update lightweight checkout
        self.build_tree(['tree/lightcheckout/a'])
        tree2.add('a')
        tree2.commit('commit one')
        rev = repo.get_revision(branch2.revision_history()[0])
        datestring_first = format_date(rev.timestamp, rev.timezone)
        out, err = self.runbzr('info tree/lightcheckout --verbose')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
    shared repository: %s
    repository branch: branch

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         %d KiB
""" % (tree2.bzrdir.root_transport.base,
       repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Out of date checkout
        out, err = self.runbzr('info tree/checkout')
        self.assertEqualDiff(
"""Location:
       checkout root: %s
  checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Branch is out of date: missing 1 revision.

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (tree3.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Update checkout
        tree3.update()
        self.build_tree(['tree/checkout/b'])
        tree3.add('b')
        out, err = self.runbzr('info tree/checkout --verbose')
        self.assertEqualDiff(
"""Location:
       checkout root: %s
  checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         1 unchanged
         0 modified
         1 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         %d KiB
""" % (tree3.bzrdir.root_transport.base, branch1.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)
        tree3.commit('commit two')

        # Out of date lightweight checkout
        rev = repo.get_revision(branch1.revision_history()[-1])
        datestring_last = format_date(rev.timestamp, rev.timezone)
        out, err = self.runbzr('info tree/lightcheckout --verbose')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
    shared repository: %s
    repository branch: branch

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Working tree is out of date: missing 1 revision.

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         2 revisions
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         2 revisions
         %d KiB
""" % (tree2.bzrdir.root_transport.base,
       repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       datestring_first, datestring_last,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Show info about shared branch
        out, err = self.runbzr('info repo/branch --verbose')
        self.assertEqualDiff(
"""Location:
  shared repository: %s
  repository branch: branch

Format:
       control: Meta directory format 1
        branch: Branch format 5
    repository: %s

Branch history:
         2 revisions
         1 committer
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         2 revisions
         %d KiB
""" % (repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       datestring_first, datestring_last,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Show info about repository with revisions
        out, err = self.runbzr('info repo')
        self.assertEqualDiff(
"""Location:
  shared repository: %s

Format:
       control: Meta directory format 1
    repository: %s

Revision store:
         2 revisions
         %d KiB
""" % (repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        bzrlib.bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_info_shared_repository_with_trees(self):
        old_format = bzrlib.bzrdir.BzrDirFormat.get_default_format()
        bzrlib.bzrdir.BzrDirFormat.set_default_format(bzrlib.bzrdir.BzrDirMetaFormat1())
        transport = self.get_transport()

        # Create shared repository with working trees
        repo = self.make_repository('repo', shared=True)
        repo.set_make_working_trees(True)
        out, err = self.runbzr('info repo')
        self.assertEqualDiff(
"""Location:
  shared repository: %s

Format:
       control: Meta directory format 1
    repository: %s

Create working tree for new branches inside the repository.

Revision store:
         0 revisions
         0 KiB
""" % (repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create two branches
        repo.bzrdir.root_transport.mkdir('branch1')
        branch1 = repo.bzrdir.create_branch_convenience('repo/branch1')
        branch2 = branch1.bzrdir.sprout('repo/branch2').open_branch()

        # Empty first branch
        out, err = self.runbzr('info repo/branch1 --verbose')
        self.assertEqualDiff(
"""Location:
    shared repository: %s
  repository checkout: branch1

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
         0 committers

Revision store:
         0 revisions
         0 KiB
""" % (repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Update first branch
        self.build_tree(['repo/branch1/a'])
        tree1 = branch1.bzrdir.open_workingtree()
        tree1.add('a')
        tree1.commit('commit one')
        rev = repo.get_revision(branch1.revision_history()[0])
        datestring_first = format_date(rev.timestamp, rev.timezone)
        out, err = self.runbzr('info repo/branch1')
        self.assertEqualDiff(
"""Location:
    shared repository: %s
  repository checkout: branch1

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         %d KiB
""" % (repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Out of date second branch
        out, err = self.runbzr('info repo/branch2 --verbose')
        self.assertEqualDiff(
"""Location:
    shared repository: %s
  repository checkout: branch2

Related branches:
  parent branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions
         0 committers

Revision store:
         1 revision
         %d KiB
""" % (repo.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Update second branch
        tree2 = branch2.bzrdir.open_workingtree()
        tree2.pull(branch1)
        out, err = self.runbzr('info repo/branch2')
        self.assertEqualDiff(
"""Location:
    shared repository: %s
  repository checkout: branch2

Related branches:
  parent branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         1 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         1 revision
         0 days old
   first revision: %s
  latest revision: %s

Revision store:
         1 revision
         %d KiB
""" % (repo.bzrdir.root_transport.base,
       branch1.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       datestring_first, datestring_first,
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ), out)
        self.assertEqual('', err)

        # Show info about repository with revisions
        out, err = self.runbzr('info repo')
        self.assertEqualDiff(
"""Location:
  shared repository: %s

Format:
       control: Meta directory format 1
    repository: %s

Create working tree for new branches inside the repository.

Revision store:
         1 revision
         %d KiB
""" % (repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       # poking at _revision_store isn't all that clean, but neither is
       # having the ui test dependent on the exact overhead of a given store.
       repo._revision_store.total_size(repo.get_transaction())[1] / 1024,
       ),
       out)
        self.assertEqual('', err)

        bzrlib.bzrdir.BzrDirFormat.set_default_format(old_format)
    
    def test_info_shared_repository_with_tree_in_root(self):
        old_format = bzrlib.bzrdir.BzrDirFormat.get_default_format()
        bzrlib.bzrdir.BzrDirFormat.set_default_format(bzrlib.bzrdir.BzrDirMetaFormat1())
        transport = self.get_transport()

        # Create shared repository with working trees
        repo = self.make_repository('repo', shared=True)
        repo.set_make_working_trees(True)
        out, err = self.runbzr('info repo')
        self.assertEqualDiff(
"""Location:
  shared repository: %s

Format:
       control: Meta directory format 1
    repository: %s

Create working tree for new branches inside the repository.

Revision store:
         0 revisions
         0 KiB
""" % (repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        # Create branch in root of repository
        control = repo.bzrdir
        branch = control.create_branch()
        control.create_workingtree()
        out, err = self.runbzr('info repo')
        self.assertEqualDiff(
"""Location:
    shared repository: %s
  repository checkout: .

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (repo.bzrdir.root_transport.base,
       repo._format.get_format_description(),
       ), out)
        self.assertEqual('', err)

        bzrlib.bzrdir.BzrDirFormat.set_default_format(old_format)

    def test_info_locking(self):
        transport = self.get_transport()
        # Create shared repository with a branch
        repo = self.make_repository('repo', shared=True,
                                    format=bzrlib.bzrdir.BzrDirMetaFormat1())
        repo.set_make_working_trees(False)
        repo.bzrdir.root_transport.mkdir('branch')
        repo_branch = repo.bzrdir.create_branch_convenience('repo/branch',
                                    format=bzrlib.bzrdir.BzrDirMetaFormat1())
        # Do a heavy checkout
        transport.mkdir('tree')
        transport.mkdir('tree/checkout')
        co_branch = bzrlib.bzrdir.BzrDir.create_branch_convenience('tree/checkout',
                                    format=bzrlib.bzrdir.BzrDirMetaFormat1())
        co_branch.bind(repo_branch)
        # Do a light checkout of the heavy one
        transport.mkdir('tree/lightcheckout')
        lco_dir = bzrlib.bzrdir.BzrDirMetaFormat1().initialize('tree/lightcheckout')
        bzrlib.branch.BranchReferenceFormat().initialize(lco_dir, co_branch)
        lco_dir.create_workingtree()
        lco_tree = lco_dir.open_workingtree()

        # Test all permutations of locking the working tree, branch and repository
        # W B R

        # U U U
        out, err = self.runbzr('info tree/lightcheckout')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
   checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (lco_tree.bzrdir.root_transport.base,
       lco_tree.branch.bzrdir.root_transport.base,
       lco_tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        # U U L
        lco_tree.branch.repository.lock_write()
        out, err = self.runbzr('info tree/lightcheckout')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
   checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Lock status:
  working tree: unlocked
        branch: unlocked
    repository: locked

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (lco_tree.bzrdir.root_transport.base,
       lco_tree.branch.bzrdir.root_transport.base,
       lco_tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        lco_tree.branch.repository.unlock()
        # U L L
        lco_tree.branch.lock_write()
        out, err = self.runbzr('info tree/lightcheckout')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
   checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Lock status:
  working tree: unlocked
        branch: locked
    repository: locked

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (lco_tree.bzrdir.root_transport.base,
       lco_tree.branch.bzrdir.root_transport.base,
       lco_tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        lco_tree.branch.unlock()
        # L L L
        lco_tree.lock_write()
        out, err = self.runbzr('info tree/lightcheckout')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
   checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Lock status:
  working tree: locked
        branch: locked
    repository: locked

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (lco_tree.bzrdir.root_transport.base,
       lco_tree.branch.bzrdir.root_transport.base,
       lco_tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        lco_tree.unlock()
        # L L U
        lco_tree.lock_write()
        lco_tree.branch.repository.unlock()
        out, err = self.runbzr('info tree/lightcheckout')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
   checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Lock status:
  working tree: locked
        branch: locked
    repository: unlocked

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (lco_tree.bzrdir.root_transport.base,
       lco_tree.branch.bzrdir.root_transport.base,
       lco_tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        lco_tree.branch.repository.lock_write()
        lco_tree.unlock()
        # L U U
        lco_tree.lock_write()
        lco_tree.branch.unlock()
        out, err = self.runbzr('info tree/lightcheckout')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
   checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Lock status:
  working tree: locked
        branch: unlocked
    repository: unlocked

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (lco_tree.bzrdir.root_transport.base,
       lco_tree.branch.bzrdir.root_transport.base,
       lco_tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        lco_tree.branch.lock_write()
        lco_tree.unlock()
        # L U L
        lco_tree.lock_write()
        lco_tree.branch.unlock()
        lco_tree.branch.repository.lock_write()
        out, err = self.runbzr('info tree/lightcheckout')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
   checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Lock status:
  working tree: locked
        branch: unlocked
    repository: locked

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (lco_tree.bzrdir.root_transport.base,
       lco_tree.branch.bzrdir.root_transport.base,
       lco_tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        lco_tree.branch.repository.unlock()
        lco_tree.branch.lock_write()
        lco_tree.unlock()
        # U L U
        lco_tree.branch.lock_write()
        lco_tree.branch.repository.unlock()
        out, err = self.runbzr('info tree/lightcheckout')
        self.assertEqualDiff(
"""Location:
  light checkout root: %s
   checkout of branch: %s

Format:
       control: Meta directory format 1
  working tree: Working tree format 3
        branch: Branch format 5
    repository: %s

Lock status:
  working tree: unlocked
        branch: locked
    repository: unlocked

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (lco_tree.bzrdir.root_transport.base,
       lco_tree.branch.bzrdir.root_transport.base,
       lco_tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        lco_tree.branch.repository.lock_write()
        lco_tree.branch.unlock()

    def test_info_locking_oslocks(self):
        tree = self.make_branch_and_tree('branch',
                                         format=bzrlib.bzrdir.BzrDirFormat6())

        # Test all permutations of locking the working tree, branch and repository
        # XXX: Well not yet, as we can't query oslocks yet. Currently, it's
        # implemented by raising NotImplementedError and get_physical_lock_status()
        # always returns false. This makes bzr info hide the lock status.  (Olaf)
        # W B R

        # U U U
        out, err = self.runbzr('info branch')
        self.assertEqualDiff(
"""Location:
  branch root: %s

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: %s

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (tree.bzrdir.root_transport.base,
       tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        # L L L
        tree.lock_write()
        out, err = self.runbzr('info branch')
        self.assertEqualDiff(
"""Location:
  branch root: %s

Format:
       control: All-in-one format 6
  working tree: Working tree format 2
        branch: Branch format 4
    repository: %s

In the working tree:
         0 unchanged
         0 modified
         0 added
         0 removed
         0 renamed
         0 unknown
         0 ignored
         0 versioned subdirectories

Branch history:
         0 revisions

Revision store:
         0 revisions
         0 KiB
""" % (tree.bzrdir.root_transport.base,
       tree.branch.repository._format.get_format_description(),
       ), out)
        self.assertEqual('', err)
        tree.unlock()
