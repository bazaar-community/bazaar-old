# Copyright (C) 2005, 2006 Canonical Ltd
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


"""Copying of history from one branch to another.

The basic plan is that every branch knows the history of everything
that has merged into it.  As the first step of a merge, pull, or
branch operation we copy history from the source into the destination
branch.

The copying is done in a slightly complicated order.  We don't want to
add a revision to the store until everything it refers to is also
stored, so that if a revision is present we can totally recreate it.
However, we can't know what files are included in a revision until we
read its inventory.  So we query the inventory store of the source for
the ids we need, and then pull those ids and finally actually join
the inventories.
"""

import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import (InstallFailed,
                           )
from bzrlib.progress import ProgressPhase
from bzrlib.revision import NULL_REVISION
from bzrlib.symbol_versioning import (deprecated_function,
        deprecated_method,
        zero_eight,
        )
from bzrlib.trace import mutter
import bzrlib.ui

from bzrlib.lazy_import import lazy_import

# TODO: Avoid repeatedly opening weaves so many times.

# XXX: This doesn't handle ghost (not present in branch) revisions at
# all yet.  I'm not sure they really should be supported.

# NOTE: This doesn't copy revisions which may be present but not
# merged into the last revision.  I'm not sure we want to do that.

# - get a list of revisions that need to be pulled in
# - for each one, pull in that revision file
#   and get the inventory, and store the inventory with right
#   parents.
# - and get the ancestry, and store that with right parents too
# - and keep a note of all file ids and version seen
# - then go through all files; for each one get the weave,
#   and add in all file versions


@deprecated_function(zero_eight)
def greedy_fetch(to_branch, from_branch, revision=None, pb=None):
    """Legacy API, please see branch.fetch(from_branch, last_revision, pb)."""
    f = Fetcher(to_branch, from_branch, revision, pb)
    return f.count_copied, f.failed_revisions

fetch = greedy_fetch


