# Copyright (C) 2005, 2007, 2008 Canonical Ltd
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


"""Black-box tests for bzr push."""

import re

from bzrlib import (
    branch,
    bzrdir,
    errors,
    osutils,
    tests,
    transport,
    uncommit,
    urlutils,
    workingtree
    )
from bzrlib.repofmt import knitrepo
from bzrlib.tests import http_server
from bzrlib.transport import memory


def load_tests(standard_tests, module, loader):
    """Multiply tests for the push command."""
    result = loader.suiteClass()

    # one for each king of change
    changes_tests, remaining_tests = tests.split_suite_by_condition(
        standard_tests, tests.condition_isinstance((
                TestPushStrictWithChanges,
                )))
    changes_scenarios = [
        ('uncommitted',
         dict(_changes_type= '_uncommitted_changes')),
        ('pending-merges',
         dict(_changes_type= '_pending_merges')),
        ('out-of-sync-trees',
         dict(_changes_type= '_out_of_sync_trees')),
        ]
    tests.multiply_tests(changes_tests, changes_scenarios, result)
    # No parametrization for the remaining tests
    result.addTests(remaining_tests)

    return result


class TestPush(tests.TestCaseWithTransport):

    def test_push_error_on_vfs_http(self):
        """ pushing a branch to a HTTP server fails cleanly. """
        # the trunk is published on a web server
        self.transport_readonly_server = http_server.HttpServer
        self.make_branch('source')
        public_url = self.get_readonly_url('target')
        self.run_bzr_error(['http does not support mkdir'],
                           ['push', public_url],
                           working_dir='source')

    def test_push_remember(self):
        """Push changes from one branch to another and test push location."""
        transport = self.get_transport()
        tree_a = self.make_branch_and_tree('branch_a')
        branch_a = tree_a.branch
        self.build_tree(['branch_a/a'])
        tree_a.add('a')
        tree_a.commit('commit a')
        tree_b = branch_a.bzrdir.sprout('branch_b').open_workingtree()
        branch_b = tree_b.branch
        tree_c = branch_a.bzrdir.sprout('branch_c').open_workingtree()
        branch_c = tree_c.branch
        self.build_tree(['branch_a/b'])
        tree_a.add('b')
        tree_a.commit('commit b')
        self.build_tree(['branch_b/c'])
        tree_b.add('c')
        tree_b.commit('commit c')
        # initial push location must be empty
        self.assertEqual(None, branch_b.get_push_location())

        # test push for failure without push location set
        out = self.run_bzr('push', working_dir='branch_a', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: No push location known or specified.\n'))

        # test not remembered if cannot actually push
        self.run_bzr('push path/which/doesnt/exist',
                     working_dir='branch_a', retcode=3)
        out = self.run_bzr('push', working_dir='branch_a', retcode=3)
        self.assertEquals(
                ('', 'bzr: ERROR: No push location known or specified.\n'),
                out)

        # test implicit --remember when no push location set, push fails
        out = self.run_bzr('push ../branch_b',
                           working_dir='branch_a', retcode=3)
        self.assertEquals(out,
                ('','bzr: ERROR: These branches have diverged.  '
                 'See "bzr help diverged-branches" for more information.\n'))
        self.assertEquals(osutils.abspath(branch_a.get_push_location()),
                          osutils.abspath(branch_b.bzrdir.root_transport.base))

        # test implicit --remember after resolving previous failure
        uncommit.uncommit(branch=branch_b, tree=tree_b)
        transport.delete('branch_b/c')
        out, err = self.run_bzr('push', working_dir='branch_a')
        path = branch_a.get_push_location()
        self.assertEquals(out,
                          'Using saved push location: %s\n'
                          % urlutils.local_path_from_url(path))
        self.assertEqual(err,
                         'All changes applied successfully.\n'
                         'Pushed up to revision 2.\n')
        self.assertEqual(path,
                         branch_b.bzrdir.root_transport.base)
        # test explicit --remember
        self.run_bzr('push ../branch_c --remember', working_dir='branch_a')
        self.assertEquals(branch_a.get_push_location(),
                          branch_c.bzrdir.root_transport.base)

    def test_push_without_tree(self):
        # bzr push from a branch that does not have a checkout should work.
        b = self.make_branch('.')
        out, err = self.run_bzr('push pushed-location')
        self.assertEqual('', out)
        self.assertEqual('Created new branch.\n', err)
        b2 = branch.Branch.open('pushed-location')
        self.assertEndsWith(b2.base, 'pushed-location/')

    def test_push_new_branch_revision_count(self):
        # bzr push of a branch with revisions to a new location
        # should print the number of revisions equal to the length of the
        # local branch.
        t = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        t.add('file')
        t.commit('commit 1')
        out, err = self.run_bzr('push -d tree pushed-to')
        self.assertEqual('', out)
        self.assertEqual('Created new branch.\n', err)

    def test_push_only_pushes_history(self):
        # Knit branches should only push the history for the current revision.
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = knitrepo.RepositoryFormatKnit1()
        shared_repo = self.make_repository('repo', format=format, shared=True)
        shared_repo.set_make_working_trees(True)

        def make_shared_tree(path):
            shared_repo.bzrdir.root_transport.mkdir(path)
            shared_repo.bzrdir.create_branch_convenience('repo/' + path)
            return workingtree.WorkingTree.open('repo/' + path)
        tree_a = make_shared_tree('a')
        self.build_tree(['repo/a/file'])
        tree_a.add('file')
        tree_a.commit('commit a-1', rev_id='a-1')
        f = open('repo/a/file', 'ab')
        f.write('more stuff\n')
        f.close()
        tree_a.commit('commit a-2', rev_id='a-2')

        tree_b = make_shared_tree('b')
        self.build_tree(['repo/b/file'])
        tree_b.add('file')
        tree_b.commit('commit b-1', rev_id='b-1')

        self.assertTrue(shared_repo.has_revision('a-1'))
        self.assertTrue(shared_repo.has_revision('a-2'))
        self.assertTrue(shared_repo.has_revision('b-1'))

        # Now that we have a repository with shared files, make sure
        # that things aren't copied out by a 'push'
        self.run_bzr('push ../../push-b', working_dir='repo/b')
        pushed_tree = workingtree.WorkingTree.open('push-b')
        pushed_repo = pushed_tree.branch.repository
        self.assertFalse(pushed_repo.has_revision('a-1'))
        self.assertFalse(pushed_repo.has_revision('a-2'))
        self.assertTrue(pushed_repo.has_revision('b-1'))

    def test_push_funky_id(self):
        t = self.make_branch_and_tree('tree')
        self.build_tree(['tree/filename'])
        t.add('filename', 'funky-chars<>%&;"\'')
        t.commit('commit filename')
        self.run_bzr('push -d tree new-tree')

    def test_push_dash_d(self):
        t = self.make_branch_and_tree('from')
        t.commit(allow_pointless=True,
                message='first commit')
        self.run_bzr('push -d from to-one')
        self.failUnlessExists('to-one')
        self.run_bzr('push -d %s %s'
            % tuple(map(urlutils.local_path_to_url, ['from', 'to-two'])))
        self.failUnlessExists('to-two')

    def test_push_smart_non_stacked_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('from')
        t.commit(allow_pointless=True, message='first commit')
        self.reset_smart_call_log()
        self.run_bzr(['push', self.get_url('to-one')], working_dir='from')
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(9, self.hpss_calls)

    def test_push_smart_stacked_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        parent = self.make_branch_and_tree('parent', format='1.9')
        parent.commit(message='first commit')
        local = parent.bzrdir.sprout('local').open_workingtree()
        local.commit(message='local commit')
        self.reset_smart_call_log()
        self.run_bzr(['push', '--stacked', '--stacked-on', '../parent',
            self.get_url('public')], working_dir='local')
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(14, self.hpss_calls)
        remote = branch.Branch.open('public')
        self.assertEndsWith(remote.get_stacked_on_url(), '/parent')

    def test_push_smart_tags_streaming_acceptance(self):
        self.setup_smart_server_with_call_log()
        t = self.make_branch_and_tree('from')
        rev_id = t.commit(allow_pointless=True, message='first commit')
        t.branch.tags.set_tag('new-tag', rev_id)
        self.reset_smart_call_log()
        self.run_bzr(['push', self.get_url('to-one')], working_dir='from')
        # This figure represent the amount of work to perform this use case. It
        # is entirely ok to reduce this number if a test fails due to rpc_count
        # being too low. If rpc_count increases, more network roundtrips have
        # become necessary for this use case. Please do not adjust this number
        # upwards without agreement from bzr's network support maintainers.
        self.assertLength(11, self.hpss_calls)

    def test_push_smart_with_default_stacking_url_path_segment(self):
        # If the default stacked-on location is a path element then branches
        # we push there over the smart server are stacked and their
        # stacked_on_url is that exact path segment. Added to nail bug 385132.
        self.setup_smart_server_with_call_log()
        self.make_branch('stack-on', format='1.9')
        self.make_bzrdir('.').get_config().set_default_stack_on(
            '/stack-on')
        self.make_branch('from', format='1.9')
        out, err = self.run_bzr(['push', '-d', 'from', self.get_url('to')])
        b = branch.Branch.open(self.get_url('to'))
        self.assertEqual('/extra/stack-on', b.get_stacked_on_url())

    def test_push_smart_with_default_stacking_relative_path(self):
        # If the default stacked-on location is a relative path then branches
        # we push there over the smart server are stacked and their
        # stacked_on_url is a relative path. Added to nail bug 385132.
        self.setup_smart_server_with_call_log()
        self.make_branch('stack-on', format='1.9')
        self.make_bzrdir('.').get_config().set_default_stack_on('stack-on')
        self.make_branch('from', format='1.9')
        out, err = self.run_bzr(['push', '-d', 'from', self.get_url('to')])
        b = branch.Branch.open(self.get_url('to'))
        self.assertEqual('../stack-on', b.get_stacked_on_url())

    def create_simple_tree(self):
        tree = self.make_branch_and_tree('tree')
        self.build_tree(['tree/a'])
        tree.add(['a'], ['a-id'])
        tree.commit('one', rev_id='r1')
        return tree

    def test_push_create_prefix(self):
        """'bzr push --create-prefix' will create leading directories."""
        tree = self.create_simple_tree()

        self.run_bzr_error(['Parent directory of ../new/tree does not exist'],
                           'push ../new/tree',
                           working_dir='tree')
        self.run_bzr('push ../new/tree --create-prefix',
                     working_dir='tree')
        new_tree = workingtree.WorkingTree.open('new/tree')
        self.assertEqual(tree.last_revision(), new_tree.last_revision())
        self.failUnlessExists('new/tree/a')

    def test_push_use_existing(self):
        """'bzr push --use-existing-dir' can push into an existing dir.

        By default, 'bzr push' will not use an existing, non-versioned dir.
        """
        tree = self.create_simple_tree()
        self.build_tree(['target/'])

        self.run_bzr_error(['Target directory ../target already exists',
                            'Supply --use-existing-dir',
                           ],
                           'push ../target', working_dir='tree')

        self.run_bzr('push --use-existing-dir ../target',
                     working_dir='tree')

        new_tree = workingtree.WorkingTree.open('target')
        self.assertEqual(tree.last_revision(), new_tree.last_revision())
        # The push should have created target/a
        self.failUnlessExists('target/a')

    def test_push_onto_repo(self):
        """We should be able to 'bzr push' into an existing bzrdir."""
        tree = self.create_simple_tree()
        repo = self.make_repository('repo', shared=True)

        self.run_bzr('push ../repo',
                     working_dir='tree')

        # Pushing onto an existing bzrdir will create a repository and
        # branch as needed, but will only create a working tree if there was
        # no BzrDir before.
        self.assertRaises(errors.NoWorkingTree,
                          workingtree.WorkingTree.open, 'repo')
        new_branch = branch.Branch.open('repo')
        self.assertEqual(tree.last_revision(), new_branch.last_revision())

    def test_push_onto_just_bzrdir(self):
        """We don't handle when the target is just a bzrdir.

        Because you shouldn't be able to create *just* a bzrdir in the wild.
        """
        # TODO: jam 20070109 Maybe it would be better to create the repository
        #       if at this point
        tree = self.create_simple_tree()
        a_bzrdir = self.make_bzrdir('dir')

        self.run_bzr_error(['At ../dir you have a valid .bzr control'],
                'push ../dir',
                working_dir='tree')

    def test_push_with_revisionspec(self):
        """We should be able to push a revision older than the tip."""
        tree_from = self.make_branch_and_tree('from')
        tree_from.commit("One.", rev_id="from-1")
        tree_from.commit("Two.", rev_id="from-2")

        self.run_bzr('push -r1 ../to', working_dir='from')

        tree_to = workingtree.WorkingTree.open('to')
        repo_to = tree_to.branch.repository
        self.assertTrue(repo_to.has_revision('from-1'))
        self.assertFalse(repo_to.has_revision('from-2'))
        self.assertEqual(tree_to.branch.last_revision_info()[1], 'from-1')

        self.run_bzr_error(
            ['bzr: ERROR: bzr push --revision '
             'takes exactly one revision identifier\n'],
            'push -r0..2 ../to', working_dir='from')

    def create_trunk_and_feature_branch(self):
        # We have a mainline
        trunk_tree = self.make_branch_and_tree('target',
            format='1.9')
        trunk_tree.commit('mainline')
        # and a branch from it
        branch_tree = self.make_branch_and_tree('branch',
            format='1.9')
        branch_tree.pull(trunk_tree.branch)
        branch_tree.branch.set_parent(trunk_tree.branch.base)
        # with some work on it
        branch_tree.commit('moar work plz')
        return trunk_tree, branch_tree

    def assertPublished(self, branch_revid, stacked_on):
        """Assert that the branch 'published' has been published correctly."""
        published_branch = branch.Branch.open('published')
        # The published branch refers to the mainline
        self.assertEqual(stacked_on, published_branch.get_stacked_on_url())
        # and the branch's work was pushed
        self.assertTrue(published_branch.repository.has_revision(branch_revid))

    def test_push_new_branch_stacked_on(self):
        """Pushing a new branch with --stacked-on creates a stacked branch."""
        trunk_tree, branch_tree = self.create_trunk_and_feature_branch()
        # we publish branch_tree with a reference to the mainline.
        out, err = self.run_bzr(['push', '--stacked-on', trunk_tree.branch.base,
            self.get_url('published')], working_dir='branch')
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
            trunk_tree.branch.base, err)
        self.assertPublished(branch_tree.last_revision(),
            trunk_tree.branch.base)

    def test_push_new_branch_stacked_uses_parent_when_no_public_url(self):
        """When the parent has no public url the parent is used as-is."""
        trunk_tree, branch_tree = self.create_trunk_and_feature_branch()
        # now we do a stacked push, which should determine the public location
        # for us.
        out, err = self.run_bzr(['push', '--stacked',
            self.get_url('published')], working_dir='branch')
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
            trunk_tree.branch.base, err)
        self.assertPublished(branch_tree.last_revision(),
                             trunk_tree.branch.base)

    def test_push_new_branch_stacked_uses_parent_public(self):
        """Pushing a new branch with --stacked creates a stacked branch."""
        trunk_tree, branch_tree = self.create_trunk_and_feature_branch()
        # the trunk is published on a web server
        self.transport_readonly_server = http_server.HttpServer
        trunk_public = self.make_branch('public_trunk', format='1.9')
        trunk_public.pull(trunk_tree.branch)
        trunk_public_url = self.get_readonly_url('public_trunk')
        trunk_tree.branch.set_public_branch(trunk_public_url)
        # now we do a stacked push, which should determine the public location
        # for us.
        out, err = self.run_bzr(['push', '--stacked',
            self.get_url('published')], working_dir='branch')
        self.assertEqual('', out)
        self.assertEqual('Created new stacked branch referring to %s.\n' %
            trunk_public_url, err)
        self.assertPublished(branch_tree.last_revision(), trunk_public_url)

    def test_push_new_branch_stacked_no_parent(self):
        """Pushing with --stacked and no parent branch errors."""
        branch = self.make_branch_and_tree('branch', format='1.9')
        # now we do a stacked push, which should fail as the place to refer too
        # cannot be determined.
        out, err = self.run_bzr_error(
            ['Could not determine branch to refer to\\.'], ['push', '--stacked',
            self.get_url('published')], working_dir='branch')
        self.assertEqual('', out)
        self.assertFalse(self.get_transport('published').has('.'))

    def test_push_notifies_default_stacking(self):
        self.make_branch('stack_on', format='1.6')
        self.make_bzrdir('.').get_config().set_default_stack_on('stack_on')
        self.make_branch('from', format='1.6')
        out, err = self.run_bzr('push -d from to')
        self.assertContainsRe(err,
                              'Using default stacking branch stack_on at .*')

    def test_push_stacks_with_default_stacking_if_target_is_stackable(self):
        self.make_branch('stack_on', format='1.6')
        self.make_bzrdir('.').get_config().set_default_stack_on('stack_on')
        self.make_branch('from', format='pack-0.92')
        out, err = self.run_bzr('push -d from to')
        b = branch.Branch.open('to')
        self.assertEqual('../stack_on', b.get_stacked_on_url())

    def test_push_does_not_change_format_with_default_if_target_cannot(self):
        self.make_branch('stack_on', format='pack-0.92')
        self.make_bzrdir('.').get_config().set_default_stack_on('stack_on')
        self.make_branch('from', format='pack-0.92')
        out, err = self.run_bzr('push -d from to')
        b = branch.Branch.open('to')
        self.assertRaises(errors.UnstackableBranchFormat, b.get_stacked_on_url)

    def test_push_doesnt_create_broken_branch(self):
        """Pushing a new standalone branch works even when there's a default
        stacking policy at the destination.

        The new branch will preserve the repo format (even if it isn't the
        default for the branch), and will be stacked when the repo format
        allows (which means that the branch format isn't necessarly preserved).
        """
        self.make_repository('repo', shared=True, format='1.6')
        builder = self.make_branch_builder('repo/local', format='pack-0.92')
        builder.start_series()
        builder.build_snapshot('rev-1', None, [
            ('add', ('', 'root-id', 'directory', '')),
            ('add', ('filename', 'f-id', 'file', 'content\n'))])
        builder.build_snapshot('rev-2', ['rev-1'], [])
        builder.build_snapshot('rev-3', ['rev-2'],
            [('modify', ('f-id', 'new-content\n'))])
        builder.finish_series()
        branch = builder.get_branch()
        # Push rev-1 to "trunk", so that we can stack on it.
        self.run_bzr('push -d repo/local trunk -r 1')
        # Set a default stacking policy so that new branches will automatically
        # stack on trunk.
        self.make_bzrdir('.').get_config().set_default_stack_on('trunk')
        # Push rev-2 to a new branch "remote".  It will be stacked on "trunk".
        out, err = self.run_bzr('push -d repo/local remote -r 2')
        self.assertContainsRe(
            err, 'Using default stacking branch trunk at .*')
        # Push rev-3 onto "remote".  If "remote" not stacked and is missing the
        # fulltext record for f-id @ rev-1, then this will fail.
        out, err = self.run_bzr('push -d repo/local remote -r 3')

    def test_push_verbose_shows_log(self):
        tree = self.make_branch_and_tree('source')
        tree.commit('rev1')
        out, err = self.run_bzr('push -v -d source target')
        # initial push contains log
        self.assertContainsRe(out, 'rev1')
        tree.commit('rev2')
        out, err = self.run_bzr('push -v -d source target')
        # subsequent push contains log
        self.assertContainsRe(out, 'rev2')
        # subsequent log is accurate
        self.assertNotContainsRe(out, 'rev1')

    def test_push_from_subdir(self):
        t = self.make_branch_and_tree('tree')
        self.build_tree(['tree/dir/', 'tree/dir/file'])
        t.add('dir', 'dir/file')
        t.commit('r1')
        out, err = self.run_bzr('push ../../pushloc', working_dir='tree/dir')
        self.assertEqual('', out)
        self.assertEqual('Created new branch.\n', err)


