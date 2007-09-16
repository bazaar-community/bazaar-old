# Copyright (C) 2004, 2005, 2006, 2007 Canonical Ltd
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

"""builtin bzr commands"""

import os
from StringIO import StringIO

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import codecs
import errno
import sys
import tempfile
import time

import bzrlib
from bzrlib import (
    branch,
    bugtracker,
    bundle,
    bzrdir,
    delta,
    config,
    errors,
    globbing,
    ignores,
    log,
    merge as _mod_merge,
    merge_directive,
    osutils,
    registry,
    repository,
    revision as _mod_revision,
    revisionspec,
    symbol_versioning,
    transport,
    tree as _mod_tree,
    ui,
    urlutils,
    )
from bzrlib.branch import Branch
from bzrlib.conflicts import ConflictList
from bzrlib.revisionspec import RevisionSpec
from bzrlib.smtp_connection import SMTPConnection
from bzrlib.workingtree import WorkingTree
""")

from bzrlib.commands import Command, display_command
from bzrlib.option import ListOption, Option, RegistryOption, custom_help
from bzrlib.progress import DummyProgress, ProgressPhase
from bzrlib.trace import mutter, note, log_error, warning, is_quiet, info


def tree_files(file_list, default_branch=u'.'):
    try:
        return internal_tree_files(file_list, default_branch)
    except errors.FileInWrongBranch, e:
        raise errors.BzrCommandError("%s is not in the same branch as %s" %
                                     (e.path, file_list[0]))


# XXX: Bad function name; should possibly also be a class method of
# WorkingTree rather than a function.
def internal_tree_files(file_list, default_branch=u'.'):
    """Convert command-line paths to a WorkingTree and relative paths.

    This is typically used for command-line processors that take one or
    more filenames, and infer the workingtree that contains them.

    The filenames given are not required to exist.

    :param file_list: Filenames to convert.  

    :param default_branch: Fallback tree path to use if file_list is empty or
        None.

    :return: workingtree, [relative_paths]
    """
    if file_list is None or len(file_list) == 0:
        return WorkingTree.open_containing(default_branch)[0], file_list
    tree = WorkingTree.open_containing(osutils.realpath(file_list[0]))[0]
    new_list = []
    for filename in file_list:
        try:
            new_list.append(tree.relpath(osutils.dereference_path(filename)))
        except errors.PathNotChild:
            raise errors.FileInWrongBranch(tree.branch, filename)
    return tree, new_list


@symbol_versioning.deprecated_function(symbol_versioning.zero_fifteen)
def get_format_type(typestring):
    """Parse and return a format specifier."""
    # Have to use BzrDirMetaFormat1 directly, so that
    # RepositoryFormat.set_default_format works
    if typestring == "default":
        return bzrdir.BzrDirMetaFormat1()
    try:
        return bzrdir.format_registry.make_bzrdir(typestring)
    except KeyError:
        msg = 'Unknown bzr format "%s". See "bzr help formats".' % typestring
        raise errors.BzrCommandError(msg)


# TODO: Make sure no commands unconditionally use the working directory as a
# branch.  If a filename argument is used, the first of them should be used to
# specify the branch.  (Perhaps this can be factored out into some kind of
# Argument class, representing a file in a branch, where the first occurrence
# opens the branch?)

class cmd_status(Command):
    """Display status summary.

    This reports on versioned and unknown files, reporting them
    grouped by state.  Possible states are:

    added
        Versioned in the working copy but not in the previous revision.

    removed
        Versioned in the previous revision but removed or deleted
        in the working copy.

    renamed
        Path of this file changed from the previous revision;
        the text may also have changed.  This includes files whose
        parent directory was renamed.

    modified
        Text has changed since the previous revision.

    kind changed
        File kind has been changed (e.g. from file to directory).

    unknown
        Not versioned and not matching an ignore pattern.

    To see ignored files use 'bzr ignored'.  For details on the
    changes to file texts, use 'bzr diff'.
    
    Note that --short or -S gives status flags for each item, similar
    to Subversion's status command. To get output similar to svn -q,
    use bzr -SV.

    If no arguments are specified, the status of the entire working
    directory is shown.  Otherwise, only the status of the specified
    files or directories is reported.  If a directory is given, status
    is reported for everything inside that directory.

    If a revision argument is given, the status is calculated against
    that revision, or between two revisions if two are provided.
    """
    
    # TODO: --no-recurse, --recurse options
    
    takes_args = ['file*']
    takes_options = ['show-ids', 'revision', 'change',
                     Option('short', help='Use short status indicators.',
                            short_name='S'),
                     Option('versioned', help='Only show versioned files.',
                            short_name='V')
                     ]
    aliases = ['st', 'stat']

    encoding_type = 'replace'
    _see_also = ['diff', 'revert', 'status-flags']
    
    @display_command
    def run(self, show_ids=False, file_list=None, revision=None, short=False,
            versioned=False):
        from bzrlib.status import show_tree_status

        if revision and len(revision) > 2:
            raise errors.BzrCommandError('bzr status --revision takes exactly'
                                         ' one or two revision specifiers')

        tree, file_list = tree_files(file_list)
            
        show_tree_status(tree, show_ids=show_ids,
                         specific_files=file_list, revision=revision,
                         to_file=self.outf, short=short, versioned=versioned)


class cmd_cat_revision(Command):
    """Write out metadata for a revision.
    
    The revision to print can either be specified by a specific
    revision identifier, or you can use --revision.
    """

    hidden = True
    takes_args = ['revision_id?']
    takes_options = ['revision']
    # cat-revision is more for frontends so should be exact
    encoding = 'strict'
    
    @display_command
    def run(self, revision_id=None, revision=None):

        revision_id = osutils.safe_revision_id(revision_id, warn=False)
        if revision_id is not None and revision is not None:
            raise errors.BzrCommandError('You can only supply one of'
                                         ' revision_id or --revision')
        if revision_id is None and revision is None:
            raise errors.BzrCommandError('You must supply either'
                                         ' --revision or a revision_id')
        b = WorkingTree.open_containing(u'.')[0].branch

        # TODO: jam 20060112 should cat-revision always output utf-8?
        if revision_id is not None:
            self.outf.write(b.repository.get_revision_xml(revision_id).decode('utf-8'))
        elif revision is not None:
            for rev in revision:
                if rev is None:
                    raise errors.BzrCommandError('You cannot specify a NULL'
                                                 ' revision.')
                revno, rev_id = rev.in_history(b)
                self.outf.write(b.repository.get_revision_xml(rev_id).decode('utf-8'))
    

class cmd_remove_tree(Command):
    """Remove the working tree from a given branch/checkout.

    Since a lightweight checkout is little more than a working tree
    this will refuse to run against one.

    To re-create the working tree, use "bzr checkout".
    """
    _see_also = ['checkout', 'working-trees']

    takes_args = ['location?']

    def run(self, location='.'):
        d = bzrdir.BzrDir.open(location)
        
        try:
            working = d.open_workingtree()
        except errors.NoWorkingTree:
            raise errors.BzrCommandError("No working tree to remove")
        except errors.NotLocalUrl:
            raise errors.BzrCommandError("You cannot remove the working tree of a "
                                         "remote path")
        
        working_path = working.bzrdir.root_transport.base
        branch_path = working.branch.bzrdir.root_transport.base
        if working_path != branch_path:
            raise errors.BzrCommandError("You cannot remove the working tree from "
                                         "a lightweight checkout")
        
        d.destroy_workingtree()
        

class cmd_revno(Command):
    """Show current revision number.

    This is equal to the number of revisions on this branch.
    """

    _see_also = ['info']
    takes_args = ['location?']

    @display_command
    def run(self, location=u'.'):
        self.outf.write(str(Branch.open_containing(location)[0].revno()))
        self.outf.write('\n')


class cmd_revision_info(Command):
    """Show revision number and revision id for a given revision identifier.
    """
    hidden = True
    takes_args = ['revision_info*']
    takes_options = ['revision']

    @display_command
    def run(self, revision=None, revision_info_list=[]):

        revs = []
        if revision is not None:
            revs.extend(revision)
        if revision_info_list is not None:
            for rev in revision_info_list:
                revs.append(RevisionSpec.from_string(rev))

        b = Branch.open_containing(u'.')[0]

        if len(revs) == 0:
            revs.append(RevisionSpec.from_string('-1'))

        for rev in revs:
            revinfo = rev.in_history(b)
            if revinfo.revno is None:
                dotted_map = b.get_revision_id_to_revno_map()
                revno = '.'.join(str(i) for i in dotted_map[revinfo.rev_id])
                print '%s %s' % (revno, revinfo.rev_id)
            else:
                print '%4d %s' % (revinfo.revno, revinfo.rev_id)

    
class cmd_add(Command):
    """Add specified files or directories.

    In non-recursive mode, all the named items are added, regardless
    of whether they were previously ignored.  A warning is given if
    any of the named files are already versioned.

    In recursive mode (the default), files are treated the same way
    but the behaviour for directories is different.  Directories that
    are already versioned do not give a warning.  All directories,
    whether already versioned or not, are searched for files or
    subdirectories that are neither versioned or ignored, and these
    are added.  This search proceeds recursively into versioned
    directories.  If no names are given '.' is assumed.

    Therefore simply saying 'bzr add' will version all files that
    are currently unknown.

    Adding a file whose parent directory is not versioned will
    implicitly add the parent, and so on up to the root. This means
    you should never need to explicitly add a directory, they'll just
    get added when you add a file in the directory.

    --dry-run will show which files would be added, but not actually 
    add them.

    --file-ids-from will try to use the file ids from the supplied path.
    It looks up ids trying to find a matching parent directory with the
    same filename, and then by pure path. This option is rarely needed
    but can be useful when adding the same logical file into two
    branches that will be merged later (without showing the two different
    adds as a conflict). It is also useful when merging another project
    into a subdirectory of this one.
    """
    takes_args = ['file*']
    takes_options = [
        Option('no-recurse',
               help="Don't recursively add the contents of directories."),
        Option('dry-run',
               help="Show what would be done, but don't actually do anything."),
        'verbose',
        Option('file-ids-from',
               type=unicode,
               help='Lookup file ids from this tree.'),
        ]
    encoding_type = 'replace'
    _see_also = ['remove']

    def run(self, file_list, no_recurse=False, dry_run=False, verbose=False,
            file_ids_from=None):
        import bzrlib.add

        base_tree = None
        if file_ids_from is not None:
            try:
                base_tree, base_path = WorkingTree.open_containing(
                                            file_ids_from)
            except errors.NoWorkingTree:
                base_branch, base_path = Branch.open_containing(
                                            file_ids_from)
                base_tree = base_branch.basis_tree()

            action = bzrlib.add.AddFromBaseAction(base_tree, base_path,
                          to_file=self.outf, should_print=(not is_quiet()))
        else:
            action = bzrlib.add.AddAction(to_file=self.outf,
                should_print=(not is_quiet()))

        if base_tree:
            base_tree.lock_read()
        try:
            file_list = self._maybe_expand_globs(file_list)
            if file_list:
                tree = WorkingTree.open_containing(file_list[0])[0]
            else:
                tree = WorkingTree.open_containing(u'.')[0]
            added, ignored = tree.smart_add(file_list, not
                no_recurse, action=action, save=not dry_run)
        finally:
            if base_tree is not None:
                base_tree.unlock()
        if len(ignored) > 0:
            if verbose:
                for glob in sorted(ignored.keys()):
                    for path in ignored[glob]:
                        self.outf.write("ignored %s matching \"%s\"\n" 
                                        % (path, glob))
            else:
                match_len = 0
                for glob, paths in ignored.items():
                    match_len += len(paths)
                self.outf.write("ignored %d file(s).\n" % match_len)
            self.outf.write("If you wish to add some of these files,"
                            " please add them by name.\n")


class cmd_mkdir(Command):
    """Create a new versioned directory.

    This is equivalent to creating the directory and then adding it.
    """

    takes_args = ['dir+']
    encoding_type = 'replace'

    def run(self, dir_list):
        for d in dir_list:
            os.mkdir(d)
            wt, dd = WorkingTree.open_containing(d)
            wt.add([dd])
            self.outf.write('added %s\n' % d)


class cmd_relpath(Command):
    """Show path of a file relative to root"""

    takes_args = ['filename']
    hidden = True
    
    @display_command
    def run(self, filename):
        # TODO: jam 20050106 Can relpath return a munged path if
        #       sys.stdout encoding cannot represent it?
        tree, relpath = WorkingTree.open_containing(filename)
        self.outf.write(relpath)
        self.outf.write('\n')


class cmd_inventory(Command):
    """Show inventory of the current working copy or a revision.

    It is possible to limit the output to a particular entry
    type using the --kind option.  For example: --kind file.

    It is also possible to restrict the list of files to a specific
    set. For example: bzr inventory --show-ids this/file
    """

    hidden = True
    _see_also = ['ls']
    takes_options = [
        'revision',
        'show-ids',
        Option('kind',
               help='List entries of a particular kind: file, directory, symlink.',
               type=unicode),
        ]
    takes_args = ['file*']

    @display_command
    def run(self, revision=None, show_ids=False, kind=None, file_list=None):
        if kind and kind not in ['file', 'directory', 'symlink']:
            raise errors.BzrCommandError('invalid kind %r specified' % (kind,))

        work_tree, file_list = tree_files(file_list)
        work_tree.lock_read()
        try:
            if revision is not None:
                if len(revision) > 1:
                    raise errors.BzrCommandError(
                        'bzr inventory --revision takes exactly one revision'
                        ' identifier')
                revision_id = revision[0].in_history(work_tree.branch).rev_id
                tree = work_tree.branch.repository.revision_tree(revision_id)

                extra_trees = [work_tree]
                tree.lock_read()
            else:
                tree = work_tree
                extra_trees = []

            if file_list is not None:
                file_ids = tree.paths2ids(file_list, trees=extra_trees,
                                          require_versioned=True)
                # find_ids_across_trees may include some paths that don't
                # exist in 'tree'.
                entries = sorted((tree.id2path(file_id), tree.inventory[file_id])
                                 for file_id in file_ids if file_id in tree)
            else:
                entries = tree.inventory.entries()
        finally:
            tree.unlock()
            if tree is not work_tree:
                work_tree.unlock()

        for path, entry in entries:
            if kind and kind != entry.kind:
                continue
            if show_ids:
                self.outf.write('%-50s %s\n' % (path, entry.file_id))
            else:
                self.outf.write(path)
                self.outf.write('\n')


class cmd_mv(Command):
    """Move or rename a file.

    :Usage:
        bzr mv OLDNAME NEWNAME

        bzr mv SOURCE... DESTINATION

    If the last argument is a versioned directory, all the other names
    are moved into it.  Otherwise, there must be exactly two arguments
    and the file is changed to a new name.

    If OLDNAME does not exist on the filesystem but is versioned and
    NEWNAME does exist on the filesystem but is not versioned, mv
    assumes that the file has been manually moved and only updates
    its internal inventory to reflect that change.
    The same is valid when moving many SOURCE files to a DESTINATION.

    Files cannot be moved between branches.
    """

    takes_args = ['names*']
    takes_options = [Option("after", help="Move only the bzr identifier"
        " of the file, because the file has already been moved."),
        ]
    aliases = ['move', 'rename']
    encoding_type = 'replace'

    def run(self, names_list, after=False):
        if names_list is None:
            names_list = []

        if len(names_list) < 2:
            raise errors.BzrCommandError("missing file argument")
        tree, rel_names = tree_files(names_list)
        
        if os.path.isdir(names_list[-1]):
            # move into existing directory
            for pair in tree.move(rel_names[:-1], rel_names[-1], after=after):
                self.outf.write("%s => %s\n" % pair)
        else:
            if len(names_list) != 2:
                raise errors.BzrCommandError('to mv multiple files the'
                                             ' destination must be a versioned'
                                             ' directory')
            tree.rename_one(rel_names[0], rel_names[1], after=after)
            self.outf.write("%s => %s\n" % (rel_names[0], rel_names[1]))
            
    
class cmd_pull(Command):
    """Turn this branch into a mirror of another branch.

    This command only works on branches that have not diverged.  Branches are
    considered diverged if the destination branch's most recent commit is one
    that has not been merged (directly or indirectly) into the parent.

    If branches have diverged, you can use 'bzr merge' to integrate the changes
    from one into the other.  Once one branch has merged, the other should
    be able to pull it again.

    If you want to forget your local changes and just update your branch to
    match the remote one, use pull --overwrite.

    If there is no default location set, the first pull will set it.  After
    that, you can omit the location to use the default.  To change the
    default, use --remember. The value will only be saved if the remote
    location can be accessed.
    """

    _see_also = ['push', 'update', 'status-flags']
    takes_options = ['remember', 'overwrite', 'revision',
        custom_help('verbose',
            help='Show logs of pulled revisions.'),
        Option('directory',
            help='Branch to pull into, '
                 'rather than the one containing the working directory.',
            short_name='d',
            type=unicode,
            ),
        ]
    takes_args = ['location?']
    encoding_type = 'replace'

    def run(self, location=None, remember=False, overwrite=False,
            revision=None, verbose=False,
            directory=None):
        # FIXME: too much stuff is in the command class
        revision_id = None
        mergeable = None
        if directory is None:
            directory = u'.'
        try:
            tree_to = WorkingTree.open_containing(directory)[0]
            branch_to = tree_to.branch
        except errors.NoWorkingTree:
            tree_to = None
            branch_to = Branch.open_containing(directory)[0]

        if location is not None:
            mergeable, location_transport = _get_mergeable_helper(location)

        stored_loc = branch_to.get_parent()
        if location is None:
            if stored_loc is None:
                raise errors.BzrCommandError("No pull location known or"
                                             " specified.")
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                location = stored_loc
                location_transport = transport.get_transport(location)

        if mergeable is not None:
            if revision is not None:
                raise errors.BzrCommandError(
                    'Cannot use -r with merge directives or bundles')
            mergeable.install_revisions(branch_to.repository)
            base_revision_id, revision_id, verified = \
                mergeable.get_merge_request(branch_to.repository)
            branch_from = branch_to
        else:
            branch_from = Branch.open_from_transport(location_transport)

            if branch_to.get_parent() is None or remember:
                branch_to.set_parent(branch_from.base)

        if revision is not None:
            if len(revision) == 1:
                revision_id = revision[0].in_history(branch_from).rev_id
            else:
                raise errors.BzrCommandError(
                    'bzr pull --revision takes one value.')

        if verbose:
            old_rh = branch_to.revision_history()
        if tree_to is not None:
            result = tree_to.pull(branch_from, overwrite, revision_id,
                delta._ChangeReporter(unversioned_filter=tree_to.is_ignored))
        else:
            result = branch_to.pull(branch_from, overwrite, revision_id)

        result.report(self.outf)
        if verbose:
            new_rh = branch_to.revision_history()
            log.show_changed_revisions(branch_to, old_rh, new_rh,
                                       to_file=self.outf)


class cmd_push(Command):
    """Update a mirror of this branch.
    
    The target branch will not have its working tree populated because this
    is both expensive, and is not supported on remote file systems.
    
    Some smart servers or protocols *may* put the working tree in place in
    the future.

    This command only works on branches that have not diverged.  Branches are
    considered diverged if the destination branch's most recent commit is one
    that has not been merged (directly or indirectly) by the source branch.

    If branches have diverged, you can use 'bzr push --overwrite' to replace
    the other branch completely, discarding its unmerged changes.
    
    If you want to ensure you have the different changes in the other branch,
    do a merge (see bzr help merge) from the other branch, and commit that.
    After that you will be able to do a push without '--overwrite'.

    If there is no default push location set, the first push will set it.
    After that, you can omit the location to use the default.  To change the
    default, use --remember. The value will only be saved if the remote
    location can be accessed.
    """

    _see_also = ['pull', 'update', 'working-trees']
    takes_options = ['remember', 'overwrite', 'verbose',
        Option('create-prefix',
               help='Create the path leading up to the branch '
                    'if it does not already exist.'),
        Option('directory',
            help='Branch to push from, '
                 'rather than the one containing the working directory.',
            short_name='d',
            type=unicode,
            ),
        Option('use-existing-dir',
               help='By default push will fail if the target'
                    ' directory exists, but does not already'
                    ' have a control directory.  This flag will'
                    ' allow push to proceed.'),
        ]
    takes_args = ['location?']
    encoding_type = 'replace'

    def run(self, location=None, remember=False, overwrite=False,
            create_prefix=False, verbose=False,
            use_existing_dir=False,
            directory=None):
        # FIXME: Way too big!  Put this into a function called from the
        # command.
        if directory is None:
            directory = '.'
        br_from = Branch.open_containing(directory)[0]
        stored_loc = br_from.get_push_location()
        if location is None:
            if stored_loc is None:
                raise errors.BzrCommandError("No push location known or specified.")
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                location = stored_loc

        to_transport = transport.get_transport(location)

        br_to = repository_to = dir_to = None
        try:
            dir_to = bzrdir.BzrDir.open_from_transport(to_transport)
        except errors.NotBranchError:
            pass # Didn't find anything
        else:
            # If we can open a branch, use its direct repository, otherwise see
            # if there is a repository without a branch.
            try:
                br_to = dir_to.open_branch()
            except errors.NotBranchError:
                # Didn't find a branch, can we find a repository?
                try:
                    repository_to = dir_to.find_repository()
                except errors.NoRepositoryPresent:
                    pass
            else:
                # Found a branch, so we must have found a repository
                repository_to = br_to.repository
        push_result = None
        if verbose:
            old_rh = []
        if dir_to is None:
            # The destination doesn't exist; create it.
            # XXX: Refactor the create_prefix/no_create_prefix code into a
            #      common helper function
            try:
                to_transport.mkdir('.')
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
                _create_prefix(to_transport)

            # Now the target directory exists, but doesn't have a .bzr
            # directory. So we need to create it, along with any work to create
            # all of the dependent branches, etc.
            dir_to = br_from.bzrdir.clone_on_transport(to_transport,
                revision_id=br_from.last_revision())
            br_to = dir_to.open_branch()
            # TODO: Some more useful message about what was copied
            note('Created new branch.')
            # We successfully created the target, remember it
            if br_from.get_push_location() is None or remember:
                br_from.set_push_location(br_to.base)
        elif repository_to is None:
            # we have a bzrdir but no branch or repository
            # XXX: Figure out what to do other than complain.
            raise errors.BzrCommandError("At %s you have a valid .bzr control"
                " directory, but not a branch or repository. This is an"
                " unsupported configuration. Please move the target directory"
                " out of the way and try again."
                % location)
        elif br_to is None:
            # We have a repository but no branch, copy the revisions, and then
            # create a branch.
            last_revision_id = br_from.last_revision()
            repository_to.fetch(br_from.repository,
                                revision_id=last_revision_id)
            br_to = br_from.clone(dir_to, revision_id=last_revision_id)
            note('Created new branch.')
            if br_from.get_push_location() is None or remember:
                br_from.set_push_location(br_to.base)
        else: # We have a valid to branch
            # We were able to connect to the remote location, so remember it
            # we don't need to successfully push because of possible divergence.
            if br_from.get_push_location() is None or remember:
                br_from.set_push_location(br_to.base)
            if verbose:
                old_rh = br_to.revision_history()
            try:
                try:
                    tree_to = dir_to.open_workingtree()
                except errors.NotLocalUrl:
                    warning("This transport does not update the working " 
                            "tree of: %s. See 'bzr help working-trees' for "
                            "more information." % br_to.base)
                    push_result = br_from.push(br_to, overwrite)
                except errors.NoWorkingTree:
                    push_result = br_from.push(br_to, overwrite)
                else:
                    tree_to.lock_write()
                    try:
                        push_result = br_from.push(tree_to.branch, overwrite)
                        tree_to.update()
                    finally:
                        tree_to.unlock()
            except errors.DivergedBranches:
                raise errors.BzrCommandError('These branches have diverged.'
                                        '  Try using "merge" and then "push".')
        if push_result is not None:
            push_result.report(self.outf)
        elif verbose:
            new_rh = br_to.revision_history()
            if old_rh != new_rh:
                # Something changed
                from bzrlib.log import show_changed_revisions
                show_changed_revisions(br_to, old_rh, new_rh,
                                       to_file=self.outf)
        else:
            # we probably did a clone rather than a push, so a message was
            # emitted above
            pass


class cmd_branch(Command):
    """Create a new copy of a branch.

    If the TO_LOCATION is omitted, the last component of the FROM_LOCATION will
    be used.  In other words, "branch ../foo/bar" will attempt to create ./bar.
    If the FROM_LOCATION has no / or path separator embedded, the TO_LOCATION
    is derived from the FROM_LOCATION by stripping a leading scheme or drive
    identifier, if any. For example, "branch lp:foo-bar" will attempt to
    create ./foo-bar.

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "branch foo/bar -r 5".
    """

    _see_also = ['checkout']
    takes_args = ['from_location', 'to_location?']
    takes_options = ['revision']
    aliases = ['get', 'clone']

    def run(self, from_location, to_location=None, revision=None):
        from bzrlib.tag import _merge_tags_if_possible
        if revision is None:
            revision = [None]
        elif len(revision) > 1:
            raise errors.BzrCommandError(
                'bzr branch --revision takes exactly 1 revision value')

        br_from = Branch.open(from_location)
        br_from.lock_read()
        try:
            if len(revision) == 1 and revision[0] is not None:
                revision_id = revision[0].in_history(br_from)[1]
            else:
                # FIXME - wt.last_revision, fallback to branch, fall back to
                # None or perhaps NULL_REVISION to mean copy nothing
                # RBC 20060209
                revision_id = br_from.last_revision()
            if to_location is None:
                to_location = urlutils.derive_to_location(from_location)
                name = None
            else:
                name = os.path.basename(to_location) + '\n'

            to_transport = transport.get_transport(to_location)
            try:
                to_transport.mkdir('.')
            except errors.FileExists:
                raise errors.BzrCommandError('Target directory "%s" already'
                                             ' exists.' % to_location)
            except errors.NoSuchFile:
                raise errors.BzrCommandError('Parent of "%s" does not exist.'
                                             % to_location)
            try:
                # preserve whatever source format we have.
                dir = br_from.bzrdir.sprout(to_transport.base, revision_id,
                                            possible_transports=[to_transport])
                branch = dir.open_branch()
            except errors.NoSuchRevision:
                to_transport.delete_tree('.')
                msg = "The branch %s has no revision %s." % (from_location, revision[0])
                raise errors.BzrCommandError(msg)
            if name:
                branch.control_files.put_utf8('branch-name', name)
            _merge_tags_if_possible(br_from, branch)
            note('Branched %d revision(s).' % branch.revno())
        finally:
            br_from.unlock()


class cmd_checkout(Command):
    """Create a new checkout of an existing branch.

    If BRANCH_LOCATION is omitted, checkout will reconstitute a working tree for
    the branch found in '.'. This is useful if you have removed the working tree
    or if it was never created - i.e. if you pushed the branch to its current
    location using SFTP.
    
    If the TO_LOCATION is omitted, the last component of the BRANCH_LOCATION will
    be used.  In other words, "checkout ../foo/bar" will attempt to create ./bar.
    If the BRANCH_LOCATION has no / or path separator embedded, the TO_LOCATION
    is derived from the BRANCH_LOCATION by stripping a leading scheme or drive
    identifier, if any. For example, "checkout lp:foo-bar" will attempt to
    create ./foo-bar.

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "checkout foo/bar -r 5". Note that this will be immediately
    out of date [so you cannot commit] but it may be useful (i.e. to examine old
    code.)
    """

    _see_also = ['checkouts', 'branch']
    takes_args = ['branch_location?', 'to_location?']
    takes_options = ['revision',
                     Option('lightweight',
                            help="Perform a lightweight checkout.  Lightweight "
                                 "checkouts depend on access to the branch for "
                                 "every operation.  Normal checkouts can perform "
                                 "common operations like diff and status without "
                                 "such access, and also support local commits."
                            ),
                     ]
    aliases = ['co']

    def run(self, branch_location=None, to_location=None, revision=None,
            lightweight=False):
        if revision is None:
            revision = [None]
        elif len(revision) > 1:
            raise errors.BzrCommandError(
                'bzr checkout --revision takes exactly 1 revision value')
        if branch_location is None:
            branch_location = osutils.getcwd()
            to_location = branch_location
        source = Branch.open(branch_location)
        if len(revision) == 1 and revision[0] is not None:
            revision_id = _mod_revision.ensure_null(
                revision[0].in_history(source)[1])
        else:
            revision_id = None
        if to_location is None:
            to_location = urlutils.derive_to_location(branch_location)
        # if the source and to_location are the same, 
        # and there is no working tree,
        # then reconstitute a branch
        if (osutils.abspath(to_location) ==
            osutils.abspath(branch_location)):
            try:
                source.bzrdir.open_workingtree()
            except errors.NoWorkingTree:
                source.bzrdir.create_workingtree(revision_id)
                return
        source.create_checkout(to_location, revision_id, lightweight)


class cmd_renames(Command):
    """Show list of renamed files.
    """
    # TODO: Option to show renames between two historical versions.

    # TODO: Only show renames under dir, rather than in the whole branch.
    _see_also = ['status']
    takes_args = ['dir?']

    @display_command
    def run(self, dir=u'.'):
        tree = WorkingTree.open_containing(dir)[0]
        tree.lock_read()
        try:
            new_inv = tree.inventory
            old_tree = tree.basis_tree()
            old_tree.lock_read()
            try:
                old_inv = old_tree.inventory
                renames = list(_mod_tree.find_renames(old_inv, new_inv))
                renames.sort()
                for old_name, new_name in renames:
                    self.outf.write("%s => %s\n" % (old_name, new_name))
            finally:
                old_tree.unlock()
        finally:
            tree.unlock()


class cmd_update(Command):
    """Update a tree to have the latest code committed to its branch.
    
    This will perform a merge into the working tree, and may generate
    conflicts. If you have any local changes, you will still 
    need to commit them after the update for the update to be complete.
    
    If you want to discard your local changes, you can just do a 
    'bzr revert' instead of 'bzr commit' after the update.
    """

    _see_also = ['pull', 'working-trees', 'status-flags']
    takes_args = ['dir?']
    aliases = ['up']

    def run(self, dir='.'):
        tree = WorkingTree.open_containing(dir)[0]
        possible_transports = []
        master = tree.branch.get_master_branch(
            possible_transports=possible_transports)
        if master is not None:
            tree.lock_write()
        else:
            tree.lock_tree_write()
        try:
            existing_pending_merges = tree.get_parent_ids()[1:]
            last_rev = _mod_revision.ensure_null(tree.last_revision())
            if last_rev == _mod_revision.ensure_null(
                tree.branch.last_revision()):
                # may be up to date, check master too.
                if master is None or last_rev == _mod_revision.ensure_null(
                    master.last_revision()):
                    revno = tree.branch.revision_id_to_revno(last_rev)
                    note("Tree is up to date at revision %d." % (revno,))
                    return 0
            conflicts = tree.update(
                delta._ChangeReporter(unversioned_filter=tree.is_ignored),
                possible_transports=possible_transports)
            revno = tree.branch.revision_id_to_revno(
                _mod_revision.ensure_null(tree.last_revision()))
            note('Updated to revision %d.' % (revno,))
            if tree.get_parent_ids()[1:] != existing_pending_merges:
                note('Your local commits will now show as pending merges with '
                     "'bzr status', and can be committed with 'bzr commit'.")
            if conflicts != 0:
                return 1
            else:
                return 0
        finally:
            tree.unlock()


class cmd_info(Command):
    """Show information about a working tree, branch or repository.

    This command will show all known locations and formats associated to the
    tree, branch or repository.  Statistical information is included with
    each report.

    Branches and working trees will also report any missing revisions.
    """
    _see_also = ['revno', 'working-trees', 'repositories']
    takes_args = ['location?']
    takes_options = ['verbose']

    @display_command
    def run(self, location=None, verbose=False):
        if verbose:
            noise_level = 2
        else:
            noise_level = 0
        from bzrlib.info import show_bzrdir_info
        show_bzrdir_info(bzrdir.BzrDir.open_containing(location)[0],
                         verbose=noise_level)


class cmd_remove(Command):
    """Remove files or directories.

    This makes bzr stop tracking changes to the specified files and
    delete them if they can easily be recovered using revert.

    You can specify one or more files, and/or --new.  If you specify --new,
    only 'added' files will be removed.  If you specify both, then new files
    in the specified directories will be removed.  If the directories are
    also new, they will also be removed.
    """
    takes_args = ['file*']
    takes_options = ['verbose',
        Option('new', help='Remove newly-added files.'),
        RegistryOption.from_kwargs('file-deletion-strategy',
            'The file deletion mode to be used.',
            title='Deletion Strategy', value_switches=True, enum_switch=False,
            safe='Only delete files if they can be'
                 ' safely recovered (default).',
            keep="Don't delete any files.",
            force='Delete all the specified files, even if they can not be '
                'recovered and even if they are non-empty directories.')]
    aliases = ['rm']
    encoding_type = 'replace'

    def run(self, file_list, verbose=False, new=False,
        file_deletion_strategy='safe'):
        tree, file_list = tree_files(file_list)

        if file_list is not None:
            file_list = [f for f in file_list]
        elif not new:
            raise errors.BzrCommandError('Specify one or more files to'
            ' remove, or use --new.')

        if new:
            added = tree.changes_from(tree.basis_tree(),
                specific_files=file_list).added
            file_list = sorted([f[0] for f in added], reverse=True)
            if len(file_list) == 0:
                raise errors.BzrCommandError('No matching files.')
        tree.remove(file_list, verbose=verbose, to_file=self.outf,
            keep_files=file_deletion_strategy=='keep',
            force=file_deletion_strategy=='force')


class cmd_file_id(Command):
    """Print file_id of a particular file or directory.

    The file_id is assigned when the file is first added and remains the
    same through all revisions where the file exists, even when it is
    moved or renamed.
    """

    hidden = True
    _see_also = ['inventory', 'ls']
    takes_args = ['filename']

    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        i = tree.path2id(relpath)
        if i is None:
            raise errors.NotVersionedError(filename)
        else:
            self.outf.write(i + '\n')


class cmd_file_path(Command):
    """Print path of file_ids to a file or directory.

    This prints one line for each directory down to the target,
    starting at the branch root.
    """

    hidden = True
    takes_args = ['filename']

    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        fid = tree.path2id(relpath)
        if fid is None:
            raise errors.NotVersionedError(filename)
        segments = osutils.splitpath(relpath)
        for pos in range(1, len(segments) + 1):
            path = osutils.joinpath(segments[:pos])
            self.outf.write("%s\n" % tree.path2id(path))


class cmd_reconcile(Command):
    """Reconcile bzr metadata in a branch.

    This can correct data mismatches that may have been caused by
    previous ghost operations or bzr upgrades. You should only
    need to run this command if 'bzr check' or a bzr developer 
    advises you to run it.

    If a second branch is provided, cross-branch reconciliation is
    also attempted, which will check that data like the tree root
    id which was not present in very early bzr versions is represented
    correctly in both branches.

    At the same time it is run it may recompress data resulting in 
    a potential saving in disk space or performance gain.

    The branch *MUST* be on a listable system such as local disk or sftp.
    """

    _see_also = ['check']
    takes_args = ['branch?']

    def run(self, branch="."):
        from bzrlib.reconcile import reconcile
        dir = bzrdir.BzrDir.open(branch)
        reconcile(dir)


class cmd_revision_history(Command):
    """Display the list of revision ids on a branch."""

    _see_also = ['log']
    takes_args = ['location?']

    hidden = True

    @display_command
    def run(self, location="."):
        branch = Branch.open_containing(location)[0]
        for revid in branch.revision_history():
            self.outf.write(revid)
            self.outf.write('\n')


class cmd_ancestry(Command):
    """List all revisions merged into this branch."""

    _see_also = ['log', 'revision-history']
    takes_args = ['location?']

    hidden = True

    @display_command
    def run(self, location="."):
        try:
            wt = WorkingTree.open_containing(location)[0]
        except errors.NoWorkingTree:
            b = Branch.open(location)
            last_revision = b.last_revision()
        else:
            b = wt.branch
            last_revision = wt.last_revision()

        revision_ids = b.repository.get_ancestry(last_revision)
        assert revision_ids[0] is None
        revision_ids.pop(0)
        for revision_id in revision_ids:
            self.outf.write(revision_id + '\n')


class cmd_init(Command):
    """Make a directory into a versioned branch.

    Use this to create an empty branch, or before importing an
    existing project.

    If there is a repository in a parent directory of the location, then 
    the history of the branch will be stored in the repository.  Otherwise
    init creates a standalone branch which carries its own history
    in the .bzr directory.

    If there is already a branch at the location but it has no working tree,
    the tree can be populated with 'bzr checkout'.

    Recipe for importing a tree of files::

        cd ~/project
        bzr init
        bzr add .
        bzr status
        bzr commit -m 'imported project'
    """

    _see_also = ['init-repository', 'branch', 'checkout']
    takes_args = ['location?']
    takes_options = [
        Option('create-prefix',
               help='Create the path leading up to the branch '
                    'if it does not already exist.'),
         RegistryOption('format',
                help='Specify a format for this branch. '
                'See "help formats".',
                registry=bzrdir.format_registry,
                converter=bzrdir.format_registry.make_bzrdir,
                value_switches=True,
                title="Branch Format",
                ),
         Option('append-revisions-only',
                help='Never change revnos or the existing log.'
                '  Append revisions to it only.')
         ]
    def run(self, location=None, format=None, append_revisions_only=False,
            create_prefix=False):
        if format is None:
            format = bzrdir.format_registry.make_bzrdir('default')
        if location is None:
            location = u'.'

        to_transport = transport.get_transport(location)

        # The path has to exist to initialize a
        # branch inside of it.
        # Just using os.mkdir, since I don't
        # believe that we want to create a bunch of
        # locations if the user supplies an extended path
        try:
            to_transport.ensure_base()
        except errors.NoSuchFile:
            if not create_prefix:
                raise errors.BzrCommandError("Parent directory of %s"
                    " does not exist."
                    "\nYou may supply --create-prefix to create all"
                    " leading parent directories."
                    % location)
            _create_prefix(to_transport)

        try:
            existing_bzrdir = bzrdir.BzrDir.open_from_transport(to_transport)
        except errors.NotBranchError:
            # really a NotBzrDir error...
            create_branch = bzrdir.BzrDir.create_branch_convenience
            branch = create_branch(to_transport.base, format=format,
                                   possible_transports=[to_transport])
        else:
            from bzrlib.transport.local import LocalTransport
            if existing_bzrdir.has_branch():
                if (isinstance(to_transport, LocalTransport)
                    and not existing_bzrdir.has_workingtree()):
                        raise errors.BranchExistsWithoutWorkingTree(location)
                raise errors.AlreadyBranchError(location)
            else:
                branch = existing_bzrdir.create_branch()
                existing_bzrdir.create_workingtree()
        if append_revisions_only:
            try:
                branch.set_append_revisions_only(True)
            except errors.UpgradeRequired:
                raise errors.BzrCommandError('This branch format cannot be set'
                    ' to append-revisions-only.  Try --experimental-branch6')


class cmd_init_repository(Command):
    """Create a shared repository to hold branches.

    New branches created under the repository directory will store their
    revisions in the repository, not in the branch directory.

    If the --no-trees option is used then the branches in the repository
    will not have working trees by default.

    :Examples:
        Create a shared repositories holding just branches::

            bzr init-repo --no-trees repo
            bzr init repo/trunk

        Make a lightweight checkout elsewhere::

            bzr checkout --lightweight repo/trunk trunk-checkout
            cd trunk-checkout
            (add files here)
    """

    _see_also = ['init', 'branch', 'checkout', 'repositories']
    takes_args = ["location"]
    takes_options = [RegistryOption('format',
                            help='Specify a format for this repository. See'
                                 ' "bzr help formats" for details.',
                            registry=bzrdir.format_registry,
                            converter=bzrdir.format_registry.make_bzrdir,
                            value_switches=True, title='Repository format'),
                     Option('no-trees',
                             help='Branches in the repository will default to'
                                  ' not having a working tree.'),
                    ]
    aliases = ["init-repo"]

    def run(self, location, format=None, no_trees=False):
        if format is None:
            format = bzrdir.format_registry.make_bzrdir('default')

        if location is None:
            location = '.'

        to_transport = transport.get_transport(location)
        to_transport.ensure_base()

        newdir = format.initialize_on_transport(to_transport)
        repo = newdir.create_repository(shared=True)
        repo.set_make_working_trees(not no_trees)


class cmd_diff(Command):
    """Show differences in the working tree or between revisions.
    
    If files are listed, only the changes in those files are listed.
    Otherwise, all changes for the tree are listed.

    "bzr diff -p1" is equivalent to "bzr diff --prefix old/:new/", and
    produces patches suitable for "patch -p1".

    :Examples:
        Shows the difference in the working tree versus the last commit::

            bzr diff

        Difference between the working tree and revision 1::

            bzr diff -r1

        Difference between revision 2 and revision 1::

            bzr diff -r1..2

        Same as 'bzr diff' but prefix paths with old/ and new/::

            bzr diff --prefix old/:new/

        Show the differences between the two working trees::

            bzr diff bzr.mine bzr.dev

        Show just the differences for 'foo.c'::

            bzr diff foo.c
    """
    # TODO: Option to use external diff command; could be GNU diff, wdiff,
    #       or a graphical diff.

    # TODO: Python difflib is not exactly the same as unidiff; should
    #       either fix it up or prefer to use an external diff.

    # TODO: Selected-file diff is inefficient and doesn't show you
    #       deleted files.

    # TODO: This probably handles non-Unix newlines poorly.

    _see_also = ['status']
    takes_args = ['file*']
    takes_options = [
        Option('diff-options', type=str,
               help='Pass these options to the external diff program.'),
        Option('prefix', type=str,
               short_name='p',
               help='Set prefixes to added to old and new filenames, as '
                    'two values separated by a colon. (eg "old/:new/").'),
        'revision',
        'change',
        ]
    aliases = ['di', 'dif']
    encoding_type = 'exact'

    @display_command
    def run(self, revision=None, file_list=None, diff_options=None,
            prefix=None):
        from bzrlib.diff import diff_cmd_helper, show_diff_trees

        if (prefix is None) or (prefix == '0'):
            # diff -p0 format
            old_label = ''
            new_label = ''
        elif prefix == '1':
            old_label = 'old/'
            new_label = 'new/'
        elif ':' in prefix:
            old_label, new_label = prefix.split(":")
        else:
            raise errors.BzrCommandError(
                '--prefix expects two values separated by a colon'
                ' (eg "old/:new/")')

        if revision and len(revision) > 2:
            raise errors.BzrCommandError('bzr diff --revision takes exactly'
                                         ' one or two revision specifiers')

        try:
            tree1, file_list = internal_tree_files(file_list)
            tree2 = None
            b = None
            b2 = None
        except errors.FileInWrongBranch:
            if len(file_list) != 2:
                raise errors.BzrCommandError("Files are in different branches")

            tree1, file1 = WorkingTree.open_containing(file_list[0])
            tree2, file2 = WorkingTree.open_containing(file_list[1])
            if file1 != "" or file2 != "":
                # FIXME diff those two files. rbc 20051123
                raise errors.BzrCommandError("Files are in different branches")
            file_list = None
        except errors.NotBranchError:
            if (revision is not None and len(revision) == 2
                and not revision[0].needs_branch()
                and not revision[1].needs_branch()):
                # If both revision specs include a branch, we can
                # diff them without needing a local working tree
                tree1, tree2 = None, None
            else:
                raise

        if tree2 is not None:
            if revision is not None:
                # FIXME: but there should be a clean way to diff between
                # non-default versions of two trees, it's not hard to do
                # internally...
                raise errors.BzrCommandError(
                        "Sorry, diffing arbitrary revisions across branches "
                        "is not implemented yet")
            return show_diff_trees(tree1, tree2, sys.stdout, 
                                   specific_files=file_list,
                                   external_diff_options=diff_options,
                                   old_label=old_label, new_label=new_label)

        return diff_cmd_helper(tree1, file_list, diff_options,
                               revision_specs=revision,
                               old_label=old_label, new_label=new_label)


class cmd_deleted(Command):
    """List files deleted in the working tree.
    """
    # TODO: Show files deleted since a previous revision, or
    # between two revisions.
    # TODO: Much more efficient way to do this: read in new
    # directories with readdir, rather than stating each one.  Same
    # level of effort but possibly much less IO.  (Or possibly not,
    # if the directories are very large...)
    _see_also = ['status', 'ls']
    takes_options = ['show-ids']

    @display_command
    def run(self, show_ids=False):
        tree = WorkingTree.open_containing(u'.')[0]
        tree.lock_read()
        try:
            old = tree.basis_tree()
            old.lock_read()
            try:
                for path, ie in old.inventory.iter_entries():
                    if not tree.has_id(ie.file_id):
                        self.outf.write(path)
                        if show_ids:
                            self.outf.write(' ')
                            self.outf.write(ie.file_id)
                        self.outf.write('\n')
            finally:
                old.unlock()
        finally:
            tree.unlock()


class cmd_modified(Command):
    """List files modified in working tree.
    """

    hidden = True
    _see_also = ['status', 'ls']

    @display_command
    def run(self):
        tree = WorkingTree.open_containing(u'.')[0]
        td = tree.changes_from(tree.basis_tree())
        for path, id, kind, text_modified, meta_modified in td.modified:
            self.outf.write(path + '\n')


class cmd_added(Command):
    """List files added in working tree.
    """

    hidden = True
    _see_also = ['status', 'ls']

    @display_command
    def run(self):
        wt = WorkingTree.open_containing(u'.')[0]
        wt.lock_read()
        try:
            basis = wt.basis_tree()
            basis.lock_read()
            try:
                basis_inv = basis.inventory
                inv = wt.inventory
                for file_id in inv:
                    if file_id in basis_inv:
                        continue
                    if inv.is_root(file_id) and len(basis_inv) == 0:
                        continue
                    path = inv.id2path(file_id)
                    if not os.access(osutils.abspath(path), os.F_OK):
                        continue
                    self.outf.write(path + '\n')
            finally:
                basis.unlock()
        finally:
            wt.unlock()


class cmd_root(Command):
    """Show the tree root directory.

    The root is the nearest enclosing directory with a .bzr control
    directory."""

    takes_args = ['filename?']
    @display_command
    def run(self, filename=None):
        """Print the branch root."""
        tree = WorkingTree.open_containing(filename)[0]
        self.outf.write(tree.basedir + '\n')


def _parse_limit(limitstring):
    try:
        return int(limitstring)
    except ValueError:
        msg = "The limit argument must be an integer."
        raise errors.BzrCommandError(msg)


class cmd_log(Command):
    """Show log of a branch, file, or directory.

    By default show the log of the branch containing the working directory.

    To request a range of logs, you can use the command -r begin..end
    -r revision requests a specific revision, -r ..end or -r begin.. are
    also valid.

    :Examples:
        Log the current branch::

            bzr log

        Log a file::

            bzr log foo.c

        Log the last 10 revisions of a branch::

            bzr log -r -10.. http://server/branch
    """

    # TODO: Make --revision support uuid: and hash: [future tag:] notation.

    takes_args = ['location?']
    takes_options = [
            Option('forward',
                   help='Show from oldest to newest.'),
            Option('timezone',
                   type=str,
                   help='Display timezone as local, original, or utc.'),
            custom_help('verbose',
                   help='Show files changed in each revision.'),
            'show-ids',
            'revision',
            'log-format',
            Option('message',
                   short_name='m',
                   help='Show revisions whose message matches this '
                        'regular expression.',
                   type=str),
            Option('limit',
                   help='Limit the output to the first N revisions.',
                   argname='N',
                   type=_parse_limit),
            ]
    encoding_type = 'replace'

    @display_command
    def run(self, location=None, timezone='original',
            verbose=False,
            show_ids=False,
            forward=False,
            revision=None,
            log_format=None,
            message=None,
            limit=None):
        from bzrlib.log import show_log
        assert message is None or isinstance(message, basestring), \
            "invalid message argument %r" % message
        direction = (forward and 'forward') or 'reverse'
        
        # log everything
        file_id = None
        if location:
            # find the file id to log:

            tree, b, fp = bzrdir.BzrDir.open_containing_tree_or_branch(
                location)
            if fp != '':
                if tree is None:
                    tree = b.basis_tree()
                file_id = tree.path2id(fp)
                if file_id is None:
                    raise errors.BzrCommandError(
                        "Path does not have any revision history: %s" %
                        location)
        else:
            # local dir only
            # FIXME ? log the current subdir only RBC 20060203 
            if revision is not None \
                    and len(revision) > 0 and revision[0].get_branch():
                location = revision[0].get_branch()
            else:
                location = '.'
            dir, relpath = bzrdir.BzrDir.open_containing(location)
            b = dir.open_branch()

        b.lock_read()
        try:
            if revision is None:
                rev1 = None
                rev2 = None
            elif len(revision) == 1:
                rev1 = rev2 = revision[0].in_history(b)
            elif len(revision) == 2:
                if revision[1].get_branch() != revision[0].get_branch():
                    # b is taken from revision[0].get_branch(), and
                    # show_log will use its revision_history. Having
                    # different branches will lead to weird behaviors.
                    raise errors.BzrCommandError(
                        "Log doesn't accept two revisions in different"
                        " branches.")
                rev1 = revision[0].in_history(b)
                rev2 = revision[1].in_history(b)
            else:
                raise errors.BzrCommandError(
                    'bzr log --revision takes one or two values.')

            if log_format is None:
                log_format = log.log_formatter_registry.get_default(b)

            lf = log_format(show_ids=show_ids, to_file=self.outf,
                            show_timezone=timezone)

            show_log(b,
                     lf,
                     file_id,
                     verbose=verbose,
                     direction=direction,
                     start_revision=rev1,
                     end_revision=rev2,
                     search=message,
                     limit=limit)
        finally:
            b.unlock()


def get_log_format(long=False, short=False, line=False, default='long'):
    log_format = default
    if long:
        log_format = 'long'
    if short:
        log_format = 'short'
    if line:
        log_format = 'line'
    return log_format


class cmd_touching_revisions(Command):
    """Return revision-ids which affected a particular file.

    A more user-friendly interface is "bzr log FILE".
    """

    hidden = True
    takes_args = ["filename"]

    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        b = tree.branch
        file_id = tree.path2id(relpath)
        for revno, revision_id, what in log.find_touching_revisions(b, file_id):
            self.outf.write("%6d %s\n" % (revno, what))


class cmd_ls(Command):
    """List files in a tree.
    """

    _see_also = ['status', 'cat']
    takes_args = ['path?']
    # TODO: Take a revision or remote path and list that tree instead.
    takes_options = [
            'verbose',
            'revision',
            Option('non-recursive',
                   help='Don\'t recurse into subdirectories.'),
            Option('from-root',
                   help='Print paths relative to the root of the branch.'),
            Option('unknown', help='Print unknown files.'),
            Option('versioned', help='Print versioned files.'),
            Option('ignored', help='Print ignored files.'),
            Option('null',
                   help='Write an ascii NUL (\\0) separator '
                   'between files rather than a newline.'),
            Option('kind',
                   help='List entries of a particular kind: file, directory, symlink.',
                   type=unicode),
            'show-ids',
            ]
    @display_command
    def run(self, revision=None, verbose=False,
            non_recursive=False, from_root=False,
            unknown=False, versioned=False, ignored=False,
            null=False, kind=None, show_ids=False, path=None):

        if kind and kind not in ('file', 'directory', 'symlink'):
            raise errors.BzrCommandError('invalid kind specified')

        if verbose and null:
            raise errors.BzrCommandError('Cannot set both --verbose and --null')
        all = not (unknown or versioned or ignored)

        selection = {'I':ignored, '?':unknown, 'V':versioned}

        if path is None:
            fs_path = '.'
            prefix = ''
        else:
            if from_root:
                raise errors.BzrCommandError('cannot specify both --from-root'
                                             ' and PATH')
            fs_path = path
            prefix = path
        tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(
            fs_path)
        if from_root:
            relpath = u''
        elif relpath:
            relpath += '/'
        if revision is not None:
            tree = branch.repository.revision_tree(
                revision[0].in_history(branch).rev_id)
        elif tree is None:
            tree = branch.basis_tree()

        tree.lock_read()
        try:
            for fp, fc, fkind, fid, entry in tree.list_files(include_root=False):
                if fp.startswith(relpath):
                    fp = osutils.pathjoin(prefix, fp[len(relpath):])
                    if non_recursive and '/' in fp:
                        continue
                    if not all and not selection[fc]:
                        continue
                    if kind is not None and fkind != kind:
                        continue
                    if verbose:
                        kindch = entry.kind_character()
                        outstring = '%-8s %s%s' % (fc, fp, kindch)
                        if show_ids and fid is not None:
                            outstring = "%-50s %s" % (outstring, fid)
                        self.outf.write(outstring + '\n')
                    elif null:
                        self.outf.write(fp + '\0')
                        if show_ids:
                            if fid is not None:
                                self.outf.write(fid)
                            self.outf.write('\0')
                        self.outf.flush()
                    else:
                        if fid is not None:
                            my_id = fid
                        else:
                            my_id = ''
                        if show_ids:
                            self.outf.write('%-50s %s\n' % (fp, my_id))
                        else:
                            self.outf.write(fp + '\n')
        finally:
            tree.unlock()


class cmd_unknowns(Command):
    """List unknown files.
    """

    hidden = True
    _see_also = ['ls']

    @display_command
    def run(self):
        for f in WorkingTree.open_containing(u'.')[0].unknowns():
            self.outf.write(osutils.quotefn(f) + '\n')


class cmd_ignore(Command):
    """Ignore specified files or patterns.

    To remove patterns from the ignore list, edit the .bzrignore file.

    Trailing slashes on patterns are ignored. 
    If the pattern contains a slash or is a regular expression, it is compared 
    to the whole path from the branch root.  Otherwise, it is compared to only
    the last component of the path.  To match a file only in the root 
    directory, prepend './'.

    Ignore patterns specifying absolute paths are not allowed.

    Ignore patterns may include globbing wildcards such as::

      ? - Matches any single character except '/'
      * - Matches 0 or more characters except '/'
      /**/ - Matches 0 or more directories in a path
      [a-z] - Matches a single character from within a group of characters
 
    Ignore patterns may also be Python regular expressions.  
    Regular expression ignore patterns are identified by a 'RE:' prefix 
    followed by the regular expression.  Regular expression ignore patterns
    may not include named or numbered groups.

    Note: ignore patterns containing shell wildcards must be quoted from 
    the shell on Unix.

    :Examples:
        Ignore the top level Makefile::

            bzr ignore ./Makefile

        Ignore class files in all directories::

            bzr ignore '*.class'

        Ignore .o files under the lib directory::

            bzr ignore 'lib/**/*.o'

        Ignore .o files under the lib directory::

            bzr ignore 'RE:lib/.*\.o'
    """

    _see_also = ['status', 'ignored']
    takes_args = ['name_pattern*']
    takes_options = [
        Option('old-default-rules',
               help='Write out the ignore rules bzr < 0.9 always used.')
        ]
    
    def run(self, name_pattern_list=None, old_default_rules=None):
        from bzrlib.atomicfile import AtomicFile
        if old_default_rules is not None:
            # dump the rules and exit
            for pattern in ignores.OLD_DEFAULTS:
                print pattern
            return
        if not name_pattern_list:
            raise errors.BzrCommandError("ignore requires at least one "
                                  "NAME_PATTERN or --old-default-rules")
        name_pattern_list = [globbing.normalize_pattern(p) 
                             for p in name_pattern_list]
        for name_pattern in name_pattern_list:
            if (name_pattern[0] == '/' or 
                (len(name_pattern) > 1 and name_pattern[1] == ':')):
                raise errors.BzrCommandError(
                    "NAME_PATTERN should not be an absolute path")
        tree, relpath = WorkingTree.open_containing(u'.')
        ifn = tree.abspath('.bzrignore')
        if os.path.exists(ifn):
            f = open(ifn, 'rt')
            try:
                igns = f.read().decode('utf-8')
            finally:
                f.close()
        else:
            igns = ''

        # TODO: If the file already uses crlf-style termination, maybe
        # we should use that for the newly added lines?

        if igns and igns[-1] != '\n':
            igns += '\n'
        for name_pattern in name_pattern_list:
            igns += name_pattern + '\n'

        f = AtomicFile(ifn, 'wb')
        try:
            f.write(igns.encode('utf-8'))
            f.commit()
        finally:
            f.close()

        if not tree.path2id('.bzrignore'):
            tree.add(['.bzrignore'])

        ignored = globbing.Globster(name_pattern_list)
        matches = []
        tree.lock_read()
        for entry in tree.list_files():
            id = entry[3]
            if id is not None:
                filename = entry[0]
                if ignored.match(filename):
                    matches.append(filename.encode('utf-8'))
        tree.unlock()
        if len(matches) > 0:
            print "Warning: the following files are version controlled and" \
                  " match your ignore pattern:\n%s" % ("\n".join(matches),)

class cmd_ignored(Command):
    """List ignored files and the patterns that matched them.
    """

    _see_also = ['ignore']
    @display_command
    def run(self):
        tree = WorkingTree.open_containing(u'.')[0]
        tree.lock_read()
        try:
            for path, file_class, kind, file_id, entry in tree.list_files():
                if file_class != 'I':
                    continue
                ## XXX: Slightly inefficient since this was already calculated
                pat = tree.is_ignored(path)
                print '%-50s %s' % (path, pat)
        finally:
            tree.unlock()


class cmd_lookup_revision(Command):
    """Lookup the revision-id from a revision-number

    :Examples:
        bzr lookup-revision 33
    """
    hidden = True
    takes_args = ['revno']
    
    @display_command
    def run(self, revno):
        try:
            revno = int(revno)
        except ValueError:
            raise errors.BzrCommandError("not a valid revision-number: %r" % revno)

        print WorkingTree.open_containing(u'.')[0].branch.get_rev_id(revno)


class cmd_export(Command):
    """Export current or past revision to a destination directory or archive.

    If no revision is specified this exports the last committed revision.

    Format may be an "exporter" name, such as tar, tgz, tbz2.  If none is
    given, try to find the format with the extension. If no extension
    is found exports to a directory (equivalent to --format=dir).

    If root is supplied, it will be used as the root directory inside
    container formats (tar, zip, etc). If it is not supplied it will default
    to the exported filename. The root option has no effect for 'dir' format.

    If branch is omitted then the branch containing the current working
    directory will be used.

    Note: Export of tree with non-ASCII filenames to zip is not supported.

      =================       =========================
      Supported formats       Autodetected by extension
      =================       =========================
         dir                         (none)
         tar                          .tar
         tbz2                    .tar.bz2, .tbz2
         tgz                      .tar.gz, .tgz
         zip                          .zip
      =================       =========================
    """
    takes_args = ['dest', 'branch?']
    takes_options = [
        Option('format',
               help="Type of file to export to.",
               type=unicode),
        'revision',
        Option('root',
               type=str,
               help="Name of the root directory inside the exported file."),
        ]
    def run(self, dest, branch=None, revision=None, format=None, root=None):
        from bzrlib.export import export

        if branch is None:
            tree = WorkingTree.open_containing(u'.')[0]
            b = tree.branch
        else:
            b = Branch.open(branch)
            
        if revision is None:
            # should be tree.last_revision  FIXME
            rev_id = b.last_revision()
        else:
            if len(revision) != 1:
                raise errors.BzrCommandError('bzr export --revision takes exactly 1 argument')
            rev_id = revision[0].in_history(b).rev_id
        t = b.repository.revision_tree(rev_id)
        try:
            export(t, dest, format, root)
        except errors.NoSuchExportFormat, e:
            raise errors.BzrCommandError('Unsupported export format: %s' % e.format)


class cmd_cat(Command):
    """Write the contents of a file as of a given revision to standard output.

    If no revision is nominated, the last revision is used.

    Note: Take care to redirect standard output when using this command on a
    binary file. 
    """

    _see_also = ['ls']
    takes_options = [
        Option('name-from-revision', help='The path name in the old tree.'),
        'revision',
        ]
    takes_args = ['filename']
    encoding_type = 'exact'

    @display_command
    def run(self, filename, revision=None, name_from_revision=False):
        if revision is not None and len(revision) != 1:
            raise errors.BzrCommandError("bzr cat --revision takes exactly"
                                        " one number")

        tree = None
        try:
            tree, b, relpath = \
                    bzrdir.BzrDir.open_containing_tree_or_branch(filename)
        except errors.NotBranchError:
            pass

        if revision is not None and revision[0].get_branch() is not None:
            b = Branch.open(revision[0].get_branch())
        if tree is None:
            tree = b.basis_tree()
        if revision is None:
            revision_id = b.last_revision()
        else:
            revision_id = revision[0].in_history(b).rev_id

        cur_file_id = tree.path2id(relpath)
        rev_tree = b.repository.revision_tree(revision_id)
        old_file_id = rev_tree.path2id(relpath)
        
        if name_from_revision:
            if old_file_id is None:
                raise errors.BzrCommandError("%r is not present in revision %s"
                                                % (filename, revision_id))
            else:
                rev_tree.print_file(old_file_id)
        elif cur_file_id is not None:
            rev_tree.print_file(cur_file_id)
        elif old_file_id is not None:
            rev_tree.print_file(old_file_id)
        else:
            raise errors.BzrCommandError("%r is not present in revision %s" %
                                         (filename, revision_id))


class cmd_local_time_offset(Command):
    """Show the offset in seconds from GMT to local time."""
    hidden = True    
    @display_command
    def run(self):
        print osutils.local_time_offset()



class cmd_commit(Command):
    """Commit changes into a new revision.
    
    If no arguments are given, the entire tree is committed.

    If selected files are specified, only changes to those files are
    committed.  If a directory is specified then the directory and everything 
    within it is committed.

    If author of the change is not the same person as the committer, you can
    specify the author's name using the --author option. The name should be
    in the same format as a committer-id, e.g. "John Doe <jdoe@example.com>".

    A selected-file commit may fail in some cases where the committed
    tree would be invalid. Consider::

      bzr init foo
      mkdir foo/bar
      bzr add foo/bar
      bzr commit foo -m "committing foo"
      bzr mv foo/bar foo/baz
      mkdir foo/bar
      bzr add foo/bar
      bzr commit foo/bar -m "committing bar but not baz"

    In the example above, the last commit will fail by design. This gives
    the user the opportunity to decide whether they want to commit the
    rename at the same time, separately first, or not at all. (As a general
    rule, when in doubt, Bazaar has a policy of Doing the Safe Thing.)

    Note: A selected-file commit after a merge is not yet supported.
    """
    # TODO: Run hooks on tree to-be-committed, and after commit.

    # TODO: Strict commit that fails if there are deleted files.
    #       (what does "deleted files" mean ??)

    # TODO: Give better message for -s, --summary, used by tla people

    # XXX: verbose currently does nothing

    _see_also = ['bugs', 'uncommit']
    takes_args = ['selected*']
    takes_options = [
            Option('message', type=unicode,
                   short_name='m',
                   help="Description of the new revision."),
            'verbose',
             Option('unchanged',
                    help='Commit even if nothing has changed.'),
             Option('file', type=str,
                    short_name='F',
                    argname='msgfile',
                    help='Take commit message from this file.'),
             Option('strict',
                    help="Refuse to commit if there are unknown "
                    "files in the working tree."),
             ListOption('fixes', type=str,
                    help="Mark a bug as being fixed by this revision."),
             Option('author', type=str,
                    help="Set the author's name, if it's different "
                         "from the committer."),
             Option('local',
                    help="Perform a local commit in a bound "
                         "branch.  Local commits are not pushed to "
                         "the master branch until a normal commit "
                         "is performed."
                    ),
              Option('show-diff',
                     help='When no message is supplied, show the diff along'
                     ' with the status summary in the message editor.'),
             ]
    aliases = ['ci', 'checkin']

    def _get_bug_fix_properties(self, fixes, branch):
        properties = []
        # Configure the properties for bug fixing attributes.
        for fixed_bug in fixes:
            tokens = fixed_bug.split(':')
            if len(tokens) != 2:
                raise errors.BzrCommandError(
                    "Invalid bug %s. Must be in the form of 'tag:id'. "
                    "Commit refused." % fixed_bug)
            tag, bug_id = tokens
            try:
                bug_url = bugtracker.get_bug_url(tag, branch, bug_id)
            except errors.UnknownBugTrackerAbbreviation:
                raise errors.BzrCommandError(
                    'Unrecognized bug %s. Commit refused.' % fixed_bug)
            except errors.MalformedBugIdentifier:
                raise errors.BzrCommandError(
                    "Invalid bug identifier for %s. Commit refused."
                    % fixed_bug)
            properties.append('%s fixed' % bug_url)
        return '\n'.join(properties)

    def run(self, message=None, file=None, verbose=False, selected_list=None,
            unchanged=False, strict=False, local=False, fixes=None,
            author=None, show_diff=False):
        from bzrlib.commit import (
            NullCommitReporter,
            ReportCommitToLog
        )
        from bzrlib.errors import (
            PointlessCommit,
            ConflictsInTree,
            StrictCommitFailed
        )
        from bzrlib.msgeditor import (
            edit_commit_message_encoded,
            make_commit_message_template_encoded
        )

        # TODO: Need a blackbox test for invoking the external editor; may be
        # slightly problematic to run this cross-platform.

        # TODO: do more checks that the commit will succeed before 
        # spending the user's valuable time typing a commit message.

        properties = {}

        tree, selected_list = tree_files(selected_list)
        if selected_list == ['']:
            # workaround - commit of root of tree should be exactly the same
            # as just default commit in that tree, and succeed even though
            # selected-file merge commit is not done yet
            selected_list = []

        bug_property = self._get_bug_fix_properties(fixes, tree.branch)
        if bug_property:
            properties['bugs'] = bug_property

        if local and not tree.branch.get_bound_location():
            raise errors.LocalRequiresBoundBranch()

        def get_message(commit_obj):
            """Callback to get commit message"""
            my_message = message
            if my_message is None and not file:
                t = make_commit_message_template_encoded(tree,
                        selected_list, diff=show_diff,
                        output_encoding=bzrlib.user_encoding)
                my_message = edit_commit_message_encoded(t)
                if my_message is None:
                    raise errors.BzrCommandError("please specify a commit"
                        " message with either --message or --file")
            elif my_message and file:
                raise errors.BzrCommandError(
                    "please specify either --message or --file")
            if file:
                my_message = codecs.open(file, 'rt', 
                                         bzrlib.user_encoding).read()
            if my_message == "":
                raise errors.BzrCommandError("empty commit message specified")
            return my_message

        try:
            tree.commit(message_callback=get_message,
                        specific_files=selected_list,
                        allow_pointless=unchanged, strict=strict, local=local,
                        reporter=None, verbose=verbose, revprops=properties,
                        author=author)
        except PointlessCommit:
            # FIXME: This should really happen before the file is read in;
            # perhaps prepare the commit; get the message; then actually commit
            raise errors.BzrCommandError("no changes to commit."
                              " use --unchanged to commit anyhow")
        except ConflictsInTree:
            raise errors.BzrCommandError('Conflicts detected in working '
                'tree.  Use "bzr conflicts" to list, "bzr resolve FILE" to'
                ' resolve.')
        except StrictCommitFailed:
            raise errors.BzrCommandError("Commit refused because there are"
                              " unknown files in the working tree.")
        except errors.BoundBranchOutOfDate, e:
            raise errors.BzrCommandError(str(e) + "\n"
            'To commit to master branch, run update and then commit.\n'
            'You can also pass --local to commit to continue working '
            'disconnected.')


class cmd_check(Command):
    """Validate consistency of branch history.

    This command checks various invariants about the branch storage to
    detect data corruption or bzr bugs.
    """

    _see_also = ['reconcile']
    takes_args = ['branch?']
    takes_options = ['verbose']

    def run(self, branch=None, verbose=False):
        from bzrlib.check import check
        if branch is None:
            tree = WorkingTree.open_containing()[0]
            branch = tree.branch
        else:
            branch = Branch.open(branch)
        check(branch, verbose)


class cmd_upgrade(Command):
    """Upgrade branch storage to current format.

    The check command or bzr developers may sometimes advise you to run
    this command. When the default format has changed you may also be warned
    during other operations to upgrade.
    """

    _see_also = ['check']
    takes_args = ['url?']
    takes_options = [
                    RegistryOption('format',
                        help='Upgrade to a specific format.  See "bzr help'
                             ' formats" for details.',
                        registry=bzrdir.format_registry,
                        converter=bzrdir.format_registry.make_bzrdir,
                        value_switches=True, title='Branch format'),
                    ]

    def run(self, url='.', format=None):
        from bzrlib.upgrade import upgrade
        if format is None:
            format = bzrdir.format_registry.make_bzrdir('default')
        upgrade(url, format)


class cmd_whoami(Command):
    """Show or set bzr user id.
    
    :Examples:
        Show the email of the current user::

            bzr whoami --email

        Set the current user::

            bzr whoami 'Frank Chu <fchu@example.com>'
    """
    takes_options = [ Option('email',
                             help='Display email address only.'),
                      Option('branch',
                             help='Set identity for the current branch instead of '
                                  'globally.'),
                    ]
    takes_args = ['name?']
    encoding_type = 'replace'
    
    @display_command
    def run(self, email=False, branch=False, name=None):
        if name is None:
            # use branch if we're inside one; otherwise global config
            try:
                c = Branch.open_containing('.')[0].get_config()
            except errors.NotBranchError:
                c = config.GlobalConfig()
            if email:
                self.outf.write(c.user_email() + '\n')
            else:
                self.outf.write(c.username() + '\n')
            return

        # display a warning if an email address isn't included in the given name.
        try:
            config.extract_email_address(name)
        except errors.NoEmailInUsername, e:
            warning('"%s" does not seem to contain an email address.  '
                    'This is allowed, but not recommended.', name)
        
        # use global config unless --branch given
        if branch:
            c = Branch.open_containing('.')[0].get_config()
        else:
            c = config.GlobalConfig()
        c.set_user_option('email', name)


class cmd_nick(Command):
    """Print or set the branch nickname.  

    If unset, the tree root directory name is used as the nickname
    To print the current nickname, execute with no argument.  
    """

    _see_also = ['info']
    takes_args = ['nickname?']
    def run(self, nickname=None):
        branch = Branch.open_containing(u'.')[0]
        if nickname is None:
            self.printme(branch)
        else:
            branch.nick = nickname

    @display_command
    def printme(self, branch):
        print branch.nick


class cmd_selftest(Command):
    """Run internal test suite.
    
    If arguments are given, they are regular expressions that say which tests
    should run.  Tests matching any expression are run, and other tests are
    not run.

    Alternatively if --first is given, matching tests are run first and then
    all other tests are run.  This is useful if you have been working in a
    particular area, but want to make sure nothing else was broken.

    If --exclude is given, tests that match that regular expression are
    excluded, regardless of whether they match --first or not.

    To help catch accidential dependencies between tests, the --randomize
    option is useful. In most cases, the argument used is the word 'now'.
    Note that the seed used for the random number generator is displayed
    when this option is used. The seed can be explicitly passed as the
    argument to this option if required. This enables reproduction of the
    actual ordering used if and when an order sensitive problem is encountered.

    If --list-only is given, the tests that would be run are listed. This is
    useful when combined with --first, --exclude and/or --randomize to
    understand their impact. The test harness reports "Listed nn tests in ..."
    instead of "Ran nn tests in ..." when list mode is enabled.

    If the global option '--no-plugins' is given, plugins are not loaded
    before running the selftests.  This has two effects: features provided or
    modified by plugins will not be tested, and tests provided by plugins will
    not be run.

    Tests that need working space on disk use a common temporary directory, 
    typically inside $TMPDIR or /tmp.

    :Examples:
        Run only tests relating to 'ignore'::

            bzr selftest ignore

        Disable plugins and list tests as they're run::

            bzr --no-plugins selftest -v
    """
    # NB: this is used from the class without creating an instance, which is
    # why it does not have a self parameter.
    def get_transport_type(typestring):
        """Parse and return a transport specifier."""
        if typestring == "sftp":
            from bzrlib.transport.sftp import SFTPAbsoluteServer
            return SFTPAbsoluteServer
        if typestring == "memory":
            from bzrlib.transport.memory import MemoryServer
            return MemoryServer
        if typestring == "fakenfs":
            from bzrlib.transport.fakenfs import FakeNFSServer
            return FakeNFSServer
        msg = "No known transport type %s. Supported types are: sftp\n" %\
            (typestring)
        raise errors.BzrCommandError(msg)

    hidden = True
    takes_args = ['testspecs*']
    takes_options = ['verbose',
                     Option('one',
                             help='Stop when one test fails.',
                             short_name='1',
                             ),
                     Option('transport',
                            help='Use a different transport by default '
                                 'throughout the test suite.',
                            type=get_transport_type),
                     Option('benchmark',
                            help='Run the benchmarks rather than selftests.'),
                     Option('lsprof-timed',
                            help='Generate lsprof output for benchmarked'
                                 ' sections of code.'),
                     Option('cache-dir', type=str,
                            help='Cache intermediate benchmark output in this '
                                 'directory.'),
                     Option('first',
                            help='Run all tests, but run specified tests first.',
                            short_name='f',
                            ),
                     Option('list-only',
                            help='List the tests instead of running them.'),
                     Option('randomize', type=str, argname="SEED",
                            help='Randomize the order of tests using the given'
                                 ' seed or "now" for the current time.'),
                     Option('exclude', type=str, argname="PATTERN",
                            short_name='x',
                            help='Exclude tests that match this regular'
                                 ' expression.'),
                     Option('strict', help='Fail on missing dependencies or '
                            'known failures.'),
                     ]
    encoding_type = 'replace'

    def run(self, testspecs_list=None, verbose=False, one=False,
            transport=None, benchmark=None,
            lsprof_timed=None, cache_dir=None,
            first=False, list_only=False,
            randomize=None, exclude=None, strict=False):
        import bzrlib.ui
        from bzrlib.tests import selftest
        import bzrlib.benchmarks as benchmarks
        from bzrlib.benchmarks import tree_creator

        if cache_dir is not None:
            tree_creator.TreeCreator.CACHE_ROOT = osutils.abspath(cache_dir)
        if not list_only:
            print 'testing: %s' % (osutils.realpath(sys.argv[0]),)
            print '   %s (%s python%s)' % (
                    bzrlib.__path__[0],
                    bzrlib.version_string,
                    '.'.join(map(str, sys.version_info)),
                    )
        print
        if testspecs_list is not None:
            pattern = '|'.join(testspecs_list)
        else:
            pattern = ".*"
        if benchmark:
            test_suite_factory = benchmarks.test_suite
            # Unless user explicitly asks for quiet, be verbose in benchmarks
            verbose = not is_quiet()
            # TODO: should possibly lock the history file...
            benchfile = open(".perf_history", "at", buffering=1)
        else:
            test_suite_factory = None
            benchfile = None
        try:
            result = selftest(verbose=verbose,
                              pattern=pattern,
                              stop_on_failure=one,
                              transport=transport,
                              test_suite_factory=test_suite_factory,
                              lsprof_timed=lsprof_timed,
                              bench_history=benchfile,
                              matching_tests_first=first,
                              list_only=list_only,
                              random_seed=randomize,
                              exclude_pattern=exclude,
                              strict=strict,
                              )
        finally:
            if benchfile is not None:
                benchfile.close()
        if result:
            info('tests passed')
        else:
            info('tests failed')
        return int(not result)


class cmd_version(Command):
    """Show version of bzr."""

    encoding_type = 'replace'

    @display_command
    def run(self):
        from bzrlib.version import show_version
        show_version(to_file=self.outf)


class cmd_rocks(Command):
    """Statement of optimism."""

    hidden = True

    @display_command
    def run(self):
        print "It sure does!"


class cmd_find_merge_base(Command):
    """Find and print a base revision for merging two branches."""
    # TODO: Options to specify revisions on either side, as if
    #       merging only part of the history.
    takes_args = ['branch', 'other']
    hidden = True
    
    @display_command
    def run(self, branch, other):
        from bzrlib.revision import ensure_null, MultipleRevisionSources
        
        branch1 = Branch.open_containing(branch)[0]
        branch2 = Branch.open_containing(other)[0]

        last1 = ensure_null(branch1.last_revision())
        last2 = ensure_null(branch2.last_revision())

        graph = branch1.repository.get_graph(branch2.repository)
        base_rev_id = graph.find_unique_lca(last1, last2)

        print 'merge base is revision %s' % base_rev_id


class cmd_merge(Command):
    """Perform a three-way merge.
    
    The branch is the branch you will merge from.  By default, it will merge
    the latest revision.  If you specify a revision, that revision will be
    merged.  If you specify two revisions, the first will be used as a BASE,
    and the second one as OTHER.  Revision numbers are always relative to the
    specified branch.

    By default, bzr will try to merge in all new work from the other
    branch, automatically determining an appropriate base.  If this
    fails, you may need to give an explicit base.
    
    Merge will do its best to combine the changes in two branches, but there
    are some kinds of problems only a human can fix.  When it encounters those,
    it will mark a conflict.  A conflict means that you need to fix something,
    before you should commit.

    Use bzr resolve when you have fixed a problem.  See also bzr conflicts.

    If there is no default branch set, the first merge will set it. After
    that, you can omit the branch to use the default.  To change the
    default, use --remember. The value will only be saved if the remote
    location can be accessed.

    The results of the merge are placed into the destination working
    directory, where they can be reviewed (with bzr diff), tested, and then
    committed to record the result of the merge.
    
    merge refuses to run if there are any uncommitted changes, unless
    --force is given.

    :Examples:
        To merge the latest revision from bzr.dev::

            bzr merge ../bzr.dev

        To merge changes up to and including revision 82 from bzr.dev::

            bzr merge -r 82 ../bzr.dev

        To merge the changes introduced by 82, without previous changes::

            bzr merge -r 81..82 ../bzr.dev
    """

    _see_also = ['update', 'remerge', 'status-flags']
    takes_args = ['branch?']
    takes_options = [
        'revision',
        Option('force',
               help='Merge even if the destination tree has uncommitted changes.'),
        'merge-type',
        'reprocess',
        'remember',
        Option('show-base', help="Show base revision text in "
               "conflicts."),
        Option('uncommitted', help='Apply uncommitted changes'
               ' from a working copy, instead of branch changes.'),
        Option('pull', help='If the destination is already'
                ' completely merged into the source, pull from the'
                ' source rather than merging.  When this happens,'
                ' you do not need to commit the result.'),
        Option('directory',
               help='Branch to merge into, '
                    'rather than the one containing the working directory.',
               short_name='d',
               type=unicode,
               ),
    ]

    def run(self, branch=None, revision=None, force=False, merge_type=None,
            show_base=False, reprocess=False, remember=False,
            uncommitted=False, pull=False,
            directory=None,
            ):
        from bzrlib.tag import _merge_tags_if_possible
        # This is actually a branch (or merge-directive) *location*.
        location = branch
        del branch

        if merge_type is None:
            merge_type = _mod_merge.Merge3Merger

        if directory is None: directory = u'.'
        possible_transports = []
        merger = None
        allow_pending = True
        verified = 'inapplicable'
        tree = WorkingTree.open_containing(directory)[0]
        change_reporter = delta._ChangeReporter(
            unversioned_filter=tree.is_ignored)
        cleanups = []
        try:
            pb = ui.ui_factory.nested_progress_bar()
            cleanups.append(pb.finished)
            tree.lock_write()
            cleanups.append(tree.unlock)
            if location is not None:
                mergeable, other_transport = _get_mergeable_helper(location)
                if mergeable:
                    if uncommitted:
                        raise errors.BzrCommandError('Cannot use --uncommitted'
                            ' with bundles or merge directives.')

                    if revision is not None:
                        raise errors.BzrCommandError(
                            'Cannot use -r with merge directives or bundles')
                    merger, verified = _mod_merge.Merger.from_mergeable(tree,
                       mergeable, pb)
                possible_transports.append(other_transport)

            if merger is None and uncommitted:
                if revision is not None and len(revision) > 0:
                    raise errors.BzrCommandError('Cannot use --uncommitted and'
                        ' --revision at the same time.')
                location = self._select_branch_location(tree, location)[0]
                other_tree, other_path = WorkingTree.open_containing(location)
                merger = _mod_merge.Merger.from_uncommitted(tree, other_tree,
                    pb)
                allow_pending = False

            if merger is None:
                merger, allow_pending = self._get_merger_from_branch(tree,
                    location, revision, remember, possible_transports, pb)

            merger.merge_type = merge_type
            merger.reprocess = reprocess
            merger.show_base = show_base
            merger.change_reporter = change_reporter
            self.sanity_check_merger(merger)
            if (merger.base_rev_id == merger.other_rev_id and
                merger.other_rev_id != None):
                note('Nothing to do.')
                return 0
            if pull:
                if merger.interesting_files is not None:
                    raise BzrCommandError('Cannot pull individual files')
                if (merger.base_rev_id == tree.last_revision()):
                    result = tree.pull(merger.other_branch, False,
                                       merger.other_rev_id)
                    result.report(self.outf)
                    return 0
            merger.check_basis(not force)
            conflict_count = merger.do_merge()
            if allow_pending:
                merger.set_pending()
            if verified == 'failed':
                warning('Preview patch does not match changes')
            if conflict_count != 0:
                return 1
            else:
                return 0
        finally:
            for cleanup in reversed(cleanups):
                cleanup()

    def sanity_check_merger(self, merger):
        if (merger.show_base and
            not merger.merge_type is _mod_merge.Merge3Merger):
            raise errors.BzrCommandError("Show-base is not supported for this"
                                         " merge type. %s" % merger.merge_type)
        if merger.reprocess and not merger.merge_type.supports_reprocess:
            raise errors.BzrCommandError("Conflict reduction is not supported"
                                         " for merge type %s." %
                                         merger.merge_type)
        if merger.reprocess and merger.show_base:
            raise errors.BzrCommandError("Cannot do conflict reduction and"
                                         " show base.")

    def _get_merger_from_branch(self, tree, location, revision, remember,
                                possible_transports, pb):
        """Produce a merger from a location, assuming it refers to a branch."""
        from bzrlib.tag import _merge_tags_if_possible
        assert revision is None or len(revision) < 3
        # find the branch locations
        other_loc, location = self._select_branch_location(tree, location,
            revision, -1)
        if revision is not None and len(revision) == 2:
            base_loc, location = self._select_branch_location(tree, location,
                                                              revision, 0)
        else:
            base_loc = other_loc
        # Open the branches
        other_branch, other_path = Branch.open_containing(other_loc,
            possible_transports)
        if base_loc == other_loc:
            base_branch = other_branch
        else:
            base_branch, base_path = Branch.open_containing(base_loc,
                possible_transports)
        # Find the revision ids
        if revision is None or len(revision) < 1 or revision[-1] is None:
            other_revision_id = _mod_revision.ensure_null(
                other_branch.last_revision())
        else:
            other_revision_id = \
                _mod_revision.ensure_null(
                    revision[-1].in_history(other_branch).rev_id)
        if (revision is not None and len(revision) == 2
            and revision[0] is not None):
            base_revision_id = \
                _mod_revision.ensure_null(
                    revision[0].in_history(base_branch).rev_id)
        else:
            base_revision_id = None
        # Remember where we merge from
        if ((tree.branch.get_parent() is None or remember) and
            other_branch is not None):
            tree.branch.set_parent(other_branch.base)
        _merge_tags_if_possible(other_branch, tree.branch)
        merger = _mod_merge.Merger.from_revision_ids(pb, tree,
            other_revision_id, base_revision_id, other_branch, base_branch)
        if other_path != '':
            allow_pending = False
            merger.interesting_files = [other_path]
        else:
            allow_pending = True
        return merger, allow_pending

    def _select_branch_location(self, tree, location, revision=None,
                                index=None):
        """Select a branch location, according to possible inputs.

        If provided, branches from ``revision`` are preferred.  (Both
        ``revision`` and ``index`` must be supplied.)

        Otherwise, the ``location`` parameter is used.  If it is None, then the
        ``parent`` location is used, and a note is printed.

        :param tree: The working tree to select a branch for merging into
        :param location: The location entered by the user
        :param revision: The revision parameter to the command
        :param index: The index to use for the revision parameter.  Negative
            indices are permitted.
        :return: (selected_location, default_location).  The default location
            will be the user-entered location, if any, or else the remembered
            location.
        """
        if (revision is not None and index is not None
            and revision[index] is not None):
            branch = revision[index].get_branch()
            if branch is not None:
                return branch, location
        location = self._get_remembered_parent(tree, location, 'Merging from')
        return location, location

    # TODO: move up to common parent; this isn't merge-specific anymore. 
    def _get_remembered_parent(self, tree, supplied_location, verb_string):
        """Use tree.branch's parent if none was supplied.

        Report if the remembered location was used.
        """
        if supplied_location is not None:
            return supplied_location
        stored_location = tree.branch.get_parent()
        mutter("%s", stored_location)
        if stored_location is None:
            raise errors.BzrCommandError("No location specified or remembered")
        display_url = urlutils.unescape_for_display(stored_location,
            self.outf.encoding)
        self.outf.write("%s remembered location %s\n" % (verb_string,
            display_url))
        return stored_location


class cmd_remerge(Command):
    """Redo a merge.

    Use this if you want to try a different merge technique while resolving
    conflicts.  Some merge techniques are better than others, and remerge 
    lets you try different ones on different files.

    The options for remerge have the same meaning and defaults as the ones for
    merge.  The difference is that remerge can (only) be run when there is a
    pending merge, and it lets you specify particular files.

    :Examples:
        Re-do the merge of all conflicted files, and show the base text in
        conflict regions, in addition to the usual THIS and OTHER texts::
      
            bzr remerge --show-base

        Re-do the merge of "foobar", using the weave merge algorithm, with
        additional processing to reduce the size of conflict regions::
      
            bzr remerge --merge-type weave --reprocess foobar
    """
    takes_args = ['file*']
    takes_options = [
            'merge-type',
            'reprocess',
            Option('show-base',
                   help="Show base revision text in conflicts."),
            ]

    def run(self, file_list=None, merge_type=None, show_base=False,
            reprocess=False):
        if merge_type is None:
            merge_type = _mod_merge.Merge3Merger
        tree, file_list = tree_files(file_list)
        tree.lock_write()
        try:
            parents = tree.get_parent_ids()
            if len(parents) != 2:
                raise errors.BzrCommandError("Sorry, remerge only works after normal"
                                             " merges.  Not cherrypicking or"
                                             " multi-merges.")
            repository = tree.branch.repository
            graph = repository.get_graph()
            base_revision = graph.find_unique_lca(parents[0], parents[1])
            base_tree = repository.revision_tree(base_revision)
            other_tree = repository.revision_tree(parents[1])
            interesting_ids = None
            new_conflicts = []
            conflicts = tree.conflicts()
            if file_list is not None:
                interesting_ids = set()
                for filename in file_list:
                    file_id = tree.path2id(filename)
                    if file_id is None:
                        raise errors.NotVersionedError(filename)
                    interesting_ids.add(file_id)
                    if tree.kind(file_id) != "directory":
                        continue
                    
                    for name, ie in tree.inventory.iter_entries(file_id):
                        interesting_ids.add(ie.file_id)
                new_conflicts = conflicts.select_conflicts(tree, file_list)[0]
            else:
                # Remerge only supports resolving contents conflicts
                allowed_conflicts = ('text conflict', 'contents conflict')
                restore_files = [c.path for c in conflicts
                                 if c.typestring in allowed_conflicts]
            _mod_merge.transform_tree(tree, tree.basis_tree(), interesting_ids)
            tree.set_conflicts(ConflictList(new_conflicts))
            if file_list is not None:
                restore_files = file_list
            for filename in restore_files:
                try:
                    restore(tree.abspath(filename))
                except errors.NotConflicted:
                    pass
            # Disable pending merges, because the file texts we are remerging
            # have not had those merges performed.  If we use the wrong parents
            # list, we imply that the working tree text has seen and rejected
            # all the changes from the other tree, when in fact those changes
            # have not yet been seen.
            tree.set_parent_ids(parents[:1])
            try:
                conflicts = _mod_merge.merge_inner(
                                          tree.branch, other_tree, base_tree,
                                          this_tree=tree,
                                          interesting_ids=interesting_ids,
                                          other_rev_id=parents[1],
                                          merge_type=merge_type,
                                          show_base=show_base,
                                          reprocess=reprocess)
            finally:
                tree.set_parent_ids(parents)
        finally:
            tree.unlock()
        if conflicts > 0:
            return 1
        else:
            return 0


class cmd_revert(Command):
    """Revert files to a previous revision.

    Giving a list of files will revert only those files.  Otherwise, all files
    will be reverted.  If the revision is not specified with '--revision', the
    last committed revision is used.

    To remove only some changes, without reverting to a prior version, use
    merge instead.  For example, "merge . --r-2..-3" will remove the changes
    introduced by -2, without affecting the changes introduced by -1.  Or
    to remove certain changes on a hunk-by-hunk basis, see the Shelf plugin.
    
    By default, any files that have been manually changed will be backed up
    first.  (Files changed only by merge are not backed up.)  Backup files have
    '.~#~' appended to their name, where # is a number.

    When you provide files, you can use their current pathname or the pathname
    from the target revision.  So you can use revert to "undelete" a file by
    name.  If you name a directory, all the contents of that directory will be
    reverted.

    Any files that have been newly added since that revision will be deleted,
    with a backup kept if appropriate.  Directories containing unknown files
    will not be deleted.
    """

    _see_also = ['cat', 'export']
    takes_options = [
            'revision',
            Option('no-backup', "Do not save backups of reverted files."),
            ]
    takes_args = ['file*']

    def run(self, revision=None, no_backup=False, file_list=None):
        if file_list is not None:
            if len(file_list) == 0:
                raise errors.BzrCommandError("No files specified")
        
        tree, file_list = tree_files(file_list)
        if revision is None:
            # FIXME should be tree.last_revision
            rev_id = tree.last_revision()
        elif len(revision) != 1:
            raise errors.BzrCommandError('bzr revert --revision takes exactly 1 argument')
        else:
            rev_id = revision[0].in_history(tree.branch).rev_id
        pb = ui.ui_factory.nested_progress_bar()
        try:
            tree.revert(file_list, 
                        tree.branch.repository.revision_tree(rev_id),
                        not no_backup, pb, report_changes=True)
        finally:
            pb.finished()


class cmd_assert_fail(Command):
    """Test reporting of assertion failures"""
    # intended just for use in testing

    hidden = True

    def run(self):
        raise AssertionError("always fails")


class cmd_help(Command):
    """Show help on a command or other topic.
    """

    _see_also = ['topics']
    takes_options = [
            Option('long', 'Show help on all commands.'),
            ]
    takes_args = ['topic?']
    aliases = ['?', '--help', '-?', '-h']
    
    @display_command
    def run(self, topic=None, long=False):
        import bzrlib.help
        if topic is None and long:
            topic = "commands"
        bzrlib.help.help(topic)


class cmd_shell_complete(Command):
    """Show appropriate completions for context.

    For a list of all available commands, say 'bzr shell-complete'.
    """
    takes_args = ['context?']
    aliases = ['s-c']
    hidden = True
    
    @display_command
    def run(self, context=None):
        import shellcomplete
        shellcomplete.shellcomplete(context)


class cmd_fetch(Command):
    """Copy in history from another branch but don't merge it.

    This is an internal method used for pull and merge.
    """
    hidden = True
    takes_args = ['from_branch', 'to_branch']
    def run(self, from_branch, to_branch):
        from bzrlib.fetch import Fetcher
        from_b = Branch.open(from_branch)
        to_b = Branch.open(to_branch)
        Fetcher(to_b, from_b)


class cmd_missing(Command):
    """Show unmerged/unpulled revisions between two branches.
    
    OTHER_BRANCH may be local or remote.
    """

    _see_also = ['merge', 'pull']
    takes_args = ['other_branch?']
    takes_options = [
            Option('reverse', 'Reverse the order of revisions.'),
            Option('mine-only',
                   'Display changes in the local branch only.'),
            Option('this' , 'Same as --mine-only.'),
            Option('theirs-only',
                   'Display changes in the remote branch only.'),
            Option('other', 'Same as --theirs-only.'),
            'log-format',
            'show-ids',
            'verbose'
            ]
    encoding_type = 'replace'

    @display_command
    def run(self, other_branch=None, reverse=False, mine_only=False,
            theirs_only=False, log_format=None, long=False, short=False, line=False, 
            show_ids=False, verbose=False, this=False, other=False):
        from bzrlib.missing import find_unmerged, iter_log_revisions
        from bzrlib.log import log_formatter

        if this:
          mine_only = this
        if other:
          theirs_only = other

        local_branch = Branch.open_containing(u".")[0]
        parent = local_branch.get_parent()
        if other_branch is None:
            other_branch = parent
            if other_branch is None:
                raise errors.BzrCommandError("No peer location known"
                                             " or specified.")
            display_url = urlutils.unescape_for_display(parent,
                                                        self.outf.encoding)
            self.outf.write("Using last location: " + display_url + "\n")

        remote_branch = Branch.open(other_branch)
        if remote_branch.base == local_branch.base:
            remote_branch = local_branch
        local_branch.lock_read()
        try:
            remote_branch.lock_read()
            try:
                local_extra, remote_extra = find_unmerged(local_branch,
                                                          remote_branch)
                if log_format is None:
                    registry = log.log_formatter_registry
                    log_format = registry.get_default(local_branch)
                lf = log_format(to_file=self.outf,
                                show_ids=show_ids,
                                show_timezone='original')
                if reverse is False:
                    local_extra.reverse()
                    remote_extra.reverse()
                if local_extra and not theirs_only:
                    self.outf.write("You have %d extra revision(s):\n" %
                                    len(local_extra))
                    for revision in iter_log_revisions(local_extra,
                                        local_branch.repository,
                                        verbose):
                        lf.log_revision(revision)
                    printed_local = True
                else:
                    printed_local = False
                if remote_extra and not mine_only:
                    if printed_local is True:
                        self.outf.write("\n\n\n")
                    self.outf.write("You are missing %d revision(s):\n" %
                                    len(remote_extra))
                    for revision in iter_log_revisions(remote_extra,
                                        remote_branch.repository,
                                        verbose):
                        lf.log_revision(revision)
                if not remote_extra and not local_extra:
                    status_code = 0
                    self.outf.write("Branches are up to date.\n")
                else:
                    status_code = 1
            finally:
                remote_branch.unlock()
        finally:
            local_branch.unlock()
        if not status_code and parent is None and other_branch is not None:
            local_branch.lock_write()
            try:
                # handle race conditions - a parent might be set while we run.
                if local_branch.get_parent() is None:
                    local_branch.set_parent(remote_branch.base)
            finally:
                local_branch.unlock()
        return status_code


class cmd_pack(Command):
    """Compress the data within a repository."""

    _see_also = ['repositories']
    takes_args = ['branch_or_repo?']

    def run(self, branch_or_repo='.'):
        dir = bzrdir.BzrDir.open_containing(branch_or_repo)[0]
        try:
            branch = dir.open_branch()
            repository = branch.repository
        except errors.NotBranchError:
            repository = dir.open_repository()
        repository.pack()


class cmd_plugins(Command):
    """List the installed plugins.
    
    This command displays the list of installed plugins including the
    path where each one is located and a short description of each.

    A plugin is an external component for Bazaar that extends the
    revision control system, by adding or replacing code in Bazaar.
    Plugins can do a variety of things, including overriding commands,
    adding new commands, providing additional network transports and
    customizing log output.

    See the Bazaar web site, http://bazaar-vcs.org, for further
    information on plugins including where to find them and how to
    install them. Instructions are also provided there on how to
    write new plugins using the Python programming language.
    """

    @display_command
    def run(self):
        import bzrlib.plugin
        from inspect import getdoc
        for name, plugin in bzrlib.plugin.plugins().items():
            print plugin.path(), "[%s]" % plugin.__version__
            d = getdoc(plugin.module)
            if d:
                print '\t', d.split('\n')[0]


class cmd_testament(Command):
    """Show testament (signing-form) of a revision."""
    takes_options = [
            'revision',
            Option('long', help='Produce long-format testament.'),
            Option('strict',
                   help='Produce a strict-format testament.')]
    takes_args = ['branch?']
    @display_command
    def run(self, branch=u'.', revision=None, long=False, strict=False):
        from bzrlib.testament import Testament, StrictTestament
        if strict is True:
            testament_class = StrictTestament
        else:
            testament_class = Testament
        b = WorkingTree.open_containing(branch)[0].branch
        b.lock_read()
        try:
            if revision is None:
                rev_id = b.last_revision()
            else:
                rev_id = revision[0].in_history(b).rev_id
            t = testament_class.from_revision(b.repository, rev_id)
            if long:
                sys.stdout.writelines(t.as_text_lines())
            else:
                sys.stdout.write(t.as_short_text())
        finally:
            b.unlock()


class cmd_annotate(Command):
    """Show the origin of each line in a file.

    This prints out the given file with an annotation on the left side
    indicating which revision, author and date introduced the change.

    If the origin is the same for a run of consecutive lines, it is 
    shown only at the top, unless the --all option is given.
    """
    # TODO: annotate directories; showing when each file was last changed
    # TODO: if the working copy is modified, show annotations on that 
    #       with new uncommitted lines marked
    aliases = ['ann', 'blame', 'praise']
    takes_args = ['filename']
    takes_options = [Option('all', help='Show annotations on all lines.'),
                     Option('long', help='Show commit date in annotations.'),
                     'revision',
                     'show-ids',
                     ]
    encoding_type = 'exact'

    @display_command
    def run(self, filename, all=False, long=False, revision=None,
            show_ids=False):
        from bzrlib.annotate import annotate_file
        tree, relpath = WorkingTree.open_containing(filename)
        branch = tree.branch
        branch.lock_read()
        try:
            if revision is None:
                revision_id = branch.last_revision()
            elif len(revision) != 1:
                raise errors.BzrCommandError('bzr annotate --revision takes exactly 1 argument')
            else:
                revision_id = revision[0].in_history(branch).rev_id
            file_id = tree.path2id(relpath)
            if file_id is None:
                raise errors.NotVersionedError(filename)
            tree = branch.repository.revision_tree(revision_id)
            file_version = tree.inventory[file_id].revision
            annotate_file(branch, file_version, file_id, long, all, self.outf,
                          show_ids=show_ids)
        finally:
            branch.unlock()


class cmd_re_sign(Command):
    """Create a digital signature for an existing revision."""
    # TODO be able to replace existing ones.

    hidden = True # is this right ?
    takes_args = ['revision_id*']
    takes_options = ['revision']
    
    def run(self, revision_id_list=None, revision=None):
        import bzrlib.gpg as gpg
        if revision_id_list is not None and revision is not None:
            raise errors.BzrCommandError('You can only supply one of revision_id or --revision')
        if revision_id_list is None and revision is None:
            raise errors.BzrCommandError('You must supply either --revision or a revision_id')
        b = WorkingTree.open_containing(u'.')[0].branch
        gpg_strategy = gpg.GPGStrategy(b.get_config())
        if revision_id_list is not None:
            for revision_id in revision_id_list:
                b.repository.sign_revision(revision_id, gpg_strategy)
        elif revision is not None:
            if len(revision) == 1:
                revno, rev_id = revision[0].in_history(b)
                b.repository.sign_revision(rev_id, gpg_strategy)
            elif len(revision) == 2:
                # are they both on rh- if so we can walk between them
                # might be nice to have a range helper for arbitrary
                # revision paths. hmm.
                from_revno, from_revid = revision[0].in_history(b)
                to_revno, to_revid = revision[1].in_history(b)
                if to_revid is None:
                    to_revno = b.revno()
                if from_revno is None or to_revno is None:
                    raise errors.BzrCommandError('Cannot sign a range of non-revision-history revisions')
                for revno in range(from_revno, to_revno + 1):
                    b.repository.sign_revision(b.get_rev_id(revno), 
                                               gpg_strategy)
            else:
                raise errors.BzrCommandError('Please supply either one revision, or a range.')


class cmd_bind(Command):
    """Convert the current branch into a checkout of the supplied branch.

    Once converted into a checkout, commits must succeed on the master branch
    before they will be applied to the local branch.
    """

    _see_also = ['checkouts', 'unbind']
    takes_args = ['location?']
    takes_options = []

    def run(self, location=None):
        b, relpath = Branch.open_containing(u'.')
        if location is None:
            try:
                location = b.get_old_bound_location()
            except errors.UpgradeRequired:
                raise errors.BzrCommandError('No location supplied.  '
                    'This format does not remember old locations.')
            else:
                if location is None:
                    raise errors.BzrCommandError('No location supplied and no '
                        'previous location known')
        b_other = Branch.open(location)
        try:
            b.bind(b_other)
        except errors.DivergedBranches:
            raise errors.BzrCommandError('These branches have diverged.'
                                         ' Try merging, and then bind again.')


class cmd_unbind(Command):
    """Convert the current checkout into a regular branch.

    After unbinding, the local branch is considered independent and subsequent
    commits will be local only.
    """

    _see_also = ['checkouts', 'bind']
    takes_args = []
    takes_options = []

    def run(self):
        b, relpath = Branch.open_containing(u'.')
        if not b.unbind():
            raise errors.BzrCommandError('Local branch is not bound')


class cmd_uncommit(Command):
    """Remove the last committed revision.

    --verbose will print out what is being removed.
    --dry-run will go through all the motions, but not actually
    remove anything.

    If --revision is specified, uncommit revisions to leave the branch at the
    specified revision.  For example, "bzr uncommit -r 15" will leave the
    branch at revision 15.

    In the future, uncommit will create a revision bundle, which can then
    be re-applied.
    """

    # TODO: jam 20060108 Add an option to allow uncommit to remove
    # unreferenced information in 'branch-as-repository' branches.
    # TODO: jam 20060108 Add the ability for uncommit to remove unreferenced
    # information in shared branches as well.
    _see_also = ['commit']
    takes_options = ['verbose', 'revision',
                    Option('dry-run', help='Don\'t actually make changes.'),
                    Option('force', help='Say yes to all questions.')]
    takes_args = ['location?']
    aliases = []

    def run(self, location=None,
            dry_run=False, verbose=False,
            revision=None, force=False):
        from bzrlib.log import log_formatter, show_log
        import sys
        from bzrlib.uncommit import uncommit

        if location is None:
            location = u'.'
        control, relpath = bzrdir.BzrDir.open_containing(location)
        try:
            tree = control.open_workingtree()
            b = tree.branch
        except (errors.NoWorkingTree, errors.NotLocalUrl):
            tree = None
            b = control.open_branch()

        rev_id = None
        if revision is None:
            revno = b.revno()
        else:
            # 'bzr uncommit -r 10' actually means uncommit
            # so that the final tree is at revno 10.
            # but bzrlib.uncommit.uncommit() actually uncommits
            # the revisions that are supplied.
            # So we need to offset it by one
            revno = revision[0].in_history(b).revno+1

        if revno <= b.revno():
            rev_id = b.get_rev_id(revno)
        if rev_id is None:
            self.outf.write('No revisions to uncommit.\n')
            return 1

        lf = log_formatter('short',
                           to_file=self.outf,
                           show_timezone='original')

        show_log(b,
                 lf,
                 verbose=False,
                 direction='forward',
                 start_revision=revno,
                 end_revision=b.revno())

        if dry_run:
            print 'Dry-run, pretending to remove the above revisions.'
            if not force:
                val = raw_input('Press <enter> to continue')
        else:
            print 'The above revision(s) will be removed.'
            if not force:
                val = raw_input('Are you sure [y/N]? ')
                if val.lower() not in ('y', 'yes'):
                    print 'Canceled'
                    return 0

        uncommit(b, tree=tree, dry_run=dry_run, verbose=verbose,
                revno=revno)


class cmd_break_lock(Command):
    """Break a dead lock on a repository, branch or working directory.

    CAUTION: Locks should only be broken when you are sure that the process
    holding the lock has been stopped.

    You can get information on what locks are open via the 'bzr info' command.
    
    :Examples:
        bzr break-lock
    """
    takes_args = ['location?']

    def run(self, location=None, show=False):
        if location is None:
            location = u'.'
        control, relpath = bzrdir.BzrDir.open_containing(location)
        try:
            control.break_lock()
        except NotImplementedError:
            pass
        

class cmd_wait_until_signalled(Command):
    """Test helper for test_start_and_stop_bzr_subprocess_send_signal.

    This just prints a line to signal when it is ready, then blocks on stdin.
    """

    hidden = True

    def run(self):
        sys.stdout.write("running\n")
        sys.stdout.flush()
        sys.stdin.readline()


class cmd_serve(Command):
    """Run the bzr server."""

    aliases = ['server']

    takes_options = [
        Option('inet',
               help='Serve on stdin/out for use from inetd or sshd.'),
        Option('port',
               help='Listen for connections on nominated port of the form '
                    '[hostname:]portnumber.  Passing 0 as the port number will '
                    'result in a dynamically allocated port.  The default port is '
                    '4155.',
               type=str),
        Option('directory',
               help='Serve contents of this directory.',
               type=unicode),
        Option('allow-writes',
               help='By default the server is a readonly server.  Supplying '
                    '--allow-writes enables write access to the contents of '
                    'the served directory and below.'
                ),
        ]

    def run(self, port=None, inet=False, directory=None, allow_writes=False):
        from bzrlib.smart import medium, server
        from bzrlib.transport import get_transport
        from bzrlib.transport.chroot import ChrootServer
        from bzrlib.transport.remote import BZR_DEFAULT_PORT, BZR_DEFAULT_INTERFACE
        if directory is None:
            directory = os.getcwd()
        url = urlutils.local_path_to_url(directory)
        if not allow_writes:
            url = 'readonly+' + url
        chroot_server = ChrootServer(get_transport(url))
        chroot_server.setUp()
        t = get_transport(chroot_server.get_url())
        if inet:
            smart_server = medium.SmartServerPipeStreamMedium(
                sys.stdin, sys.stdout, t)
        else:
            host = BZR_DEFAULT_INTERFACE
            if port is None:
                port = BZR_DEFAULT_PORT
            else:
                if ':' in port:
                    host, port = port.split(':')
                port = int(port)
            smart_server = server.SmartTCPServer(t, host=host, port=port)
            print 'listening on port: ', smart_server.port
            sys.stdout.flush()
        # for the duration of this server, no UI output is permitted.
        # note that this may cause problems with blackbox tests. This should
        # be changed with care though, as we dont want to use bandwidth sending
        # progress over stderr to smart server clients!
        old_factory = ui.ui_factory
        try:
            ui.ui_factory = ui.SilentUIFactory()
            smart_server.serve()
        finally:
            ui.ui_factory = old_factory


class cmd_join(Command):
    """Combine a subtree into its containing tree.
    
    This command is for experimental use only.  It requires the target tree
    to be in dirstate-with-subtree format, which cannot be converted into
    earlier formats.

    The TREE argument should be an independent tree, inside another tree, but
    not part of it.  (Such trees can be produced by "bzr split", but also by
    running "bzr branch" with the target inside a tree.)

    The result is a combined tree, with the subtree no longer an independant
    part.  This is marked as a merge of the subtree into the containing tree,
    and all history is preserved.

    If --reference is specified, the subtree retains its independence.  It can
    be branched by itself, and can be part of multiple projects at the same
    time.  But operations performed in the containing tree, such as commit
    and merge, will recurse into the subtree.
    """

    _see_also = ['split']
    takes_args = ['tree']
    takes_options = [
            Option('reference', help='Join by reference.'),
            ]
    hidden = True

    def run(self, tree, reference=False):
        sub_tree = WorkingTree.open(tree)
        parent_dir = osutils.dirname(sub_tree.basedir)
        containing_tree = WorkingTree.open_containing(parent_dir)[0]
        repo = containing_tree.branch.repository
        if not repo.supports_rich_root():
            raise errors.BzrCommandError(
                "Can't join trees because %s doesn't support rich root data.\n"
                "You can use bzr upgrade on the repository."
                % (repo,))
        if reference:
            try:
                containing_tree.add_reference(sub_tree)
            except errors.BadReferenceTarget, e:
                # XXX: Would be better to just raise a nicely printable
                # exception from the real origin.  Also below.  mbp 20070306
                raise errors.BzrCommandError("Cannot join %s.  %s" %
                                             (tree, e.reason))
        else:
            try:
                containing_tree.subsume(sub_tree)
            except errors.BadSubsumeSource, e:
                raise errors.BzrCommandError("Cannot join %s.  %s" % 
                                             (tree, e.reason))


class cmd_split(Command):
    """Split a tree into two trees.

    This command is for experimental use only.  It requires the target tree
    to be in dirstate-with-subtree format, which cannot be converted into
    earlier formats.

    The TREE argument should be a subdirectory of a working tree.  That
    subdirectory will be converted into an independent tree, with its own
    branch.  Commits in the top-level tree will not apply to the new subtree.
    If you want that behavior, do "bzr join --reference TREE".
    """

    _see_also = ['join']
    takes_args = ['tree']

    hidden = True

    def run(self, tree):
        containing_tree, subdir = WorkingTree.open_containing(tree)
        sub_id = containing_tree.path2id(subdir)
        if sub_id is None:
            raise errors.NotVersionedError(subdir)
        try:
            containing_tree.extract(sub_id)
        except errors.RootNotRich:
            raise errors.UpgradeRequired(containing_tree.branch.base)



class cmd_merge_directive(Command):
    """Generate a merge directive for auto-merge tools.

    A directive requests a merge to be performed, and also provides all the
    information necessary to do so.  This means it must either include a
    revision bundle, or the location of a branch containing the desired
    revision.

    A submit branch (the location to merge into) must be supplied the first
    time the command is issued.  After it has been supplied once, it will
    be remembered as the default.

    A public branch is optional if a revision bundle is supplied, but required
    if --diff or --plain is specified.  It will be remembered as the default
    after the first use.
    """

    takes_args = ['submit_branch?', 'public_branch?']

    hidden = True

    _see_also = ['send']

    takes_options = [
        RegistryOption.from_kwargs('patch-type',
            'The type of patch to include in the directive.',
            title='Patch type',
            value_switches=True,
            enum_switch=False,
            bundle='Bazaar revision bundle (default).',
            diff='Normal unified diff.',
            plain='No patch, just directive.'),
        Option('sign', help='GPG-sign the directive.'), 'revision',
        Option('mail-to', type=str,
            help='Instead of printing the directive, email to this address.'),
        Option('message', type=str, short_name='m',
            help='Message to use when committing this merge.')
        ]

    encoding_type = 'exact'

    def run(self, submit_branch=None, public_branch=None, patch_type='bundle',
            sign=False, revision=None, mail_to=None, message=None):
        from bzrlib.revision import ensure_null, NULL_REVISION
        include_patch, include_bundle = {
            'plain': (False, False),
            'diff': (True, False),
            'bundle': (True, True),
            }[patch_type]
        branch = Branch.open('.')
        stored_submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            submit_branch = stored_submit_branch
        else:
            if stored_submit_branch is None:
                branch.set_submit_branch(submit_branch)
        if submit_branch is None:
            submit_branch = branch.get_parent()
        if submit_branch is None:
            raise errors.BzrCommandError('No submit branch specified or known')

        stored_public_branch = branch.get_public_branch()
        if public_branch is None:
            public_branch = stored_public_branch
        elif stored_public_branch is None:
            branch.set_public_branch(public_branch)
        if not include_bundle and public_branch is None:
            raise errors.BzrCommandError('No public branch specified or'
                                         ' known')
        base_revision_id = None
        if revision is not None:
            if len(revision) > 2:
                raise errors.BzrCommandError('bzr merge-directive takes '
                    'at most two one revision identifiers')
            revision_id = revision[-1].in_history(branch).rev_id
            if len(revision) == 2:
                base_revision_id = revision[0].in_history(branch).rev_id
                base_revision_id = ensure_null(base_revision_id)
        else:
            revision_id = branch.last_revision()
        revision_id = ensure_null(revision_id)
        if revision_id == NULL_REVISION:
            raise errors.BzrCommandError('No revisions to bundle.')
        directive = merge_directive.MergeDirective2.from_objects(
            branch.repository, revision_id, time.time(),
            osutils.local_time_offset(), submit_branch,
            public_branch=public_branch, include_patch=include_patch,
            include_bundle=include_bundle, message=message,
            base_revision_id=base_revision_id)
        if mail_to is None:
            if sign:
                self.outf.write(directive.to_signed(branch))
            else:
                self.outf.writelines(directive.to_lines())
        else:
            message = directive.to_email(mail_to, branch, sign)
            s = SMTPConnection(branch.get_config())
            s.send_email(message)


class cmd_send(Command):
    """Mail or create a merge-directive for submiting changes.

    A merge directive provides many things needed for requesting merges:

    * A machine-readable description of the merge to perform

    * An optional patch that is a preview of the changes requested

    * An optional bundle of revision data, so that the changes can be applied
      directly from the merge directive, without retrieving data from a
      branch.

    If --no-bundle is specified, then public_branch is needed (and must be
    up-to-date), so that the receiver can perform the merge using the
    public_branch.  The public_branch is always included if known, so that
    people can check it later.

    The submit branch defaults to the parent, but can be overridden.  Both
    submit branch and public branch will be remembered if supplied.

    If a public_branch is known for the submit_branch, that public submit
    branch is used in the merge instructions.  This means that a local mirror
    can be used as your actual submit branch, once you have set public_branch
    for that mirror.

    Mail is sent using your preferred mail program.  This should be transparent
    on Windows (it uses MAPI).  On *nix, it requires the xdg-email utility.  If
    the preferred client can't be found (or used), your editor will be used.
    
    To use a specific mail program, set the mail_client configuration option.
    (For Thunderbird 1.5, this works around some bugs.)  Supported values for
    specific clients are "evolution", "kmail", "mutt", and "thunderbird";
    generic options are "default", "editor", "mapi", and "xdg-email".

    If mail is being sent, a to address is required.  This can be supplied
    either on the commandline, or by setting the submit_to configuration
    option.

    Two formats are currently supported: "4" uses revision bundle format 4 and
    merge directive format 2.  It is significantly faster and smaller than
    older formats.  It is compatible with Bazaar 0.19 and later.  It is the
    default.  "0.9" uses revision bundle format 0.9 and merge directive
    format 1.  It is compatible with Bazaar 0.12 - 0.18.
    """

    encoding_type = 'exact'

    _see_also = ['merge']

    takes_args = ['submit_branch?', 'public_branch?']

    takes_options = [
        Option('no-bundle',
               help='Do not include a bundle in the merge directive.'),
        Option('no-patch', help='Do not include a preview patch in the merge'
               ' directive.'),
        Option('remember',
               help='Remember submit and public branch.'),
        Option('from',
               help='Branch to generate the submission from, '
               'rather than the one containing the working directory.',
               short_name='f',
               type=unicode),
        Option('output', short_name='o', help='Write directive to this file.',
               type=unicode),
        Option('mail-to', help='Mail the request to this address.',
               type=unicode),
        'revision',
        'message',
        RegistryOption.from_kwargs('format',
        'Use the specified output format.',
        **{'4': 'Bundle format 4, Merge Directive 2 (default)',
           '0.9': 'Bundle format 0.9, Merge Directive 1',})
        ]

    def run(self, submit_branch=None, public_branch=None, no_bundle=False,
            no_patch=False, revision=None, remember=False, output=None,
            format='4', mail_to=None, message=None, **kwargs):
        return self._run(submit_branch, revision, public_branch, remember,
                         format, no_bundle, no_patch, output,
                         kwargs.get('from', '.'), mail_to, message)

    def _run(self, submit_branch, revision, public_branch, remember, format,
             no_bundle, no_patch, output, from_, mail_to, message):
        from bzrlib.revision import ensure_null, NULL_REVISION
        if output is None:
            outfile = StringIO()
        elif output == '-':
            outfile = self.outf
        else:
            outfile = open(output, 'wb')
        try:
            branch = Branch.open_containing(from_)[0]
            if output is None:
                config = branch.get_config()
                if mail_to is None:
                    mail_to = config.get_user_option('submit_to')
                if mail_to is None:
                    raise errors.BzrCommandError('No mail-to address'
                                                 ' specified')
                mail_client = config.get_mail_client()
            if remember and submit_branch is None:
                raise errors.BzrCommandError(
                    '--remember requires a branch to be specified.')
            stored_submit_branch = branch.get_submit_branch()
            remembered_submit_branch = False
            if submit_branch is None:
                submit_branch = stored_submit_branch
                remembered_submit_branch = True
            else:
                if stored_submit_branch is None or remember:
                    branch.set_submit_branch(submit_branch)
            if submit_branch is None:
                submit_branch = branch.get_parent()
                remembered_submit_branch = True
            if submit_branch is None:
                raise errors.BzrCommandError('No submit branch known or'
                                             ' specified')
            if remembered_submit_branch:
                note('Using saved location: %s', submit_branch)

            stored_public_branch = branch.get_public_branch()
            if public_branch is None:
                public_branch = stored_public_branch
            elif stored_public_branch is None or remember:
                branch.set_public_branch(public_branch)
            if no_bundle and public_branch is None:
                raise errors.BzrCommandError('No public branch specified or'
                                             ' known')
            base_revision_id = None
            revision_id = None
            if revision is not None:
                if len(revision) > 2:
                    raise errors.BzrCommandError('bzr send takes '
                        'at most two one revision identifiers')
                revision_id = revision[-1].in_history(branch).rev_id
                if len(revision) == 2:
                    base_revision_id = revision[0].in_history(branch).rev_id
            if revision_id is None:
                revision_id = branch.last_revision()
            if revision_id == NULL_REVISION:
                raise errors.BzrCommandError('No revisions to submit.')
            if format == '4':
                directive = merge_directive.MergeDirective2.from_objects(
                    branch.repository, revision_id, time.time(),
                    osutils.local_time_offset(), submit_branch,
                    public_branch=public_branch, include_patch=not no_patch,
                    include_bundle=not no_bundle, message=message,
                    base_revision_id=base_revision_id)
            elif format == '0.9':
                if not no_bundle:
                    if not no_patch:
                        patch_type = 'bundle'
                    else:
                        raise errors.BzrCommandError('Format 0.9 does not'
                            ' permit bundle with no patch')
                else:
                    if not no_patch:
                        patch_type = 'diff'
                    else:
                        patch_type = None
                directive = merge_directive.MergeDirective.from_objects(
                    branch.repository, revision_id, time.time(),
                    osutils.local_time_offset(), submit_branch,
                    public_branch=public_branch, patch_type=patch_type,
                    message=message)

            outfile.writelines(directive.to_lines())
            if output is None:
                subject = '[MERGE] '
                if message is not None:
                    subject += message
                else:
                    revision = branch.repository.get_revision(revision_id)
                    subject += revision.get_summary()
                mail_client.compose_merge_request(mail_to, subject,
                                                  outfile.getvalue())
        finally:
            if output != '-':
                outfile.close()


class cmd_bundle_revisions(cmd_send):

    """Create a merge-directive for submiting changes.

    A merge directive provides many things needed for requesting merges:

    * A machine-readable description of the merge to perform

    * An optional patch that is a preview of the changes requested

    * An optional bundle of revision data, so that the changes can be applied
      directly from the merge directive, without retrieving data from a
      branch.

    If --no-bundle is specified, then public_branch is needed (and must be
    up-to-date), so that the receiver can perform the merge using the
    public_branch.  The public_branch is always included if known, so that
    people can check it later.

    The submit branch defaults to the parent, but can be overridden.  Both
    submit branch and public branch will be remembered if supplied.

    If a public_branch is known for the submit_branch, that public submit
    branch is used in the merge instructions.  This means that a local mirror
    can be used as your actual submit branch, once you have set public_branch
    for that mirror.

    Two formats are currently supported: "4" uses revision bundle format 4 and
    merge directive format 2.  It is significantly faster and smaller than
    older formats.  It is compatible with Bazaar 0.19 and later.  It is the
    default.  "0.9" uses revision bundle format 0.9 and merge directive
    format 1.  It is compatible with Bazaar 0.12 - 0.18.
    """

    takes_options = [
        Option('no-bundle',
               help='Do not include a bundle in the merge directive.'),
        Option('no-patch', help='Do not include a preview patch in the merge'
               ' directive.'),
        Option('remember',
               help='Remember submit and public branch.'),
        Option('from',
               help='Branch to generate the submission from, '
               'rather than the one containing the working directory.',
               short_name='f',
               type=unicode),
        Option('output', short_name='o', help='Write directive to this file.',
               type=unicode),
        'revision',
        RegistryOption.from_kwargs('format',
        'Use the specified output format.',
        **{'4': 'Bundle format 4, Merge Directive 2 (default)',
           '0.9': 'Bundle format 0.9, Merge Directive 1',})
        ]
    aliases = ['bundle']

    _see_also = ['send', 'merge']

    hidden = True

    def run(self, submit_branch=None, public_branch=None, no_bundle=False,
            no_patch=False, revision=None, remember=False, output=None,
            format='4', **kwargs):
        if output is None:
            output = '-'
        return self._run(submit_branch, revision, public_branch, remember,
                         format, no_bundle, no_patch, output,
                         kwargs.get('from', '.'), None, None)


class cmd_tag(Command):
    """Create, remove or modify a tag naming a revision.
    
    Tags give human-meaningful names to revisions.  Commands that take a -r
    (--revision) option can be given -rtag:X, where X is any previously
    created tag.

    Tags are stored in the branch.  Tags are copied from one branch to another
    along when you branch, push, pull or merge.

    It is an error to give a tag name that already exists unless you pass 
    --force, in which case the tag is moved to point to the new revision.
    """

    _see_also = ['commit', 'tags']
    takes_args = ['tag_name']
    takes_options = [
        Option('delete',
            help='Delete this tag rather than placing it.',
            ),
        Option('directory',
            help='Branch in which to place the tag.',
            short_name='d',
            type=unicode,
            ),
        Option('force',
            help='Replace existing tags.',
            ),
        'revision',
        ]

    def run(self, tag_name,
            delete=None,
            directory='.',
            force=None,
            revision=None,
            ):
        branch, relpath = Branch.open_containing(directory)
        branch.lock_write()
        try:
            if delete:
                branch.tags.delete_tag(tag_name)
                self.outf.write('Deleted tag %s.\n' % tag_name)
            else:
                if revision:
                    if len(revision) != 1:
                        raise errors.BzrCommandError(
                            "Tags can only be placed on a single revision, "
                            "not on a range")
                    revision_id = revision[0].in_history(branch).rev_id
                else:
                    revision_id = branch.last_revision()
                if (not force) and branch.tags.has_tag(tag_name):
                    raise errors.TagAlreadyExists(tag_name)
                branch.tags.set_tag(tag_name, revision_id)
                self.outf.write('Created tag %s.\n' % tag_name)
        finally:
            branch.unlock()


class cmd_tags(Command):
    """List tags.

    This tag shows a table of tag names and the revisions they reference.
    """

    _see_also = ['tag']
    takes_options = [
        Option('directory',
            help='Branch whose tags should be displayed.',
            short_name='d',
            type=unicode,
            ),
    ]

    @display_command
    def run(self,
            directory='.',
            ):
        branch, relpath = Branch.open_containing(directory)
        for tag_name, target in sorted(branch.tags.get_tag_dict().items()):
            self.outf.write('%-20s %s\n' % (tag_name, target))


def _create_prefix(cur_transport):
    needed = [cur_transport]
    # Recurse upwards until we can create a directory successfully
    while True:
        new_transport = cur_transport.clone('..')
        if new_transport.base == cur_transport.base:
            raise errors.BzrCommandError(
                "Failed to create path prefix for %s."
                % cur_transport.base)
        try:
            new_transport.mkdir('.')
        except errors.NoSuchFile:
            needed.append(new_transport)
            cur_transport = new_transport
        else:
            break
    # Now we only need to create child directories
    while needed:
        cur_transport = needed.pop()
        cur_transport.ensure_base()


def _get_mergeable_helper(location):
    """Get a merge directive or bundle if 'location' points to one.

    Try try to identify a bundle and returns its mergeable form. If it's not,
    we return the tried transport anyway so that it can reused to access the
    branch

    :param location: can point to a bundle or a branch.

    :return: mergeable, transport
    """
    mergeable = None
    url = urlutils.normalize_url(location)
    url, filename = urlutils.split(url, exclude_trailing_slash=False)
    location_transport = transport.get_transport(url)
    if filename:
        try:
            # There may be redirections but we ignore the intermediate
            # and final transports used
            read = bundle.read_mergeable_from_transport
            mergeable, t = read(location_transport, filename)
        except errors.NotABundle:
            # Continue on considering this url a Branch but adjust the
            # location_transport
            location_transport = location_transport.clone(filename)
    return mergeable, location_transport


# these get imported and then picked up by the scan for cmd_*
# TODO: Some more consistent way to split command definitions across files;
# we do need to load at least some information about them to know of 
# aliases.  ideally we would avoid loading the implementation until the
# details were needed.
from bzrlib.cmd_version_info import cmd_version_info
from bzrlib.conflicts import cmd_resolve, cmd_conflicts, restore
from bzrlib.bundle.commands import (
    cmd_bundle_info,
    )
from bzrlib.sign_my_commits import cmd_sign_my_commits
from bzrlib.weave_commands import cmd_versionedfile_list, cmd_weave_join, \
        cmd_weave_plan_merge, cmd_weave_merge_text
