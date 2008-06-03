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

"""Reconcilers are able to fix some potential data errors in a branch."""


__all__ = [
    'KnitReconciler',
    'PackReconciler',
    'reconcile',
    'Reconciler',
    'RepoReconciler',
    ]


from bzrlib import (
    errors,
    ui,
    repository,
    repofmt,
    )
from bzrlib.trace import mutter, note
from bzrlib.tsort import TopoSorter


def reconcile(dir, other=None):
    """Reconcile the data in dir.

    Currently this is limited to a inventory 'reweave'.

    This is a convenience method, for using a Reconciler object.

    Directly using Reconciler is recommended for library users that
    desire fine grained control or analysis of the found issues.

    :param other: another bzrdir to reconcile against.
    """
    reconciler = Reconciler(dir, other=other)
    reconciler.reconcile()


class Reconciler(object):
    """Reconcilers are used to reconcile existing data."""

    def __init__(self, dir, other=None):
        """Create a Reconciler."""
        self.bzrdir = dir

    def reconcile(self):
        """Perform reconciliation.
        
        After reconciliation the following attributes document found issues:
        inconsistent_parents: The number of revisions in the repository whose
                              ancestry was being reported incorrectly.
        garbage_inventories: The number of inventory objects without revisions
                             that were garbage collected.
        fixed_branch_history: None if there was no branch, False if the branch
                              history was correct, True if the branch history
                              needed to be re-normalized.
        """
        self.pb = ui.ui_factory.nested_progress_bar()
        try:
            self._reconcile()
        finally:
            self.pb.finished()

    def _reconcile(self):
        """Helper function for performing reconciliation."""
        self._reconcile_branch()
        self._reconcile_repository()

    def _reconcile_branch(self):
        try:
            self.branch = self.bzrdir.open_branch()
        except errors.NotBranchError:
            # Nothing to check here
            self.fixed_branch_history = None
            return
        self.pb.note('Reconciling branch %s',
                     self.branch.base)
        branch_reconciler = self.branch.reconcile(thorough=True)
        self.fixed_branch_history = branch_reconciler.fixed_history

    def _reconcile_repository(self):
        self.repo = self.bzrdir.find_repository()
        self.pb.note('Reconciling repository %s',
                     self.repo.bzrdir.root_transport.base)
        self.pb.update("Reconciling repository", 0, 1)
        repo_reconciler = self.repo.reconcile(thorough=True)
        self.inconsistent_parents = repo_reconciler.inconsistent_parents
        self.garbage_inventories = repo_reconciler.garbage_inventories
        if repo_reconciler.aborted:
            self.pb.note(
                'Reconcile aborted: revision index has inconsistent parents.')
            self.pb.note(
                'Run "bzr check" for more details.')
        else:
            self.pb.note('Reconciliation complete.')


class BranchReconciler(object):
    """Reconciler that works on a branch."""

    def __init__(self, a_branch, thorough=False):
        self.fixed_history = None
        self.thorough = thorough
        self.branch = a_branch

    def reconcile(self):
        self.branch.lock_write()
        try:
            self.pb = ui.ui_factory.nested_progress_bar()
            try:
                self._reconcile_steps()
            finally:
                self.pb.finished()
        finally:
            self.branch.unlock()

    def _reconcile_steps(self):
        self._reconcile_revision_history()

    def _reconcile_revision_history(self):
        repo = self.branch.repository
        last_revno, last_revision_id = self.branch.last_revision_info()
        real_history = list(repo.iter_reverse_revision_history(
                                last_revision_id))
        real_history.reverse()
        if last_revno != len(real_history):
            self.fixed_history = True
            # Technically for Branch5 formats, it is more efficient to use
            # set_revision_history, as this will regenerate it again.
            # Not really worth a whole BranchReconciler class just for this,
            # though.
            self.pb.note('Fixing last revision info %s => %s',
                         last_revno, len(real_history))
            self.branch.set_last_revision_info(len(real_history),
                                               last_revision_id)
        else:
            self.fixed_history = False
            self.pb.note('revision_history ok.')