class RedirectingMemoryTransport(memory.MemoryTransport):

    def mkdir(self, relpath, mode=None):
        if self._cwd == '/source/':
            raise errors.RedirectRequested(self.abspath(relpath),
                                           self.abspath('../target'),
                                           is_permanent=True)
        elif self._cwd == '/infinite-loop/':
            raise errors.RedirectRequested(self.abspath(relpath),
                                           self.abspath('../infinite-loop'),
                                           is_permanent=True)
        else:
            return super(RedirectingMemoryTransport, self).mkdir(
                relpath, mode)

    def get(self, relpath):
        if self.clone(relpath)._cwd == '/infinite-loop/':
            raise errors.RedirectRequested(self.abspath(relpath),
                                           self.abspath('../infinite-loop'),
                                           is_permanent=True)
        else:
            return super(RedirectingMemoryTransport, self).get(relpath)

    def _redirected_to(self, source, target):
        # We do accept redirections
        return transport.get_transport(target)


class RedirectingMemoryServer(memory.MemoryServer):

    def setUp(self):
        self._dirs = {'/': None}
        self._files = {}
        self._locks = {}
        self._scheme = 'redirecting-memory+%s:///' % id(self)
        transport.register_transport(self._scheme, self._memory_factory)

    def _memory_factory(self, url):
        result = RedirectingMemoryTransport(url)
        result._dirs = self._dirs
        result._files = self._files
        result._locks = self._locks
        return result

    def tearDown(self):
        transport.unregister_transport(self._scheme, self._memory_factory)