class RepoFetcher(object):
    """Pull revisions and texts from one repository to another.

    last_revision
        if set, try to limit to the data this revision references.

    after running:
    count_copied -- number of revisions copied

    This should not be used directory, its essential a object to encapsulate
    the logic in InterRepository.fetch().
    """
    def __init__(self, to_repository, from_repository, last_revision=None, pb=None):
        # result variables.
        self.failed_revisions = []
        self.count_copied = 0
        if to_repository.control_files._transport.base == from_repository.control_files._transport.base:
            # check that last_revision is in 'from' and then return a no-operation.
            if last_revision not in (None, NULL_REVISION):
                from_repository.get_revision(last_revision)
            return
        self.to_repository = to_repository
        self.from_repository = from_repository
        # must not mutate self._last_revision as its potentially a shared instance
        self._last_revision = last_revision
        if pb is None:
            self.pb = bzrlib.ui.ui_factory.nested_progress_bar()
            self.nested_pb = self.pb
        else:
            self.pb = pb
            self.nested_pb = None
        self.from_repository.lock_read()
        try:
            self.to_repository.lock_write()
            try:
                self.to_repository.start_write_group()
                try:
                    self.__fetch()
                except:
                    self.to_repository.abort_write_group()
                    raise
                else:
                    self.to_repository.commit_write_group()
            finally:
                if self.nested_pb is not None:
                    self.nested_pb.finished()
                self.to_repository.unlock()
        finally:
            self.from_repository.unlock()

    def __fetch(self):
        """Primary worker function.

        This initialises all the needed variables, and then fetches the 
        requested revisions, finally clearing the progress bar.
        """
        self.to_weaves = self.to_repository.weave_store
        self.to_control = self.to_repository.control_weaves
        self.from_weaves = self.from_repository.weave_store
        self.from_control = self.from_repository.control_weaves
        self.count_total = 0
        self.file_ids_names = {}
        pp = ProgressPhase('Fetch phase', 4, self.pb)
        try:
            pp.next_phase()
            revs = self._revids_to_fetch()
            # something to do ?
            if revs:
                pp.next_phase()
                self._fetch_weave_texts(revs)
                pp.next_phase()
                self._fetch_inventory_weave(revs)
                pp.next_phase()
                self._fetch_revision_texts(revs)
                self.count_copied += len(revs)
        finally:
            self.pb.clear()

    def _revids_to_fetch(self):
        mutter('fetch up to rev {%s}', self._last_revision)
        if self._last_revision is NULL_REVISION:
            # explicit limit of no revisions needed
            return None
        if (self._last_revision is not None and
            self.to_repository.has_revision(self._last_revision)):
            return None
            
        try:
            return self.to_repository.missing_revision_ids(self.from_repository,
                                                           self._last_revision)
        except errors.NoSuchRevision:
            raise InstallFailed([self._last_revision])

    def _fetch_weave_texts(self, revs):
        texts_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            # fileids_altered_by_revision_ids requires reading the inventory
            # weave, we will need to read the inventory weave again when
            # all this is done, so enable caching for that specific weave
            inv_w = self.from_repository.get_inventory_weave()
            inv_w.enable_cache()
            file_ids = self.from_repository.fileids_altered_by_revision_ids(revs)
            count = 0
            num_file_ids = len(file_ids)
            for file_id, required_versions in file_ids.items():
                texts_pb.update("fetch texts", count, num_file_ids)
                count +=1
                to_weave = self.to_weaves.get_weave_or_empty(file_id,
                    self.to_repository.get_transaction())
                from_weave = self.from_weaves.get_weave(file_id,
                    self.from_repository.get_transaction())
                # we fetch all the texts, because texts do
                # not reference anything, and its cheap enough
                to_weave.join(from_weave, version_ids=required_versions)
                # we don't need *all* of this data anymore, but we dont know
                # what we do. This cache clearing will result in a new read 
                # of the knit data when we do the checkout, but probably we
                # want to emit the needed data on the fly rather than at the
                # end anyhow.
                # the from weave should know not to cache data being joined,
                # but its ok to ask it to clear.
                from_weave.clear_cache()
                to_weave.clear_cache()
        finally:
            texts_pb.finished()

    def _fetch_inventory_weave(self, revs):
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            pb.update("fetch inventory", 0, 2)
            to_weave = self.to_control.get_weave('inventory',
                    self.to_repository.get_transaction())
    
            child_pb = bzrlib.ui.ui_factory.nested_progress_bar()
            try:
                # just merge, this is optimisable and its means we don't
                # copy unreferenced data such as not-needed inventories.
                pb.update("fetch inventory", 1, 3)
                from_weave = self.from_repository.get_inventory_weave()
                pb.update("fetch inventory", 2, 3)
                # we fetch only the referenced inventories because we do not
                # know for unselected inventories whether all their required
                # texts are present in the other repository - it could be
                # corrupt.
                to_weave.join(from_weave, pb=child_pb, msg='merge inventory',
                              version_ids=revs)
                from_weave.clear_cache()
            finally:
                child_pb.finished()
        finally:
            pb.finished()


class GenericRepoFetcher(RepoFetcher):
    """This is a generic repo to repo fetcher.

    This makes minimal assumptions about repo layout and contents.
    It triggers a reconciliation after fetching to ensure integrity.
    """

    def _fetch_revision_texts(self, revs):
        """Fetch revision object texts"""
        rev_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            to_txn = self.to_transaction = self.to_repository.get_transaction()
            count = 0
            total = len(revs)
            to_store = self.to_repository._revision_store
            for rev in revs:
                pb = bzrlib.ui.ui_factory.nested_progress_bar()
                try:
                    pb.update('copying revisions', count, total)
                    try:
                        sig_text = self.from_repository.get_signature_text(rev)
                        to_store.add_revision_signature_text(rev, sig_text, to_txn)
                    except errors.NoSuchRevision:
                        # not signed.
                        pass
                    to_store.add_revision(self.from_repository.get_revision(rev),
                                          to_txn)
                    count += 1
                finally:
                    pb.finished()
            # fixup inventory if needed: 
            # this is expensive because we have no inverse index to current ghosts.
            # but on local disk its a few seconds and sftp push is already insane.
            # so we just-do-it.
            # FIXME: repository should inform if this is needed.
            self.to_repository.reconcile()
        finally:
            rev_pb.finished()
    

