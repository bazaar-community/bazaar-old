# Copyright (C) 2007 Canonical Ltd
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

"""Tests for repository write groups."""

import sys

from bzrlib import (
    bzrdir,
    errors,
    graph,
    memorytree,
    osutils,
    remote,
    versionedfile,
    )
from bzrlib.branch import BzrBranchFormat7
from bzrlib.transport import local, memory
from bzrlib.tests import TestNotApplicable
from bzrlib.tests.per_repository import TestCaseWithRepository


class TestWriteGroup(TestCaseWithRepository):

    def test_start_write_group_unlocked_needs_write_lock(self):
        repo = self.make_repository('.')
        self.assertRaises(errors.NotWriteLocked, repo.start_write_group)

    def test_start_write_group_read_locked_needs_write_lock(self):
        repo = self.make_repository('.')
        repo.lock_read()
        try:
            self.assertRaises(errors.NotWriteLocked, repo.start_write_group)
        finally:
            repo.unlock()

    def test_start_write_group_write_locked_gets_None(self):
        repo = self.make_repository('.')
        repo.lock_write()
        self.assertEqual(None, repo.start_write_group())
        repo.commit_write_group()
        repo.unlock()

    def test_start_write_group_twice_errors(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        try:
            # don't need a specific exception for now - this is
            # really to be sure it's used right, not for signalling
            # semantic information.
            self.assertRaises(errors.BzrError, repo.start_write_group)
        finally:
            repo.commit_write_group()
            repo.unlock()

    def test_commit_write_group_does_not_error(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        # commit_write_group can either return None (for repositories without
        # isolated transactions) or a hint for pack(). So we only check it
        # works in this interface test, because all repositories are exercised.
        repo.commit_write_group()
        repo.unlock()

    def test_unlock_in_write_group(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        # don't need a specific exception for now - this is
        # really to be sure it's used right, not for signalling
        # semantic information.
        self.assertLogsError(errors.BzrError, repo.unlock)
        # after this error occurs, the repository is unlocked, and the write
        # group is gone.  you've had your chance, and you blew it. ;-)
        self.assertFalse(repo.is_locked())
        self.assertRaises(errors.BzrError, repo.commit_write_group)
        self.assertRaises(errors.BzrError, repo.unlock)

    def test_is_in_write_group(self):
        repo = self.make_repository('.')
        self.assertFalse(repo.is_in_write_group())
        repo.lock_write()
        repo.start_write_group()
        self.assertTrue(repo.is_in_write_group())
        repo.commit_write_group()
        self.assertFalse(repo.is_in_write_group())
        # abort also removes the in_write_group status.
        repo.start_write_group()
        self.assertTrue(repo.is_in_write_group())
        repo.abort_write_group()
        self.assertFalse(repo.is_in_write_group())
        repo.unlock()

    def test_abort_write_group_gets_None(self):
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        self.assertEqual(None, repo.abort_write_group())
        repo.unlock()

    def test_abort_write_group_does_not_raise_when_suppressed(self):
        if self.transport_server is local.LocalURLServer:
            self.transport_server = None
        self.vfs_transport_factory = memory.MemoryServer
        repo = self.make_repository('repo')
        token = repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        # Damage the repository on the filesystem
        t = self.get_transport('')
        t.rename('repo', 'foo')
        self.addCleanup(t.rename, 'foo', 'repo')
        # abort_write_group will not raise an error, because either an
        # exception was not generated, or the exception was caught and
        # suppressed.  See also test_pack_repository's test of the same name.
        self.assertEqual(None, repo.abort_write_group(suppress_errors=True))


class TestGetMissingParentInventories(TestCaseWithRepository):

    def test_empty_get_missing_parent_inventories(self):
        """A new write group has no missing parent inventories."""
        repo = self.make_repository('.')
        repo.lock_write()
        repo.start_write_group()
        try:
            self.assertEqual(set(), set(repo.get_missing_parent_inventories()))
        finally:
            repo.commit_write_group()
            repo.unlock()

    def branch_trunk_and_make_tree(self, trunk_repo, relpath):
        tree = self.make_branch_and_memory_tree('branch')
        trunk_repo.lock_read()
        self.addCleanup(trunk_repo.unlock)
        tree.branch.repository.fetch(trunk_repo, revision_id='rev-1')
        tree.set_parent_ids(['rev-1'])
        return tree 

    def make_first_commit(self, repo):
        trunk = repo.bzrdir.create_branch()
        tree = memorytree.MemoryTree.create_on_branch(trunk)
        tree.lock_write()
        tree.add([''], ['TREE_ROOT'], ['directory'])
        tree.add(['dir'], ['dir-id'], ['directory'])
        tree.add(['filename'], ['file-id'], ['file'])
        tree.put_file_bytes_non_atomic('file-id', 'content\n')
        tree.commit('Trunk commit', rev_id='rev-0')
        tree.commit('Trunk commit', rev_id='rev-1')
        tree.unlock()

    def make_new_commit_in_new_repo(self, trunk_repo, parents=None):
        tree = self.branch_trunk_and_make_tree(trunk_repo, 'branch')
        tree.set_parent_ids(parents)
        tree.commit('Branch commit', rev_id='rev-2')
        branch_repo = tree.branch.repository
        branch_repo.lock_read()
        self.addCleanup(branch_repo.unlock)
        return branch_repo

    def make_stackable_repo(self, relpath='trunk'):
        if isinstance(self.repository_format, remote.RemoteRepositoryFormat):
            # RemoteRepository by default builds a default format real
            # repository, but the default format is unstackble.  So explicitly
            # make a stackable real repository and use that.
            repo = self.make_repository(relpath, format='1.9')
            repo = bzrdir.BzrDir.open(self.get_url(relpath)).open_repository()
        else:
            repo = self.make_repository(relpath)
        if not repo._format.supports_external_lookups:
            raise TestNotApplicable('format not stackable')
        repo.bzrdir._format.set_branch_format(BzrBranchFormat7())
        return repo

    def reopen_repo_and_resume_write_group(self, repo):
        try:
            resume_tokens = repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup:
            # If we got this far, and this repo does not support resuming write
            # groups, then get_missing_parent_inventories works in all
            # cases this repo supports.
            repo.unlock()
            return
        repo.unlock()
        reopened_repo = repo.bzrdir.open_repository()
        reopened_repo.lock_write()
        self.addCleanup(reopened_repo.unlock)
        reopened_repo.resume_write_group(resume_tokens)
        return reopened_repo

    def test_ghost_revision(self):
        """A parent inventory may be absent if all the needed texts are present.
        i.e., a ghost revision isn't (necessarily) considered to be a missing
        parent inventory.
        """
        # Make a trunk with one commit.
        trunk_repo = self.make_stackable_repo()
        self.make_first_commit(trunk_repo)
        trunk_repo.lock_read()
        self.addCleanup(trunk_repo.unlock)
        # Branch the trunk, add a new commit.
        branch_repo = self.make_new_commit_in_new_repo(
            trunk_repo, parents=['rev-1', 'ghost-rev'])
        inv = branch_repo.get_inventory('rev-2')
        # Make a new repo stacked on trunk, and then copy into it:
        #  - all texts in rev-2
        #  - the new inventory (rev-2)
        #  - the new revision (rev-2)
        repo = self.make_stackable_repo('stacked')
        repo.lock_write()
        repo.start_write_group()
        # Add all texts from in rev-2 inventory.  Note that this has to exclude
        # the root if the repo format does not support rich roots.
        rich_root = branch_repo._format.rich_root_data
        all_texts = [
            (ie.file_id, ie.revision) for ie in inv.iter_just_entries()
             if rich_root or inv.id2path(ie.file_id) != '']
        repo.texts.insert_record_stream(
            branch_repo.texts.get_record_stream(all_texts, 'unordered', False))
        # Add inventory and revision for rev-2.
        repo.add_inventory('rev-2', inv, ['rev-1', 'ghost-rev'])
        repo.revisions.insert_record_stream(
            branch_repo.revisions.get_record_stream(
                [('rev-2',)], 'unordered', False))
        # Now, no inventories are reported as missing, even though there is a
        # ghost.
        self.assertEqual(set(), repo.get_missing_parent_inventories())
        # Resuming the write group does not affect
        # get_missing_parent_inventories.
        reopened_repo = self.reopen_repo_and_resume_write_group(repo)
        self.assertEqual(set(), reopened_repo.get_missing_parent_inventories())
        reopened_repo.abort_write_group()

    def test_get_missing_parent_inventories(self):
        """A stacked repo with a single revision and inventory (no parent
        inventory) in it must have all the texts in its inventory (even if not
        changed w.r.t. to the absent parent), otherwise it will report missing
        texts/parent inventory.

        The core of this test is that a file was changed in rev-1, but in a
        stacked repo that only has rev-2
        """
        # Make a trunk with one commit.
        trunk_repo = self.make_stackable_repo()
        self.make_first_commit(trunk_repo)
        trunk_repo.lock_read()
        self.addCleanup(trunk_repo.unlock)
        # Branch the trunk, add a new commit.
        branch_repo = self.make_new_commit_in_new_repo(
            trunk_repo, parents=['rev-1'])
        inv = branch_repo.get_inventory('rev-2')
        # Make a new repo stacked on trunk, and copy the new commit's revision
        # and inventory records to it.
        repo = self.make_stackable_repo('stacked')
        repo.lock_write()
        repo.start_write_group()
        # Insert a single fulltext inv (using add_inventory because it's
        # simpler than insert_record_stream)
        repo.add_inventory('rev-2', inv, ['rev-1'])
        repo.revisions.insert_record_stream(
            branch_repo.revisions.get_record_stream(
                [('rev-2',)], 'unordered', False))
        # There should be no missing compression parents
        self.assertEqual(set(),
                repo.inventories.get_missing_compression_parent_keys())
        self.assertEqual(
            set([('inventories', 'rev-1')]),
            repo.get_missing_parent_inventories())
        # Resuming the write group does not affect
        # get_missing_parent_inventories.
        reopened_repo = self.reopen_repo_and_resume_write_group(repo)
        self.assertEqual(
            set([('inventories', 'rev-1')]),
            reopened_repo.get_missing_parent_inventories())
        # Adding the parent inventory satisfies get_missing_parent_inventories.
        reopened_repo.inventories.insert_record_stream(
            branch_repo.inventories.get_record_stream(
                [('rev-1',)], 'unordered', False))
        self.assertEqual(
            set(), reopened_repo.get_missing_parent_inventories())
        reopened_repo.abort_write_group()

    def test_get_missing_parent_inventories_check(self):
        builder = self.make_branch_builder('test')
        builder.build_snapshot('A-id', ['ghost-parent-id'], [
            ('add', ('', 'root-id', 'directory', None)),
            ('add', ('file', 'file-id', 'file', 'content\n'))],
            allow_leftmost_as_ghost=True)
        b = builder.get_branch()
        b.lock_read()
        self.addCleanup(b.unlock)
        repo = self.make_repository('test-repo')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        self.addCleanup(repo.abort_write_group)
        # Now, add the objects manually
        text_keys = [('file-id', 'A-id')]
        if repo.supports_rich_root():
            text_keys.append(('root-id', 'A-id'))
        # Directly add the texts, inventory, and revision object for 'A-id'
        repo.texts.insert_record_stream(b.repository.texts.get_record_stream(
            text_keys, 'unordered', True))
        repo.add_revision('A-id', b.repository.get_revision('A-id'),
                          b.repository.get_inventory('A-id'))
        get_missing = repo.get_missing_parent_inventories
        if repo._format.supports_external_lookups:
            self.assertEqual(set([('inventories', 'ghost-parent-id')]),
                get_missing(check_for_missing_texts=False))
            self.assertEqual(set(), get_missing(check_for_missing_texts=True))
            self.assertEqual(set(), get_missing())
        else:
            # If we don't support external lookups, we always return empty
            self.assertEqual(set(), get_missing(check_for_missing_texts=False))
            self.assertEqual(set(), get_missing(check_for_missing_texts=True))
            self.assertEqual(set(), get_missing())

    def test_insert_stream_passes_resume_info(self):
        repo = self.make_repository('test-repo')
        if (not repo._format.supports_external_lookups or
            isinstance(repo, remote.RemoteRepository)):
            raise TestNotApplicable(
                'only valid for direct connections to resumable repos')
        # log calls to get_missing_parent_inventories, so that we can assert it
        # is called with the correct parameters
        call_log = []
        orig = repo.get_missing_parent_inventories
        def get_missing(check_for_missing_texts=True):
            call_log.append(check_for_missing_texts)
            return orig(check_for_missing_texts=check_for_missing_texts)
        repo.get_missing_parent_inventories = get_missing
        repo.lock_write()
        self.addCleanup(repo.unlock)
        sink = repo._get_sink()
        sink.insert_stream((), repo._format, [])
        self.assertEqual([False], call_log)
        del call_log[:]
        repo.start_write_group()
        # We need to insert something, or suspend_write_group won't actually
        # create a token
        repo.texts.insert_record_stream([versionedfile.FulltextContentFactory(
            ('file-id', 'rev-id'), (), None, 'lines\n')])
        tokens = repo.suspend_write_group()
        self.assertNotEqual([], tokens)
        sink.insert_stream((), repo._format, tokens)
        self.assertEqual([True], call_log)


class TestResumeableWriteGroup(TestCaseWithRepository):

    def make_write_locked_repo(self, relpath='repo'):
        repo = self.make_repository(relpath)
        repo.lock_write()
        self.addCleanup(repo.unlock)
        return repo

    def reopen_repo(self, repo):
        same_repo = repo.bzrdir.open_repository()
        same_repo.lock_write()
        self.addCleanup(same_repo.unlock)
        return same_repo

    def require_suspendable_write_groups(self, reason):
        repo = self.make_repository('__suspend_test')
        repo.lock_write()
        self.addCleanup(repo.unlock)
        repo.start_write_group()
        try:
            wg_tokens = repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup:
            repo.abort_write_group()
            raise TestNotApplicable(reason)

    def test_suspend_write_group(self):
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        repo.texts.add_lines(('file-id', 'revid'), (), ['lines'])
        try:
            wg_tokens = repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup:
            # The contract for repos that don't support suspending write groups
            # is that suspend_write_group raises UnsuspendableWriteGroup, but
            # is otherwise a no-op.  So we can still e.g. abort the write group
            # as usual.
            self.assertTrue(repo.is_in_write_group())
            repo.abort_write_group()
        else:
            # After suspending a write group we are no longer in a write group
            self.assertFalse(repo.is_in_write_group())
            # suspend_write_group returns a list of tokens, which are strs.  If
            # no other write groups were resumed, there will only be one token.
            self.assertEqual(1, len(wg_tokens))
            self.assertIsInstance(wg_tokens[0], str)
            # See also test_pack_repository's test of the same name.

    def test_resume_write_group_then_abort(self):
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        try:
            wg_tokens = repo.suspend_write_group()
        except errors.UnsuspendableWriteGroup:
            # If the repo does not support suspending write groups, it doesn't
            # support resuming them either.
            repo.abort_write_group()
            self.assertRaises(
                errors.UnsuspendableWriteGroup, repo.resume_write_group, [])
        else:
            #self.assertEqual([], list(repo.texts.keys()))
            same_repo = self.reopen_repo(repo)
            same_repo.resume_write_group(wg_tokens)
            self.assertEqual([text_key], list(same_repo.texts.keys()))
            self.assertTrue(same_repo.is_in_write_group())
            same_repo.abort_write_group()
            self.assertEqual([], list(repo.texts.keys()))
            # See also test_pack_repository's test of the same name.

    def test_multiple_resume_write_group(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        first_key = ('file-id', 'revid')
        repo.texts.add_lines(first_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        self.assertTrue(same_repo.is_in_write_group())
        second_key = ('file-id', 'second-revid')
        same_repo.texts.add_lines(second_key, (first_key,), ['more lines'])
        try:
            new_wg_tokens = same_repo.suspend_write_group()
        except:
            e = sys.exc_info()
            same_repo.abort_write_group(suppress_errors=True)
            raise e[0], e[1], e[2]
        self.assertEqual(2, len(new_wg_tokens))
        self.assertSubset(wg_tokens, new_wg_tokens)
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(new_wg_tokens)
        both_keys = set([first_key, second_key])
        self.assertEqual(both_keys, same_repo.texts.keys())
        same_repo.abort_write_group()

    def test_no_op_suspend_resume(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        new_wg_tokens = same_repo.suspend_write_group()
        self.assertEqual(wg_tokens, new_wg_tokens)
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        self.assertEqual([text_key], list(same_repo.texts.keys()))
        same_repo.abort_write_group()

    def test_read_after_suspend_fails(self):
        self.require_suspendable_write_groups(
            'Cannot test suspend on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        self.assertEqual([], list(repo.texts.keys()))

    def test_read_after_second_suspend_fails(self):
        self.require_suspendable_write_groups(
            'Cannot test suspend on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.suspend_write_group()
        self.assertEqual([], list(same_repo.texts.keys()))

    def test_read_after_resume_abort_fails(self):
        self.require_suspendable_write_groups(
            'Cannot test suspend on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.abort_write_group()
        self.assertEqual([], list(same_repo.texts.keys()))

    def test_cannot_resume_aborted_write_group(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.abort_write_group()
        same_repo = self.reopen_repo(repo)
        self.assertRaises(
            errors.UnresumableWriteGroup, same_repo.resume_write_group,
            wg_tokens)

    def test_commit_resumed_write_group_no_new_data(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        same_repo.commit_write_group()
        self.assertEqual([text_key], list(same_repo.texts.keys()))
        self.assertEqual(
            'lines', same_repo.texts.get_record_stream([text_key],
                'unordered', True).next().get_bytes_as('fulltext'))
        self.assertRaises(
            errors.UnresumableWriteGroup, same_repo.resume_write_group,
            wg_tokens)

    def test_commit_resumed_write_group_plus_new_data(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        first_key = ('file-id', 'revid')
        repo.texts.add_lines(first_key, (), ['lines'])
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        second_key = ('file-id', 'second-revid')
        same_repo.texts.add_lines(second_key, (first_key,), ['more lines'])
        same_repo.commit_write_group()
        self.assertEqual(
            set([first_key, second_key]), set(same_repo.texts.keys()))
        self.assertEqual(
            'lines', same_repo.texts.get_record_stream([first_key],
                'unordered', True).next().get_bytes_as('fulltext'))
        self.assertEqual(
            'more lines', same_repo.texts.get_record_stream([second_key],
                'unordered', True).next().get_bytes_as('fulltext'))

    def make_source_with_delta_record(self):
        # Make a source repository with a delta record in it.
        source_repo = self.make_write_locked_repo('source')
        source_repo.start_write_group()
        key_base = ('file-id', 'base')
        key_delta = ('file-id', 'delta')
        def text_stream():
            yield versionedfile.FulltextContentFactory(
                key_base, (), None, 'lines\n')
            yield versionedfile.FulltextContentFactory(
                key_delta, (key_base,), None, 'more\nlines\n')
        source_repo.texts.insert_record_stream(text_stream())
        source_repo.commit_write_group()
        return source_repo

    def test_commit_resumed_write_group_with_missing_parents(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        source_repo = self.make_source_with_delta_record()
        key_base = ('file-id', 'base')
        key_delta = ('file-id', 'delta')
        # Start a write group, insert just a delta.
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        stream = source_repo.texts.get_record_stream(
            [key_delta], 'unordered', False)
        repo.texts.insert_record_stream(stream)
        # It's either not commitable due to the missing compression parent, or
        # the stacked location has already filled in the fulltext.
        try:
            repo.commit_write_group()
        except errors.BzrCheckError:
            # It refused to commit because we have a missing parent
            pass
        else:
            same_repo = self.reopen_repo(repo)
            same_repo.lock_read()
            record = same_repo.texts.get_record_stream([key_delta],
                                                       'unordered', True).next()
            self.assertEqual('more\nlines\n', record.get_bytes_as('fulltext'))
            return
        # Merely suspending and resuming doesn't make it commitable either.
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        self.assertRaises(
            errors.BzrCheckError, same_repo.commit_write_group)
        same_repo.abort_write_group()

    def test_commit_resumed_write_group_adding_missing_parents(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        source_repo = self.make_source_with_delta_record()
        key_base = ('file-id', 'base')
        key_delta = ('file-id', 'delta')
        # Start a write group.
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        # Add some content so this isn't an empty write group (which may return
        # 0 tokens)
        text_key = ('file-id', 'revid')
        repo.texts.add_lines(text_key, (), ['lines'])
        # Suspend it, then resume it.
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        # Add a record with a missing compression parent
        stream = source_repo.texts.get_record_stream(
            [key_delta], 'unordered', False)
        same_repo.texts.insert_record_stream(stream)
        # Just like if we'd added that record without a suspend/resume cycle,
        # commit_write_group fails.
        try:
            same_repo.commit_write_group()
        except errors.BzrCheckError:
            pass
        else:
            # If the commit_write_group didn't fail, that is because the
            # insert_record_stream already gave it a fulltext.
            same_repo = self.reopen_repo(repo)
            same_repo.lock_read()
            record = same_repo.texts.get_record_stream([key_delta],
                                                       'unordered', True).next()
            self.assertEqual('more\nlines\n', record.get_bytes_as('fulltext'))
            return
        same_repo.abort_write_group()

    def test_add_missing_parent_after_resume(self):
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        source_repo = self.make_source_with_delta_record()
        key_base = ('file-id', 'base')
        key_delta = ('file-id', 'delta')
        # Start a write group, insert just a delta.
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        stream = source_repo.texts.get_record_stream(
            [key_delta], 'unordered', False)
        repo.texts.insert_record_stream(stream)
        # Suspend it, then resume it.
        wg_tokens = repo.suspend_write_group()
        same_repo = self.reopen_repo(repo)
        same_repo.resume_write_group(wg_tokens)
        # Fill in the missing compression parent.
        stream = source_repo.texts.get_record_stream(
            [key_base], 'unordered', False)
        same_repo.texts.insert_record_stream(stream)
        same_repo.commit_write_group()

    def test_suspend_empty_initial_write_group(self):
        """Suspending a write group with no writes returns an empty token
        list.
        """
        self.require_suspendable_write_groups(
            'Cannot test suspend on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.start_write_group()
        wg_tokens = repo.suspend_write_group()
        self.assertEqual([], wg_tokens)

    def test_suspend_empty_initial_write_group(self):
        """Resuming an empty token list is equivalent to start_write_group."""
        self.require_suspendable_write_groups(
            'Cannot test resume on repo that does not support suspending')
        repo = self.make_write_locked_repo()
        repo.resume_write_group([])
        repo.abort_write_group()