class TestPushRedirect(tests.TestCaseWithTransport):

    def setUp(self):
        tests.TestCaseWithTransport.setUp(self)
        self.memory_server = RedirectingMemoryServer()
        self.start_server(self.memory_server)
        # Make the branch and tree that we'll be pushing.
        t = self.make_branch_and_tree('tree')
        self.build_tree(['tree/file'])
        t.add('file')
        t.commit('commit 1')

    def test_push_redirects_on_mkdir(self):
        """If the push requires a mkdir, push respects redirect requests.

        This is added primarily to handle lp:/ URI support, so that users can
        push to new branches by specifying lp:/ URIs.
        """
        destination_url = self.memory_server.get_url() + 'source'
        self.run_bzr(['push', '-d', 'tree', destination_url])

        local_revision = branch.Branch.open('tree').last_revision()
        remote_revision = branch.Branch.open(
            self.memory_server.get_url() + 'target').last_revision()
        self.assertEqual(remote_revision, local_revision)

    def test_push_gracefully_handles_too_many_redirects(self):
        """Push fails gracefully if the mkdir generates a large number of
        redirects.
        """
        destination_url = self.memory_server.get_url() + 'infinite-loop'
        out, err = self.run_bzr_error(
            ['Too many redirections trying to make %s\\.\n'
             % re.escape(destination_url)],
            ['push', '-d', 'tree', destination_url], retcode=3)
        self.assertEqual('', out)


