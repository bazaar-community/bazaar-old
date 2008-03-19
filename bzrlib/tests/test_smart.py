# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests for the smart wire/domain protocol.

This module contains tests for the domain-level smart requests and responses,
such as the 'Branch.lock_write' request. Many of these use specific disk
formats to exercise calls that only make sense for formats with specific
properties.

Tests for low-level protocol encoding are found in test_smart_transport.
"""

import bz2
from StringIO import StringIO
import tempfile
import tarfile

from bzrlib import bzrdir, errors, pack, smart, tests
from bzrlib.smart.request import (
    FailedSmartServerResponse,
    SmartServerResponse,
    SuccessfulSmartServerResponse,
    )
import bzrlib.smart.bzrdir
import bzrlib.smart.branch
import bzrlib.smart.repository
from bzrlib.tests import (
    iter_suite_tests,
    split_suite_by_re,
    TestScenarioApplier,
    )
from bzrlib.util import bencode


def load_tests(standard_tests, module, loader):
    """Multiply tests version and protocol consistency."""
    # FindRepository tests.
    bzrdir_mod = bzrlib.smart.bzrdir
    applier = TestScenarioApplier()
    applier.scenarios = [
        ("find_repository", {
            "_request_class":bzrdir_mod.SmartServerRequestFindRepositoryV1}),
        ("find_repositoryV2", {
            "_request_class":bzrdir_mod.SmartServerRequestFindRepositoryV2}),
        ]
    to_adapt, result = split_suite_by_re(standard_tests,
        "TestSmartServerRequestFindRepository")
    v2_only, v1_and_2 = split_suite_by_re(to_adapt,
        "_v2")
    for test in iter_suite_tests(v1_and_2):
        result.addTests(applier.adapt(test))
    del applier.scenarios[0]
    for test in iter_suite_tests(v2_only):
        result.addTests(applier.adapt(test))
    return result


class TestCaseWithSmartMedium(tests.TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithSmartMedium, self).setUp()
        # We're allowed to set  the transport class here, so that we don't use
        # the default or a parameterized class, but rather use the
        # TestCaseWithTransport infrastructure to set up a smart server and
        # transport.
        self.transport_server = smart.server.SmartTCPServer_for_testing

    def get_smart_medium(self):
        """Get a smart medium to use in tests."""
        return self.get_transport().get_smart_medium()


class TestSmartServerResponse(tests.TestCase):

    def test__eq__(self):
        self.assertEqual(SmartServerResponse(('ok', )),
            SmartServerResponse(('ok', )))
        self.assertEqual(SmartServerResponse(('ok', ), 'body'),
            SmartServerResponse(('ok', ), 'body'))
        self.assertNotEqual(SmartServerResponse(('ok', )),
            SmartServerResponse(('notok', )))
        self.assertNotEqual(SmartServerResponse(('ok', ), 'body'),
            SmartServerResponse(('ok', )))
        self.assertNotEqual(None,
            SmartServerResponse(('ok', )))


class TestSmartServerRequestFindRepository(tests.TestCaseWithTransport):
    """Tests for BzrDir.find_repository."""

    def test_no_repository(self):
        """When there is no repository to be found, ('norepository', ) is returned."""
        backing = self.get_transport()
        request = self._request_class(backing)
        self.make_bzrdir('.')
        self.assertEqual(SmartServerResponse(('norepository', )),
            request.execute(backing.local_abspath('')))

    def test_nonshared_repository(self):
        # nonshared repositorys only allow 'find' to return a handle when the 
        # path the repository is being searched on is the same as that that 
        # the repository is at.
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result()
        self.assertEqual(result, request.execute(backing.local_abspath('')))
        self.make_bzrdir('subdir')
        self.assertEqual(SmartServerResponse(('norepository', )),
            request.execute(backing.local_abspath('subdir')))

    def _make_repository_and_result(self, shared=False, format=None):
        """Convenience function to setup a repository.

        :result: The SmartServerResponse to expect when opening it.
        """
        repo = self.make_repository('.', shared=shared, format=format)
        if repo.supports_rich_root():
            rich_root = 'yes'
        else:
            rich_root = 'no'
        if repo._format.supports_tree_reference:
            subtrees = 'yes'
        else:
            subtrees = 'no'
        if (smart.bzrdir.SmartServerRequestFindRepositoryV2 ==
            self._request_class):
            # All tests so far are on formats, and for non-external
            # repositories.
            return SuccessfulSmartServerResponse(
                ('ok', '', rich_root, subtrees, 'no'))
        else:
            return SuccessfulSmartServerResponse(('ok', '', rich_root, subtrees))

    def test_shared_repository(self):
        """When there is a shared repository, we get 'ok', 'relpath-to-repo'."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(shared=True)
        self.assertEqual(result, request.execute(backing.local_abspath('')))
        self.make_bzrdir('subdir')
        result2 = SmartServerResponse(result.args[0:1] + ('..', ) + result.args[2:])
        self.assertEqual(result2,
            request.execute(backing.local_abspath('subdir')))
        self.make_bzrdir('subdir/deeper')
        result3 = SmartServerResponse(result.args[0:1] + ('../..', ) + result.args[2:])
        self.assertEqual(result3,
            request.execute(backing.local_abspath('subdir/deeper')))

    def test_rich_root_and_subtree_encoding(self):
        """Test for the format attributes for rich root and subtree support."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(format='dirstate-with-subtree')
        # check the test will be valid
        self.assertEqual('yes', result.args[2])
        self.assertEqual('yes', result.args[3])
        self.assertEqual(result, request.execute(backing.local_abspath('')))

    def test_supports_external_lookups_no_v2(self):
        """Test for the supports_external_lookups attribute."""
        backing = self.get_transport()
        request = self._request_class(backing)
        result = self._make_repository_and_result(format='dirstate-with-subtree')
        # check the test will be valid
        self.assertEqual('no', result.args[4])
        self.assertEqual(result, request.execute(backing.local_abspath('')))


class TestSmartServerRequestInitializeBzrDir(tests.TestCaseWithTransport):

    def test_empty_dir(self):
        """Initializing an empty dir should succeed and do it."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestInitializeBzrDir(backing)
        self.assertEqual(SmartServerResponse(('ok', )),
            request.execute(backing.local_abspath('.')))
        made_dir = bzrdir.BzrDir.open_from_transport(backing)
        # no branch, tree or repository is expected with the current 
        # default formart.
        self.assertRaises(errors.NoWorkingTree, made_dir.open_workingtree)
        self.assertRaises(errors.NotBranchError, made_dir.open_branch)
        self.assertRaises(errors.NoRepositoryPresent, made_dir.open_repository)

    def test_missing_dir(self):
        """Initializing a missing directory should fail like the bzrdir api."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestInitializeBzrDir(backing)
        self.assertRaises(errors.NoSuchFile,
            request.execute, backing.local_abspath('subdir'))

    def test_initialized_dir(self):
        """Initializing an extant bzrdir should fail like the bzrdir api."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestInitializeBzrDir(backing)
        self.make_bzrdir('subdir')
        self.assertRaises(errors.FileExists,
            request.execute, backing.local_abspath('subdir'))