class RepoReconciler(object):
    """Reconciler that reconciles a repository.

    The goal of repository reconciliation is to make any derived data
    consistent with the core data committed by a user. This can involve 
    reindexing, or removing unreferenced data if that can interfere with
    queries in a given repository.

    Currently this consists of an inventory reweave with revision cross-checks.
    """

    def __init__(self, repo, other=None, thorough=False):
        """Construct a RepoReconciler.

        :param thorough: perform a thorough check which may take longer but
                         will correct non-data loss issues such as incorrect
                         cached data.
        """
        self.garbage_inventories = 0
        self.inconsistent_parents = 0
        self.aborted = False
        self.repo = repo
        self.thorough = thorough

    def reconcile(self):
        """Perform reconciliation.
        
        After reconciliation the following attributes document found issues:
        inconsistent_parents: The number of revisions in the repository whose
                              ancestry was being reported incorrectly.
        garbage_inventories: The number of inventory objects without revisions
                             that were garbage collected.
        """
        self.repo.lock_write()
        try:
            self.pb = ui.ui_factory.nested_progress_bar()
            try:
                self._reconcile_steps()
            finally:
                self.pb.finished()
        finally:
            self.repo.unlock()

    def _reconcile_steps(self):
        """Perform the steps to reconcile this repository."""
        self._reweave_inventory()

    def _reweave_inventory(self):
        """Regenerate the inventory weave for the repository from scratch.
        
        This is a smart function: it will only do the reweave if doing it 
        will correct data issues. The self.thorough flag controls whether
        only data-loss causing issues (!self.thorough) or all issues
        (self.thorough) are treated as requiring the reweave.
        """
        # local because needing to know about WeaveFile is a wart we want to hide
        from bzrlib.weave import WeaveFile, Weave
        transaction = self.repo.get_transaction()
        self.pb.update('Reading inventory data.')
        self.inventory = self.repo.get_inventory_weave()
        # the total set of revisions to process
        self.pending = set([rev_id for rev_id in self.repo._revision_store.all_revision_ids(transaction)])

        # mapping from revision_id to parents
        self._rev_graph = {}
        # errors that we detect
        self.inconsistent_parents = 0
        # we need the revision id of each revision and its available parents list
        self._setup_steps(len(self.pending))
        for rev_id in self.pending:
            # put a revision into the graph.
            self._graph_revision(rev_id)
        self._check_garbage_inventories()
        # if there are no inconsistent_parents and 
        # (no garbage inventories or we are not doing a thorough check)
        if (not self.inconsistent_parents and 
            (not self.garbage_inventories or not self.thorough)):
            self.pb.note('Inventory ok.')
            return
        self.pb.update('Backing up inventory...', 0, 0)
        self.repo.control_weaves.copy(self.inventory, 'inventory.backup', self.repo.get_transaction())
        self.pb.note('Backup Inventory created.')
        # asking for '' should never return a non-empty weave
        new_inventory_vf = self.repo.control_weaves.get_empty('inventory.new',
            self.repo.get_transaction())

        # we have topological order of revisions and non ghost parents ready.
        self._setup_steps(len(self._rev_graph))
        for rev_id in TopoSorter(self._rev_graph.items()).iter_topo_order():
            parents = self._rev_graph[rev_id]
            # double check this really is in topological order.
            unavailable = [p for p in parents if p not in new_inventory_vf]
            if unavailable:
                raise AssertionError('unavailable parents: %r'
                    % unavailable)
            # this entry has all the non ghost parents in the inventory
            # file already.
            self._reweave_step('adding inventories')
            if isinstance(new_inventory_vf, WeaveFile):
                # It's really a WeaveFile, but we call straight into the
                # Weave's add method to disable the auto-write-out behaviour.
                # This is done to avoid a revision_count * time-to-write additional overhead on 
                # reconcile.
                new_inventory_vf._check_write_ok()
                Weave._add_lines(new_inventory_vf, rev_id, parents,
                    self.inventory.get_lines(rev_id), None, None, None, False, True)
            else:
                new_inventory_vf.add_lines(rev_id, parents, self.inventory.get_lines(rev_id))

        if isinstance(new_inventory_vf, WeaveFile):
            new_inventory_vf._save()
        # if this worked, the set of new_inventory_vf.names should equal
        # self.pending
        if not (set(new_inventory_vf.versions()) == self.pending):
            raise AssertionError()
        self.pb.update('Writing weave')
        self.repo.control_weaves.copy(new_inventory_vf, 'inventory', self.repo.get_transaction())
        self.repo.control_weaves.delete('inventory.new', self.repo.get_transaction())
        self.inventory = None
        self.pb.note('Inventory regenerated.')

    def _setup_steps(self, new_total):
        """Setup the markers we need to control the progress bar."""
        self.total = new_total
        self.count = 0

    def _graph_revision(self, rev_id):
        """Load a revision into the revision graph."""
        # pick a random revision
        # analyse revision id rev_id and put it in the stack.
        self._reweave_step('loading revisions')
        rev = self.repo.get_revision_reconcile(rev_id)
        parents = []
        for parent in rev.parent_ids:
            if self._parent_is_available(parent):
                parents.append(parent)
            else:
                mutter('found ghost %s', parent)
        self._rev_graph[rev_id] = parents
        if self._parents_are_inconsistent(rev_id, parents):
            self.inconsistent_parents += 1
            mutter('Inconsistent inventory parents: id {%s} '
                   'inventory claims %r, '
                   'available parents are %r, '
                   'unavailable parents are %r',
                   rev_id,
                   set(self.inventory.get_parent_map([rev_id])[rev_id]),
                   set(parents),
                   set(rev.parent_ids).difference(set(parents)))

    def _parents_are_inconsistent(self, rev_id, parents):
        """Return True if the parents list of rev_id does not match the weave.

        This detects inconsistencies based on the self.thorough value:
        if thorough is on, the first parent value is checked as well as ghost
        differences.
        Otherwise only the ghost differences are evaluated.
        """
        weave_parents = self.inventory.get_parent_map([rev_id])[rev_id]
        weave_missing_old_ghosts = set(weave_parents) != set(parents)
        first_parent_is_wrong = (
            len(weave_parents) and len(parents) and
            parents[0] != weave_parents[0])
        if self.thorough:
            return weave_missing_old_ghosts or first_parent_is_wrong
        else:
            return weave_missing_old_ghosts

    def _check_garbage_inventories(self):
        """Check for garbage inventories which we cannot trust

        We cant trust them because their pre-requisite file data may not
        be present - all we know is that their revision was not installed.
        """
        if not self.thorough:
            return
        inventories = set(self.inventory.versions())
        revisions = set(self._rev_graph.keys())
        garbage = inventories.difference(revisions)
        self.garbage_inventories = len(garbage)
        for revision_id in garbage:
            mutter('Garbage inventory {%s} found.', revision_id)

    def _parent_is_available(self, parent):
        """True if parent is a fully available revision

        A fully available revision has a inventory and a revision object in the
        repository.
        """
        return (parent in self._rev_graph or 
                (parent in self.inventory and self.repo.has_revision(parent)))

    def _reweave_step(self, message):
        """Mark a single step of regeneration complete."""
        self.pb.update(message, self.count, self.total)
        self.count += 1


