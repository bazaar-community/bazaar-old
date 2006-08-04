# Copyright (C) 2004, 2005, 2006 by Canonical Ltd
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


import codecs
import errno
import os
import os.path
import sys

import bzrlib
from bzrlib import (
    branch,
    bundle,
    bzrdir,
    config,
    errors,
    ignores,
    log,
    osutils,
    repository,
    transport,
    ui,
    urlutils,
    )
from bzrlib.branch import Branch, BranchReferenceFormat
from bzrlib.bundle import read_bundle_from_url
from bzrlib.bundle.apply_bundle import install_bundle, merge_bundle
from bzrlib.conflicts import ConflictList
from bzrlib.commands import Command, display_command
from bzrlib.errors import (BzrError, BzrCheckError, BzrCommandError, 
                           NotBranchError, DivergedBranches, NotConflicted,
                           NoSuchFile, NoWorkingTree, FileInWrongBranch,
                           NotVersionedError, NotABundle)
from bzrlib.merge import Merge3Merger
from bzrlib.option import Option
from bzrlib.progress import DummyProgress, ProgressPhase
from bzrlib.revision import common_ancestor
from bzrlib.revisionspec import RevisionSpec
from bzrlib.trace import mutter, note, log_error, warning, is_quiet, info
from bzrlib.transport.local import LocalTransport
from bzrlib.workingtree import WorkingTree


def tree_files(file_list, default_branch=u'.'):
    try:
        return internal_tree_files(file_list, default_branch)
    except FileInWrongBranch, e:
        raise BzrCommandError("%s is not in the same branch as %s" %
                             (e.path, file_list[0]))


# XXX: Bad function name; should possibly also be a class method of
# WorkingTree rather than a function.
def internal_tree_files(file_list, default_branch=u'.'):
    """Convert command-line paths to a WorkingTree and relative paths.

    This is typically used for command-line processors that take one or
    more filenames, and infer the workingtree that contains them.

    The filenames given are not required to exist.

    :param file_list: Filenames to convert.  

    :param default_branch: Fallback tree path to use if file_list is empty or None.

    :return: workingtree, [relative_paths]
    """
    if file_list is None or len(file_list) == 0:
        return WorkingTree.open_containing(default_branch)[0], file_list
    tree = WorkingTree.open_containing(file_list[0])[0]
    new_list = []
    for filename in file_list:
        try:
            new_list.append(tree.relpath(filename))
        except errors.PathNotChild:
            raise FileInWrongBranch(tree.branch, filename)
    return tree, new_list


