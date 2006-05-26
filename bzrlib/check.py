# Copyright (C) 2005, 2006 by Canonical Ltd

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

# TODO: Check ancestries are correct for every revision: includes
# every committed so far, and in a reasonable order.

# TODO: Also check non-mainline revisions mentioned as parents.

# TODO: Check for extra files in the control directory.

# TODO: Check revision, inventory and entry objects have all 
# required fields.

# TODO: Get every revision in the revision-store even if they're not
# referenced by history and make sure they're all valid.

# TODO: Perhaps have a way to record errors other than by raising exceptions;
# would perhaps be enough to accumulate exception objects in a list without
# raising them.  If there's more than one exception it'd be good to see them
# all.

from bzrlib.errors import BzrCheckError, NoSuchRevision
from bzrlib.symbol_versioning import *
from bzrlib.trace import mutter, note, warning
import bzrlib.ui


class Check(object):
    """Check a repository"""

    # The Check object interacts with InventoryEntry.check, etc.

    def __init__(self, repository):
        self.repository = repository
        self.checked_text_cnt = 0
        self.checked_rev_cnt = 0
        self.ghosts = []
        self.repeated_text_cnt = 0
        self.missing_parent_links = {}
        self.missing_inventory_sha_cnt = 0
        self.missing_revision_cnt = 0
        # maps (file-id, version) -> sha1; used by InventoryFile._check
        self.checked_texts = {}
        self.checked_weaves = {}

    def check(self):
        self.repository.lock_read()
        self.progress = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            self.progress.update('retrieving inventory', 0, 0)
            # do not put in init, as it should be done with progess,
            # and inside the lock.
            self.inventory_weave = self.repository.get_inventory_weave()
            self.plan_revisions()
            revno = 0
            self.check_weaves()
            while revno < len(self.planned_revisions):
                rev_id = self.planned_revisions[revno]
                self.progress.update('checking revision', revno,
                                     len(self.planned_revisions))
                revno += 1
                self.check_one_rev(rev_id)
        finally:
            self.progress.finished()
            self.repository.unlock()

    def plan_revisions(self):
        repository = self.repository
        self.planned_revisions = set(repository.all_revision_ids())
        self.progress.clear()
        inventoried = set(self.inventory_weave.versions())
        awol = self.planned_revisions - inventoried
        if len(awol) > 0:
            raise BzrCheckError('Stored revisions missing from inventory'
                '{%s}' % ','.join([f for f in awol]))
        self.planned_revisions = list(self.planned_revisions)

    def report_results(self, verbose):
        note('checked repository %s format %s',
             self.repository.bzrdir.root_transport,
             self.repository._format)
        note('%6d revisions', self.checked_rev_cnt)
        note('%6d unique file texts', self.checked_text_cnt)
        note('%6d repeated file texts', self.repeated_text_cnt)
        note('%6d weaves', len(self.checked_weaves))
        if self.missing_inventory_sha_cnt:
            note('%6d revisions are missing inventory_sha1',
                 self.missing_inventory_sha_cnt)
        if self.missing_revision_cnt:
            note('%6d revisions are mentioned but not present',
                 self.missing_revision_cnt)
        if len(self.ghosts):
            note('%6d ghost revisions', len(self.ghosts))
            if verbose:
                for ghost in self.ghosts:
                    note('      %s', ghost)
        if len(self.missing_parent_links):
            note('%6d revisions missing parents in ancestry',
                 len(self.missing_parent_links))
            if verbose:
                for link, linkers in self.missing_parent_links.items():
                    note('      %s should be in the ancestry for:', link)
                    for linker in linkers:
                        note('       * %s', linker)

    def check_one_rev(self, rev_id):
        """Check one revision.

        rev_id - the one to check
        """
        rev = self.repository.get_revision(rev_id)
                
        if rev.revision_id != rev_id:
            raise BzrCheckError('wrong internal revision id in revision {%s}'
                                % rev_id)

        for parent in rev.parent_ids:
            if not parent in self.planned_revisions:
                missing_links = self.missing_parent_links.get(parent, [])
                missing_links.append(rev_id)
                self.missing_parent_links[parent] = missing_links
                # list based so somewhat slow,
                # TODO have a planned_revisions list and set.
                if self.repository.has_revision(parent):
                    missing_ancestry = self.repository.get_ancestry(parent)
                    for missing in missing_ancestry:
                        if (missing is not None 
                            and missing not in self.planned_revisions):
                            self.planned_revisions.append(missing)
                else:
                    self.ghosts.append(rev_id)

        if rev.inventory_sha1:
            inv_sha1 = self.repository.get_inventory_sha1(rev_id)
            if inv_sha1 != rev.inventory_sha1:
                raise BzrCheckError('Inventory sha1 hash doesn\'t match'
                    ' value in revision {%s}' % rev_id)
        else:
            missing_inventory_sha_cnt += 1
            mutter("no inventory_sha1 on revision {%s}", rev_id)
        self._check_revision_tree(rev_id)
        self.checked_rev_cnt += 1

    def check_weaves(self):
        """Check all the weaves we can get our hands on.
        """
        n_weaves = 1
        weave_ids = []
        if self.repository.weave_store.listable():
            weave_ids = list(self.repository.weave_store)
            n_weaves = len(weave_ids)
        self.progress.update('checking weave', 0, n_weaves)
        self.inventory_weave.check(progress_bar=self.progress)
        for i, weave_id in enumerate(weave_ids):
            self.progress.update('checking weave', i, n_weaves)
            w = self.repository.weave_store.get_weave(weave_id,
                    self.repository.get_transaction())
            # No progress here, because it looks ugly.
            w.check()
            self.checked_weaves[weave_id] = True

    def _check_revision_tree(self, rev_id):
        tree = self.repository.revision_tree(rev_id)
        inv = tree.inventory
        seen_ids = {}
        for file_id in inv:
            if file_id in seen_ids:
                raise BzrCheckError('duplicated file_id {%s} '
                                    'in inventory for revision {%s}'
                                    % (file_id, rev_id))
            seen_ids[file_id] = True
        for file_id in inv:
            ie = inv[file_id]
            ie.check(self, rev_id, inv, tree)
        seen_names = {}
        for path, ie in inv.iter_entries():
            if path in seen_names:
                raise BzrCheckError('duplicated path %s '
                                    'in inventory for revision {%s}'
                                    % (path, rev_id))
            seen_names[path] = True


def check(branch, verbose):
    """Run consistency checks on a branch.
    
    Results are reported through logging.
    
    :raise BzrCheckError: if there's a consistency error.
    """
    branch.lock_read()
    try:
        branch_result = branch.check()
        repo_result = branch.repository.check([branch.last_revision()])
    finally:
        branch.unlock()
    branch_result.report_results(verbose)
    repo_result.report_results(verbose)