class KnitRepoFetcher(RepoFetcher):
    """This is a knit format repository specific fetcher.

    This differs from the GenericRepoFetcher by not doing a 
    reconciliation after copying, and using knit joining to
    copy revision texts.
    """

    def _fetch_revision_texts(self, revs):
        # may need to be a InterRevisionStore call here.
        from_transaction = self.from_repository.get_transaction()
        to_transaction = self.to_repository.get_transaction()
        to_sf = self.to_repository._revision_store.get_signature_file(
            to_transaction)
        from_sf = self.from_repository._revision_store.get_signature_file(
            from_transaction)
        to_sf.join(from_sf, version_ids=revs, ignore_missing=True)
        to_rf = self.to_repository._revision_store.get_revision_file(
            to_transaction)
        from_rf = self.from_repository._revision_store.get_revision_file(
            from_transaction)
        to_rf.join(from_rf, version_ids=revs)


class Inter1and2Helper(object):
    """Helper for operations that convert data from model 1 and 2
    
    This is for use by fetchers and converters.
    """

    def __init__(self, source, target):
        """Constructor.

        :param source: The repository data comes from
        :param target: The repository data goes to
        """
        self.source = source
        self.target = target

    def iter_rev_trees(self, revs):
        """Iterate through RevisionTrees efficiently.

        Additionally, the inventory's revision_id is set if unset.

        Trees are retrieved in batches of 100, and then yielded in the order
        they were requested.

        :param revs: A list of revision ids
        """
        while revs:
            for tree in self.source.revision_trees(revs[:100]):
                if tree.inventory.revision_id is None:
                    tree.inventory.revision_id = tree.get_revision_id()
                yield tree
            revs = revs[100:]

    def generate_root_texts(self, revs):
        """Generate VersionedFiles for all root ids.
        
        :param revs: the revisions to include
        """
        inventory_weave = self.source.get_inventory_weave()
        parent_texts = {}
        versionedfile = {}
        to_store = self.target.weave_store
        for tree in self.iter_rev_trees(revs):
            revision_id = tree.inventory.root.revision
            root_id = tree.inventory.root.file_id
            parents = inventory_weave.get_parents(revision_id)
            if root_id not in versionedfile:
                versionedfile[root_id] = to_store.get_weave_or_empty(root_id, 
                    self.target.get_transaction())
            parent_texts[root_id] = versionedfile[root_id].add_lines(
                revision_id, parents, [], parent_texts)

    def regenerate_inventory(self, revs):
        """Generate a new inventory versionedfile in target, convertin data.
        
        The inventory is retrieved from the source, (deserializing it), and
        stored in the target (reserializing it in a different format).
        :param revs: The revisions to include
        """
        inventory_weave = self.source.get_inventory_weave()
        for tree in self.iter_rev_trees(revs):
            parents = inventory_weave.get_parents(tree.get_revision_id())
            self.target.add_inventory(tree.get_revision_id(), tree.inventory,
                                      parents)


class Model1toKnit2Fetcher(GenericRepoFetcher):
    """Fetch from a Model1 repository into a Knit2 repository
    """
    def __init__(self, to_repository, from_repository, last_revision=None, 
                 pb=None):
        self.helper = Inter1and2Helper(from_repository, to_repository)
        GenericRepoFetcher.__init__(self, to_repository, from_repository,
                                    last_revision, pb)

    def _fetch_weave_texts(self, revs):
        GenericRepoFetcher._fetch_weave_texts(self, revs)
        # Now generate a weave for the tree root
        self.helper.generate_root_texts(revs)

    def _fetch_inventory_weave(self, revs):
        self.helper.regenerate_inventory(revs)
 

class Knit1to2Fetcher(KnitRepoFetcher):
    """Fetch from a Knit1 repository into a Knit2 repository"""

    def __init__(self, to_repository, from_repository, last_revision=None, 
                 pb=None):
        self.helper = Inter1and2Helper(from_repository, to_repository)
        KnitRepoFetcher.__init__(self, to_repository, from_repository,
                                 last_revision, pb)

    def _fetch_weave_texts(self, revs):
        KnitRepoFetcher._fetch_weave_texts(self, revs)
        # Now generate a weave for the tree root
        self.helper.generate_root_texts(revs)

    def _fetch_inventory_weave(self, revs):
        self.helper.regenerate_inventory(revs)
        

class Fetcher(object):
    """Backwards compatibility glue for branch.fetch()."""

    @deprecated_method(zero_eight)
    def __init__(self, to_branch, from_branch, last_revision=None, pb=None):
        """Please see branch.fetch()."""
        to_branch.fetch(from_branch, last_revision, pb)
