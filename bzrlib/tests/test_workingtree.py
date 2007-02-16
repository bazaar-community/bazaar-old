# Copyright (C) 2005, 2006 Canonical Ltd
# Authors:  Robert Collins <robert.collins@canonical.com>
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

from cStringIO import StringIO
import os

from bzrlib import dirstate, ignores
import bzrlib
from bzrlib.branch import Branch
from bzrlib import bzrdir, conflicts, errors, workingtree
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import NotBranchError, NotVersionedError
from bzrlib.lockdir import LockDir
from bzrlib.mutabletree import needs_tree_write_lock
from bzrlib.osutils import pathjoin, getcwd, has_symlinks
from bzrlib.symbol_versioning import zero_thirteen
from bzrlib.tests import TestCase, TestCaseWithTransport, TestSkipped
from bzrlib.trace import mutter
from bzrlib.transport import get_transport
from bzrlib.workingtree import (
    TreeEntry,
    TreeDirectory,
    TreeFile,
    TreeLink,
    WorkingTree,
    )

class TestTreeDirectory(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeDirectory().kind_character(), '/')


class TestTreeEntry(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeEntry().kind_character(), '???')


class TestTreeFile(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeFile().kind_character(), '')


class TestTreeLink(TestCaseWithTransport):

    def test_kind_character(self):
        self.assertEqual(TreeLink().kind_character(), '')


class TestDefaultFormat(TestCaseWithTransport):

    def test_get_set_default_format(self):
        old_format = workingtree.WorkingTreeFormat.get_default_format()
        # default is 3
        self.assertTrue(isinstance(old_format, workingtree.WorkingTreeFormat3))
        workingtree.WorkingTreeFormat.set_default_format(SampleTreeFormat())
        try:
            # the default branch format is used by the meta dir format
            # which is not the default bzrdir format at this point
            dir = bzrdir.BzrDirMetaFormat1().initialize('.')
            dir.create_repository()
            dir.create_branch()
            result = dir.create_workingtree()
            self.assertEqual(result, 'A tree')
        finally:
            workingtree.WorkingTreeFormat.set_default_format(old_format)
        self.assertEqual(old_format, workingtree.WorkingTreeFormat.get_default_format())


class SampleTreeFormat(workingtree.WorkingTreeFormat):
    """A sample format

    this format is initializable, unsupported to aid in testing the 
    open and open_downlevel routines.
    """

    def get_format_string(self):
        """See WorkingTreeFormat.get_format_string()."""
        return "Sample tree format."

    def initialize(self, a_bzrdir, revision_id=None):
        """Sample branches cannot be created."""
        t = a_bzrdir.get_workingtree_transport(self)
        t.put_bytes('format', self.get_format_string())
        return 'A tree'

    def is_supported(self):
        return False

    def open(self, transport, _found=False):
        return "opened tree."


