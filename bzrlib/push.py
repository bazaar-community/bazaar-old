# Copyright (C) 2008 Canonical Ltd
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

"""UI helper for the push command."""

from bzrlib import (
    builtins,
    branch,
    bzrdir,
    errors,
    revision as _mod_revision,
    transport,
    )
from bzrlib.inter import (
    InterObject,
    )
from bzrlib.trace import (
    note,
    warning,
    )


class PushResult(object):
    """Result of a push operation.

    :ivar branch_push_result: Result of a push between branches
    :ivar target_branch: The target branch
    :ivar stacked_on: URL of the branch on which the result is stacked
    :ivar workingtree_updated: Whether or not the target workingtree was updated.
    """

    def __init__(self):
        self.branch_push_result = None
        self.stacked_on = None
        self.workingtree_updated = None
        self.target_branch = None

    def report(self, to_file):
        """Write a human-readable description of the result."""
        if self.branch_push_result is None:
            if self.stacked_on is not None:
                note('Created new stacked branch referring to %s.' %
                    self.stacked_on)
            else:
                note('Created new branch.')
        else:
            self.branch_push_result.report(to_file)


def _show_push_branch(br_from, revision_id, location, to_file, verbose=False,
    overwrite=False, remember=False, stacked_on=None, create_prefix=False,
    use_existing_dir=False):
    """Push a branch to a location.

    :param br_from: the source branch
    :param revision_id: the revision-id to push up to
    :param location: the url of the destination
    :param to_file: the output stream
    :param verbose: if True, display more output than normal
    :param overwrite: if False, a current branch at the destination may not
        have diverged from the source, otherwise the push fails
    :param remember: if True, store the location as the push location for
        the source branch
    :param stacked_on: the url of the branch, if any, to stack on;
        if set, only the revisions not in that branch are pushed
    :param create_prefix: if True, create the necessary parent directories
        at the destination if they don't already exist
    :param use_existing_dir: if True, proceed even if the destination
        directory exists without a current .bzr directory in it
    """
    to_transport = transport.get_transport(location)
    br_to = repository_to = dir_to = None
    try:
        dir_to = bzrdir.BzrDir.open_from_transport(to_transport)
    except errors.NotBranchError:
        pass # Didn't find anything

    push_result = PushResult()
    if dir_to is None:
        # The destination doesn't exist; create it.
        # XXX: Refactor the create_prefix/no_create_prefix code into a
        #      common helper function

        def make_directory(transport):
            transport.mkdir('.')
            return transport

        def redirected(transport, e, redirection_notice):
            note(redirection_notice)
            return transport._redirected_to(e.source, e.target)

        try:
            to_transport = transport.do_catching_redirections(
                make_directory, to_transport, redirected)
        except errors.FileExists:
            if not use_existing_dir:
                raise errors.BzrCommandError("Target directory %s"
                     " already exists, but does not have a valid .bzr"
                     " directory. Supply --use-existing-dir to push"
                     " there anyway." % location)
        except errors.NoSuchFile:
            if not create_prefix:
                raise errors.BzrCommandError("Parent directory of %s"
                    " does not exist."
                    "\nYou may supply --create-prefix to create all"
                    " leading parent directories."
                    % location)
            builtins._create_prefix(to_transport)
        except errors.TooManyRedirections:
            raise errors.BzrCommandError("Too many redirections trying "
                                         "to make %s." % location)

        # Now the target directory exists, but doesn't have a .bzr
        # directory. So we need to create it, along with any work to create
        # all of the dependent branches, etc.
        br_to = br_from.create_clone_on_transport(to_transport,
            revision_id=revision_id, stacked_on=stacked_on)
        # TODO: Some more useful message about what was copied
        try:
            push_result.stacked_on = br_to.get_stacked_on_url()
        except (errors.UnstackableBranchFormat,
                errors.UnstackableRepositoryFormat,
                errors.NotStacked):
            push_result.stacked_on = None
        push_result.target_branch = br_to
        push_result.old_revid = _mod_revision.NULL_REVISION
        push_result.old_revno = 0
        if br_from.get_push_location() is None or remember:
            br_from.set_push_location(br_to.base)
    else:
        if stacked_on is not None:
            warning("Ignoring request for a stacked branch as repository "
                    "already exists at the destination location.")
        inter = InterBranchBzrDir.get(br_from, dir_to)
        try:
            push_result = inter.push(revision_id, overwrite, remember)
        except errors.DivergedBranches:
            raise errors.BzrCommandError('These branches have diverged.'
                                    '  Try using "merge" and then "push".')
        except errors.NoRepositoryPresent:
            # we have a bzrdir but no branch or repository
            # XXX: Figure out what to do other than complain.
            raise errors.BzrCommandError("At %s you have a valid .bzr"
                " control directory, but not a branch or repository. This"
                " is an unsupported configuration. Please move the target"
                " directory out of the way and try again." % location)
        if push_result.workingtree_updated == False:
            warning("This transport does not update the working " 
                    "tree of: %s. See 'bzr help working-trees' for "
                    "more information." % push_result.target_branch.base)
    push_result.report(to_file)
    if verbose:
        br_to = push_result.target_branch
        br_to.lock_read()
        try:
            from bzrlib.log import show_branch_change
            show_branch_change(br_to, to_file, push_result.old_revno, 
                               push_result.old_revid)
        finally:
            br_to.unlock()