class KnitReconciler(RepoReconciler):
    """Reconciler that reconciles a knit format repository.

    This will detect garbage inventories and remove them in thorough mode.
    """

    def _reconcile_steps(self):
        """Perform the steps to reconcile this repository."""
        if self.thorough:
            try:
                self._load_indexes()
            except errors.BzrCheckError:
                self.aborted = True
                return
            # knits never suffer this
            self._gc_inventory()
            self._fix_text_parents()

    def _load_indexes(self):
        """Load indexes for the reconciliation."""
        self.transaction = self.repo.get_transaction()
        self.pb.update('Reading indexes.', 0, 2)
        self.inventory = self.repo.get_inventory_weave()
        self.pb.update('Reading indexes.', 1, 2)
        self.repo._check_for_inconsistent_revision_parents()
        self.revisions = self.repo._revision_store.get_revision_file(self.transaction)
        self.pb.update('Reading indexes.', 2, 2)

    def _gc_inventory(self):
        """Remove inventories that are not referenced from the revision store."""
        self.pb.update('Checking unused inventories.', 0, 1)
        self._check_garbage_inventories()
        self.pb.update('Checking unused inventories.', 1, 3)
        if not self.garbage_inventories:
            self.pb.note('Inventory ok.')
            return
        self.pb.update('Backing up inventory...', 0, 0)
        self.repo.control_weaves.copy(self.inventory, 'inventory.backup', self.transaction)
        self.pb.note('Backup Inventory created.')
        # asking for '' should never return a non-empty weave
        new_inventory_vf = self.repo.control_weaves.get_empty('inventory.new',
            self.transaction)

        # we have topological order of revisions and non ghost parents ready.
        self._setup_steps(len(self.revisions))
        revision_ids = self.revisions.versions()
        graph = self.revisions.get_parent_map(revision_ids)
        for rev_id in TopoSorter(graph.items()).iter_topo_order():
            parents = graph[rev_id]
            # double check this really is in topological order, ignoring existing ghosts.
            unavailable = [p for p in parents if p not in new_inventory_vf and
                p in self.revisions]
            if unavailable:
                raise AssertionError(
                    'unavailable parents: %r' % (unavailable,))
            # this entry has all the non ghost parents in the inventory
            # file already.
            self._reweave_step('adding inventories')
            # ugly but needed, weaves are just way tooooo slow else.
            new_inventory_vf.add_lines_with_ghosts(rev_id, parents,
                self.inventory.get_lines(rev_id))

        # if this worked, the set of new_inventory_vf.names should equal
        # self.pending
        if not(set(new_inventory_vf.versions()) == set(self.revisions.versions())):
            raise AssertionError()
        self.pb.update('Writing weave')
        self.repo.control_weaves.copy(new_inventory_vf, 'inventory', self.transaction)
        self.repo.control_weaves.delete('inventory.new', self.transaction)
        self.inventory = None
        self.pb.note('Inventory regenerated.')

    def _check_garbage_inventories(self):
        """Check for garbage inventories which we cannot trust

        We cant trust them because their pre-requisite file data may not
        be present - all we know is that their revision was not installed.
        """
        inventories = set(self.inventory.versions())
        revisions = set(self.revisions.versions())
        garbage = inventories.difference(revisions)
        self.garbage_inventories = len(garbage)
        for revision_id in garbage:
            mutter('Garbage inventory {%s} found.', revision_id)

    def _fix_text_parents(self):
        """Fix bad versionedfile parent entries.

        It is possible for the parents entry in a versionedfile entry to be
        inconsistent with the values in the revision and inventory.

        This method finds entries with such inconsistencies, corrects their
        parent lists, and replaces the versionedfile with a corrected version.
        """
        transaction = self.repo.get_transaction()
        versions = self.revisions.versions()
        mutter('Prepopulating revision text cache with %d revisions',
                len(versions))
        vf_checker = self.repo._get_versioned_file_checker()
        # List all weaves before altering, to avoid race conditions when we
        # delete unused weaves.
        weaves = list(enumerate(self.repo.weave_store))
        for num, file_id in weaves:
            self.pb.update('Fixing text parents', num,
                           len(self.repo.weave_store))
            vf = self.repo.weave_store.get_weave(file_id, transaction)
            versions_with_bad_parents, unused_versions = \
                vf_checker.check_file_version_parents(vf, file_id)
            if (len(versions_with_bad_parents) == 0 and
                len(unused_versions) == 0):
                continue
            full_text_versions = set()
            self._fix_text_parent(file_id, vf, versions_with_bad_parents,
                full_text_versions, unused_versions)

    def _fix_text_parent(self, file_id, vf, versions_with_bad_parents,
            full_text_versions, unused_versions):
        """Fix bad versionedfile entries in a single versioned file."""
        mutter('fixing text parent: %r (%d versions)', file_id,
                len(versions_with_bad_parents))
        mutter('(%d need to be full texts, %d are unused)',
                len(full_text_versions), len(unused_versions))
        new_vf = self.repo.weave_store.get_empty('temp:%s' % file_id,
            self.transaction)
        new_parents = {}
        for version in vf.versions():
            if version in unused_versions:
                continue
            elif version in versions_with_bad_parents:
                parents = versions_with_bad_parents[version][1]
            else:
                parents = vf.get_parent_map([version])[version]
            new_parents[version] = parents
        if not len(new_parents):
            # No used versions, remove the VF.
            self.repo.weave_store.delete(file_id, self.transaction)
            return
        for version in TopoSorter(new_parents.items()).iter_topo_order():
            lines = vf.get_lines(version)
            parents = new_parents[version]
            if parents and (parents[0] in full_text_versions):
                # Force this record to be a fulltext, not a delta.
                new_vf._add(version, lines, parents, False,
                    None, None, None, False)
            else:
                new_vf.add_lines(version, parents, lines)
        self.repo.weave_store.copy(new_vf, file_id, self.transaction)
        self.repo.weave_store.delete('temp:%s' % file_id, self.transaction)