class TestPushStrictMixin(object):

    def make_local_branch_and_tree(self):
        self.tree = self.make_branch_and_tree('local')
        self.build_tree_contents([('local/file', 'initial')])
        self.tree.add('file')
        self.tree.commit('adding file', rev_id='added')
        self.build_tree_contents([('local/file', 'modified')])
        self.tree.commit('modify file', rev_id='modified')

    def set_config_push_strict(self, value):
        # set config var (any of bazaar.conf, locations.conf, branch.conf
        # should do)
        conf = self.tree.branch.get_config()
        conf.set_user_option('push_strict', value)

    _default_command = ['push', '../to']
    _default_wd = 'local'
    _default_errors = ['Working tree ".*/local/" has uncommitted '
                       'changes \(See bzr status\)\.',]
    _default_pushed_revid = 'modified'

    def assertPushFails(self, args):
        self.run_bzr_error(self._default_errors, self._default_command + args,
                           working_dir=self._default_wd, retcode=3)

    def assertPushSucceeds(self, args, pushed_revid=None):
        self.run_bzr(self._default_command + args,
                     working_dir=self._default_wd)
        if pushed_revid is None:
            pushed_revid = self._default_pushed_revid
        tree_to = workingtree.WorkingTree.open('to')
        repo_to = tree_to.branch.repository
        self.assertTrue(repo_to.has_revision(pushed_revid))
        self.assertEqual(tree_to.branch.last_revision_info()[1], pushed_revid)



