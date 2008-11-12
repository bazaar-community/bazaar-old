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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Foreign branch utilities."""

from bzrlib.branch import Branch
from bzrlib.commands import Command, Option
from bzrlib.revision import Revision
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    errors,
    registry,
    )
""")

class VcsMapping(object):
    """Describes the mapping between the semantics of Bazaar and a foreign vcs.

    """
    # Whether this is an experimental mapping that is still open to changes.
    experimental = False

    # Whether this mapping supports exporting and importing all bzr semantics.
    roundtripping = False

    # Prefix used when importing native foreign revisions (not roundtripped) 
    # using this mapping.
    revid_prefix = None

    def revision_id_bzr_to_foreign(self, bzr_revid):
        """Parse a bzr revision id and convert it to a foreign revid.

        :param bzr_revid: The bzr revision id (a string).
        :return: A foreign revision id, can be any sort of object.
        """
        raise NotImplementedError(self.revision_id_bzr_to_foreign)

    def revision_id_foreign_to_bzr(self, foreign_revid):
        """Parse a foreign revision id and convert it to a bzr revid.

        :param foreign_revid: Foreign revision id, can be any sort of object.
        :return: A bzr revision id.
        """
        raise NotImplementedError(self.revision_id_foreign_to_bzr)

    def show_foreign_revid(self, foreign_revid):
        """Prepare a foreign revision id for formatting using bzr log.
        
        :param foreign_revid: Foreign revision id.
        :return: Dictionary mapping string keys to string values.
        """
        # TODO: This could be on ForeignVcs instead
        return { }


class VcsMappingRegistry(registry.Registry):
    """Registry for Bazaar<->foreign VCS mappings.
    
    There should be one instance of this registry for every foreign VCS.
    """

    def register(self, key, factory, help):
        """Register a mapping between Bazaar and foreign VCS semantics.

        The factory must be a callable that takes one parameter: the key.
        It must produce an instance of VcsMapping when called.
        """
        if ":" in key:
            raise ValueError("mapping name can not contain colon (:)")
        registry.Registry.register(self, key, factory, help)

    def set_default(self, key):
        """Set the 'default' key to be a clone of the supplied key.

        This method must be called once and only once.
        """
        self._set_default_key(key)

    def get_default(self):
        """Convenience function for obtaining the default mapping to use."""
        return self.get(self._get_default_key())

    def revision_id_bzr_to_foreign(self, revid):
        """Convert a bzr revision id to a foreign revid."""
        raise NotImplementedError(self.revision_id_bzr_to_foreign)


class ForeignBranch(Branch):
    """Branch that exists in a foreign version control system."""

    def __init__(self, mapping):
        super(ForeignBranch, self).__init__()
        self.mapping = mapping

    def dpull(self, source, stop_revision=None):
        """Pull deltas from another branch.

        :note: This does not, like pull, retain the revision ids from 
        the source branch and will, rather than adding bzr-specific metadata,
        push only those semantics of the revision that can be natively 
        represented in this branch.

        :param source: Source branch
        :param stop_revision: Revision to pull, defaults to last revision.
        """
        raise NotImplementedError(self.pull)


class cmd_dpush(Command):
    """Push diffs into a foreign version control system without any 
    Bazaar-specific metadata.

    This will afterwards rebase the local Bazaar branch on the remote
    branch unless the --no-rebase option is used, in which case 
    the two branches will be out of sync. 
    """
    takes_args = ['location?']
    takes_options = ['remember', Option('directory',
            help='Branch to push from, '
                 'rather than the one containing the working directory.',
            short_name='d',
            type=unicode,
            ),
            Option('no-rebase', help="Don't rebase after push")]

    def run(self, location=None, remember=False, directory=None, 
            no_rebase=False):
        from bzrlib import urlutils
        from bzrlib.bzrdir import BzrDir
        from bzrlib.errors import BzrCommandError, NoWorkingTree
        from bzrlib.trace import info
        from bzrlib.workingtree import WorkingTree

        if directory is None:
            directory = "."
        try:
            source_wt = WorkingTree.open_containing(directory)[0]
            source_branch = source_wt.branch
        except NoWorkingTree:
            source_branch = Branch.open_containing(directory)[0]
            source_wt = None
        stored_loc = source_branch.get_push_location()
        if location is None:
            if stored_loc is None:
                raise BzrCommandError("No push location known or specified.")
            else:
                display_url = urlutils.unescape_for_display(stored_loc,
                        self.outf.encoding)
                self.outf.write("Using saved location: %s\n" % display_url)
                location = stored_loc

        bzrdir = BzrDir.open(location)
        target_branch = bzrdir.open_branch()
        target_branch.lock_write()
        if not isinstance(target_branch, ForeignBranch):
            info("target branch is not a foreign branch, using regular push.")
            target_branch.pull(source_branch)
            no_rebase = True
        else:
            revid_map = target_branch.dpull(source_branch)
        # We successfully created the target, remember it
        if source_branch.get_push_location() is None or remember:
            source_branch.set_push_location(target_branch.base)
        if not no_rebase:
            _, old_last_revid = source_branch.last_revision_info()
            new_last_revid = revid_map[old_last_revid]
            if source_wt is not None:
                source_wt.pull(target_branch, overwrite=True, 
                               stop_revision=new_last_revid)
            else:
                source_branch.pull(target_branch, overwrite=True, 
                                   stop_revision=new_last_revid)


class ForeignRevision(Revision):
    """A Revision from a Foreign repository. Remembers 
    information about foreign revision id and mapping.

    """

    def __init__(self, foreign_revid, mapping, *args, **kwargs):
        super(ForeignRevision, self).__init__(*args, **kwargs)
        self.foreign_revid = foreign_revid
        self.mapping = mapping


def show_foreign_properties(rev):
    """Custom log displayer for foreign revision identifiers.

    :param rev: Revision object.
    """
    # Revision comes directly from a foreign repository
    if isinstance(rev, ForeignRevision):
        return rev.mapping.show_foreign_revid(rev.foreign_revid)

    # Revision was once imported from a foreign repository
    try:
        foreign_revid, mapping = \
            foreign_vcs_registry.parse_revision_id(rev.revision_id)
    except errors.InvalidRevisionId:
        return {}

    return mapping.show_foreign_revid(foreign_revid)


class ForeignVcs(object):
    """A foreign version control system."""

    def __init__(self, mapping_registry):
        self.mapping_registry = mapping_registry


class ForeignVcsRegistry(registry.Registry):
    """Registry for Foreign VCSes.

    There should be one entry per foreign VCS. Example entries would be 
    "git", "svn", "hg", "darcs", etc.
    
    """

    def register(self, key, foreign_vcs, help):
        """Register a foreign VCS.

        :param key: Prefix of the foreign VCS in revision ids
        :param foreign_vcs: ForeignVCS instance
        :param help: Description of the foreign VCS
        """
        if ":" in key or "-" in key:
            raise ValueError("vcs name can not contain : or -")
        registry.Registry.register(self, key, foreign_vcs, help)

    def parse_revision_id(self, revid):
        """Parse a bzr revision and return the matching mapping and foreign 
        revid.
        
        :param revid: The bzr revision id
        :return: tuple with foreign revid and vcs mapping
        """
        if not "-" in revid:
            raise errors.InvalidRevisionId(revid, None)
        try:
            foreign_vcs = self.get(revid.split("-")[0])
        except KeyError:
            raise errors.InvalidRevisionId(revid, None)
        return foreign_vcs.mapping_registry.revision_id_bzr_to_foreign(revid)


foreign_vcs_registry = ForeignVcsRegistry()
