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

"""Tests for repository implementations - tests a repository format."""

from cStringIO import StringIO
import re

from bzrlib import (
    branch as _mod_branch,
    bzrdir,
    delta as _mod_delta,
    errors,
    gpg,
    info,
    inventory,
    remote,
    repository,
    revision as _mod_revision,
    tests,
    transport,
    upgrade,
    versionedfile,
    workingtree,
    )
from bzrlib.repofmt import (
    pack_repo,
    )
from bzrlib.tests import (
    per_repository,
    test_server,
    )
from bzrlib.tests.matchers import *


class TestRepositoryMakeBranchAndTree(per_repository.TestCaseWithRepository):

    def test_repository_format(self):
        # make sure the repository on tree.branch is of the desired format,
        # because developers use this api to setup the tree, branch and
        # repository for their tests: having it now give the right repository
        # type would invalidate the tests.
        tree = self.make_branch_and_tree('repo')
        self.assertIsInstance(tree.branch.repository._format,
            self.repository_format.__class__)


class TestRepository(per_repository.TestCaseWithRepository):

    def assertFormatAttribute(self, attribute, allowed_values):
        """Assert that the format has an attribute 'attribute'."""
        repo = self.make_repository('repo')
        self.assertSubset([getattr(repo._format, attribute)], allowed_values)

    def test_attribute__fetch_order(self):
        """Test the _fetch_order attribute."""
        self.assertFormatAttribute('_fetch_order', ('topological', 'unordered'))

    def test_attribute__fetch_uses_deltas(self):
        """Test the _fetch_uses_deltas attribute."""
        self.assertFormatAttribute('_fetch_uses_deltas', (True, False))

    def test_attribute_fast_deltas(self):
        """Test the format.fast_deltas attribute."""
        self.assertFormatAttribute('fast_deltas', (True, False))

    def test_attribute__fetch_reconcile(self):
        """Test the _fetch_reconcile attribute."""
        self.assertFormatAttribute('_fetch_reconcile', (True, False))

    def test_attribute_format_experimental(self):
        self.assertFormatAttribute('experimental', (True, False))

    def test_attribute_format_pack_compresses(self):
        self.assertFormatAttribute('pack_compresses', (True, False))

    def test_attribute_inventories_store(self):
        """Test the existence of the inventories attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.inventories, versionedfile.VersionedFiles)

    def test_attribute_inventories_basics(self):
        """Test basic aspects of the inventories attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        rev_id = (tree.commit('a'),)
        tree.lock_read()
        self.addCleanup(tree.unlock)
        self.assertEqual(set([rev_id]), set(repo.inventories.keys()))

    def test_attribute_revision_store(self):
        """Test the existence of the revisions attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.revisions,
            versionedfile.VersionedFiles)

    def test_attribute_revision_store_basics(self):
        """Test the basic behaviour of the revisions attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        repo.lock_write()
        try:
            self.assertEqual(set(), set(repo.revisions.keys()))
            revid = (tree.commit("foo"),)
            self.assertEqual(set([revid]), set(repo.revisions.keys()))
            self.assertEqual({revid:()},
                repo.revisions.get_parent_map([revid]))
        finally:
            repo.unlock()
        tree2 = self.make_branch_and_tree('tree2')
        tree2.pull(tree.branch)
        left_id = (tree2.commit('left'),)
        right_id = (tree.commit('right'),)
        tree.merge_from_branch(tree2.branch)
        merge_id = (tree.commit('merged'),)
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(set([revid, left_id, right_id, merge_id]),
            set(repo.revisions.keys()))
        self.assertEqual({revid:(), left_id:(revid,), right_id:(revid,),
             merge_id:(right_id, left_id)},
            repo.revisions.get_parent_map(repo.revisions.keys()))

    def test_attribute_signature_store(self):
        """Test the existence of the signatures attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.signatures,
            versionedfile.VersionedFiles)

    def test_attribute_text_store_basics(self):
        """Test the basic behaviour of the text store."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        file_id = "Foo:Bar"
        file_key = (file_id,)
        tree.lock_write()
        try:
            self.assertEqual(set(), set(repo.texts.keys()))
            tree.add(['foo'], [file_id], ['file'])
            tree.put_file_bytes_non_atomic(file_id, 'content\n')
            try:
                rev_key = (tree.commit("foo"),)
            except errors.IllegalPath:
                raise tests.TestNotApplicable(
                    'file_id %r cannot be stored on this'
                    ' platform for this repo format' % (file_id,))
            if repo._format.rich_root_data:
                root_commit = (tree.get_root_id(),) + rev_key
                keys = set([root_commit])
                parents = {root_commit:()}
            else:
                keys = set()
                parents = {}
            keys.add(file_key + rev_key)
            parents[file_key + rev_key] = ()
            self.assertEqual(keys, set(repo.texts.keys()))
            self.assertEqual(parents,
                repo.texts.get_parent_map(repo.texts.keys()))
        finally:
            tree.unlock()
        tree2 = self.make_branch_and_tree('tree2')
        tree2.pull(tree.branch)
        tree2.put_file_bytes_non_atomic('Foo:Bar', 'right\n')
        right_key = (tree2.commit('right'),)
        keys.add(file_key + right_key)
        parents[file_key + right_key] = (file_key + rev_key,)
        tree.put_file_bytes_non_atomic('Foo:Bar', 'left\n')
        left_key = (tree.commit('left'),)
        keys.add(file_key + left_key)
        parents[file_key + left_key] = (file_key + rev_key,)
        tree.merge_from_branch(tree2.branch)
        tree.put_file_bytes_non_atomic('Foo:Bar', 'merged\n')
        try:
            tree.auto_resolve()
        except errors.UnsupportedOperation:
            pass
        merge_key = (tree.commit('merged'),)
        keys.add(file_key + merge_key)
        parents[file_key + merge_key] = (file_key + left_key,
                                         file_key + right_key)
        repo.lock_read()
        self.addCleanup(repo.unlock)
        self.assertEqual(keys, set(repo.texts.keys()))
        self.assertEqual(parents, repo.texts.get_parent_map(repo.texts.keys()))

    def test_attribute_text_store(self):
        """Test the existence of the texts attribute."""
        tree = self.make_branch_and_tree('tree')
        repo = tree.branch.repository
        self.assertIsInstance(repo.texts,
            versionedfile.VersionedFiles)

    def test_exposed_versioned_files_are_marked_dirty(self):
        repo = self.make_repository('.')
        repo.lock_write()
        signatures = repo.signatures
        revisions = repo.revisions
        inventories = repo.inventories
        repo.unlock()
        self.assertRaises(errors.ObjectNotLocked,
            signatures.keys)
        self.assertRaises(errors.ObjectNotLocked,
            revisions.keys)
        self.assertRaises(errors.ObjectNotLocked,
            inventories.keys)
        self.assertRaises(errors.ObjectNotLocked,
            signatures.add_lines, ('foo',), [], [])
        self.assertRaises(errors.ObjectNotLocked,
            revisions.add_lines, ('foo',), [], [])
        self.assertRaises(errors.ObjectNotLocked,
            inventories.add_lines, ('foo',), [], [])

    def test_clone_to_default_format(self):
        #TODO: Test that cloning a repository preserves all the information
        # such as signatures[not tested yet] etc etc.
        # when changing to the current default format.
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        bzrdirb = self.make_bzrdir('b')
        repo_b = tree_a.branch.repository.clone(bzrdirb)
        tree_b = repo_b.revision_tree('rev1')
        tree_b.lock_read()
        self.addCleanup(tree_b.unlock)
        tree_b.get_file_text('file1')
        rev1 = repo_b.get_revision('rev1')

    def test_iter_inventories_is_ordered(self):
        # just a smoke test
        tree = self.make_branch_and_tree('a')
        first_revision = tree.commit('')
        second_revision = tree.commit('')
        tree.lock_read()
        self.addCleanup(tree.unlock)
        revs = (first_revision, second_revision)
        invs = tree.branch.repository.iter_inventories(revs)
        for rev_id, inv in zip(revs, invs):
            self.assertEqual(rev_id, inv.revision_id)
            self.assertIsInstance(inv, inventory.CommonInventory)

    def test_supports_rich_root(self):
        tree = self.make_branch_and_tree('a')
        tree.commit('')
        second_revision = tree.commit('')
        rev_tree = tree.branch.repository.revision_tree(second_revision)
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        inv = rev_tree.inventory
        rich_root = (inv.root.revision != second_revision)
        self.assertEqual(rich_root,
                         tree.branch.repository.supports_rich_root())

    def test_clone_specific_format(self):
        """todo"""

    def test_format_initialize_find_open(self):
        # loopback test to check the current format initializes to itself.
        if not self.repository_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        # supported formats must be able to init and open
        t = transport.get_transport(self.get_url())
        readonly_t = transport.get_transport(self.get_readonly_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = self.repository_format.initialize(made_control)
        self.assertEqual(made_control, made_repo.bzrdir)

        # find it via bzrdir opening:
        opened_control = bzrdir.BzrDir.open(readonly_t.base)
        direct_opened_repo = opened_control.open_repository()
        self.assertEqual(direct_opened_repo.__class__, made_repo.__class__)
        self.assertEqual(opened_control, direct_opened_repo.bzrdir)

        self.assertIsInstance(direct_opened_repo._format,
                              self.repository_format.__class__)
        # find it via Repository.open
        opened_repo = repository.Repository.open(readonly_t.base)
        self.failUnless(isinstance(opened_repo, made_repo.__class__))
        self.assertEqual(made_repo._format.__class__,
                         opened_repo._format.__class__)
        # if it has a unique id string, can we probe for it ?
        try:
            self.repository_format.get_format_string()
        except NotImplementedError:
            return
        self.assertEqual(self.repository_format,
                         repository.RepositoryFormat.find_format(opened_control))

    def test_format_matchingbzrdir(self):
        self.assertEqual(self.repository_format,
            self.repository_format._matchingbzrdir.repository_format)
        self.assertEqual(self.repository_format,
            self.bzrdir_format.repository_format)

    def test_format_network_name(self):
        repo = self.make_repository('r')
        format = repo._format
        network_name = format.network_name()
        self.assertIsInstance(network_name, str)
        # We want to test that the network_name matches the actual format on
        # disk.  For local repositories, that means that using network_name as
        # a key in the registry gives back the same format.  For remote
        # repositories, that means that the network_name of the
        # RemoteRepositoryFormat we have locally matches the actual format
        # present on the remote side.
        if isinstance(format, remote.RemoteRepositoryFormat):
            repo._ensure_real()
            real_repo = repo._real_repository
            self.assertEqual(real_repo._format.network_name(), network_name)
        else:
            registry = repository.network_format_registry
            looked_up_format = registry.get(network_name)
            self.assertEqual(format.__class__, looked_up_format.__class__)

    def test_create_repository(self):
        # bzrdir can construct a repository for itself.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = transport.get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        made_repo = made_control.create_repository()
        # Check that we have a repository object.
        made_repo.has_revision('foo')
        self.assertEqual(made_control, made_repo.bzrdir)

    def test_create_repository_shared(self):
        # bzrdir can construct a shared repository.
        if not self.bzrdir_format.is_supported():
            # unsupported formats are not loopback testable
            # because the default open will not open them and
            # they may not be initializable.
            return
        t = transport.get_transport(self.get_url())
        made_control = self.bzrdir_format.initialize(t.base)
        try:
            made_repo = made_control.create_repository(shared=True)
        except errors.IncompatibleFormat:
            # not all repository formats understand being shared, or
            # may only be shared in some circumstances.
            return
        # Check that we have a repository object.
        made_repo.has_revision('foo')
        self.assertEqual(made_control, made_repo.bzrdir)
        self.assertTrue(made_repo.is_shared())

    def test_revision_tree(self):
        wt = self.make_branch_and_tree('.')
        wt.set_root_id('fixed-root')
        wt.commit('lala!', rev_id='revision-1', allow_pointless=True)
        tree = wt.branch.repository.revision_tree('revision-1')
        tree.lock_read()
        try:
            self.assertEqual('revision-1', tree.inventory.root.revision)
            expected = inventory.InventoryDirectory('fixed-root', '', None)
            expected.revision = 'revision-1'
            self.assertEqual([('', 'V', 'directory', 'fixed-root', expected)],
                             list(tree.list_files(include_root=True)))
        finally:
            tree.unlock()
        tree = self.callDeprecated(['NULL_REVISION should be used for the null'
            ' revision instead of None, as of bzr 0.91.'],
            wt.branch.repository.revision_tree, None)
        tree.lock_read()
        try:
            self.assertEqual([], list(tree.list_files(include_root=True)))
        finally:
            tree.unlock()
        tree = wt.branch.repository.revision_tree(_mod_revision.NULL_REVISION)
        tree.lock_read()
        try:
            self.assertEqual([], list(tree.list_files(include_root=True)))
        finally:
            tree.unlock()

    def test_get_revision_delta(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo'])
        tree_a.add('foo', 'file1')
        tree_a.commit('rev1', rev_id='rev1')
        self.build_tree(['a/vla'])
        tree_a.add('vla', 'file2')
        tree_a.commit('rev2', rev_id='rev2')

        delta = tree_a.branch.repository.get_revision_delta('rev1')
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([('foo', 'file1', 'file')], delta.added)
        delta = tree_a.branch.repository.get_revision_delta('rev2')
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([('vla', 'file2', 'file')], delta.added)

    def test_get_revision_delta_filtered(self):
        tree_a = self.make_branch_and_tree('a')
        self.build_tree(['a/foo', 'a/bar/', 'a/bar/b1', 'a/bar/b2', 'a/baz'])
        tree_a.add(['foo', 'bar', 'bar/b1', 'bar/b2', 'baz'],
                   ['foo-id', 'bar-id', 'b1-id', 'b2-id', 'baz-id'])
        tree_a.commit('rev1', rev_id='rev1')
        self.build_tree(['a/bar/b3'])
        tree_a.add('bar/b3', 'b3-id')
        tree_a.commit('rev2', rev_id='rev2')

        # Test multiple files
        delta = tree_a.branch.repository.get_revision_delta('rev1',
            specific_fileids=['foo-id', 'baz-id'])
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([
            ('baz', 'baz-id', 'file'),
            ('foo', 'foo-id', 'file'),
            ], delta.added)
        # Test a directory
        delta = tree_a.branch.repository.get_revision_delta('rev1',
            specific_fileids=['bar-id'])
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([
            ('bar', 'bar-id', 'directory'),
            ('bar/b1', 'b1-id', 'file'),
            ('bar/b2', 'b2-id', 'file'),
            ], delta.added)
        # Test a file in a directory
        delta = tree_a.branch.repository.get_revision_delta('rev1',
            specific_fileids=['b2-id'])
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([
            ('bar', 'bar-id', 'directory'),
            ('bar/b2', 'b2-id', 'file'),
            ], delta.added)
        # Try another revision
        delta = tree_a.branch.repository.get_revision_delta('rev2',
                specific_fileids=['b3-id'])
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([
            ('bar', 'bar-id', 'directory'),
            ('bar/b3', 'b3-id', 'file'),
            ], delta.added)
        delta = tree_a.branch.repository.get_revision_delta('rev2',
                specific_fileids=['foo-id'])
        self.assertIsInstance(delta, _mod_delta.TreeDelta)
        self.assertEqual([], delta.added)

    def test_clone_bzrdir_repository_revision(self):
        # make a repository with some revisions,
        # and clone it, this should not have unreferenced revisions.
        # also: test cloning with a revision id of NULL_REVISION -> empty repo.
        raise tests.TestSkipped('revision limiting is not implemented yet.')

    def test_clone_repository_basis_revision(self):
        raise tests.TestSkipped(
            'the use of a basis should not add noise data to the result.')

    def test_clone_shared_no_tree(self):
        # cloning a shared repository keeps it shared
        # and preserves the make_working_tree setting.
        made_control = self.make_bzrdir('source')
        try:
            made_repo = made_control.create_repository(shared=True)
        except errors.IncompatibleFormat:
            # not all repository formats understand being shared, or
            # may only be shared in some circumstances.
            return
        try:
            made_repo.set_make_working_trees(False)
        except NotImplementedError:
            # the repository does not support having its tree-making flag
            # toggled.
            return
        result = made_control.clone(self.get_url('target'))
        # Check that we have a repository object.
        made_repo.has_revision('foo')

        self.assertEqual(made_control, made_repo.bzrdir)
        self.assertTrue(result.open_repository().is_shared())
        self.assertFalse(result.open_repository().make_working_trees())

    def test_upgrade_preserves_signatures(self):
        wt = self.make_branch_and_tree('source')
        wt.commit('A', allow_pointless=True, rev_id='A')
        repo = wt.branch.repository
        repo.lock_write()
        repo.start_write_group()
        repo.sign_revision('A', gpg.LoopbackGPGStrategy(None))
        repo.commit_write_group()
        repo.unlock()
        old_signature = repo.get_signature_text('A')
        try:
            old_format = bzrdir.BzrDirFormat.get_default_format()
            # This gives metadir branches something they can convert to.
            # it would be nice to have a 'latest' vs 'default' concept.
            format = bzrdir.format_registry.make_bzrdir('dirstate-with-subtree')
            upgrade.upgrade(repo.bzrdir.root_transport.base, format=format)
        except errors.UpToDateFormat:
            # this is in the most current format already.
            return
        except errors.BadConversionTarget, e:
            raise tests.TestSkipped(str(e))
        wt = workingtree.WorkingTree.open(wt.basedir)
        new_signature = wt.branch.repository.get_signature_text('A')
        self.assertEqual(old_signature, new_signature)

    def test_format_description(self):
        repo = self.make_repository('.')
        text = repo._format.get_format_description()
        self.failUnless(len(text))

    def test_format_supports_external_lookups(self):
        repo = self.make_repository('.')
        self.assertSubset(
            [repo._format.supports_external_lookups], (True, False))

    def assertMessageRoundtrips(self, message):
        """Assert that message roundtrips to a repository and back intact."""
        tree = self.make_branch_and_tree('.')
        tree.commit(message, rev_id='a', allow_pointless=True)
        rev = tree.branch.repository.get_revision('a')
        if tree.branch.repository._serializer.squashes_xml_invalid_characters:
            # we have to manually escape this as we dont try to
            # roundtrip xml invalid characters in the xml-based serializers.
            escaped_message, escape_count = re.subn(
                u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
                lambda match: match.group(0).encode('unicode_escape'),
                message)
            self.assertEqual(rev.message, escaped_message)
        else:
            self.assertEqual(rev.message, message)
        # insist the class is unicode no matter what came in for
        # consistency.
        self.assertIsInstance(rev.message, unicode)

    def test_commit_unicode_message(self):
        # a siple unicode message should be preserved
        self.assertMessageRoundtrips(u'foo bar gamm\xae plop')

    def test_commit_unicode_control_characters(self):
        # a unicode message with control characters should roundtrip too.
        unichars = [unichr(x) for x in range(256)]
        # '\r' is not directly allowed anymore, as it used to be translated
        # into '\n' anyway
        unichars[ord('\r')] = u'\n'
        self.assertMessageRoundtrips(
            u"All 8-bit chars: " +  ''.join(unichars))

    def test_check_repository(self):
        """Check a fairly simple repository's history"""
        tree = self.make_branch_and_tree('.')
        tree.commit('initial empty commit', rev_id='a-rev',
                    allow_pointless=True)
        result = tree.branch.repository.check()
        # writes to log; should accept both verbose or non-verbose
        result.report_results(verbose=True)
        result.report_results(verbose=False)

    def test_get_revisions(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('initial empty commit', rev_id='a-rev',
                    allow_pointless=True)
        tree.commit('second empty commit', rev_id='b-rev',
                    allow_pointless=True)
        tree.commit('third empty commit', rev_id='c-rev',
                    allow_pointless=True)
        repo = tree.branch.repository
        revision_ids = ['a-rev', 'b-rev', 'c-rev']
        revisions = repo.get_revisions(revision_ids)
        self.assertEqual(len(revisions), 3)
        zipped = zip(revisions, revision_ids)
        self.assertEqual(len(zipped), 3)
        for revision, revision_id in zipped:
            self.assertEqual(revision.revision_id, revision_id)
            self.assertEqual(revision, repo.get_revision(revision_id))

    def test_root_entry_has_revision(self):
        tree = self.make_branch_and_tree('.')
        tree.commit('message', rev_id='rev_id')
        rev_tree = tree.branch.repository.revision_tree(tree.last_revision())
        rev_tree.lock_read()
        self.addCleanup(rev_tree.unlock)
        self.assertEqual('rev_id', rev_tree.inventory.root.revision)

    def test_upgrade_from_format4(self):
        from bzrlib.tests.test_upgrade import _upgrade_dir_template
        if isinstance(self.repository_format, remote.RemoteRepositoryFormat):
            return # local conversion to/from RemoteObjects is irrelevant.
        if self.repository_format.get_format_description() \
            == "Repository format 4":
            raise tests.TestSkipped('Cannot convert format-4 to itself')
        self.build_tree_contents(_upgrade_dir_template)
        old_repodir = bzrdir.BzrDir.open_unsupported('.')
        old_repo_format = old_repodir.open_repository()._format
        format = self.repository_format._matchingbzrdir
        try:
            format.repository_format = self.repository_format
        except AttributeError:
            pass
        upgrade.upgrade('.', format)

    def test_pointless_commit(self):
        tree = self.make_branch_and_tree('.')
        self.assertRaises(errors.PointlessCommit, tree.commit, 'pointless',
                          allow_pointless=False)
        tree.commit('pointless', allow_pointless=True)

    def test_format_attributes(self):
        """All repository formats should have some basic attributes."""
        # create a repository to get a real format instance, not the
        # template from the test suite parameterization.
        repo = self.make_repository('.')
        repo._format.rich_root_data
        repo._format.supports_tree_reference

    def test_get_serializer_format(self):
        repo = self.make_repository('.')
        format = repo.get_serializer_format()
        self.assertEqual(repo._serializer.format_num, format)

    def test_iter_files_bytes(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree_contents([('tree/file1', 'foo'),
                                  ('tree/file2', 'bar')])
        tree.add(['file1', 'file2'], ['file1-id', 'file2-id'])
        tree.commit('rev1', rev_id='rev1')
        self.build_tree_contents([('tree/file1', 'baz')])
        tree.commit('rev2', rev_id='rev2')
        repository = tree.branch.repository
        repository.lock_read()
        self.addCleanup(repository.unlock)
        extracted = dict((i, ''.join(b)) for i, b in
                         repository.iter_files_bytes(
                         [('file1-id', 'rev1', 'file1-old'),
                          ('file1-id', 'rev2', 'file1-new'),
                          ('file2-id', 'rev1', 'file2'),
                         ]))
        self.assertEqual('foo', extracted['file1-old'])
        self.assertEqual('bar', extracted['file2'])
        self.assertEqual('baz', extracted['file1-new'])
        self.assertRaises(errors.RevisionNotPresent, list,
                          repository.iter_files_bytes(
                          [('file1-id', 'rev3', 'file1-notpresent')]))
        self.assertRaises((errors.RevisionNotPresent, errors.NoSuchId), list,
                          repository.iter_files_bytes(
                          [('file3-id', 'rev3', 'file1-notpresent')]))

    def test_item_keys_introduced_by(self):
        # Make a repo with one revision and one versioned file.
        tree = self.make_branch_and_tree('t')
        self.build_tree(['t/foo'])
        tree.add('foo', 'file1')
        tree.commit('message', rev_id='rev_id')
        repo = tree.branch.repository
        repo.lock_write()
        repo.start_write_group()
        repo.sign_revision('rev_id', gpg.LoopbackGPGStrategy(None))
        repo.commit_write_group()
        repo.unlock()
        repo.lock_read()
        self.addCleanup(repo.unlock)

        # Item keys will be in this order, for maximum convenience for
        # generating data to insert into knit repository:
        #   * files
        #   * inventory
        #   * signatures
        #   * revisions
        expected_item_keys = [
            ('file', 'file1', ['rev_id']),
            ('inventory', None, ['rev_id']),
            ('signatures', None, ['rev_id']),
            ('revisions', None, ['rev_id'])]
        item_keys = list(repo.item_keys_introduced_by(['rev_id']))
        item_keys = [
            (kind, file_id, list(versions))
            for (kind, file_id, versions) in item_keys]

        if repo.supports_rich_root():
            # Check for the root versioned file in the item_keys, then remove
            # it from streamed_names so we can compare that with
            # expected_record_names.
            # Note that the file keys can be in any order, so this test is
            # written to allow that.
            inv = repo.get_inventory('rev_id')
            root_item_key = ('file', inv.root.file_id, ['rev_id'])
            self.assertTrue(root_item_key in item_keys)
            item_keys.remove(root_item_key)

        self.assertEqual(expected_item_keys, item_keys)

    def test_get_graph(self):
        """Bare-bones smoketest that all repositories implement get_graph."""
        repo = self.make_repository('repo')
        repo.lock_read()
        self.addCleanup(repo.unlock)
        repo.get_graph()

    def test_graph_ghost_handling(self):
        tree = self.make_branch_and_tree('here')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit('initial commit', rev_id='rev1')
        tree.add_parent_tree_id('ghost')
        tree.commit('commit-with-ghost', rev_id='rev2')
        graph = tree.branch.repository.get_graph()
        parents = graph.get_parent_map(['ghost', 'rev2'])
        self.assertTrue('ghost' not in parents)
        self.assertEqual(parents['rev2'], ('rev1', 'ghost'))

    def test_get_known_graph_ancestry(self):
        tree = self.make_branch_and_tree('here')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        # A
        # |\
        # | B
        # |/
        # C
        tree.commit('initial commit', rev_id='A')
        tree_other = tree.bzrdir.sprout('there').open_workingtree()
        tree_other.commit('another', rev_id='B')
        tree.merge_from_branch(tree_other.branch)
        tree.commit('another', rev_id='C')
        kg = tree.branch.repository.get_known_graph_ancestry(
            ['C'])
        self.assertEqual(['C'], list(kg.heads(['A', 'B', 'C'])))
        self.assertEqual(['A', 'B', 'C'], list(kg.topo_sort()))

    def test_parent_map_type(self):
        tree = self.make_branch_and_tree('here')
        tree.lock_write()
        self.addCleanup(tree.unlock)
        tree.commit('initial commit', rev_id='rev1')
        tree.commit('next commit', rev_id='rev2')
        graph = tree.branch.repository.get_graph()
        parents = graph.get_parent_map(
            [_mod_revision.NULL_REVISION, 'rev1', 'rev2'])
        for value in parents.values():
            self.assertIsInstance(value, tuple)

    def test_implements_revision_graph_can_have_wrong_parents(self):
        """All repositories should implement
        revision_graph_can_have_wrong_parents, so that check and reconcile can
        work correctly.
        """
        repo = self.make_repository('.')
        # This should work, not raise NotImplementedError:
        if not repo.revision_graph_can_have_wrong_parents():
            return
        repo.lock_read()
        self.addCleanup(repo.unlock)
        # This repo must also implement
        # _find_inconsistent_revision_parents and
        # _check_for_inconsistent_revision_parents.  So calling these
        # should not raise NotImplementedError.
        list(repo._find_inconsistent_revision_parents())
        repo._check_for_inconsistent_revision_parents()

    def test_add_signature_text(self):
        repo = self.make_repository('repo')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        inv = inventory.Inventory(revision_id='A')
        inv.root.revision = 'A'
        repo.add_inventory('A', inv, [])
        repo.add_revision('A', _mod_revision.Revision(
                'A', committer='A', timestamp=0,
                inventory_sha1='', timezone=0, message='A'))
        repo.add_signature_text('A', 'This might be a signature')
        self.assertEqual('This might be a signature',
                         repo.get_signature_text('A'))

    def test_add_revision_inventory_sha1(self):
        inv = inventory.Inventory(revision_id='A')
        inv.root.revision = 'A'
        inv.root.file_id = 'fixed-root'
        # Insert the inventory on its own to an identical repository, to get
        # its sha1.
        reference_repo = self.make_repository('reference_repo')
        reference_repo.lock_write()
        reference_repo.start_write_group()
        inv_sha1 = reference_repo.add_inventory('A', inv, [])
        reference_repo.abort_write_group()
        reference_repo.unlock()
        # Now insert a revision with this inventory, and it should get the same
        # sha1.
        repo = self.make_repository('repo')
        repo.lock_write()
        repo.start_write_group()
        root_id = inv.root.file_id
        repo.texts.add_lines(('fixed-root', 'A'), [], [])
        repo.add_revision('A', _mod_revision.Revision(
                'A', committer='B', timestamp=0,
                timezone=0, message='C'), inv=inv)
        repo.commit_write_group()
        repo.unlock()
        repo.lock_read()
        self.assertEquals(inv_sha1, repo.get_revision('A').inventory_sha1)
        repo.unlock()

    def test_install_revisions(self):
        wt = self.make_branch_and_tree('source')
        wt.commit('A', allow_pointless=True, rev_id='A')
        repo = wt.branch.repository
        repo.lock_write()
        repo.start_write_group()
        repo.sign_revision('A', gpg.LoopbackGPGStrategy(None))
        repo.commit_write_group()
        repo.unlock()
        repo.lock_read()
        self.addCleanup(repo.unlock)
        repo2 = self.make_repository('repo2')
        revision = repo.get_revision('A')
        tree = repo.revision_tree('A')
        signature = repo.get_signature_text('A')
        repo2.lock_write()
        self.addCleanup(repo2.unlock)
        repository.install_revisions(repo2, [(revision, tree, signature)])
        self.assertEqual(revision, repo2.get_revision('A'))
        self.assertEqual(signature, repo2.get_signature_text('A'))

    # XXX: this helper duplicated from tests.test_repository
    def make_remote_repository(self, path, shared=False):
        """Make a RemoteRepository object backed by a real repository that will
        be created at the given path."""
        repo = self.make_repository(path, shared=shared)
        smart_server = test_server.SmartTCPServer_for_testing()
        self.start_server(smart_server, self.get_server())
        remote_transport = transport.get_transport(
            smart_server.get_url()).clone(path)
        remote_bzrdir = bzrdir.BzrDir.open_from_transport(remote_transport)
        remote_repo = remote_bzrdir.open_repository()
        return remote_repo

    def test_sprout_from_hpss_preserves_format(self):
        """repo.sprout from a smart server preserves the repository format."""
        remote_repo = self.make_remote_repository('remote')
        local_bzrdir = self.make_bzrdir('local')
        try:
            local_repo = remote_repo.sprout(local_bzrdir)
        except errors.TransportNotPossible:
            raise tests.TestNotApplicable(
                "Cannot lock_read old formats like AllInOne over HPSS.")
        remote_backing_repo = bzrdir.BzrDir.open(
            self.get_vfs_only_url('remote')).open_repository()
        self.assertEqual(remote_backing_repo._format, local_repo._format)

    def test_sprout_branch_from_hpss_preserves_repo_format(self):
        """branch.sprout from a smart server preserves the repository format.
        """
        from bzrlib.plugins.weave_fmt.repository import (
            RepositoryFormat5, RepositoryFormat6, RepositoryFormat7)
        weave_formats = [RepositoryFormat5(),
                         RepositoryFormat6(),
                         RepositoryFormat7()]
        if self.repository_format in weave_formats:
            raise tests.TestNotApplicable(
                "Cannot fetch weaves over smart protocol.")
        remote_repo = self.make_remote_repository('remote')
        remote_branch = remote_repo.bzrdir.create_branch()
        try:
            local_bzrdir = remote_branch.bzrdir.sprout('local')
        except errors.TransportNotPossible:
            raise tests.TestNotApplicable(
                "Cannot lock_read old formats like AllInOne over HPSS.")
        local_repo = local_bzrdir.open_repository()
        remote_backing_repo = bzrdir.BzrDir.open(
            self.get_vfs_only_url('remote')).open_repository()
        self.assertEqual(remote_backing_repo._format, local_repo._format)

    def test_sprout_branch_from_hpss_preserves_shared_repo_format(self):
        """branch.sprout from a smart server preserves the repository format of
        a branch from a shared repository.
        """
        from bzrlib.plugins.weave_fmt.repository import (
            RepositoryFormat5, RepositoryFormat6, RepositoryFormat7)
        weave_formats = [RepositoryFormat5(),
                         RepositoryFormat6(),
                         RepositoryFormat7()]
        if self.repository_format in weave_formats:
            raise tests.TestNotApplicable(
                "Cannot fetch weaves over smart protocol.")
        # Make a shared repo
        remote_repo = self.make_remote_repository('remote', shared=True)
        remote_backing_repo = bzrdir.BzrDir.open(
            self.get_vfs_only_url('remote')).open_repository()
        # Make a branch in that repo in an old format that isn't the default
        # branch format for the repo.
        from bzrlib.branch import BzrBranchFormat5
        format = remote_backing_repo.bzrdir.cloning_metadir()
        format._branch_format = BzrBranchFormat5()
        remote_transport = remote_repo.bzrdir.root_transport.clone('branch')
        remote_backing_repo.bzrdir.create_branch_convenience(
            remote_transport.base, force_new_repo=False, format=format)
        remote_branch = bzrdir.BzrDir.open_from_transport(
            remote_transport).open_branch()
        try:
            local_bzrdir = remote_branch.bzrdir.sprout('local')
        except errors.TransportNotPossible:
            raise tests.TestNotApplicable(
                "Cannot lock_read old formats like AllInOne over HPSS.")
        local_repo = local_bzrdir.open_repository()
        self.assertEqual(remote_backing_repo._format, local_repo._format)

    def test_clone_to_hpss(self):
        from bzrlib.plugins.weave_fmt.repository import (
            RepositoryFormat5,
            RepositoryFormat6,
            )
        pre_metadir_formats = [RepositoryFormat5(),
                               RepositoryFormat6()]
        if self.repository_format in pre_metadir_formats:
            raise tests.TestNotApplicable(
                "Cannot lock pre_metadir_formats remotely.")
        remote_transport = self.make_smart_server('remote')
        local_branch = self.make_branch('local')
        remote_branch = local_branch.create_clone_on_transport(remote_transport)
        self.assertEqual(
            local_branch.repository._format.supports_external_lookups,
            remote_branch.repository._format.supports_external_lookups)

    def test_clone_stacking_policy_upgrades(self):
        """Cloning an unstackable branch format to somewhere with a default
        stack-on branch upgrades branch and repo to match the target and honour
        the policy.
        """
        try:
            repo = self.make_repository('repo', shared=True)
        except errors.IncompatibleFormat:
            raise tests.TestNotApplicable('Cannot make a shared repository')
        from bzrlib.plugins.weave_fmt.bzrdir import BzrDirPreSplitOut
        if isinstance(repo.bzrdir, BzrDirPreSplitOut):
            raise tests.KnownFailure(
                "pre metadir branches do not upgrade on push "
                "with stacking policy")
        if isinstance(repo._format,
                      pack_repo.RepositoryFormatKnitPack5RichRootBroken):
            raise tests.TestNotApplicable("unsupported format")
        # Make a source branch in 'repo' in an unstackable branch format
        bzrdir_format = self.repository_format._matchingbzrdir
        transport = self.get_transport('repo/branch')
        transport.mkdir('.')
        target_bzrdir = bzrdir_format.initialize_on_transport(transport)
        branch = _mod_branch.BzrBranchFormat6().initialize(target_bzrdir)
        # Ensure that stack_on will be stackable and match the serializer of
        # repo.
        if isinstance(repo, remote.RemoteRepository):
            repo._ensure_real()
            info_repo = repo._real_repository
        else:
            info_repo = repo
        format_description = info.describe_format(info_repo.bzrdir,
            info_repo, None, None)
        formats = format_description.split(' or ')
        stack_on_format = formats[0]
        if stack_on_format in ["pack-0.92", "dirstate", "metaweave"]:
            stack_on_format = "1.9"
        elif stack_on_format in ["dirstate-with-subtree", "rich-root",
            "rich-root-pack", "pack-0.92-subtree"]:
            stack_on_format = "1.9-rich-root"
        # formats not tested for above are already stackable, so we can use the
        # format as-is.
        stack_on = self.make_branch('stack-on-me', format=stack_on_format)
        self.make_bzrdir('.').get_config().set_default_stack_on('stack-on-me')
        target = branch.bzrdir.clone(self.get_url('target'))
        # The target branch supports stacking.
        self.assertTrue(target.open_branch()._format.supports_stacking())
        if isinstance(repo, remote.RemoteRepository):
            repo._ensure_real()
            repo = repo._real_repository
        target_repo = target.open_repository()
        if isinstance(target_repo, remote.RemoteRepository):
            target_repo._ensure_real()
            target_repo = target_repo._real_repository
        # The repository format is unchanged if it could already stack, or the
        # same as the stack on.
        if repo._format.supports_external_lookups:
            self.assertEqual(repo._format, target_repo._format)
        else:
            self.assertEqual(stack_on.repository._format, target_repo._format)

    def test__get_sink(self):
        repo = self.make_repository('repo')
        sink = repo._get_sink()
        self.assertIsInstance(sink, repository.StreamSink)

    def test__make_parents_provider(self):
        """Repositories must have a _make_parents_provider method that returns
        an object with a get_parent_map method.
        """
        repo = self.make_repository('repo')
        repo._make_parents_provider().get_parent_map

    def make_repository_and_foo_bar(self, shared):
        made_control = self.make_bzrdir('repository')
        repo = made_control.create_repository(shared=shared)
        bzrdir.BzrDir.create_branch_convenience(self.get_url('repository/foo'),
                                                force_new_repo=False)
        bzrdir.BzrDir.create_branch_convenience(self.get_url('repository/bar'),
                                                force_new_repo=True)
        baz = self.make_bzrdir('repository/baz')
        qux = self.make_branch('repository/baz/qux')
        quxx = self.make_branch('repository/baz/qux/quxx')
        return repo

    def test_find_branches(self):
        repo = self.make_repository_and_foo_bar(shared=False)
        branches = repo.find_branches()
        self.assertContainsRe(branches[-1].base, 'repository/foo/$')
        self.assertContainsRe(branches[-3].base, 'repository/baz/qux/$')
        self.assertContainsRe(branches[-2].base, 'repository/baz/qux/quxx/$')
        # in some formats, creating a repo creates a branch
        if len(branches) == 6:
            self.assertContainsRe(branches[-4].base, 'repository/baz/$')
            self.assertContainsRe(branches[-5].base, 'repository/bar/$')
            self.assertContainsRe(branches[-6].base, 'repository/$')
        else:
            self.assertEqual(4, len(branches))
            self.assertContainsRe(branches[-4].base, 'repository/bar/$')

    def test_find_branches_using(self):
        try:
            repo = self.make_repository_and_foo_bar(shared=True)
        except errors.IncompatibleFormat:
            raise tests.TestNotApplicable
        branches = repo.find_branches(using=True)
        self.assertContainsRe(branches[-1].base, 'repository/foo/$')
        # in some formats, creating a repo creates a branch
        if len(branches) == 2:
            self.assertContainsRe(branches[-2].base, 'repository/$')
        else:
            self.assertEqual(1, len(branches))

    def test_find_branches_using_standalone(self):
        branch = self.make_branch('branch')
        contained = self.make_branch('branch/contained')
        branches = branch.repository.find_branches(using=True)
        self.assertEqual([branch.base], [b.base for b in branches])
        branches = branch.repository.find_branches(using=False)
        self.assertEqual([branch.base, contained.base],
                         [b.base for b in branches])

    def test_find_branches_using_empty_standalone_repo(self):
        repo = self.make_repository('repo')
        self.assertFalse(repo.is_shared())
        try:
            repo.bzrdir.open_branch()
        except errors.NotBranchError:
            self.assertEqual([], repo.find_branches(using=True))
        else:
            self.assertEqual([repo.bzrdir.root_transport.base],
                             [b.base for b in repo.find_branches(using=True)])

    def test_set_get_make_working_trees_true(self):
        repo = self.make_repository('repo')
        try:
            repo.set_make_working_trees(True)
        except errors.RepositoryUpgradeRequired, e:
            raise tests.TestNotApplicable('Format does not support this flag.')
        self.assertTrue(repo.make_working_trees())

    def test_set_get_make_working_trees_false(self):
        repo = self.make_repository('repo')
        try:
            repo.set_make_working_trees(False)
        except errors.RepositoryUpgradeRequired, e:
            raise tests.TestNotApplicable('Format does not support this flag.')
        self.assertFalse(repo.make_working_trees())


class TestRepositoryLocking(per_repository.TestCaseWithRepository):

    def test_leave_lock_in_place(self):
        repo = self.make_repository('r')
        # Lock the repository, then use leave_lock_in_place so that when we
        # unlock the repository the lock is still held on disk.
        token = repo.lock_write().repository_token
        try:
            if token is None:
                # This test does not apply, because this repository refuses lock
                # tokens.
                self.assertRaises(NotImplementedError, repo.leave_lock_in_place)
                return
            repo.leave_lock_in_place()
        finally:
            repo.unlock()
        # We should be unable to relock the repo.
        self.assertRaises(errors.LockContention, repo.lock_write)
        # Cleanup
        repo.lock_write(token)
        repo.dont_leave_lock_in_place()
        repo.unlock()

    def test_dont_leave_lock_in_place(self):
        repo = self.make_repository('r')
        # Create a lock on disk.
        token = repo.lock_write().repository_token
        try:
            if token is None:
                # This test does not apply, because this repository refuses lock
                # tokens.
                self.assertRaises(NotImplementedError,
                                  repo.dont_leave_lock_in_place)
                return
            try:
                repo.leave_lock_in_place()
            except NotImplementedError:
                # This repository doesn't support this API.
                return
        finally:
            repo.unlock()
        # Reacquire the lock (with a different repository object) by using the
        # token.
        new_repo = repo.bzrdir.open_repository()
        new_repo.lock_write(token=token)
        # Call dont_leave_lock_in_place, so that the lock will be released by
        # this instance, even though the lock wasn't originally acquired by it.
        new_repo.dont_leave_lock_in_place()
        new_repo.unlock()
        # Now the repository is unlocked.  Test this by locking it (without a
        # token).
        repo.lock_write()
        repo.unlock()

    def test_lock_read_then_unlock(self):
        # Calling lock_read then unlocking should work without errors.
        repo = self.make_repository('r')
        repo.lock_read()
        repo.unlock()

    def test_lock_read_returns_unlockable(self):
        repo = self.make_repository('r')
        self.assertThat(repo.lock_read, ReturnsUnlockable(repo))

    def test_lock_write_returns_unlockable(self):
        repo = self.make_repository('r')
        self.assertThat(repo.lock_write, ReturnsUnlockable(repo))


class TestCaseWithComplexRepository(per_repository.TestCaseWithRepository):

    def setUp(self):
        super(TestCaseWithComplexRepository, self).setUp()
        tree_a = self.make_branch_and_tree('a')
        self.bzrdir = tree_a.branch.bzrdir
        # add a corrupt inventory 'orphan'
        # this may need some generalising for knits.
        tree_a.lock_write()
        try:
            tree_a.branch.repository.start_write_group()
            try:
                inv_file = tree_a.branch.repository.inventories
                inv_file.add_lines(('orphan',), [], [])
            except:
                tree_a.branch.repository.commit_write_group()
                raise
            else:
                tree_a.branch.repository.abort_write_group()
        finally:
            tree_a.unlock()
        # add a real revision 'rev1'
        tree_a.commit('rev1', rev_id='rev1', allow_pointless=True)
        # add a real revision 'rev2' based on rev1
        tree_a.commit('rev2', rev_id='rev2', allow_pointless=True)
        # add a reference to a ghost
        tree_a.add_parent_tree_id('ghost1')
        try:
            tree_a.commit('rev3', rev_id='rev3', allow_pointless=True)
        except errors.RevisionNotPresent:
            raise tests.TestNotApplicable(
                "Cannot test with ghosts for this format.")
        # add another reference to a ghost, and a second ghost.
        tree_a.add_parent_tree_id('ghost1')
        tree_a.add_parent_tree_id('ghost2')
        tree_a.commit('rev4', rev_id='rev4', allow_pointless=True)

    def test_revision_trees(self):
        revision_ids = ['rev1', 'rev2', 'rev3', 'rev4']
        repository = self.bzrdir.open_repository()
        repository.lock_read()
        self.addCleanup(repository.unlock)
        trees1 = list(repository.revision_trees(revision_ids))
        trees2 = [repository.revision_tree(t) for t in revision_ids]
        self.assertEqual(len(trees1), len(trees2))
        for tree1, tree2 in zip(trees1, trees2):
            self.assertFalse(tree2.changes_from(tree1).has_changed())

    def test_get_deltas_for_revisions(self):
        repository = self.bzrdir.open_repository()
        repository.lock_read()
        self.addCleanup(repository.unlock)
        revisions = [repository.get_revision(r) for r in
                     ['rev1', 'rev2', 'rev3', 'rev4']]
        deltas1 = list(repository.get_deltas_for_revisions(revisions))
        deltas2 = [repository.get_revision_delta(r.revision_id) for r in
                   revisions]
        self.assertEqual(deltas1, deltas2)

    def test_all_revision_ids(self):
        # all_revision_ids -> all revisions
        self.assertEqual(set(['rev1', 'rev2', 'rev3', 'rev4']),
            set(self.bzrdir.open_repository().all_revision_ids()))

    def test_get_ancestry_missing_revision(self):
        # get_ancestry(revision that is in some data but not fully installed
        # -> NoSuchRevision
        self.assertRaises(errors.NoSuchRevision,
                          self.bzrdir.open_repository().get_ancestry, 'orphan')

    def test_get_unordered_ancestry(self):
        repo = self.bzrdir.open_repository()
        self.assertEqual(set(repo.get_ancestry('rev3')),
                         set(repo.get_ancestry('rev3', topo_sorted=False)))

    def test_reserved_id(self):
        repo = self.make_repository('repository')
        repo.lock_write()
        repo.start_write_group()
        try:
            self.assertRaises(errors.ReservedId, repo.add_inventory, 'reserved:',
                              None, None)
            self.assertRaises(errors.ReservedId, repo.add_inventory_by_delta,
                "foo", [], 'reserved:', None)
            self.assertRaises(errors.ReservedId, repo.add_revision, 'reserved:',
                              None)
        finally:
            repo.abort_write_group()
            repo.unlock()


class TestCaseWithCorruptRepository(per_repository.TestCaseWithRepository):

    def setUp(self):
        super(TestCaseWithCorruptRepository, self).setUp()
        # a inventory with no parents and the revision has parents..
        # i.e. a ghost.
        repo = self.make_repository('inventory_with_unnecessary_ghost')
        repo.lock_write()
        repo.start_write_group()
        inv = inventory.Inventory(revision_id = 'ghost')
        inv.root.revision = 'ghost'
        if repo.supports_rich_root():
            root_id = inv.root.file_id
            repo.texts.add_lines((root_id, 'ghost'), [], [])
        sha1 = repo.add_inventory('ghost', inv, [])
        rev = _mod_revision.Revision(
            timestamp=0, timezone=None, committer="Foo Bar <foo@example.com>",
            message="Message", inventory_sha1=sha1, revision_id='ghost')
        rev.parent_ids = ['the_ghost']
        try:
            repo.add_revision('ghost', rev)
        except (errors.NoSuchRevision, errors.RevisionNotPresent):
            raise tests.TestNotApplicable(
                "Cannot test with ghosts for this format.")

        inv = inventory.Inventory(revision_id = 'the_ghost')
        inv.root.revision = 'the_ghost'
        if repo.supports_rich_root():
            root_id = inv.root.file_id
            repo.texts.add_lines((root_id, 'the_ghost'), [], [])
        sha1 = repo.add_inventory('the_ghost', inv, [])
        rev = _mod_revision.Revision(
            timestamp=0, timezone=None, committer="Foo Bar <foo@example.com>",
            message="Message", inventory_sha1=sha1, revision_id='the_ghost')
        rev.parent_ids = []
        repo.add_revision('the_ghost', rev)
        # check its setup usefully
        inv_weave = repo.inventories
        possible_parents = (None, (('ghost',),))
        self.assertSubset(inv_weave.get_parent_map([('ghost',)])[('ghost',)],
            possible_parents)
        repo.commit_write_group()
        repo.unlock()

    def test_corrupt_revision_access_asserts_if_reported_wrong(self):
        repo_url = self.get_url('inventory_with_unnecessary_ghost')
        repo = repository.Repository.open(repo_url)
        reported_wrong = False
        try:
            if repo.get_ancestry('ghost') != [None, 'the_ghost', 'ghost']:
                reported_wrong = True
        except errors.CorruptRepository:
            # caught the bad data:
            return
        if not reported_wrong:
            return
        self.assertRaises(errors.CorruptRepository, repo.get_revision, 'ghost')

    def test_corrupt_revision_get_revision_reconcile(self):
        repo_url = self.get_url('inventory_with_unnecessary_ghost')
        repo = repository.Repository.open(repo_url)
        repo.get_revision_reconcile('ghost')


# FIXME: document why this is a TestCaseWithTransport rather than a
#        TestCaseWithRepository
class TestEscaping(tests.TestCaseWithTransport):
    """Test that repositories can be stored correctly on VFAT transports.

    Makes sure we have proper escaping of invalid characters, etc.

    It'd be better to test all operations on the FakeVFATTransportDecorator,
    but working trees go straight to the os not through the Transport layer.
    Therefore we build some history first in the regular way and then
    check it's safe to access for vfat.
    """

    def test_on_vfat(self):
        # dont bother with remote repository testing, because this test is
        # about local disk layout/support.
        if isinstance(self.repository_format, remote.RemoteRepositoryFormat):
            return
        self.transport_server = test_server.FakeVFATServer
        FOO_ID = 'foo<:>ID'
        REV_ID = 'revid-1'
        # this makes a default format repository always, which is wrong:
        # it should be a TestCaseWithRepository in order to get the
        # default format.
        wt = self.make_branch_and_tree('repo')
        self.build_tree(["repo/foo"], line_endings='binary')
        # add file with id containing wierd characters
        wt.add(['foo'], [FOO_ID])
        wt.commit('this is my new commit', rev_id=REV_ID)
        # now access over vfat; should be safe
        branch = bzrdir.BzrDir.open(self.get_url('repo')).open_branch()
        revtree = branch.repository.revision_tree(REV_ID)
        revtree.lock_read()
        self.addCleanup(revtree.unlock)
        contents = revtree.get_file_text(FOO_ID)
        self.assertEqual(contents, 'contents of repo/foo\n')

    def test_create_bundle(self):
        wt = self.make_branch_and_tree('repo')
        self.build_tree(['repo/file1'])
        wt.add('file1')
        wt.commit('file1', rev_id='rev1')
        fileobj = StringIO()
        wt.branch.repository.create_bundle(
            'rev1', _mod_revision.NULL_REVISION, fileobj)




class TestRepositoryControlComponent(per_repository.TestCaseWithRepository):
    """Repository implementations adequately implement ControlComponent."""
    
    def test_urls(self):
        repo = self.make_repository('repo')
        self.assertIsInstance(repo.user_url, str)
        self.assertEqual(repo.user_url, repo.user_transport.base)
        # for all current bzrdir implementations the user dir must be 
        # above the control dir but we might need to relax that?
        self.assertEqual(repo.control_url.find(repo.user_url), 0)
        self.assertEqual(repo.control_url, repo.control_transport.base)