class TestWorkingTreeFormat(TestCaseWithTransport):
    """Tests for the WorkingTreeFormat facility."""

    def test_find_format(self):
        # is the right format object found for a working tree?
        # create a branch with a few known format objects.
        self.build_tree(["foo/", "bar/"])
        def check_format(format, url):
            dir = format._matchingbzrdir.initialize(url)
            dir.create_repository()
            dir.create_branch()
            format.initialize(dir)
            t = get_transport(url)
            found_format = workingtree.WorkingTreeFormat.find_format(dir)
            self.failUnless(isinstance(found_format, format.__class__))
        check_format(workingtree.WorkingTreeFormat3(), "bar")
        
    def test_find_format_no_tree(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        self.assertRaises(errors.NoWorkingTree,
                          workingtree.WorkingTreeFormat.find_format,
                          dir)

    def test_find_format_unknown_format(self):
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        dir.create_repository()
        dir.create_branch()
        SampleTreeFormat().initialize(dir)
        self.assertRaises(errors.UnknownFormatError,
                          workingtree.WorkingTreeFormat.find_format,
                          dir)

    def test_register_unregister_format(self):
        format = SampleTreeFormat()
        # make a control dir
        dir = bzrdir.BzrDirMetaFormat1().initialize('.')
        dir.create_repository()
        dir.create_branch()
        # make a branch
        format.initialize(dir)
        # register a format for it.
        workingtree.WorkingTreeFormat.register_format(format)
        # which branch.Open will refuse (not supported)
        self.assertRaises(errors.UnsupportedFormatError, workingtree.WorkingTree.open, '.')
        # but open_downlevel will work
        self.assertEqual(format.open(dir), workingtree.WorkingTree.open_downlevel('.'))
        # unregister the format
        workingtree.WorkingTreeFormat.unregister_format(format)


class TestWorkingTreeFormat3(TestCaseWithTransport):
    """Tests specific to WorkingTreeFormat3."""

    def test_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        tree = workingtree.WorkingTreeFormat3().initialize(control)
        # we want:
        # format 'Bazaar-NG Working Tree format 3'
        # inventory = blank inventory
        # pending-merges = ''
        # stat-cache = ??
        # no inventory.basis yet
        t = control.get_workingtree_transport(None)
        self.assertEqualDiff('Bazaar-NG Working Tree format 3',
                             t.get('format').read())
        # self.assertContainsRe(t.get('inventory').read(), 
        #                       '<inventory file_id="[^"]*" format="5">\n'
        #                       '</inventory>\n',
        #                      )
        # WorkingTreeFormat3 doesn't default to creating a unique root id,
        # because it is incompatible with older bzr versions
        self.assertContainsRe(t.get('inventory').read(),
                              '<inventory format="5">\n'
                              '</inventory>\n',
                             )
        self.assertEqualDiff('### bzr hashcache v5\n',
                             t.get('stat-cache').read())
        self.assertFalse(t.has('inventory.basis'))
        # no last-revision file means 'None' or 'NULLREVISION'
        self.assertFalse(t.has('last-revision'))
        # TODO RBC 20060210 do a commit, check the inventory.basis is created 
        # correctly and last-revision file becomes present.

    def test_uses_lockdir(self):
        """WorkingTreeFormat3 uses its own LockDir:
            
            - lock is a directory
            - when the WorkingTree is locked, LockDir can see that
        """
        t = self.get_transport()
        url = self.get_url()
        dir = bzrdir.BzrDirMetaFormat1().initialize(url)
        repo = dir.create_repository()
        branch = dir.create_branch()
        try:
            tree = workingtree.WorkingTreeFormat3().initialize(dir)
        except errors.NotLocalUrl:
            raise TestSkipped('Not a local URL')
        self.assertIsDirectory('.bzr', t)
        self.assertIsDirectory('.bzr/checkout', t)
        self.assertIsDirectory('.bzr/checkout/lock', t)
        our_lock = LockDir(t, '.bzr/checkout/lock')
        self.assertEquals(our_lock.peek(), None)
        tree.lock_write()
        self.assertTrue(our_lock.peek())
        tree.unlock()
        self.assertEquals(our_lock.peek(), None)

    def test_missing_pending_merges(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        tree = workingtree.WorkingTreeFormat3().initialize(control)
        tree._control_files._transport.delete("pending-merges")
        self.assertEqual([], tree.get_parent_ids())


class TestWorkingTreeFormat4(TestCaseWithTransport):
    """Tests specific to WorkingTreeFormat4."""

    def test_disk_layout(self):
        control = bzrdir.BzrDirMetaFormat1().initialize(self.get_url())
        control.create_repository()
        control.create_branch()
        tree = workingtree.WorkingTreeFormat4().initialize(control)
        # we want:
        # format 'Bazaar Working Tree format 4'
        # stat-cache = ??
        t = control.get_workingtree_transport(None)
        self.assertEqualDiff('Bazaar Working Tree format 4\n',
                             t.get('format').read())
        self.assertEqualDiff('### bzr hashcache v5\n',
                             t.get('stat-cache').read())
        self.assertFalse(t.has('inventory.basis'))
        # no last-revision file means 'None' or 'NULLREVISION'
        self.assertFalse(t.has('last-revision'))
        # TODO RBC 20060210 do a commit, check the inventory.basis is created 
        # correctly and last-revision file becomes present.
        # manually make a dirstate toc check the format is as desired.
        state = dirstate.DirState.on_file(t.local_abspath('dirstate'))
        self.assertEqual([], state.get_parent_ids())

    def test_uses_lockdir(self):
        """WorkingTreeFormat4 uses its own LockDir:
            
            - lock is a directory
            - when the WorkingTree is locked, LockDir can see that
        """
        # this test could be factored into a subclass of tests common to both
        # format 3 and 4, but for now its not much of an issue as there is only one in common.
        t = self.get_transport()
        tree = self.make_workingtree()
        self.assertIsDirectory('.bzr', t)
        self.assertIsDirectory('.bzr/checkout', t)
        self.assertIsDirectory('.bzr/checkout/lock', t)
        our_lock = LockDir(t, '.bzr/checkout/lock')
        self.assertEquals(our_lock.peek(), None)
        tree.lock_write()
        self.assertTrue(our_lock.peek())
        tree.unlock()
        self.assertEquals(our_lock.peek(), None)

    def make_workingtree(self):
        url = self.get_url()
        dir = bzrdir.BzrDirMetaFormat1().initialize(url)
        repo = dir.create_repository()
        branch = dir.create_branch()
        try:
            return workingtree.WorkingTreeFormat4().initialize(dir)
        except errors.NotLocalUrl:
            raise TestSkipped('Not a local URL')

    # TODO: test that dirstate also stores & retrieves the parent list of 
    # workingtree-parent revisions, including when they have multiple parents.
    # (in other words, the case when we're constructing a merge of 
    # revisions which are themselves merges.)

    # The simplest case is that the the workingtree's primary 
    # parent tree can be retrieved.  This is required for all WorkingTrees, 
    # and covered by the generic tests.

    def test_dirstate_stores_all_parent_inventories(self):
        tree = self.make_workingtree()

        # We're going to build in tree a working tree 
        # with three parent trees, with some files in common.  
    
        # We really don't want to do commit or merge in the new dirstate-based
        # tree, because that might not work yet.  So instead we build
        # revisions elsewhere and pull them across, doing by hand part of the
        # work that merge would do.

        subtree = self.make_branch_and_tree('subdir')
        self.build_tree(['subdir/file-a',])
        subtree.add(['file-a'], ['id-a'])
        rev1 = subtree.commit('commit in subdir')
        rev1_tree = subtree.basis_tree()
        rev1_tree.lock_read()
        self.addCleanup(rev1_tree.unlock)

        subtree2 = subtree.bzrdir.sprout('subdir2').open_workingtree()
        self.build_tree(['subdir2/file-b'])
        subtree2.add(['file-b'], ['id-b'])
        rev2 = subtree2.commit('commit in subdir2')
        rev2_tree = subtree2.basis_tree()
        rev2_tree.lock_read()
        self.addCleanup(rev2_tree.unlock)

        subtree.merge_from_branch(subtree2.branch)
        rev3 = subtree.commit('merge from subdir2')
        rev3_tree = subtree.basis_tree()
        rev3_tree.lock_read()
        self.addCleanup(rev3_tree.unlock)

        repo = tree.branch.repository
        repo.fetch(subtree.branch.repository, rev3)
        # will also pull the others...

        # tree doesn't contain a text merge yet but we'll just
        # set the parents as if a merge had taken place. 
        # this should cause the tree data to be folded into the 
        # dirstate.
        tree.set_parent_trees([
            (rev1, rev1_tree),
            (rev2, rev2_tree),
            (rev3, rev3_tree), ])

        # now we should be able to get them back out
        self.assertTreesEqual(tree.revision_tree(rev1), rev1_tree)
        self.assertTreesEqual(tree.revision_tree(rev2), rev2_tree)
        self.assertTreesEqual(tree.revision_tree(rev3), rev3_tree)

    def test_dirstate_doesnt_read_parents_from_repo_when_setting(self):
        """Setting parent trees on a dirstate working tree takes
        the trees it's given and doesn't need to read them from the 
        repository.
        """
        tree = self.make_workingtree()

        subtree = self.make_branch_and_tree('subdir')
        rev1 = subtree.commit('commit in subdir')
        rev1_tree = subtree.basis_tree()
        rev1_tree.lock_read()
        self.addCleanup(rev1_tree.unlock)

        tree.branch.pull(subtree.branch)

        # break the repository's legs to make sure it only uses the trees
        # it's given; any calls to forbidden methods will raise an 
        # AssertionError
        repo = tree.branch.repository
        repo.get_revision = self.fail
        repo.get_inventory = self.fail
        repo.get_inventory_xml = self.fail
        # try to set the parent trees.
        tree.set_parent_trees([(rev1, rev1_tree)])

    def test_dirstate_doesnt_read_from_repo_when_returning_cache_tree(self):
        """Getting parent trees from a dirstate tree does not read from the 
        repos inventory store. This is an important part of the dirstate
        performance optimisation work.
        """
        tree = self.make_workingtree()

        subtree = self.make_branch_and_tree('subdir')
        rev1 = subtree.commit('commit in subdir')
        rev1_tree = subtree.basis_tree()
        rev1_tree.lock_read()
        self.addCleanup(rev1_tree.unlock)
        rev2 = subtree.commit('second commit in subdir', allow_pointless=True)
        rev2_tree = subtree.basis_tree()
        rev2_tree.lock_read()
        self.addCleanup(rev2_tree.unlock)

        tree.branch.pull(subtree.branch)

        # break the repository's legs to make sure it only uses the trees
        # it's given; any calls to forbidden methods will raise an 
        # AssertionError
        repo = tree.branch.repository
        # dont uncomment this: the revision object must be accessed to 
        # answer 'get_parent_ids' for the revision tree- dirstate does not 
        # cache the parents of a parent tree at this point.
        #repo.get_revision = self.fail
        repo.get_inventory = self.fail
        repo.get_inventory_xml = self.fail
        # set the parent trees.
        tree.set_parent_trees([(rev1, rev1_tree), (rev2, rev2_tree)])
        # read the first tree
        result_rev1_tree = tree.revision_tree(rev1)
        # read the second
        result_rev2_tree = tree.revision_tree(rev2)
        # compare - there should be no differences between the handed and 
        # returned trees
        self.assertTreesEqual(rev1_tree, result_rev1_tree)
        self.assertTreesEqual(rev2_tree, result_rev2_tree)

    def test_dirstate_doesnt_cache_non_parent_trees(self):
        """Getting parent trees from a dirstate tree does not read from the 
        repos inventory store. This is an important part of the dirstate
        performance optimisation work.
        """
        tree = self.make_workingtree()

        # make a tree that we can try for, which is able to be returned but
        # must not be
        subtree = self.make_branch_and_tree('subdir')
        rev1 = subtree.commit('commit in subdir')
        tree.branch.pull(subtree.branch)
        # check it fails
        self.assertRaises(errors.NoSuchRevision, tree.revision_tree, rev1)

    def test_no_dirstate_outside_lock(self):
        # temporary test until the code is mature enough to test from outside.
        """Getting a dirstate object fails if there is no lock."""
        def lock_and_call_current_dirstate(tree, lock_method):
            getattr(tree, lock_method)()
            tree.current_dirstate()
            tree.unlock()
        tree = self.make_workingtree()
        self.assertRaises(errors.ObjectNotLocked, tree.current_dirstate)
        lock_and_call_current_dirstate(tree, 'lock_read')
        self.assertRaises(errors.ObjectNotLocked, tree.current_dirstate)
        lock_and_call_current_dirstate(tree, 'lock_write')
        self.assertRaises(errors.ObjectNotLocked, tree.current_dirstate)
        lock_and_call_current_dirstate(tree, 'lock_tree_write')
        self.assertRaises(errors.ObjectNotLocked, tree.current_dirstate)

    def test_new_dirstate_on_new_lock(self):
        # until we have detection for when a dirstate can be reused, we
        # want to reparse dirstate on every new lock.
        known_dirstates = set()
        def lock_and_compare_all_current_dirstate(tree, lock_method):
            getattr(tree, lock_method)()
            state = tree.current_dirstate()
            self.assertFalse(state in known_dirstates)
            known_dirstates.add(state)
            tree.unlock()
        tree = self.make_workingtree()
        # lock twice with each type to prevent silly per-lock-type bugs.
        # each lock and compare looks for a unique state object.
        lock_and_compare_all_current_dirstate(tree, 'lock_read')
        lock_and_compare_all_current_dirstate(tree, 'lock_read')
        lock_and_compare_all_current_dirstate(tree, 'lock_tree_write')
        lock_and_compare_all_current_dirstate(tree, 'lock_tree_write')
        lock_and_compare_all_current_dirstate(tree, 'lock_write')
        lock_and_compare_all_current_dirstate(tree, 'lock_write')


class TestFormat2WorkingTree(TestCaseWithTransport):
    """Tests that are specific to format 2 trees."""

    def create_format2_tree(self, url):
        return self.make_branch_and_tree(
            url, format=bzrlib.bzrdir.BzrDirFormat6())

    def test_conflicts(self):
        # test backwards compatability
        tree = self.create_format2_tree('.')
        self.assertRaises(errors.UnsupportedOperation, tree.set_conflicts,
                          None)
        file('lala.BASE', 'wb').write('labase')
        expected = conflicts.ContentsConflict('lala')
        self.assertEqual(list(tree.conflicts()), [expected])
        file('lala', 'wb').write('la')
        tree.add('lala', 'lala-id')
        expected = conflicts.ContentsConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])
        file('lala.THIS', 'wb').write('lathis')
        file('lala.OTHER', 'wb').write('laother')
        # When "text conflict"s happen, stem, THIS and OTHER are text
        expected = conflicts.TextConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])
        os.unlink('lala.OTHER')
        os.mkdir('lala.OTHER')
        expected = conflicts.ContentsConflict('lala', file_id='lala-id')
        self.assertEqual(list(tree.conflicts()), [expected])