class PackReconciler(RepoReconciler):
    """Reconciler that reconciles a pack based repository.

    Garbage inventories do not affect ancestry queries, and removal is
    considerably more expensive as there is no separate versioned file for
    them, so they are not cleaned. In short it is currently a no-op.

    In future this may be a good place to hook in annotation cache checking,
    index recreation etc.
    """

    # XXX: The index corruption that _fix_text_parents performs is needed for
    # packs, but not yet implemented. The basic approach is to:
    #  - lock the names list
    #  - perform a customised pack() that regenerates data as needed
    #  - unlock the names list
    # https://bugs.edge.launchpad.net/bzr/+bug/154173

    def _reconcile_steps(self):
        """Perform the steps to reconcile this repository."""
        if not self.thorough:
            return
        collection = self.repo._pack_collection
        collection.ensure_loaded()
        collection.lock_names()
        try:
            packs = collection.all_packs()
            all_revisions = self.repo.all_revision_ids()
            total_inventories = len(list(
                collection.inventory_index.combined_index.iter_all_entries()))
            if len(all_revisions):
                self._packer = repofmt.pack_repo.ReconcilePacker(
                    collection, packs, ".reconcile", all_revisions)
                new_pack = self._packer.pack(pb=self.pb)
                if new_pack is not None:
                    self._discard_and_save(packs)
            else:
                # only make a new pack when there is data to copy.
                self._discard_and_save(packs)
            self.garbage_inventories = total_inventories - len(list(
                collection.inventory_index.combined_index.iter_all_entries()))
        finally:
            collection._unlock_names()

    def _discard_and_save(self, packs):
        """Discard some packs from the repository.

        This removes them from the memory index, saves the in-memory index
        which makes the newly reconciled pack visible and hides the packs to be
        discarded, and finally renames the packs being discarded into the
        obsolete packs directory.

        :param packs: The packs to discard.
        """
        for pack in packs:
            self.repo._pack_collection._remove_pack_from_memory(pack)
        self.repo._pack_collection._save_pack_names()
        self.repo._pack_collection._obsolete_packs(packs)