def get_format_type(typestring):
    """Parse and return a format specifier."""
    if typestring == "weave":
        return bzrdir.BzrDirFormat6()
    if typestring == "default":
        return bzrdir.BzrDirMetaFormat1()
    if typestring == "metaweave":
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = repository.RepositoryFormat7()
        return format
    if typestring == "knit":
        format = bzrdir.BzrDirMetaFormat1()
        format.repository_format = repository.RepositoryFormatKnit1()
        return format
    msg = "Unknown bzr format %s. Current formats are: default, knit,\n" \
          "metaweave and weave" % typestring
    raise BzrCommandError(msg)


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

    unknown
        Not versioned and not matching an ignore pattern.

    To see ignored files use 'bzr ignored'.  For details in the
    changes to file texts, use 'bzr diff'.

    If no arguments are specified, the status of the entire working
    directory is shown.  Otherwise, only the status of the specified
    files or directories is reported.  If a directory is given, status
    is reported for everything inside that directory.

    If a revision argument is given, the status is calculated against
    that revision, or between two revisions if two are provided.
    """
    
    # TODO: --no-recurse, --recurse options
    
    takes_args = ['file*']
    takes_options = ['show-ids', 'revision']
    aliases = ['st', 'stat']

    encoding_type = 'replace'
    
    @display_command
    def run(self, show_ids=False, file_list=None, revision=None):
        from bzrlib.status import show_tree_status

        tree, file_list = tree_files(file_list)
            
        show_tree_status(tree, show_ids=show_ids,
                         specific_files=file_list, revision=revision,
                         to_file=self.outf)


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

        if revision_id is not None and revision is not None:
            raise BzrCommandError('You can only supply one of revision_id or --revision')
        if revision_id is None and revision is None:
            raise BzrCommandError('You must supply either --revision or a revision_id')
        b = WorkingTree.open_containing(u'.')[0].branch

        # TODO: jam 20060112 should cat-revision always output utf-8?
        if revision_id is not None:
            self.outf.write(b.repository.get_revision_xml(revision_id).decode('utf-8'))
        elif revision is not None:
            for rev in revision:
                if rev is None:
                    raise BzrCommandError('You cannot specify a NULL revision.')
                revno, rev_id = rev.in_history(b)
                self.outf.write(b.repository.get_revision_xml(rev_id).decode('utf-8'))
    

class cmd_revno(Command):
    """Show current revision number.

    This is equal to the number of revisions on this branch.
    """

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
                revs.append(RevisionSpec(rev))
        if len(revs) == 0:
            raise BzrCommandError('You must supply a revision identifier')

        b = WorkingTree.open_containing(u'.')[0].branch

        for rev in revs:
            revinfo = rev.in_history(b)
            if revinfo.revno is None:
                print '     %s' % revinfo.rev_id
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
    """
    takes_args = ['file*']
    takes_options = ['no-recurse', 'dry-run', 'verbose']
    encoding_type = 'replace'

    def run(self, file_list, no_recurse=False, dry_run=False, verbose=False):
        import bzrlib.add

        action = bzrlib.add.AddAction(to_file=self.outf,
            should_print=(not is_quiet()))

        added, ignored = bzrlib.add.smart_add(file_list, not no_recurse, 
                                              action=action, save=not dry_run)
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
    type using the --kind option.  For example; --kind file.
    """

    takes_options = ['revision', 'show-ids', 'kind']
    
    @display_command
    def run(self, revision=None, show_ids=False, kind=None):
        if kind and kind not in ['file', 'directory', 'symlink']:
            raise BzrCommandError('invalid kind specified')
        tree = WorkingTree.open_containing(u'.')[0]
        if revision is None:
            inv = tree.read_working_inventory()
        else:
            if len(revision) > 1:
                raise BzrCommandError('bzr inventory --revision takes'
                    ' exactly one revision identifier')
            inv = tree.branch.repository.get_revision_inventory(
                revision[0].in_history(tree.branch).rev_id)

        for path, entry in inv.entries():
            if kind and kind != entry.kind:
                continue
            if show_ids:
                self.outf.write('%-50s %s\n' % (path, entry.file_id))
            else:
                self.outf.write(path)
                self.outf.write('\n')


class cmd_mv(Command):
    """Move or rename a file.

    usage:
        bzr mv OLDNAME NEWNAME
        bzr mv SOURCE... DESTINATION

    If the last argument is a versioned directory, all the other names
    are moved into it.  Otherwise, there must be exactly two arguments
    and the file is changed to a new name, which must not already exist.

    Files cannot be moved between branches.
    """

    takes_args = ['names*']
    aliases = ['move', 'rename']
    encoding_type = 'replace'

    def run(self, names_list):
        if names_list is None:
            names_list = []

        if len(names_list) < 2:
            raise BzrCommandError("missing file argument")
        tree, rel_names = tree_files(names_list)
        
        if os.path.isdir(names_list[-1]):
            # move into existing directory
            for pair in tree.move(rel_names[:-1], rel_names[-1]):
                self.outf.write("%s => %s\n" % pair)
        else:
            if len(names_list) != 2:
                raise BzrCommandError('to mv multiple files the destination '
                                      'must be a versioned directory')
            tree.rename_one(rel_names[0], rel_names[1])
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

    takes_options = ['remember', 'overwrite', 'revision', 'verbose']
    takes_args = ['location?']
    encoding_type = 'replace'

    def run(self, location=None, remember=False, overwrite=False, revision=None, verbose=False):
        # FIXME: too much stuff is in the command class
        try:
            tree_to = WorkingTree.open_containing(u'.')[0]
            branch_to = tree_to.branch
        except NoWorkingTree:
            tree_to = None
            branch_to = Branch.open_containing(u'.')[0]

        reader = None
        if location is not None:
            try:
                reader = bundle.read_bundle_from_url(location)
            except NotABundle:
                pass # Continue on considering this url a Branch

        stored_loc = branch_to.get_parent()
        if location is None:
            if stored_loc is None:
                raise BzrCommandError("No pull location known or specified.")
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                location = stored_loc


        if reader is not None:
            install_bundle(branch_to.repository, reader)
            branch_from = branch_to
        else:
            branch_from = Branch.open(location)

            if branch_to.get_parent() is None or remember:
                branch_to.set_parent(branch_from.base)

        rev_id = None
        if revision is None:
            if reader is not None:
                rev_id = reader.target
        elif len(revision) == 1:
            rev_id = revision[0].in_history(branch_from).rev_id
        else:
            raise BzrCommandError('bzr pull --revision takes one value.')

        old_rh = branch_to.revision_history()
        if tree_to is not None:
            count = tree_to.pull(branch_from, overwrite, rev_id)
        else:
            count = branch_to.pull(branch_from, overwrite, rev_id)
        note('%d revision(s) pulled.' % (count,))

        if verbose:
            new_rh = branch_to.revision_history()
            if old_rh != new_rh:
                # Something changed
                from bzrlib.log import show_changed_revisions
                show_changed_revisions(branch_to, old_rh, new_rh,
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

    takes_options = ['remember', 'overwrite', 'verbose',
                     Option('create-prefix', 
                            help='Create the path leading up to the branch '
                                 'if it does not already exist')]
    takes_args = ['location?']
    encoding_type = 'replace'

    def run(self, location=None, remember=False, overwrite=False,
            create_prefix=False, verbose=False):
        # FIXME: Way too big!  Put this into a function called from the
        # command.
        
        br_from = Branch.open_containing('.')[0]
        stored_loc = br_from.get_push_location()
        if location is None:
            if stored_loc is None:
                raise BzrCommandError("No push location known or specified.")
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                location = stored_loc

        to_transport = transport.get_transport(location)
        location_url = to_transport.base

        old_rh = []
        try:
            dir_to = bzrdir.BzrDir.open(location_url)
            br_to = dir_to.open_branch()
        except NotBranchError:
            # create a branch.
            to_transport = to_transport.clone('..')
            if not create_prefix:
                try:
                    relurl = to_transport.relpath(location_url)
                    mutter('creating directory %s => %s', location_url, relurl)
                    to_transport.mkdir(relurl)
                except NoSuchFile:
                    raise BzrCommandError("Parent directory of %s "
                                          "does not exist." % location)
            else:
                current = to_transport.base
                needed = [(to_transport, to_transport.relpath(location_url))]
                while needed:
                    try:
                        to_transport, relpath = needed[-1]
                        to_transport.mkdir(relpath)
                        needed.pop()
                    except NoSuchFile:
                        new_transport = to_transport.clone('..')
                        needed.append((new_transport,
                                       new_transport.relpath(to_transport.base)))
                        if new_transport.base == to_transport.base:
                            raise BzrCommandError("Could not create "
                                                  "path prefix.")
            dir_to = br_from.bzrdir.clone(location_url,
                revision_id=br_from.last_revision())
            br_to = dir_to.open_branch()
            count = len(br_to.revision_history())
            # We successfully created the target, remember it
            if br_from.get_push_location() is None or remember:
                br_from.set_push_location(br_to.base)
        else:
            # We were able to connect to the remote location, so remember it
            # we don't need to successfully push because of possible divergence.
            if br_from.get_push_location() is None or remember:
                br_from.set_push_location(br_to.base)
            old_rh = br_to.revision_history()
            try:
                try:
                    tree_to = dir_to.open_workingtree()
                except errors.NotLocalUrl:
                    warning('This transport does not update the working '
                            'tree of: %s' % (br_to.base,))
                    count = br_to.pull(br_from, overwrite)
                except NoWorkingTree:
                    count = br_to.pull(br_from, overwrite)
                else:
                    count = tree_to.pull(br_from, overwrite)
            except DivergedBranches:
                raise BzrCommandError("These branches have diverged."
                                      "  Try a merge then push with overwrite.")
        note('%d revision(s) pushed.' % (count,))

        if verbose:
            new_rh = br_to.revision_history()
            if old_rh != new_rh:
                # Something changed
                from bzrlib.log import show_changed_revisions
                show_changed_revisions(br_to, old_rh, new_rh,
                                       to_file=self.outf)


class cmd_branch(Command):
    """Create a new copy of a branch.

    If the TO_LOCATION is omitted, the last component of the FROM_LOCATION will
    be used.  In other words, "branch ../foo/bar" will attempt to create ./bar.

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "branch foo/bar -r 5".

    --basis is to speed up branching from remote branches.  When specified, it
    copies all the file-contents, inventory and revision data from the basis
    branch before copying anything from the remote branch.
    """
    takes_args = ['from_location', 'to_location?']
    takes_options = ['revision', 'basis']
    aliases = ['get', 'clone']

    def run(self, from_location, to_location=None, revision=None, basis=None):
        if revision is None:
            revision = [None]
        elif len(revision) > 1:
            raise BzrCommandError(
                'bzr branch --revision takes exactly 1 revision value')
        try:
            br_from = Branch.open(from_location)
        except OSError, e:
            if e.errno == errno.ENOENT:
                raise BzrCommandError('Source location "%s" does not'
                                      ' exist.' % to_location)
            else:
                raise
        br_from.lock_read()
        try:
            if basis is not None:
                basis_dir = bzrdir.BzrDir.open_containing(basis)[0]
            else:
                basis_dir = None
            if len(revision) == 1 and revision[0] is not None:
                revision_id = revision[0].in_history(br_from)[1]
            else:
                # FIXME - wt.last_revision, fallback to branch, fall back to
                # None or perhaps NULL_REVISION to mean copy nothing
                # RBC 20060209
                revision_id = br_from.last_revision()
            if to_location is None:
                to_location = os.path.basename(from_location.rstrip("/\\"))
                name = None
            else:
                name = os.path.basename(to_location) + '\n'

            to_transport = transport.get_transport(to_location)
            try:
                to_transport.mkdir('.')
            except errors.FileExists:
                raise BzrCommandError('Target directory "%s" already'
                                      ' exists.' % to_location)
            except errors.NoSuchFile:
                raise BzrCommandError('Parent of "%s" does not exist.' %
                                      to_location)
            try:
                # preserve whatever source format we have.
                dir = br_from.bzrdir.sprout(to_transport.base,
                        revision_id, basis_dir)
                branch = dir.open_branch()
            except errors.NoSuchRevision:
                to_transport.delete_tree('.')
                msg = "The branch %s has no revision %s." % (from_location, revision[0])
                raise BzrCommandError(msg)
            except errors.UnlistableBranch:
                osutils.rmtree(to_location)
                msg = "The branch %s cannot be used as a --basis" % (basis,)
                raise BzrCommandError(msg)
            if name:
                branch.control_files.put_utf8('branch-name', name)
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

    To retrieve the branch as of a particular revision, supply the --revision
    parameter, as in "checkout foo/bar -r 5". Note that this will be immediately
    out of date [so you cannot commit] but it may be useful (i.e. to examine old
    code.)

    --basis is to speed up checking out from remote branches.  When specified, it
    uses the inventory and file contents from the basis branch in preference to the
    branch being checked out.
    """
    takes_args = ['branch_location?', 'to_location?']
    takes_options = ['revision', # , 'basis']
                     Option('lightweight',
                            help="perform a lightweight checkout. Lightweight "
                                 "checkouts depend on access to the branch for "
                                 "every operation. Normal checkouts can perform "
                                 "common operations like diff and status without "
                                 "such access, and also support local commits."
                            ),
                     ]
    aliases = ['co']

    def run(self, branch_location=None, to_location=None, revision=None, basis=None,
            lightweight=False):
        if revision is None:
            revision = [None]
        elif len(revision) > 1:
            raise BzrCommandError(
                'bzr checkout --revision takes exactly 1 revision value')
        if branch_location is None:
            branch_location = osutils.getcwd()
            to_location = branch_location
        source = Branch.open(branch_location)
        if len(revision) == 1 and revision[0] is not None:
            revision_id = revision[0].in_history(source)[1]
        else:
            revision_id = None
        if to_location is None:
            to_location = os.path.basename(branch_location.rstrip("/\\"))
        # if the source and to_location are the same, 
        # and there is no working tree,
        # then reconstitute a branch
        if (osutils.abspath(to_location) == 
            osutils.abspath(branch_location)):
            try:
                source.bzrdir.open_workingtree()
            except errors.NoWorkingTree:
                source.bzrdir.create_workingtree()
                return
        try:
            os.mkdir(to_location)
        except OSError, e:
            if e.errno == errno.EEXIST:
                raise BzrCommandError('Target directory "%s" already'
                                      ' exists.' % to_location)
            if e.errno == errno.ENOENT:
                raise BzrCommandError('Parent of "%s" does not exist.' %
                                      to_location)
            else:
                raise
        old_format = bzrdir.BzrDirFormat.get_default_format()
        bzrdir.BzrDirFormat.set_default_format(bzrdir.BzrDirMetaFormat1())
        try:
            bzrdir.BzrDir.create_checkout_convenience(to_location, source,
                                                      revision_id, lightweight)
        finally:
            bzrdir.BzrDirFormat.set_default_format(old_format)