class InterBranchBzrDir(InterObject):
    """This class represents ops taking place between a Branch and a BzrDir.

    Its instances have methods like push() and branch(), and create a new 
    instance of a branch in a target BzrDir based on the base branch.
    """

    _optimisers = []
    """The available optimised InterBranchBzrDir types."""

    def push(self, revision_id=None, overwrite=True, remember=False):
        """Push the source branch into the target BzrDir."""
        raise NotImplementedError(self.push)


class GenericInterBranchBzrDir(InterBranchBzrDir):
    """Generic implementation of InterBranchBzrDir using standard public APIs.

    """

    def push(self, revision_id=None, overwrite=False, remember=False):
        """See InterBranchBzrDir.push."""
        br_to = None
        # If we can open a branch, use its direct repository, otherwise see
        # if there is a repository without a branch.
        try:
            br_to = self.target.open_branch()
        except errors.NotBranchError:
            # Didn't find a branch, can we find a repository?
            repository_to = self.target.find_repository()
        else:
            # Found a branch, so we must have found a repository
            repository_to = br_to.repository

        push_result = PushResult()
        if br_to is None:
            # We have a repository but no branch, copy the revisions, and then
            # create a branch.
            repository_to.fetch(self.source.repository, revision_id=revision_id)
            br_to = self.source.clone(self.target, revision_id=revision_id)
            if self.source.get_push_location() is None or remember:
                self.source.set_push_location(br_to.base)
            push_result.stacked_on = None
            push_result.branch_push_result = None
            push_result.old_revno = None
            push_result.old_revid = _mod_revision.NULL_REVISION
            push_result.source_branch = self.source
            push_result.target_branch = br_to
            push_result.master_branch = None
            push_result.workingtree_updated = False
        else:
            # We have successfully opened the branch, remember if necessary:
            if self.source.get_push_location() is None or remember:
                self.source.set_push_location(br_to.base)
            try:
                tree_to = self.target.open_workingtree()
            except errors.NotLocalUrl:
                push_result.branch_push_result = self.source.push(br_to, 
                    overwrite, stop_revision=revision_id)
                push_result.workingtree_updated = False
            except errors.NoWorkingTree:
                push_result.branch_push_result = self.source.push(br_to,
                    overwrite, stop_revision=revision_id)
                push_result.workingtree_updated = None # Not applicable
            else:
                tree_to.lock_write()
                try:
                    push_result.branch_push_result = self.source.push(
                        tree_to.branch, overwrite, stop_revision=revision_id)
                    tree_to.update()
                finally:
                    tree_to.unlock()
                push_result.workingtree_updated = True
            push_result.old_revno = push_result.branch_push_result.old_revno
            push_result.old_revid = push_result.branch_push_result.old_revid
            push_result.target_branch = push_result.branch_push_result.target_branch
        return push_result

    @classmethod
    def is_compatible(cls, source, target):
        return True


InterBranchBzrDir.register_optimiser(GenericInterBranchBzrDir)