class TestPushStrictWithoutChanges(tests.TestCaseWithTransport,
                                   TestPushStrictMixin):

    def setUp(self):
        super(TestPushStrictWithoutChanges, self).setUp()
        self.make_local_branch_and_tree()

    def test_push_default(self):
        self.assertPushSucceeds([])

    def test_push_strict(self):
        self.assertPushSucceeds(['--strict'])

    def test_push_no_strict(self):
        self.assertPushSucceeds(['--no-strict'])

    def test_push_config_var_strict(self):
        self.set_config_push_strict('true')
        self.assertPushSucceeds([])

    def test_push_config_var_no_strict(self):
        self.set_config_push_strict('false')
        self.assertPushSucceeds([])


class TestPushStrictWithChanges(tests.TestCaseWithTransport,
                                TestPushStrictMixin):

    _changes_type = None # Set by load_tests

    def setUp(self):
        super(TestPushStrictWithChanges, self).setUp()
        getattr(self, self._changes_type)()

    def _uncommitted_changes(self):
        self.make_local_branch_and_tree()
        # Make a change without committing it
        self.build_tree_contents([('local/file', 'in progress')])

    def _pending_merges(self):
        self.make_local_branch_and_tree()
        # Create 'other' branch containing a new file
        other_bzrdir = self.tree.bzrdir.sprout('other')
        other_tree = other_bzrdir.open_workingtree()
        self.build_tree_contents([('other/other-file', 'other')])
        other_tree.add('other-file')
        other_tree.commit('other commit', rev_id='other')
        # Merge and revert, leaving a pending merge
        self.tree.merge_from_branch(other_tree.branch)
        self.tree.revert(filenames=['other-file'], backups=False)

    def _out_of_sync_trees(self):
        self.make_local_branch_and_tree()
        self.run_bzr(['checkout', '--lightweight', 'local', 'checkout'])
        # Make a change and commit it
        self.build_tree_contents([('local/file', 'modified in local')])
        self.tree.commit('modify file', rev_id='modified-in-local')
        # Exercise commands from the checkout directory
        self._default_wd = 'checkout'
        self._default_errors = ["Working tree is out of date, please run"
                                " 'bzr update'\.",]
        self._default_pushed_revid = 'modified-in-local'

    def test_push_default(self):
        self.assertPushFails([])

    def test_push_with_revision(self):
        self.assertPushSucceeds(['-r', 'revid:added'], pushed_revid='added')

    def test_push_no_strict(self):
        self.assertPushSucceeds(['--no-strict'])

    def test_push_strict_with_changes(self):
        self.assertPushFails(['--strict'])

    def test_push_respect_config_var_strict(self):
        self.set_config_push_strict('true')
        self.assertPushFails([])

    def test_push_bogus_config_var_ignored(self):
        self.set_config_push_strict("I don't want you to be strict")
        self.assertPushFails([])

    def test_push_no_strict_command_line_override_config(self):
        self.set_config_push_strict('yES')
        self.assertPushFails([])
        self.assertPushSucceeds(['--no-strict'])

    def test_push_strict_command_line_override_config(self):
        self.set_config_push_strict('oFF')
        self.assertPushFails(['--strict'])
        self.assertPushSucceeds([])