class TestNonFormatSpecificCode(TestCaseWithTransport):
    """This class contains tests of workingtree that are not format specific."""

    def test_gen_file_id(self):
        file_id = self.applyDeprecated(zero_thirteen, workingtree.gen_file_id,
                                      'filename')
        self.assertStartsWith(file_id, 'filename-')

    def test_gen_root_id(self):
        file_id = self.applyDeprecated(zero_thirteen, workingtree.gen_root_id)
        self.assertStartsWith(file_id, 'tree_root-')
        

class InstrumentedTree(object):
    """A instrumented tree to check the needs_tree_write_lock decorator."""

    def __init__(self):
        self._locks = []

    def lock_tree_write(self):
        self._locks.append('t')

    @needs_tree_write_lock
    def method_with_tree_write_lock(self, *args, **kwargs):
        """A lock_tree_write decorated method that returns its arguments."""
        return args, kwargs

    @needs_tree_write_lock
    def method_that_raises(self):
        """This method causes an exception when called with parameters.
        
        This allows the decorator code to be checked - it should still call
        unlock.
        """

    def unlock(self):
        self._locks.append('u')


class TestInstrumentedTree(TestCase):

    def test_needs_tree_write_lock(self):
        """@needs_tree_write_lock should be semantically transparent."""
        tree = InstrumentedTree()
        self.assertEqual(
            'method_with_tree_write_lock',
            tree.method_with_tree_write_lock.__name__)
        self.assertEqual(
            "A lock_tree_write decorated method that returns its arguments.",
            tree.method_with_tree_write_lock.__doc__)
        args = (1, 2, 3)
        kwargs = {'a':'b'}
        result = tree.method_with_tree_write_lock(1,2,3, a='b')
        self.assertEqual((args, kwargs), result)
        self.assertEqual(['t', 'u'], tree._locks)
        self.assertRaises(TypeError, tree.method_that_raises, 'foo')
        self.assertEqual(['t', 'u', 't', 'u'], tree._locks)