class cmd_renames(Command):
    """Show list of renamed files.
    """
    # TODO: Option to show renames between two historical versions.

    # TODO: Only show renames under dir, rather than in the whole branch.
    takes_args = ['dir?']

    @display_command
    def run(self, dir=u'.'):
        from bzrlib.tree import find_renames
        tree = WorkingTree.open_containing(dir)[0]
        old_inv = tree.basis_tree().inventory
        new_inv = tree.read_working_inventory()
        renames = list(find_renames(old_inv, new_inv))
        renames.sort()
        for old_name, new_name in renames:
            self.outf.write("%s => %s\n" % (old_name, new_name))


class cmd_update(Command):
    """Update a tree to have the latest code committed to its branch.
    
    This will perform a merge into the working tree, and may generate
    conflicts. If you have any local changes, you will still 
    need to commit them after the update for the update to be complete.
    
    If you want to discard your local changes, you can just do a 
    'bzr revert' instead of 'bzr commit' after the update.
    """
    takes_args = ['dir?']
    aliases = ['up']

    def run(self, dir='.'):
        tree = WorkingTree.open_containing(dir)[0]
        tree.lock_write()
        existing_pending_merges = tree.pending_merges()
        try:
            last_rev = tree.last_revision() 
            if last_rev == tree.branch.last_revision():
                # may be up to date, check master too.
                master = tree.branch.get_master_branch()
                if master is None or last_rev == master.last_revision():
                    revno = tree.branch.revision_id_to_revno(last_rev)
                    note("Tree is up to date at revision %d." % (revno,))
                    return 0
            conflicts = tree.update()
            revno = tree.branch.revision_id_to_revno(tree.last_revision())
            note('Updated to revision %d.' % (revno,))
            if tree.pending_merges() != existing_pending_merges:
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
    takes_args = ['location?']
    takes_options = ['verbose']

    @display_command
    def run(self, location=None, verbose=False):
        from bzrlib.info import show_bzrdir_info
        show_bzrdir_info(bzrdir.BzrDir.open_containing(location)[0],
                         verbose=verbose)


class cmd_remove(Command):
    """Make a file unversioned.

    This makes bzr stop tracking changes to a versioned file.  It does
    not delete the working copy.

    You can specify one or more files, and/or --new.  If you specify --new,
    only 'added' files will be removed.  If you specify both, then new files
    in the specified directories will be removed.  If the directories are
    also new, they will also be removed.
    """
    takes_args = ['file*']
    takes_options = ['verbose', Option('new', help='remove newly-added files')]
    aliases = ['rm']
    encoding_type = 'replace'
    
    def run(self, file_list, verbose=False, new=False):
        tree, file_list = tree_files(file_list)
        if new is False:
            if file_list is None:
                raise BzrCommandError('Specify one or more files to remove, or'
                                      ' use --new.')
        else:
            added = tree.changes_from(tree.basis_tree(),
                specific_files=file_list).added
            file_list = sorted([f[0] for f in added], reverse=True)
            if len(file_list) == 0:
                raise BzrCommandError('No matching files.')
        tree.remove(file_list, verbose=verbose, to_file=self.outf)


class cmd_file_id(Command):
    """Print file_id of a particular file or directory.

    The file_id is assigned when the file is first added and remains the
    same through all revisions where the file exists, even when it is
    moved or renamed.
    """

    hidden = True
    takes_args = ['filename']

    @display_command
    def run(self, filename):
        tree, relpath = WorkingTree.open_containing(filename)
        i = tree.inventory.path2id(relpath)
        if i == None:
            raise BzrError("%r is not a versioned file" % filename)
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
        inv = tree.inventory
        fid = inv.path2id(relpath)
        if fid == None:
            raise BzrError("%r is not a versioned file" % filename)
        for fip in inv.get_idpath(fid):
            self.outf.write(fip + '\n')


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
    takes_args = ['branch?']

    def run(self, branch="."):
        from bzrlib.reconcile import reconcile
        dir = bzrdir.BzrDir.open(branch)
        reconcile(dir)


class cmd_revision_history(Command):
    """Display the list of revision ids on a branch."""
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
        assert revision_ids[0] == None
        revision_ids.pop(0)
        for revision_id in revision_ids:
            self.outf.write(revision_id + '\n')


class cmd_init(Command):
    """Make a directory into a versioned branch.

    Use this to create an empty branch, or before importing an
    existing project.

    If there is a repository in a parent directory of the location, then 
    the history of the branch will be stored in the repository.  Otherwise
    init creates a standalone branch which carries its own history in 
    .bzr.

    If there is already a branch at the location but it has no working tree,
    the tree can be populated with 'bzr checkout'.

    Recipe for importing a tree of files:
        cd ~/project
        bzr init
        bzr add .
        bzr status
        bzr commit -m 'imported project'
    """
    takes_args = ['location?']
    takes_options = [
                     Option('format', 
                            help='Specify a format for this branch. Current'
                                 ' formats are: default, knit, metaweave and'
                                 ' weave. Default is knit; metaweave and'
                                 ' weave are deprecated',
                            type=get_format_type),
                     ]
    def run(self, location=None, format=None):
        if format is None:
            format = get_format_type('default')
        if location is None:
            location = u'.'

        to_transport = transport.get_transport(location)

        # The path has to exist to initialize a
        # branch inside of it.
        # Just using os.mkdir, since I don't
        # believe that we want to create a bunch of
        # locations if the user supplies an extended path
        # TODO: create-prefix
        try:
            to_transport.mkdir('.')
        except errors.FileExists:
            pass
                    
        try:
            existing_bzrdir = bzrdir.BzrDir.open(location)
        except NotBranchError:
            # really a NotBzrDir error...
            bzrdir.BzrDir.create_branch_convenience(location, format=format)
        else:
            if existing_bzrdir.has_branch():
                if (isinstance(to_transport, LocalTransport)
                    and not existing_bzrdir.has_workingtree()):
                        raise errors.BranchExistsWithoutWorkingTree(location)
                raise errors.AlreadyBranchError(location)
            else:
                existing_bzrdir.create_branch()
                existing_bzrdir.create_workingtree()


class cmd_init_repository(Command):
    """Create a shared repository to hold branches.

    New branches created under the repository directory will store their revisions
    in the repository, not in the branch directory, if the branch format supports
    shared storage.

    example:
        bzr init-repo repo
        bzr init repo/trunk
        bzr checkout --lightweight repo/trunk trunk-checkout
        cd trunk-checkout
        (add files here)
    """
    takes_args = ["location"] 
    takes_options = [Option('format', 
                            help='Specify a format for this repository.'
                                 ' Current formats are: default, knit,'
                                 ' metaweave and weave. Default is knit;'
                                 ' metaweave and weave are deprecated',
                            type=get_format_type),
                     Option('trees',
                             help='Allows branches in repository to have'
                             ' a working tree')]
    aliases = ["init-repo"]
    def run(self, location, format=None, trees=False):
        if format is None:
            format = get_format_type('default')

        if location is None:
            location = '.'

        to_transport = transport.get_transport(location)
        try:
            to_transport.mkdir('.')
        except errors.FileExists:
            pass

        newdir = format.initialize_on_transport(to_transport)
        repo = newdir.create_repository(shared=True)
        repo.set_make_working_trees(trees)