class TestSmartServerRequestOpenBranch(tests.TestCaseWithTransport):

    def test_no_branch(self):
        """When there is no branch, ('nobranch', ) is returned."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestOpenBranch(backing)
        self.make_bzrdir('.')
        self.assertEqual(SmartServerResponse(('nobranch', )),
            request.execute(backing.local_abspath('')))

    def test_branch(self):
        """When there is a branch, 'ok' is returned."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestOpenBranch(backing)
        self.make_branch('.')
        self.assertEqual(SmartServerResponse(('ok', '')),
            request.execute(backing.local_abspath('')))

    def test_branch_reference(self):
        """When there is a branch reference, the reference URL is returned."""
        backing = self.get_transport()
        request = smart.bzrdir.SmartServerRequestOpenBranch(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        # TODO: once we have an API to probe for references of any sort, we
        # can use it here.
        reference_url = backing.abspath('branch') + '/'
        self.assertFileEqual(reference_url, 'reference/.bzr/branch/location')
        self.assertEqual(SmartServerResponse(('ok', reference_url)),
            request.execute(backing.local_abspath('reference')))


class TestSmartServerRequestRevisionHistory(tests.TestCaseWithTransport):

    def test_empty(self):
        """For an empty branch, the body is empty."""
        backing = self.get_transport()
        request = smart.branch.SmartServerRequestRevisionHistory(backing)
        self.make_branch('.')
        self.assertEqual(SmartServerResponse(('ok', ), ''),
            request.execute(backing.local_abspath('')))

    def test_not_empty(self):
        """For a non-empty branch, the body is empty."""
        backing = self.get_transport()
        request = smart.branch.SmartServerRequestRevisionHistory(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8'.encode('utf-8'))
        tree.unlock()
        self.assertEqual(
            SmartServerResponse(('ok', ), ('\x00'.join([r1, r2]))),
            request.execute(backing.local_abspath('')))


class TestSmartServerBranchRequest(tests.TestCaseWithTransport):

    def test_no_branch(self):
        """When there is a bzrdir and no branch, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequest(backing)
        self.make_bzrdir('.')
        self.assertRaises(errors.NotBranchError,
            request.execute, backing.local_abspath(''))

    def test_branch_reference(self):
        """When there is a branch reference, NotBranchError is raised."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequest(backing)
        branch = self.make_branch('branch')
        checkout = branch.create_checkout('reference',lightweight=True)
        self.assertRaises(errors.NotBranchError,
            request.execute, backing.local_abspath('checkout'))


class TestSmartServerBranchRequestLastRevisionInfo(tests.TestCaseWithTransport):

    def test_empty(self):
        """For an empty branch, the result is ('ok', '0', 'null:')."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLastRevisionInfo(backing)
        self.make_branch('.')
        self.assertEqual(SmartServerResponse(('ok', '0', 'null:')),
            request.execute(backing.local_abspath('')))

    def test_not_empty(self):
        """For a non-empty branch, the result is ('ok', 'revno', 'revid')."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLastRevisionInfo(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=rev_id_utf8)
        tree.unlock()
        self.assertEqual(
            SmartServerResponse(('ok', '2', rev_id_utf8)),
            request.execute(backing.local_abspath('')))


class TestSmartServerBranchRequestGetConfigFile(tests.TestCaseWithTransport):

    def test_default(self):
        """With no file, we get empty content."""
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchGetConfigFile(backing)
        branch = self.make_branch('.')
        # there should be no file by default
        content = ''
        self.assertEqual(SmartServerResponse(('ok', ), content),
            request.execute(backing.local_abspath('')))

    def test_with_content(self):
        # SmartServerBranchGetConfigFile should return the content from
        # branch.control_files.get('branch.conf') for now - in the future it may
        # perform more complex processing. 
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchGetConfigFile(backing)
        branch = self.make_branch('.')
        branch.control_files.put_utf8('branch.conf', 'foo bar baz')
        self.assertEqual(SmartServerResponse(('ok', ), 'foo bar baz'),
            request.execute(backing.local_abspath('')))


class TestSmartServerBranchRequestSetLastRevision(tests.TestCaseWithTransport):

    def test_empty(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestSetLastRevision(backing)
        b = self.make_branch('.')
        branch_token = b.lock_write()
        repo_token = b.repository.lock_write()
        b.repository.unlock()
        try:
            self.assertEqual(SmartServerResponse(('ok',)),
                request.execute(
                    backing.local_abspath(''), branch_token, repo_token,
                    'null:'))
        finally:
            b.unlock()

    def test_not_present_revision_id(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestSetLastRevision(backing)
        b = self.make_branch('.')
        branch_token = b.lock_write()
        repo_token = b.repository.lock_write()
        b.repository.unlock()
        try:
            revision_id = 'non-existent revision'
            self.assertEqual(
                SmartServerResponse(('NoSuchRevision', revision_id)),
                request.execute(
                    backing.local_abspath(''), branch_token, repo_token,
                    revision_id))
        finally:
            b.unlock()

    def test_revision_id_present(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestSetLastRevision(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        r1 = tree.commit('1st commit', rev_id=rev_id_utf8)
        r2 = tree.commit('2nd commit')
        tree.unlock()
        branch_token = tree.branch.lock_write()
        repo_token = tree.branch.repository.lock_write()
        tree.branch.repository.unlock()
        try:
            self.assertEqual(
                SmartServerResponse(('ok',)),
                request.execute(
                    backing.local_abspath(''), branch_token, repo_token,
                    rev_id_utf8))
            self.assertEqual([rev_id_utf8], tree.branch.revision_history())
        finally:
            tree.branch.unlock()

    def test_revision_id_present2(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestSetLastRevision(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc8'.encode('utf-8')
        r1 = tree.commit('1st commit', rev_id=rev_id_utf8)
        r2 = tree.commit('2nd commit')
        tree.unlock()
        tree.branch.set_revision_history([])
        branch_token = tree.branch.lock_write()
        repo_token = tree.branch.repository.lock_write()
        tree.branch.repository.unlock()
        try:
            self.assertEqual(
                SmartServerResponse(('ok',)),
                request.execute(
                    backing.local_abspath(''), branch_token, repo_token,
                    rev_id_utf8))
            self.assertEqual([rev_id_utf8], tree.branch.revision_history())
        finally:
            tree.branch.unlock()


class TestSmartServerBranchRequestLockWrite(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)

    def test_lock_write_on_unlocked_branch(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        repository = branch.repository
        response = request.execute(backing.local_abspath(''))
        branch_nonce = branch.control_files._lock.peek().get('nonce')
        repository_nonce = repository.control_files._lock.peek().get('nonce')
        self.assertEqual(
            SmartServerResponse(('ok', branch_nonce, repository_nonce)),
            response)
        # The branch (and associated repository) is now locked.  Verify that
        # with a new branch object.
        new_branch = repository.bzrdir.open_branch()
        self.assertRaises(errors.LockContention, new_branch.lock_write)

    def test_lock_write_on_locked_branch(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.')
        branch.lock_write()
        branch.leave_lock_in_place()
        branch.unlock()
        response = request.execute(backing.local_abspath(''))
        self.assertEqual(
            SmartServerResponse(('LockContention',)), response)

    def test_lock_write_with_tokens_on_locked_branch(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        branch_token = branch.lock_write()
        repo_token = branch.repository.lock_write()
        branch.repository.unlock()
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute(backing.local_abspath(''),
                                   branch_token, repo_token)
        self.assertEqual(
            SmartServerResponse(('ok', branch_token, repo_token)), response)

    def test_lock_write_with_mismatched_tokens_on_locked_branch(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        branch_token = branch.lock_write()
        repo_token = branch.repository.lock_write()
        branch.repository.unlock()
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute(backing.local_abspath(''),
                                   branch_token+'xxx', repo_token)
        self.assertEqual(
            SmartServerResponse(('TokenMismatch',)), response)

    def test_lock_write_on_locked_repo(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.', format='knit')
        branch.repository.lock_write()
        branch.repository.leave_lock_in_place()
        branch.repository.unlock()
        response = request.execute(backing.local_abspath(''))
        self.assertEqual(
            SmartServerResponse(('LockContention',)), response)

    def test_lock_write_on_readonly_transport(self):
        backing = self.get_readonly_transport()
        request = smart.branch.SmartServerBranchRequestLockWrite(backing)
        branch = self.make_branch('.')
        response = request.execute('')
        error_name, lock_str, why_str = response.args
        self.assertFalse(response.is_successful())
        self.assertEqual('LockFailed', error_name)


class TestSmartServerBranchRequestUnlock(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)

    def test_unlock_on_locked_branch_and_repo(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch('.', format='knit')
        # Lock the branch
        branch_token = branch.lock_write()
        repo_token = branch.repository.lock_write()
        branch.repository.unlock()
        # Unlock the branch (and repo) object, leaving the physical locks
        # in place.
        branch.leave_lock_in_place()
        branch.repository.leave_lock_in_place()
        branch.unlock()
        response = request.execute(backing.local_abspath(''),
                                   branch_token, repo_token)
        self.assertEqual(
            SmartServerResponse(('ok',)), response)
        # The branch is now unlocked.  Verify that with a new branch
        # object.
        new_branch = branch.bzrdir.open_branch()
        new_branch.lock_write()
        new_branch.unlock()

    def test_unlock_on_unlocked_branch_unlocked_repo(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch('.', format='knit')
        response = request.execute(
            backing.local_abspath(''), 'branch token', 'repo token')
        self.assertEqual(
            SmartServerResponse(('TokenMismatch',)), response)

    def test_unlock_on_unlocked_branch_locked_repo(self):
        backing = self.get_transport()
        request = smart.branch.SmartServerBranchRequestUnlock(backing)
        branch = self.make_branch('.', format='knit')
        # Lock the repository.
        repo_token = branch.repository.lock_write()
        branch.repository.leave_lock_in_place()
        branch.repository.unlock()
        # Issue branch lock_write request on the unlocked branch (with locked
        # repo).
        response = request.execute(
            backing.local_abspath(''), 'branch token', repo_token)
        self.assertEqual(
            SmartServerResponse(('TokenMismatch',)), response)


class TestSmartServerRepositoryRequest(tests.TestCaseWithTransport):

    def test_no_repository(self):
        """Raise NoRepositoryPresent when there is a bzrdir and no repo."""
        # we test this using a shared repository above the named path,
        # thus checking the right search logic is used - that is, that
        # its the exact path being looked at and the server is not
        # searching.
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryRequest(backing)
        self.make_repository('.', shared=True)
        self.make_bzrdir('subdir')
        self.assertRaises(errors.NoRepositoryPresent,
            request.execute, backing.local_abspath('subdir'))


class TestSmartServerRepositoryGetParentMap(tests.TestCaseWithTransport):

    def test_trivial_bzipped(self):
        # This tests that the wire encoding is actually bzipped
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetParentMap(backing)
        tree = self.make_branch_and_memory_tree('.')

        self.assertEqual(None,
            request.execute(backing.local_abspath(''), 'missing-id'))
        # Note that it returns a body (of '' bzipped).
        self.assertEqual(
            SuccessfulSmartServerResponse(('ok', ), bz2.compress('')),
            request.do_body('\n\n0\n'))


class TestSmartServerRepositoryGetRevisionGraph(tests.TestCaseWithTransport):

    def test_none_argument(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        r2 = tree.commit('2nd commit', rev_id=u'\xc8'.encode('utf-8'))
        tree.unlock()

        # the lines of revision_id->revision_parent_list has no guaranteed
        # order coming out of a dict, so sort both our test and response
        lines = sorted([' '.join([r2, r1]), r1])
        response = request.execute(backing.local_abspath(''), '')
        response.body = '\n'.join(sorted(response.body.split('\n')))

        self.assertEqual(
            SmartServerResponse(('ok', ), '\n'.join(lines)), response)

    def test_specific_revision_argument(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc9'.encode('utf-8')
        r1 = tree.commit('1st commit', rev_id=rev_id_utf8)
        r2 = tree.commit('2nd commit', rev_id=u'\xc8'.encode('utf-8'))
        tree.unlock()

        self.assertEqual(SmartServerResponse(('ok', ), rev_id_utf8),
            request.execute(backing.local_abspath(''), rev_id_utf8))
    
    def test_no_such_revision(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGetRevisionGraph(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        r1 = tree.commit('1st commit')
        tree.unlock()

        # Note that it still returns body (of zero bytes).
        self.assertEqual(
            SmartServerResponse(('nosuchrevision', 'missingrevision', ), ''),
            request.execute(backing.local_abspath(''), 'missingrevision'))


class TestSmartServerRequestHasRevision(tests.TestCaseWithTransport):

    def test_missing_revision(self):
        """For a missing revision, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRequestHasRevision(backing)
        self.make_repository('.')
        self.assertEqual(SmartServerResponse(('no', )),
            request.execute(backing.local_abspath(''), 'revid'))

    def test_present_revision(self):
        """For a present revision, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRequestHasRevision(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id_utf8 = u'\xc8abc'.encode('utf-8')
        r1 = tree.commit('a commit', rev_id=rev_id_utf8)
        tree.unlock()
        self.assertTrue(tree.branch.repository.has_revision(rev_id_utf8))
        self.assertEqual(SmartServerResponse(('yes', )),
            request.execute(backing.local_abspath(''), rev_id_utf8))


class TestSmartServerRepositoryGatherStats(tests.TestCaseWithTransport):

    def test_empty_revid(self):
        """With an empty revid, we get only size an number and revisions"""
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryGatherStats(backing)
        repository = self.make_repository('.')
        stats = repository.gather_stats()
        size = stats['size']
        expected_body = 'revisions: 0\nsize: %d\n' % size
        self.assertEqual(SmartServerResponse(('ok', ), expected_body),
                         request.execute(backing.local_abspath(''), '', 'no'))

    def test_revid_with_committers(self):
        """For a revid we get more infos."""
        backing = self.get_transport()
        rev_id_utf8 = u'\xc8abc'.encode('utf-8')
        request = smart.repository.SmartServerRepositoryGatherStats(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        # Let's build a predictable result
        tree.commit('a commit', timestamp=123456.2, timezone=3600)
        tree.commit('a commit', timestamp=654321.4, timezone=0,
                    rev_id=rev_id_utf8)
        tree.unlock()

        stats = tree.branch.repository.gather_stats()
        size = stats['size']
        expected_body = ('firstrev: 123456.200 3600\n'
                         'latestrev: 654321.400 0\n'
                         'revisions: 2\n'
                         'size: %d\n' % size)
        self.assertEqual(SmartServerResponse(('ok', ), expected_body),
                         request.execute(backing.local_abspath(''),
                                         rev_id_utf8, 'no'))

    def test_not_empty_repository_with_committers(self):
        """For a revid and requesting committers we get the whole thing."""
        backing = self.get_transport()
        rev_id_utf8 = u'\xc8abc'.encode('utf-8')
        request = smart.repository.SmartServerRepositoryGatherStats(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        # Let's build a predictable result
        tree.commit('a commit', timestamp=123456.2, timezone=3600,
                    committer='foo')
        tree.commit('a commit', timestamp=654321.4, timezone=0,
                    committer='bar', rev_id=rev_id_utf8)
        tree.unlock()
        stats = tree.branch.repository.gather_stats()

        size = stats['size']
        expected_body = ('committers: 2\n'
                         'firstrev: 123456.200 3600\n'
                         'latestrev: 654321.400 0\n'
                         'revisions: 2\n'
                         'size: %d\n' % size)
        self.assertEqual(SmartServerResponse(('ok', ), expected_body),
                         request.execute(backing.local_abspath(''),
                                         rev_id_utf8, 'yes'))


class TestSmartServerRepositoryIsShared(tests.TestCaseWithTransport):

    def test_is_shared(self):
        """For a shared repository, ('yes', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryIsShared(backing)
        self.make_repository('.', shared=True)
        self.assertEqual(SmartServerResponse(('yes', )),
            request.execute(backing.local_abspath(''), ))

    def test_is_not_shared(self):
        """For a shared repository, ('no', ) is returned."""
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryIsShared(backing)
        self.make_repository('.', shared=False)
        self.assertEqual(SmartServerResponse(('no', )),
            request.execute(backing.local_abspath(''), ))


class TestSmartServerRepositoryLockWrite(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)

    def test_lock_write_on_unlocked_repo(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository('.', format='knit')
        response = request.execute(backing.local_abspath(''))
        nonce = repository.control_files._lock.peek().get('nonce')
        self.assertEqual(SmartServerResponse(('ok', nonce)), response)
        # The repository is now locked.  Verify that with a new repository
        # object.
        new_repo = repository.bzrdir.open_repository()
        self.assertRaises(errors.LockContention, new_repo.lock_write)

    def test_lock_write_on_locked_repo(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository('.', format='knit')
        repository.lock_write()
        repository.leave_lock_in_place()
        repository.unlock()
        response = request.execute(backing.local_abspath(''))
        self.assertEqual(
            SmartServerResponse(('LockContention',)), response)

    def test_lock_write_on_readonly_transport(self):
        backing = self.get_readonly_transport()
        request = smart.repository.SmartServerRepositoryLockWrite(backing)
        repository = self.make_repository('.', format='knit')
        response = request.execute('')
        self.assertFalse(response.is_successful())
        self.assertEqual('LockFailed', response.args[0])


class TestSmartServerRepositoryUnlock(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)

    def test_unlock_on_locked_repo(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryUnlock(backing)
        repository = self.make_repository('.', format='knit')
        token = repository.lock_write()
        repository.leave_lock_in_place()
        repository.unlock()
        response = request.execute(backing.local_abspath(''), token)
        self.assertEqual(
            SmartServerResponse(('ok',)), response)
        # The repository is now unlocked.  Verify that with a new repository
        # object.
        new_repo = repository.bzrdir.open_repository()
        new_repo.lock_write()
        new_repo.unlock()

    def test_unlock_on_unlocked_repo(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryUnlock(backing)
        repository = self.make_repository('.', format='knit')
        response = request.execute(backing.local_abspath(''), 'some token')
        self.assertEqual(
            SmartServerResponse(('TokenMismatch',)), response)


class TestSmartServerRepositoryTarball(tests.TestCaseWithTransport):

    def test_repository_tarball(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryTarball(backing)
        repository = self.make_repository('.')
        # make some extraneous junk in the repository directory which should
        # not be copied
        self.build_tree(['.bzr/repository/extra-junk'])
        response = request.execute(backing.local_abspath(''), 'bz2')
        self.assertEqual(('ok',), response.args)
        # body should be a tbz2
        body_file = StringIO(response.body)
        body_tar = tarfile.open('body_tar.tbz2', fileobj=body_file,
            mode='r|bz2')
        # let's make sure there are some key repository components inside it.
        # the tarfile returns directories with trailing slashes...
        names = set([n.rstrip('/') for n in body_tar.getnames()])
        self.assertTrue('.bzr/repository/lock' in names)
        self.assertTrue('.bzr/repository/format' in names)
        self.assertTrue('.bzr/repository/extra-junk' not in names,
            "extraneous file present in tar file")


class TestSmartServerRepositoryStreamKnitData(tests.TestCaseWithTransport):

    def test_fetch_revisions(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryStreamKnitDataForRevisions(backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id1_utf8 = u'\xc8'.encode('utf-8')
        rev_id2_utf8 = u'\xc9'.encode('utf-8')
        r1 = tree.commit('1st commit', rev_id=rev_id1_utf8)
        r1 = tree.commit('2nd commit', rev_id=rev_id2_utf8)
        tree.unlock()

        response = request.execute(backing.local_abspath(''), rev_id2_utf8)
        self.assertEqual(('ok',), response.args)
        from cStringIO import StringIO
        unpacker = pack.ContainerReader(StringIO(response.body))
        names = []
        for [name], read_bytes in unpacker.iter_records():
            names.append(name)
            bytes = read_bytes(None)
            # The bytes should be a valid bencoded string.
            bencode.bdecode(bytes)
            # XXX: assert that the bencoded knit records have the right
            # contents?
        
    def test_no_such_revision_error(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryStreamKnitDataForRevisions(backing)
        repo = self.make_repository('.')
        rev_id1_utf8 = u'\xc8'.encode('utf-8')
        response = request.execute(backing.local_abspath(''), rev_id1_utf8)
        self.assertEqual(
            SmartServerResponse(('NoSuchRevision', rev_id1_utf8)),
            response)


class TestSmartServerRepositoryStreamRevisionsChunked(tests.TestCaseWithTransport):

    def test_fetch_revisions(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryStreamRevisionsChunked(
            backing)
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('')
        rev_id1_utf8 = u'\xc8'.encode('utf-8')
        rev_id2_utf8 = u'\xc9'.encode('utf-8')
        tree.commit('1st commit', rev_id=rev_id1_utf8)
        tree.commit('2nd commit', rev_id=rev_id2_utf8)
        tree.unlock()

        response = request.execute(backing.local_abspath(''))
        self.assertEqual(None, response)
        response = request.do_body("%s\n%s\n1" % (rev_id2_utf8, rev_id1_utf8))
        self.assertEqual(('ok',), response.args)
        from cStringIO import StringIO
        parser = pack.ContainerPushParser()
        names = []
        for stream_bytes in response.body_stream:
            parser.accept_bytes(stream_bytes)
            for [name], record_bytes in parser.read_pending_records():
                names.append(name)
                # The bytes should be a valid bencoded string.
                bencode.bdecode(record_bytes)
                # XXX: assert that the bencoded knit records have the right
                # contents?
        
    def test_no_such_revision_error(self):
        backing = self.get_transport()
        request = smart.repository.SmartServerRepositoryStreamRevisionsChunked(
            backing)
        repo = self.make_repository('.')
        rev_id1_utf8 = u'\xc8'.encode('utf-8')
        response = request.execute(backing.local_abspath(''))
        self.assertEqual(None, response)
        response = request.do_body("%s\n\n1" % (rev_id1_utf8,))
        self.assertEqual(
            FailedSmartServerResponse(('NoSuchRevision', )),
            response)


class TestSmartServerIsReadonly(tests.TestCaseWithTransport):

    def test_is_readonly_no(self):
        backing = self.get_transport()
        request = smart.request.SmartServerIsReadonly(backing)
        response = request.execute()
        self.assertEqual(
            SmartServerResponse(('no',)), response)

    def test_is_readonly_yes(self):
        backing = self.get_readonly_transport()
        request = smart.request.SmartServerIsReadonly(backing)
        response = request.execute()
        self.assertEqual(
            SmartServerResponse(('yes',)), response)


class TestHandlers(tests.TestCase):
    """Tests for the request.request_handlers object."""

    def test_registered_methods(self):
        """Test that known methods are registered to the correct object."""
        self.assertEqual(
            smart.request.request_handlers.get('Branch.get_config_file'),
            smart.branch.SmartServerBranchGetConfigFile)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.lock_write'),
            smart.branch.SmartServerBranchRequestLockWrite)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.last_revision_info'),
            smart.branch.SmartServerBranchRequestLastRevisionInfo)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.revision_history'),
            smart.branch.SmartServerRequestRevisionHistory)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.set_last_revision'),
            smart.branch.SmartServerBranchRequestSetLastRevision)
        self.assertEqual(
            smart.request.request_handlers.get('Branch.unlock'),
            smart.branch.SmartServerBranchRequestUnlock)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDir.find_repository'),
            smart.bzrdir.SmartServerRequestFindRepositoryV1)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDir.find_repositoryV2'),
            smart.bzrdir.SmartServerRequestFindRepositoryV2)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDirFormat.initialize'),
            smart.bzrdir.SmartServerRequestInitializeBzrDir)
        self.assertEqual(
            smart.request.request_handlers.get('BzrDir.open_branch'),
            smart.bzrdir.SmartServerRequestOpenBranch)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.gather_stats'),
            smart.repository.SmartServerRepositoryGatherStats)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.get_parent_map'),
            smart.repository.SmartServerRepositoryGetParentMap)
        self.assertEqual(
            smart.request.request_handlers.get(
                'Repository.get_revision_graph'),
            smart.repository.SmartServerRepositoryGetRevisionGraph)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.has_revision'),
            smart.repository.SmartServerRequestHasRevision)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.is_shared'),
            smart.repository.SmartServerRepositoryIsShared)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.lock_write'),
            smart.repository.SmartServerRepositoryLockWrite)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.tarball'),
            smart.repository.SmartServerRepositoryTarball)
        self.assertEqual(
            smart.request.request_handlers.get('Repository.unlock'),
            smart.repository.SmartServerRepositoryUnlock)
        self.assertEqual(
            smart.request.request_handlers.get('Transport.is_readonly'),
            smart.request.SmartServerIsReadonly)