class cmd_diff(Command):
    """Show differences in the working tree or between revisions.
    
    If files are listed, only the changes in those files are listed.
    Otherwise, all changes for the tree are listed.

    "bzr diff -p1" is equivalent to "bzr diff --prefix old/:new/", and
    produces patches suitable for "patch -p1".

    examples:
        bzr diff
            Shows the difference in the working tree versus the last commit
        bzr diff -r1
            Difference between the working tree and revision 1
        bzr diff -r1..2
            Difference between revision 2 and revision 1
        bzr diff --diff-prefix old/:new/
            Same as 'bzr diff' but prefix paths with old/ and new/
        bzr diff bzr.mine bzr.dev
            Show the differences between the two working trees
        bzr diff foo.c
            Show just the differences for 'foo.c'
    """
    # TODO: Option to use external diff command; could be GNU diff, wdiff,
    #       or a graphical diff.

    # TODO: Python difflib is not exactly the same as unidiff; should
    #       either fix it up or prefer to use an external diff.

    # TODO: Selected-file diff is inefficient and doesn't show you
    #       deleted files.

    # TODO: This probably handles non-Unix newlines poorly.
    
    takes_args = ['file*']
    takes_options = ['revision', 'diff-options', 'prefix']
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
        else:
            if not ':' in prefix:
                 raise BzrError("--diff-prefix expects two values separated by a colon")
            old_label, new_label = prefix.split(":")
        
        try:
            tree1, file_list = internal_tree_files(file_list)
            tree2 = None
            b = None
            b2 = None
        except FileInWrongBranch:
            if len(file_list) != 2:
                raise BzrCommandError("Files are in different branches")

            tree1, file1 = WorkingTree.open_containing(file_list[0])
            tree2, file2 = WorkingTree.open_containing(file_list[1])
            if file1 != "" or file2 != "":
                # FIXME diff those two files. rbc 20051123
                raise BzrCommandError("Files are in different branches")
            file_list = None
        except NotBranchError:
            if (revision is not None and len(revision) == 2
                and not revision[0].needs_branch()
                and not revision[1].needs_branch()):
                # If both revision specs include a branch, we can
                # diff them without needing a local working tree
                tree1, tree2 = None, None
            else:
                raise
        if revision is not None:
            if tree2 is not None:
                raise BzrCommandError("Can't specify -r with two branches")
            if (len(revision) == 1) or (revision[1].spec is None):
                return diff_cmd_helper(tree1, file_list, diff_options,
                                       revision[0], 
                                       old_label=old_label, new_label=new_label)
            elif len(revision) == 2:
                return diff_cmd_helper(tree1, file_list, diff_options,
                                       revision[0], revision[1],
                                       old_label=old_label, new_label=new_label)
            else:
                raise BzrCommandError('bzr diff --revision takes exactly one or two revision identifiers')
        else:
            if tree2 is not None:
                return show_diff_trees(tree1, tree2, sys.stdout, 
                                       specific_files=file_list,
                                       external_diff_options=diff_options,
                                       old_label=old_label, new_label=new_label)
            else:
                return diff_cmd_helper(tree1, file_list, diff_options,
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
    takes_options = ['show-ids']

    @display_command
    def run(self, show_ids=False):
        tree = WorkingTree.open_containing(u'.')[0]
        old = tree.basis_tree()
        for path, ie in old.inventory.iter_entries():
            if not tree.has_id(ie.file_id):
                self.outf.write(path)
                if show_ids:
                    self.outf.write(' ')
                    self.outf.write(ie.file_id)
                self.outf.write('\n')


class cmd_modified(Command):
    """List files modified in working tree."""
    hidden = True
    @display_command
    def run(self):
        tree = WorkingTree.open_containing(u'.')[0]
        td = tree.changes_from(tree.basis_tree())
        for path, id, kind, text_modified, meta_modified in td.modified:
            self.outf.write(path + '\n')


class cmd_added(Command):
    """List files added in working tree."""
    hidden = True
    @display_command
    def run(self):
        wt = WorkingTree.open_containing(u'.')[0]
        basis_inv = wt.basis_tree().inventory
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


class cmd_log(Command):
    """Show log of a branch, file, or directory.

    By default show the log of the branch containing the working directory.

    To request a range of logs, you can use the command -r begin..end
    -r revision requests a specific revision, -r ..end or -r begin.. are
    also valid.

    examples:
        bzr log
        bzr log foo.c
        bzr log -r -10.. http://server/branch
    """

    # TODO: Make --revision support uuid: and hash: [future tag:] notation.

    takes_args = ['location?']
    takes_options = [Option('forward', 
                            help='show from oldest to newest'),
                     'timezone', 
                     Option('verbose', 
                             help='show files changed in each revision'),
                     'show-ids', 'revision',
                     'log-format',
                     'line', 'long', 
                     Option('message',
                            help='show revisions whose message matches this regexp',
                            type=str),
                     'short',
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
            long=False,
            short=False,
            line=False):
        from bzrlib.log import log_formatter, show_log
        assert message is None or isinstance(message, basestring), \
            "invalid message argument %r" % message
        direction = (forward and 'forward') or 'reverse'
        
        # log everything
        file_id = None
        if location:
            # find the file id to log:

            dir, fp = bzrdir.BzrDir.open_containing(location)
            b = dir.open_branch()
            if fp != '':
                try:
                    # might be a tree:
                    inv = dir.open_workingtree().inventory
                except (errors.NotBranchError, errors.NotLocalUrl):
                    # either no tree, or is remote.
                    inv = b.basis_tree().inventory
                file_id = inv.path2id(fp)
        else:
            # local dir only
            # FIXME ? log the current subdir only RBC 20060203 
            dir, relpath = bzrdir.BzrDir.open_containing('.')
            b = dir.open_branch()

        if revision is None:
            rev1 = None
            rev2 = None
        elif len(revision) == 1:
            rev1 = rev2 = revision[0].in_history(b).revno
        elif len(revision) == 2:
            if revision[0].spec is None:
                # missing begin-range means first revision
                rev1 = 1
            else:
                rev1 = revision[0].in_history(b).revno

            if revision[1].spec is None:
                # missing end-range means last known revision
                rev2 = b.revno()
            else:
                rev2 = revision[1].in_history(b).revno
        else:
            raise BzrCommandError('bzr log --revision takes one or two values.')

        # By this point, the revision numbers are converted to the +ve
        # form if they were supplied in the -ve form, so we can do
        # this comparison in relative safety
        if rev1 > rev2:
            (rev2, rev1) = (rev1, rev2)

        if (log_format == None):
            default = b.get_config().log_format()
            log_format = get_log_format(long=long, short=short, line=line, 
                                        default=default)
        lf = log_formatter(log_format,
                           show_ids=show_ids,
                           to_file=self.outf,
                           show_timezone=timezone)

        show_log(b,
                 lf,
                 file_id,
                 verbose=verbose,
                 direction=direction,
                 start_revision=rev1,
                 end_revision=rev2,
                 search=message)


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
        inv = tree.read_working_inventory()
        file_id = inv.path2id(relpath)
        for revno, revision_id, what in log.find_touching_revisions(b, file_id):
            self.outf.write("%6d %s\n" % (revno, what))


class cmd_ls(Command):
    """List files in a tree.
    """
    # TODO: Take a revision or remote path and list that tree instead.
    hidden = True
    takes_options = ['verbose', 'revision',
                     Option('non-recursive',
                            help='don\'t recurse into sub-directories'),
                     Option('from-root',
                            help='Print all paths from the root of the branch.'),
                     Option('unknown', help='Print unknown files'),
                     Option('versioned', help='Print versioned files'),
                     Option('ignored', help='Print ignored files'),

                     Option('null', help='Null separate the files'),
                    ]
    @display_command
    def run(self, revision=None, verbose=False, 
            non_recursive=False, from_root=False,
            unknown=False, versioned=False, ignored=False,
            null=False):

        if verbose and null:
            raise BzrCommandError('Cannot set both --verbose and --null')
        all = not (unknown or versioned or ignored)

        selection = {'I':ignored, '?':unknown, 'V':versioned}

        tree, relpath = WorkingTree.open_containing(u'.')
        if from_root:
            relpath = u''
        elif relpath:
            relpath += '/'
        if revision is not None:
            tree = tree.branch.repository.revision_tree(
                revision[0].in_history(tree.branch).rev_id)

        for fp, fc, kind, fid, entry in tree.list_files():
            if fp.startswith(relpath):
                fp = fp[len(relpath):]
                if non_recursive and '/' in fp:
                    continue
                if not all and not selection[fc]:
                    continue
                if verbose:
                    kindch = entry.kind_character()
                    self.outf.write('%-8s %s%s\n' % (fc, fp, kindch))
                elif null:
                    self.outf.write(fp + '\0')
                    self.outf.flush()
                else:
                    self.outf.write(fp + '\n')


class cmd_unknowns(Command):
    """List unknown files."""
    @display_command
    def run(self):
        for f in WorkingTree.open_containing(u'.')[0].unknowns():
            self.outf.write(osutils.quotefn(f) + '\n')


class cmd_ignore(Command):
    """Ignore a command or pattern.

    To remove patterns from the ignore list, edit the .bzrignore file.

    If the pattern contains a slash, it is compared to the whole path
    from the branch root.  Otherwise, it is compared to only the last
    component of the path.  To match a file only in the root directory,
    prepend './'.

    Ignore patterns are case-insensitive on case-insensitive systems.

    Note: wildcards must be quoted from the shell on Unix.

    examples:
        bzr ignore ./Makefile
        bzr ignore '*.class'
    """
    # TODO: Complain if the filename is absolute
    takes_args = ['name_pattern?']
    takes_options = [
                     Option('old-default-rules',
                            help='Out the ignore rules bzr < 0.9 always used.')
                     ]
    
    def run(self, name_pattern=None, old_default_rules=None):
        from bzrlib.atomicfile import AtomicFile
        if old_default_rules is not None:
            # dump the rules and exit
            for pattern in ignores.OLD_DEFAULTS:
                print pattern
            return
        if name_pattern is None:
            raise BzrCommandError("ignore requires a NAME_PATTERN")
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
        igns += name_pattern + '\n'

        f = AtomicFile(ifn, 'wt')
        try:
            f.write(igns.encode('utf-8'))
            f.commit()
        finally:
            f.close()

        inv = tree.inventory
        if inv.path2id('.bzrignore'):
            mutter('.bzrignore is already versioned')
        else:
            mutter('need to make new .bzrignore file versioned')
            tree.add(['.bzrignore'])


class cmd_ignored(Command):
    """List ignored files and the patterns that matched them.

    See also: bzr ignore"""
    @display_command
    def run(self):
        tree = WorkingTree.open_containing(u'.')[0]
        for path, file_class, kind, file_id, entry in tree.list_files():
            if file_class != 'I':
                continue
            ## XXX: Slightly inefficient since this was already calculated
            pat = tree.is_ignored(path)
            print '%-50s %s' % (path, pat)


class cmd_lookup_revision(Command):
    """Lookup the revision-id from a revision-number

    example:
        bzr lookup-revision 33
    """
    hidden = True
    takes_args = ['revno']
    
    @display_command
    def run(self, revno):
        try:
            revno = int(revno)
        except ValueError:
            raise BzrCommandError("not a valid revision-number: %r" % revno)

        print WorkingTree.open_containing(u'.')[0].branch.get_rev_id(revno)


class cmd_export(Command):
    """Export past revision to destination directory.

    If no revision is specified this exports the last committed revision.

    Format may be an "exporter" name, such as tar, tgz, tbz2.  If none is
    given, try to find the format with the extension. If no extension
    is found exports to a directory (equivalent to --format=dir).

    Root may be the top directory for tar, tgz and tbz2 formats. If none
    is given, the top directory will be the root name of the file.

    Note: export of tree with non-ascii filenames to zip is not supported.

     Supported formats       Autodetected by extension
     -----------------       -------------------------
         dir                            -
         tar                          .tar
         tbz2                    .tar.bz2, .tbz2
         tgz                      .tar.gz, .tgz
         zip                          .zip
    """
    takes_args = ['dest']
    takes_options = ['revision', 'format', 'root']
    def run(self, dest, revision=None, format=None, root=None):
        from bzrlib.export import export
        tree = WorkingTree.open_containing(u'.')[0]
        b = tree.branch
        if revision is None:
            # should be tree.last_revision  FIXME
            rev_id = b.last_revision()
        else:
            if len(revision) != 1:
                raise BzrError('bzr export --revision takes exactly 1 argument')
            rev_id = revision[0].in_history(b).rev_id
        t = b.repository.revision_tree(rev_id)
        try:
            export(t, dest, format, root)
        except errors.NoSuchExportFormat, e:
            raise BzrCommandError('Unsupported export format: %s' % e.format)


class cmd_cat(Command):
    """Write a file's text from a previous revision."""

    takes_options = ['revision']
    takes_args = ['filename']

    @display_command
    def run(self, filename, revision=None):
        if revision is not None and len(revision) != 1:
            raise BzrCommandError("bzr cat --revision takes exactly one number")
        tree = None
        try:
            tree, relpath = WorkingTree.open_containing(filename)
            b = tree.branch
        except NotBranchError:
            pass

        if tree is None:
            b, relpath = Branch.open_containing(filename)
        if revision is None:
            revision_id = b.last_revision()
        else:
            revision_id = revision[0].in_history(b).rev_id
        b.print_file(relpath, revision_id)


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

    A selected-file commit may fail in some cases where the committed
    tree would be invalid, such as trying to commit a file in a
    newly-added directory that is not itself committed.
    """
    # TODO: Run hooks on tree to-be-committed, and after commit.

    # TODO: Strict commit that fails if there are deleted files.
    #       (what does "deleted files" mean ??)

    # TODO: Give better message for -s, --summary, used by tla people

    # XXX: verbose currently does nothing

    takes_args = ['selected*']
    takes_options = ['message', 'verbose', 
                     Option('unchanged',
                            help='commit even if nothing has changed'),
                     Option('file', type=str, 
                            argname='msgfile',
                            help='file containing commit message'),
                     Option('strict',
                            help="refuse to commit if there are unknown "
                            "files in the working tree."),
                     Option('local',
                            help="perform a local only commit in a bound "
                                 "branch. Such commits are not pushed to "
                                 "the master branch until a normal commit "
                                 "is performed."
                            ),
                     ]
    aliases = ['ci', 'checkin']

    def run(self, message=None, file=None, verbose=True, selected_list=None,
            unchanged=False, strict=False, local=False):
        from bzrlib.commit import (NullCommitReporter, ReportCommitToLog)
        from bzrlib.errors import (PointlessCommit, ConflictsInTree,
                StrictCommitFailed)
        from bzrlib.msgeditor import edit_commit_message, \
                make_commit_message_template
        from tempfile import TemporaryFile

        # TODO: Need a blackbox test for invoking the external editor; may be
        # slightly problematic to run this cross-platform.

        # TODO: do more checks that the commit will succeed before 
        # spending the user's valuable time typing a commit message.
        #
        # TODO: if the commit *does* happen to fail, then save the commit 
        # message to a temporary file where it can be recovered
        tree, selected_list = tree_files(selected_list)
        if selected_list == ['']:
            # workaround - commit of root of tree should be exactly the same
            # as just default commit in that tree, and succeed even though
            # selected-file merge commit is not done yet
            selected_list = []

        if local and not tree.branch.get_bound_location():
            raise errors.LocalRequiresBoundBranch()
        if message is None and not file:
            template = make_commit_message_template(tree, selected_list)
            message = edit_commit_message(template)
            if message is None:
                raise BzrCommandError("please specify a commit message"
                                      " with either --message or --file")
        elif message and file:
            raise BzrCommandError("please specify either --message or --file")
        
        if file:
            message = codecs.open(file, 'rt', bzrlib.user_encoding).read()

        if message == "":
            raise BzrCommandError("empty commit message specified")
        
        if verbose:
            reporter = ReportCommitToLog()
        else:
            reporter = NullCommitReporter()
        
        try:
            tree.commit(message, specific_files=selected_list,
                        allow_pointless=unchanged, strict=strict, local=local,
                        reporter=reporter)
        except PointlessCommit:
            # FIXME: This should really happen before the file is read in;
            # perhaps prepare the commit; get the message; then actually commit
            raise BzrCommandError("no changes to commit."
                                  " use --unchanged to commit anyhow")
        except ConflictsInTree:
            raise BzrCommandError("Conflicts detected in working tree.  "
                'Use "bzr conflicts" to list, "bzr resolve FILE" to resolve.')
        except StrictCommitFailed:
            raise BzrCommandError("Commit refused because there are unknown "
                                  "files in the working tree.")
        except errors.BoundBranchOutOfDate, e:
            raise BzrCommandError(str(e) + "\n"
                'To commit to master branch, run update and then commit.\n'
                'You can also pass --local to commit to continue working '
                'disconnected.')

class cmd_check(Command):
    """Validate consistency of branch history.

    This command checks various invariants about the branch storage to
    detect data corruption or bzr bugs.
    """
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


class cmd_scan_cache(Command):
    hidden = True
    def run(self):
        from bzrlib.hashcache import HashCache

        c = HashCache(u'.')
        c.read()
        c.scan()
            
        print '%6d stats' % c.stat_count
        print '%6d in hashcache' % len(c._cache)
        print '%6d files removed from cache' % c.removed_count
        print '%6d hashes updated' % c.update_count
        print '%6d files changed too recently to cache' % c.danger_count

        if c.needs_write:
            c.write()


class cmd_upgrade(Command):
    """Upgrade branch storage to current format.

    The check command or bzr developers may sometimes advise you to run
    this command. When the default format has changed you may also be warned
    during other operations to upgrade.
    """
    takes_args = ['url?']
    takes_options = [
                     Option('format', 
                            help='Upgrade to a specific format. Current formats'
                                 ' are: default, knit, metaweave and weave.'
                                 ' Default is knit; metaweave and weave are'
                                 ' deprecated',
                            type=get_format_type),
                    ]


    def run(self, url='.', format=None):
        from bzrlib.upgrade import upgrade
        if format is None:
            format = get_format_type('default')
        upgrade(url, format)


class cmd_whoami(Command):
    """Show or set bzr user id.
    
    examples:
        bzr whoami --email
        bzr whoami 'Frank Chu <fchu@example.com>'
    """
    takes_options = [ Option('email',
                             help='display email address only'),
                      Option('branch',
                             help='set identity for the current branch instead of '
                                  'globally'),
                    ]
    takes_args = ['name?']
    encoding_type = 'replace'
    
    @display_command
    def run(self, email=False, branch=False, name=None):
        if name is None:
            # use branch if we're inside one; otherwise global config
            try:
                c = Branch.open_containing('.')[0].get_config()
            except NotBranchError:
                c = config.GlobalConfig()
            if email:
                self.outf.write(c.user_email() + '\n')
            else:
                self.outf.write(c.username() + '\n')
            return

        # display a warning if an email address isn't included in the given name.
        try:
            config.extract_email_address(name)
        except BzrError, e:
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
    
    This creates temporary test directories in the working directory,
    but not existing data is affected.  These directories are deleted
    if the tests pass, or left behind to help in debugging if they
    fail and --keep-output is specified.
    
    If arguments are given, they are regular expressions that say
    which tests should run.

    If the global option '--no-plugins' is given, plugins are not loaded
    before running the selftests.  This has two effects: features provided or
    modified by plugins will not be tested, and tests provided by plugins will
    not be run.

    examples:
        bzr selftest ignore
        bzr --no-plugins selftest -v
    """
    # TODO: --list should give a list of all available tests

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
        raise BzrCommandError(msg)

    hidden = True
    takes_args = ['testspecs*']
    takes_options = ['verbose',
                     Option('one', help='stop when one test fails'),
                     Option('keep-output', 
                            help='keep output directories when tests fail'),
                     Option('transport', 
                            help='Use a different transport by default '
                                 'throughout the test suite.',
                            type=get_transport_type),
                     Option('benchmark', help='run the bzr bencharks.'),
                     Option('lsprof-timed',
                            help='generate lsprof output for benchmarked'
                                 ' sections of code.'),
                     ]

    def run(self, testspecs_list=None, verbose=None, one=False,
            keep_output=False, transport=None, benchmark=None,
            lsprof_timed=None):
        import bzrlib.ui
        from bzrlib.tests import selftest
        import bzrlib.benchmarks as benchmarks
        # we don't want progress meters from the tests to go to the
        # real output; and we don't want log messages cluttering up
        # the real logs.
        save_ui = ui.ui_factory
        print '%10s: %s' % ('bzr', osutils.realpath(sys.argv[0]))
        print '%10s: %s' % ('bzrlib', bzrlib.__path__[0])
        print
        info('running tests...')
        try:
            ui.ui_factory = ui.SilentUIFactory()
            if testspecs_list is not None:
                pattern = '|'.join(testspecs_list)
            else:
                pattern = ".*"
            if benchmark:
                test_suite_factory = benchmarks.test_suite
                if verbose is None:
                    verbose = True
            else:
                test_suite_factory = None
                if verbose is None:
                    verbose = False
            result = selftest(verbose=verbose, 
                              pattern=pattern,
                              stop_on_failure=one, 
                              keep_output=keep_output,
                              transport=transport,
                              test_suite_factory=test_suite_factory,
                              lsprof_timed=lsprof_timed)
            if result:
                info('tests passed')
            else:
                info('tests failed')
            return int(not result)
        finally:
            ui.ui_factory = save_ui


def _get_bzr_branch():
    """If bzr is run from a branch, return Branch or None"""
    from os.path import dirname
    
    try:
        branch = Branch.open(dirname(osutils.abspath(dirname(__file__))))
        return branch
    except errors.BzrError:
        return None
    

def show_version():
    import bzrlib
    print "Bazaar (bzr) %s" % bzrlib.__version__
    # is bzrlib itself in a branch?
    branch = _get_bzr_branch()
    if branch:
        rh = branch.revision_history()
        revno = len(rh)
        print "  bzr checkout, revision %d" % (revno,)
        print "  nick: %s" % (branch.nick,)
        if rh:
            print "  revid: %s" % (rh[-1],)
    print "Using python interpreter:", sys.executable
    import site
    print "Using python standard library:", os.path.dirname(site.__file__)
    print "Using bzrlib:",
    if len(bzrlib.__path__) > 1:
        # print repr, which is a good enough way of making it clear it's
        # more than one element (eg ['/foo/bar', '/foo/bzr'])
        print repr(bzrlib.__path__)
    else:
        print bzrlib.__path__[0]

    print
    print bzrlib.__copyright__
    print "http://bazaar-vcs.org/"
    print
    print "bzr comes with ABSOLUTELY NO WARRANTY.  bzr is free software, and"
    print "you may use, modify and redistribute it under the terms of the GNU"
    print "General Public License version 2 or later."


class cmd_version(Command):
    """Show version of bzr."""

    @display_command
    def run(self):
        show_version()


class cmd_rocks(Command):
    """Statement of optimism."""

    hidden = True

    @display_command
    def run(self):
        print "it sure does!"


class cmd_find_merge_base(Command):
    """Find and print a base revision for merging two branches."""
    # TODO: Options to specify revisions on either side, as if
    #       merging only part of the history.
    takes_args = ['branch', 'other']
    hidden = True
    
    @display_command
    def run(self, branch, other):
        from bzrlib.revision import common_ancestor, MultipleRevisionSources
        
        branch1 = Branch.open_containing(branch)[0]
        branch2 = Branch.open_containing(other)[0]

        history_1 = branch1.revision_history()
        history_2 = branch2.revision_history()

        last1 = branch1.last_revision()
        last2 = branch2.last_revision()

        source = MultipleRevisionSources(branch1.repository, 
                                         branch2.repository)
        
        base_rev_id = common_ancestor(last1, last2, source)

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

    Examples:

    To merge the latest revision from bzr.dev
    bzr merge ../bzr.dev

    To merge changes up to and including revision 82 from bzr.dev
    bzr merge -r 82 ../bzr.dev

    To merge the changes introduced by 82, without previous changes:
    bzr merge -r 81..82 ../bzr.dev
    
    merge refuses to run if there are any uncommitted changes, unless
    --force is given.

    The following merge types are available:
    """
    takes_args = ['branch?']
    takes_options = ['revision', 'force', 'merge-type', 'reprocess', 'remember',
                     Option('show-base', help="Show base revision text in "
                            "conflicts")]

    def help(self):
        from merge import merge_type_help
        from inspect import getdoc
        return getdoc(self) + '\n' + merge_type_help() 

    def run(self, branch=None, revision=None, force=False, merge_type=None,
            show_base=False, reprocess=False, remember=False):
        if merge_type is None:
            merge_type = Merge3Merger

        tree = WorkingTree.open_containing(u'.')[0]

        if branch is not None:
            try:
                reader = bundle.read_bundle_from_url(branch)
            except NotABundle:
                pass # Continue on considering this url a Branch
            else:
                conflicts = merge_bundle(reader, tree, not force, merge_type,
                                            reprocess, show_base)
                if conflicts == 0:
                    return 0
                else:
                    return 1

        branch = self._get_remembered_parent(tree, branch, 'Merging from')

        if revision is None or len(revision) < 1:
            base = [None, None]
            other = [branch, -1]
            other_branch, path = Branch.open_containing(branch)
        else:
            if len(revision) == 1:
                base = [None, None]
                other_branch, path = Branch.open_containing(branch)
                revno = revision[0].in_history(other_branch).revno
                other = [branch, revno]
            else:
                assert len(revision) == 2
                if None in revision:
                    raise BzrCommandError(
                        "Merge doesn't permit that revision specifier.")
                other_branch, path = Branch.open_containing(branch)

                base = [branch, revision[0].in_history(other_branch).revno]
                other = [branch, revision[1].in_history(other_branch).revno]

        if tree.branch.get_parent() is None or remember:
            tree.branch.set_parent(other_branch.base)

        if path != "":
            interesting_files = [path]
        else:
            interesting_files = None
        pb = ui.ui_factory.nested_progress_bar()
        try:
            try:
                conflict_count = merge(other, base, check_clean=(not force),
                                       merge_type=merge_type,
                                       reprocess=reprocess,
                                       show_base=show_base,
                                       pb=pb, file_list=interesting_files)
            finally:
                pb.finished()
            if conflict_count != 0:
                return 1
            else:
                return 0
        except errors.AmbiguousBase, e:
            m = ("sorry, bzr can't determine the right merge base yet\n"
                 "candidates are:\n  "
                 + "\n  ".join(e.bases)
                 + "\n"
                 "please specify an explicit base with -r,\n"
                 "and (if you want) report this to the bzr developers\n")
            log_error(m)

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
            raise BzrCommandError("No location specified or remembered")
        display_url = urlutils.unescape_for_display(stored_location, self.outf.encoding)
        self.outf.write("%s remembered location %s\n" % (verb_string, display_url))
        return stored_location


class cmd_remerge(Command):
    """Redo a merge.

    Use this if you want to try a different merge technique while resolving
    conflicts.  Some merge techniques are better than others, and remerge 
    lets you try different ones on different files.

    The options for remerge have the same meaning and defaults as the ones for
    merge.  The difference is that remerge can (only) be run when there is a
    pending merge, and it lets you specify particular files.

    Examples:
    $ bzr remerge --show-base
        Re-do the merge of all conflicted files, and show the base text in
        conflict regions, in addition to the usual THIS and OTHER texts.

    $ bzr remerge --merge-type weave --reprocess foobar
        Re-do the merge of "foobar", using the weave merge algorithm, with
        additional processing to reduce the size of conflict regions.
    
    The following merge types are available:"""
    takes_args = ['file*']
    takes_options = ['merge-type', 'reprocess',
                     Option('show-base', help="Show base revision text in "
                            "conflicts")]

    def help(self):
        from merge import merge_type_help
        from inspect import getdoc
        return getdoc(self) + '\n' + merge_type_help() 

    def run(self, file_list=None, merge_type=None, show_base=False,
            reprocess=False):
        from bzrlib.merge import merge_inner, transform_tree
        if merge_type is None:
            merge_type = Merge3Merger
        tree, file_list = tree_files(file_list)
        tree.lock_write()
        try:
            pending_merges = tree.pending_merges() 
            if len(pending_merges) != 1:
                raise BzrCommandError("Sorry, remerge only works after normal"
                                      " merges.  Not cherrypicking or"
                                      " multi-merges.")
            repository = tree.branch.repository
            base_revision = common_ancestor(tree.branch.last_revision(), 
                                            pending_merges[0], repository)
            base_tree = repository.revision_tree(base_revision)
            other_tree = repository.revision_tree(pending_merges[0])
            interesting_ids = None
            new_conflicts = []
            conflicts = tree.conflicts()
            if file_list is not None:
                interesting_ids = set()
                for filename in file_list:
                    file_id = tree.path2id(filename)
                    if file_id is None:
                        raise NotVersionedError(filename)
                    interesting_ids.add(file_id)
                    if tree.kind(file_id) != "directory":
                        continue
                    
                    for name, ie in tree.inventory.iter_entries(file_id):
                        interesting_ids.add(ie.file_id)
                new_conflicts = conflicts.select_conflicts(tree, file_list)[0]
            transform_tree(tree, tree.basis_tree(), interesting_ids)
            tree.set_conflicts(ConflictList(new_conflicts))
            if file_list is None:
                restore_files = list(tree.iter_conflicts())
            else:
                restore_files = file_list
            for filename in restore_files:
                try:
                    restore(tree.abspath(filename))
                except NotConflicted:
                    pass
            conflicts = merge_inner(tree.branch, other_tree, base_tree,
                                    this_tree=tree,
                                    interesting_ids=interesting_ids, 
                                    other_rev_id=pending_merges[0], 
                                    merge_type=merge_type, 
                                    show_base=show_base,
                                    reprocess=reprocess)
        finally:
            tree.unlock()
        if conflicts > 0:
            return 1
        else:
            return 0

class cmd_revert(Command):
    """Reverse all changes since the last commit.

    Only versioned files are affected.  Specify filenames to revert only 
    those files.  By default, any files that are changed will be backed up
    first.  Backup files have a '~' appended to their name.
    """
    takes_options = ['revision', 'no-backup']
    takes_args = ['file*']
    aliases = ['merge-revert']

    def run(self, revision=None, no_backup=False, file_list=None):
        from bzrlib.commands import parse_spec
        if file_list is not None:
            if len(file_list) == 0:
                raise BzrCommandError("No files specified")
        else:
            file_list = []
        
        tree, file_list = tree_files(file_list)
        if revision is None:
            # FIXME should be tree.last_revision
            rev_id = tree.last_revision()
        elif len(revision) != 1:
            raise BzrCommandError('bzr revert --revision takes exactly 1 argument')
        else:
            rev_id = revision[0].in_history(tree.branch).rev_id
        pb = ui.ui_factory.nested_progress_bar()
        try:
            tree.revert(file_list, 
                        tree.branch.repository.revision_tree(rev_id),
                        not no_backup, pb)
        finally:
            pb.finished()


class cmd_assert_fail(Command):
    """Test reporting of assertion failures"""
    hidden = True
    def run(self):
        assert False, "always fails"


class cmd_help(Command):
    """Show help on a command or other topic.

    For a list of all available commands, say 'bzr help commands'."""
    takes_options = [Option('long', 'show help on all commands')]
    takes_args = ['topic?']
    aliases = ['?', '--help', '-?', '-h']
    
    @display_command
    def run(self, topic=None, long=False):
        import help
        if topic is None and long:
            topic = "commands"
        help.help(topic)


class cmd_shell_complete(Command):
    """Show appropriate completions for context.

    For a list of all available commands, say 'bzr shell-complete'."""
    takes_args = ['context?']
    aliases = ['s-c']
    hidden = True
    
    @display_command
    def run(self, context=None):
        import shellcomplete
        shellcomplete.shellcomplete(context)


class cmd_fetch(Command):
    """Copy in history from another branch but don't merge it.

    This is an internal method used for pull and merge."""
    hidden = True
    takes_args = ['from_branch', 'to_branch']
    def run(self, from_branch, to_branch):
        from bzrlib.fetch import Fetcher
        from_b = Branch.open(from_branch)
        to_b = Branch.open(to_branch)
        Fetcher(to_b, from_b)


class cmd_missing(Command):
    """Show unmerged/unpulled revisions between two branches.

    OTHER_BRANCH may be local or remote."""
    takes_args = ['other_branch?']
    takes_options = [Option('reverse', 'Reverse the order of revisions'),
                     Option('mine-only', 
                            'Display changes in the local branch only'),
                     Option('theirs-only', 
                            'Display changes in the remote branch only'), 
                     'log-format',
                     'line',
                     'long', 
                     'short',
                     'show-ids',
                     'verbose'
                     ]
    encoding_type = 'replace'

    @display_command
    def run(self, other_branch=None, reverse=False, mine_only=False,
            theirs_only=False, log_format=None, long=False, short=False, line=False, 
            show_ids=False, verbose=False):
        from bzrlib.missing import find_unmerged, iter_log_data
        from bzrlib.log import log_formatter
        local_branch = Branch.open_containing(u".")[0]
        parent = local_branch.get_parent()
        if other_branch is None:
            other_branch = parent
            if other_branch is None:
                raise BzrCommandError("No peer location known or specified.")
            print "Using last location: " + local_branch.get_parent()
        remote_branch = Branch.open(other_branch)
        if remote_branch.base == local_branch.base:
            remote_branch = local_branch
        local_branch.lock_read()
        try:
            remote_branch.lock_read()
            try:
                local_extra, remote_extra = find_unmerged(local_branch, remote_branch)
                if (log_format == None):
                    default = local_branch.get_config().log_format()
                    log_format = get_log_format(long=long, short=short, 
                                                line=line, default=default)
                lf = log_formatter(log_format,
                                   to_file=self.outf,
                                   show_ids=show_ids,
                                   show_timezone='original')
                if reverse is False:
                    local_extra.reverse()
                    remote_extra.reverse()
                if local_extra and not theirs_only:
                    print "You have %d extra revision(s):" % len(local_extra)
                    for data in iter_log_data(local_extra, local_branch.repository,
                                              verbose):
                        lf.show(*data)
                    printed_local = True
                else:
                    printed_local = False
                if remote_extra and not mine_only:
                    if printed_local is True:
                        print "\n\n"
                    print "You are missing %d revision(s):" % len(remote_extra)
                    for data in iter_log_data(remote_extra, remote_branch.repository, 
                                              verbose):
                        lf.show(*data)
                if not remote_extra and not local_extra:
                    status_code = 0
                    print "Branches are up to date."
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


class cmd_plugins(Command):
    """List plugins"""
    hidden = True
    @display_command
    def run(self):
        import bzrlib.plugin
        from inspect import getdoc
        for name, plugin in bzrlib.plugin.all_plugins().items():
            if hasattr(plugin, '__path__'):
                print plugin.__path__[0]
            elif hasattr(plugin, '__file__'):
                print plugin.__file__
            else:
                print `plugin`
                
            d = getdoc(plugin)
            if d:
                print '\t', d.split('\n')[0]


class cmd_testament(Command):
    """Show testament (signing-form) of a revision."""
    takes_options = ['revision', 'long', 
                     Option('strict', help='Produce a strict-format'
                            ' testament')]
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
    takes_options = [Option('all', help='show annotations on all lines'),
                     Option('long', help='show date in annotations'),
                     'revision'
                     ]

    @display_command
    def run(self, filename, all=False, long=False, revision=None):
        from bzrlib.annotate import annotate_file
        tree, relpath = WorkingTree.open_containing(filename)
        branch = tree.branch
        branch.lock_read()
        try:
            if revision is None:
                revision_id = branch.last_revision()
            elif len(revision) != 1:
                raise BzrCommandError('bzr annotate --revision takes exactly 1 argument')
            else:
                revision_id = revision[0].in_history(branch).rev_id
            file_id = tree.inventory.path2id(relpath)
            tree = branch.repository.revision_tree(revision_id)
            file_version = tree.inventory[file_id].revision
            annotate_file(branch, file_version, file_id, long, all, sys.stdout)
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
            raise BzrCommandError('You can only supply one of revision_id or --revision')
        if revision_id_list is None and revision is None:
            raise BzrCommandError('You must supply either --revision or a revision_id')
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
                    raise BzrCommandError('Cannot sign a range of non-revision-history revisions')
                for revno in range(from_revno, to_revno + 1):
                    b.repository.sign_revision(b.get_rev_id(revno), 
                                               gpg_strategy)
            else:
                raise BzrCommandError('Please supply either one revision, or a range.')


class cmd_bind(Command):
    """Bind the current branch to a master branch.

    After binding, commits must succeed on the master branch
    before they are executed on the local one.
    """

    takes_args = ['location']
    takes_options = []

    def run(self, location=None):
        b, relpath = Branch.open_containing(u'.')
        b_other = Branch.open(location)
        try:
            b.bind(b_other)
        except DivergedBranches:
            raise BzrCommandError('These branches have diverged.'
                                  ' Try merging, and then bind again.')


class cmd_unbind(Command):
    """Unbind the current branch from its master branch.

    After unbinding, the local branch is considered independent.
    All subsequent commits will be local.
    """

    takes_args = []
    takes_options = []

    def run(self):
        b, relpath = Branch.open_containing(u'.')
        if not b.unbind():
            raise BzrCommandError('Local branch is not bound')


class cmd_uncommit(Command):
    """Remove the last committed revision.

    --verbose will print out what is being removed.
    --dry-run will go through all the motions, but not actually
    remove anything.
    
    In the future, uncommit will create a revision bundle, which can then
    be re-applied.
    """

    # TODO: jam 20060108 Add an option to allow uncommit to remove
    # unreferenced information in 'branch-as-repository' branches.
    # TODO: jam 20060108 Add the ability for uncommit to remove unreferenced
    # information in shared branches as well.
    takes_options = ['verbose', 'revision',
                    Option('dry-run', help='Don\'t actually make changes'),
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
    
    example:
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
        


# command-line interpretation helper for merge-related commands
def merge(other_revision, base_revision,
          check_clean=True, ignore_zero=False,
          this_dir=None, backup_files=False, merge_type=Merge3Merger,
          file_list=None, show_base=False, reprocess=False,
          pb=DummyProgress()):
    """Merge changes into a tree.

    base_revision
        list(path, revno) Base for three-way merge.  
        If [None, None] then a base will be automatically determined.
    other_revision
        list(path, revno) Other revision for three-way merge.
    this_dir
        Directory to merge changes into; '.' by default.
    check_clean
        If true, this_dir must have no uncommitted changes before the
        merge begins.
    ignore_zero - If true, suppress the "zero conflicts" message when 
        there are no conflicts; should be set when doing something we expect
        to complete perfectly.
    file_list - If supplied, merge only changes to selected files.

    All available ancestors of other_revision and base_revision are
    automatically pulled into the branch.

    The revno may be -1 to indicate the last revision on the branch, which is
    the typical case.

    This function is intended for use from the command line; programmatic
    clients might prefer to call merge.merge_inner(), which has less magic 
    behavior.
    """
    from bzrlib.merge import Merger
    if this_dir is None:
        this_dir = u'.'
    this_tree = WorkingTree.open_containing(this_dir)[0]
    if show_base and not merge_type is Merge3Merger:
        raise BzrCommandError("Show-base is not supported for this merge"
                              " type. %s" % merge_type)
    if reprocess and not merge_type.supports_reprocess:
        raise BzrCommandError("Conflict reduction is not supported for merge"
                              " type %s." % merge_type)
    if reprocess and show_base:
        raise BzrCommandError("Cannot do conflict reduction and show base.")
    try:
        merger = Merger(this_tree.branch, this_tree=this_tree, pb=pb)
        merger.pp = ProgressPhase("Merge phase", 5, pb)
        merger.pp.next_phase()
        merger.check_basis(check_clean)
        merger.set_other(other_revision)
        merger.pp.next_phase()
        merger.set_base(base_revision)
        if merger.base_rev_id == merger.other_rev_id:
            note('Nothing to do.')
            return 0
        merger.backup_files = backup_files
        merger.merge_type = merge_type 
        merger.set_interesting_files(file_list)
        merger.show_base = show_base 
        merger.reprocess = reprocess
        conflicts = merger.do_merge()
        if file_list is None:
            merger.set_pending()
    finally:
        pb.clear()
    return conflicts


# these get imported and then picked up by the scan for cmd_*
# TODO: Some more consistent way to split command definitions across files;
# we do need to load at least some information about them to know of 
# aliases.  ideally we would avoid loading the implementation until the
# details were needed.
from bzrlib.conflicts import cmd_resolve, cmd_conflicts, restore
from bzrlib.bundle.commands import cmd_bundle_revisions
from bzrlib.sign_my_commits import cmd_sign_my_commits
from bzrlib.weave_commands import cmd_weave_list, cmd_weave_join, \
        cmd_weave_plan_merge, cmd_weave_merge_text
