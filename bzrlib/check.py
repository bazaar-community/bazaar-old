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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

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

"""Checking of bzr objects.

check_refs is a concept used for optimising check. Objects that depend on other
objects (e.g. tree on repository) can list the objects they would be requesting
so that when the dependent object is checked, matches can be pulled out and
evaluated in-line rather than re-reading the same data many times.
check_refs are tuples (kind, value). Currently defined kinds are:
* 'trees', where value is a revid and the looked up objects are revision trees.
* 'lefthand-distance', where value is a revid and the looked up objects are the
  distance along the lefthand path to NULL for that revid.
* 'revision-existence', where value is a revid, and the result is True or False
  indicating that the revision was found/not found.
"""

from bzrlib import errors, osutils
from bzrlib import repository as _mod_repository
from bzrlib import revision
from bzrlib.branch import Branch
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import BzrCheckError
from bzrlib.repository import Repository
from bzrlib.revision import NULL_REVISION
from bzrlib.symbol_versioning import deprecated_function, deprecated_in
from bzrlib.trace import log_error, note
import bzrlib.ui
from bzrlib.workingtree import WorkingTree

class Check(object):
    """Check a repository"""

    # The Check object interacts with InventoryEntry.check, etc.

    def __init__(self, repository, check_repo=True):
        self.repository = repository
        self.checked_text_cnt = 0
        self.checked_rev_cnt = 0
        self.ghosts = set()
        self.repeated_text_cnt = 0
        self.missing_parent_links = {}
        self.missing_inventory_sha_cnt = 0
        self.missing_revision_cnt = 0
        # maps (file-id, version) -> sha1; used by InventoryFile._check
        self.checked_texts = {}
        self.checked_weaves = set()
        self.unreferenced_versions = set()
        self.inconsistent_parents = []
        self.rich_roots = repository.supports_rich_root()
        self.text_key_references = {}
        self.check_repo = check_repo
        self.other_results = []
        # Plain text lines to include in the report
        self._report_items = []
        # Sha1 expectations; may be large and need spilling to disk.
        # key->(sha1, first-referer)
        self.expected_sha1 = {}
        # Ancestors map for all of revisions being checked; while large helper
        # functions we call would create it anyway, so better to have once and
        # keep.
        self.ancestors = {}

    def check(self, callback_refs=None, check_repo=True):
        if callback_refs is None:
            callback_refs = {}
        self.repository.lock_read()
        self.progress = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            if self.check_repo:
                self.progress.update('retrieving inventory', 0, 2)
                # do not put in init, as it should be done with progess,
                # and inside the lock.
                self.inventory_weave = self.repository.inventories
                self.progress.update('checking revision graph', 1)
                self.check_revision_graph()
                self.plan_revisions()
                revno = 0
                while revno < len(self.planned_revisions):
                    rev_id = self.planned_revisions[revno]
                    self.progress.update('checking revision', revno,
                                         len(self.planned_revisions))
                    revno += 1
                    self._check_revision_tree(rev_id)
                # check_weaves is done after the revision scan so that
                # revision index is known to be valid.
                self.check_weaves()
            if callback_refs:
                repo = self.repository
                # calculate all refs, and callback the objects requesting them.
                refs = {}
                wanting_items = set()
                # Current crude version calculates everything and calls
                # everything at once. Doing a queue and popping as things are
                # satisfied would be cheaper on memory [but few people have
                # huge numbers of working trees today. TODO: fix before
                # landing].
                distances = set()
                existences = set()
                for ref, wantlist in callback_refs.iteritems():
                    wanting_items.update(wantlist)
                    kind, value = ref
                    if kind == 'trees':
                        refs[ref] = repo.revision_tree(value)
                    elif kind == 'lefthand-distance':
                        distances.add(value)
                    elif kind == 'revision-existence':
                        existences.add(value)
                    else:
                        raise AssertionError(
                            'unknown ref kind for ref %s' % ref)
                node_distances = repo.get_graph().find_lefthand_distances(distances)
                for key, distance in node_distances.iteritems():
                    refs[('lefthand-distance', key)] = distance
                    if key in existences and distance > 0:
                        refs[('revision-existence', key)] = True
                        existences.remove(key)
                parent_map = repo.get_graph().get_parent_map(existences)
                for key in parent_map:
                    refs[('revision-existence', key)] = True
                    existences.remove(key)
                for key in existences:
                    refs[('revision-existence', key)] = False
                for item in wanting_items:
                    if isinstance(item, WorkingTree):
                        item._check(refs)
                    if isinstance(item, Branch):
                        self.other_results.append(item.check(refs))
        finally:
            self.progress.finished()
            self.repository.unlock()

    def check_revisions(self, revisions_iterator):
        """Check revision objects by decorating a generator.

        :param revisions_iterator: An iterator of(revid, Revision-or-None).
        :return: A generator of the contents of revisions_iterator.
        """
        self.planned_revisions = set()
        for revid, revision in revisions_iterator:
            yield revid, revision
            self._check_one_rev(revid, revision)

    def check_revision_graph(self):
        revision_iterator = self.repository._iter_revisions(None)
        revision_iterator = self.check_revisions(revision_iterator)
        # We read the all revisions here:
        # - doing this allows later code to depend on the revision index.
        # - we can fill out existence flags at this point
        # - we can read the revision inventory sha at this point
        # - we can check properties and serialisers etc.
        if not self.repository.revision_graph_can_have_wrong_parents():
            # The check against the index isn't needed.
            self.revs_with_bad_parents_in_index = None
            for thing in revision_iterator:
                pass
        else:
            bad_revisions = self.repository._find_inconsistent_revision_parents(
                revision_iterator)
            self.revs_with_bad_parents_in_index = list(bad_revisions)

    def plan_revisions(self):
        repository = self.repository
        self.planned_revisions = repository.all_revision_ids()
        self.progress.clear()
        inventoried = set(key[-1] for key in self.inventory_weave.keys())
        awol = set(self.planned_revisions) - inventoried
        if len(awol) > 0:
            raise BzrCheckError('Stored revisions missing from inventory'
                '{%s}' % ','.join([f for f in awol]))

    def report_results(self, verbose):
        if self.check_repo:
            self._report_repo_results(verbose)
        for result in self.other_results:
            result.report_results(verbose)

    def _report_repo_results(self, verbose):
        note('checked repository %s format %s',
             self.repository.bzrdir.root_transport,
             self.repository._format)
        note('%6d revisions', self.checked_rev_cnt)
        note('%6d file-ids', len(self.checked_weaves))
        note('%6d unique file texts', self.checked_text_cnt)
        note('%6d repeated file texts', self.repeated_text_cnt)
        if verbose:
            note('%6d unreferenced text versions',
                len(self.unreferenced_versions))
        if verbose and len(self.unreferenced_versions):
                for file_id, revision_id in self.unreferenced_versions:
                    log_error('unreferenced version: {%s} in %s', revision_id,
                        file_id)
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
        if len(self.inconsistent_parents):
            note('%6d inconsistent parents', len(self.inconsistent_parents))
            if verbose:
                for info in self.inconsistent_parents:
                    revision_id, file_id, found_parents, correct_parents = info
                    note('      * %s version %s has parents %r '
                         'but should have %r'
                         % (file_id, revision_id, found_parents,
                             correct_parents))
        if self.revs_with_bad_parents_in_index:
            note('%6d revisions have incorrect parents in the revision index',
                 len(self.revs_with_bad_parents_in_index))
            if verbose:
                for item in self.revs_with_bad_parents_in_index:
                    revision_id, index_parents, actual_parents = item
                    note(
                        '       %s has wrong parents in index: '
                        '%r should be %r',
                        revision_id, index_parents, actual_parents)
        for item in self._report_items:
            note(item)

    def _check_one_rev(self, rev_id, rev):
        """Cross-check one revision.

        :param rev_id: A revision id to check.
        :param rev: A revision or None to indicate a missing revision.
        """
        if rev.revision_id != rev_id:
            self._report_items.append(
                'Mismatched internal revid {%s} and index revid {%s}' % (
                rev.revision_id, rev_id))
            rev_id = rev.revision_id
        # Check this revision tree etc, and count as seen when we encounter a
        # reference to it.
        self.planned_revisions.add(rev_id)
        # It is not a ghost
        self.ghosts.discard(rev_id)
        # Count all parents as ghosts if we haven't seen them yet.
        for parent in rev.parent_ids:
            if not parent in self.planned_revisions:
                self.ghosts.add(parent)
        
        self.ancestors[rev_id] = tuple(rev.parent_ids) or (NULL_REVISION,)
        # If the revision has an inventory sha, we want to cross check it later.
        if rev.inventory_sha1:
            self.add_sha_check(rev_id, ('inventories', rev_id),
            rev.inventory_sha1)
        self.checked_rev_cnt += 1

    def add_sha_check(self, referer, key, sha1):
        """Add a reference to a sha1 to be cross checked against a key.

        :param referer: The referer that expects key to have sha1.
        :param key: A storage key e.g. ('texts', 'foo@bar-20040504-1234')
        :param sha1: A hex sha1.
        """
        existing = self.expected_sha1.get(key)
        if existing:
            if sha1 != existing[0]:
                self._report_items.append('Multiple expected sha1s for %s. {%s}'
                    ' expects {%s}, {%s} expects {%s}', (
                    key, referer, sha1, existing[1], existing[0]))
        else:
            self.expected_sha1[key] = (sha1, referer)

    def check_weaves(self):
        """Check all the weaves we can get our hands on.
        """
        weave_ids = []
        self.progress.update('checking inventory', 0, 2)
        self.inventory_weave.check(progress_bar=self.progress)
        self.progress.update('checking text storage', 1, 2)
        self.repository.texts.check(progress_bar=self.progress)
        weave_checker = self.repository._get_versioned_file_checker(
            text_key_references=self.text_key_references,
            ancestors=self.ancestors)
        result = weave_checker.check_file_version_parents(
            self.repository.texts, progress_bar=self.progress)
        self.checked_weaves = weave_checker.file_ids
        bad_parents, unused_versions = result
        bad_parents = bad_parents.items()
        for text_key, (stored_parents, correct_parents) in bad_parents:
            # XXX not ready for id join/split operations.
            weave_id = text_key[0]
            revision_id = text_key[-1]
            weave_parents = tuple([parent[-1] for parent in stored_parents])
            correct_parents = tuple([parent[-1] for parent in correct_parents])
            self.inconsistent_parents.append(
                (revision_id, weave_id, weave_parents, correct_parents))
        self.unreferenced_versions.update(unused_versions)

    def _check_revision_tree(self, rev_id):
        tree = self.repository.revision_tree(rev_id)
        inv = tree.inventory
        seen_ids = set()
        seen_names = set()
        for path, ie in inv.iter_entries():
            self._add_entry_to_text_key_references(inv, ie)
            file_id = ie.file_id
            if file_id in seen_ids:
                raise BzrCheckError('duplicated file_id {%s} '
                                    'in inventory for revision {%s}'
                                    % (file_id, rev_id))
            seen_ids.add(file_id)
            ie.check(self, rev_id, inv, tree)
            if path in seen_names:
                raise BzrCheckError('duplicated path %s '
                                    'in inventory for revision {%s}'
                                    % (path, rev_id))
            seen_names.add(path)

    def _add_entry_to_text_key_references(self, inv, entry):
        if not self.rich_roots and entry == inv.root:
            return
        key = (entry.file_id, entry.revision)
        self.text_key_references.setdefault(key, False)
        if entry.revision == inv.revision_id:
            self.text_key_references[key] = True


@deprecated_function(deprecated_in((1,6,0)))
def check(branch, verbose):
    """Run consistency checks on a branch.

    Results are reported through logging.

    Deprecated in 1.6.  Please use check_dwim instead.

    :raise BzrCheckError: if there's a consistency error.
    """
    check_branch(branch, verbose)


@deprecated_function(deprecated_in((1,16,0)))
def check_branch(branch, verbose):
    """Run consistency checks on a branch.

    Results are reported through logging.

    :raise BzrCheckError: if there's a consistency error.
    """
    branch.lock_read()
    try:
        needed_refs = {}
        for ref in branch._get_check_refs():
            needed_refs.setdefault(ref, []).append(branch)
        result = branch.repository.check([branch.last_revision()], needed_refs)
        branch_result = result.other_results[0]
    finally:
        branch.unlock()
    branch_result.report_results(verbose)


def scan_branch(branch, needed_refs, to_unlock):
    """Scan a branch for refs.

    :param branch:  The branch to schedule for checking.
    :param needed_refs: Refs we are accumulating.
    :param to_unlock: The unlock list accumulating.
    """
    note("Checking branch at '%s'." % (branch.base,))
    branch.lock_read()
    to_unlock.append(branch)
    branch_refs = branch._get_check_refs()
    for ref in branch_refs:
        reflist = needed_refs.setdefault(ref, [])
        reflist.append(branch)


def scan_tree(base_tree, tree, needed_refs, to_unlock):
    """Scan a tree for refs.

    :param base_tree: The original tree check opened, used to detect duplicate
        tree checks.
    :param tree:  The tree to schedule for checking.
    :param needed_refs: Refs we are accumulating.
    :param to_unlock: The unlock list accumulating.
    """
    if base_tree is not None and tree.basedir == base_tree.basedir:
        return
    note("Checking working tree at '%s'." % (tree.basedir,))
    tree.lock_read()
    to_unlock.append(tree)
    tree_refs = tree._get_check_refs()
    for ref in tree_refs:
        reflist = needed_refs.setdefault(ref, [])
        reflist.append(tree)


def check_dwim(path, verbose, do_branch=False, do_repo=False, do_tree=False):
    try:
        base_tree, branch, repo, relpath = \
                        BzrDir.open_containing_tree_branch_or_repository(path)
    except errors.NotBranchError:
        base_tree = branch = repo = None

    to_unlock = []
    needed_refs= {}
    try:
        if base_tree is not None:
            # If the tree is a lightweight checkout we won't see it in
            # repo.find_branches - add now.
            if do_tree:
                scan_tree(None, base_tree, needed_refs, to_unlock)
            branch = base_tree.branch
        if branch is not None:
            # We have a branch
            if repo is None:
                # The branch is in a shared repository
                repo = branch.repository
        if repo is not None:
            repo.lock_read()
            to_unlock.append(repo)
            branches = repo.find_branches(using=True)
            saw_tree = False
            if do_branch or do_tree:
                for branch in branches:
                    if do_tree:
                        try:
                            tree = branch.bzrdir.open_workingtree()
                            saw_tree = True
                        except (errors.NotLocalUrl, errors.NoWorkingTree):
                            pass
                        else:
                            scan_tree(base_tree, tree, needed_refs, to_unlock)
                    if do_branch:
                        scan_branch(branch, needed_refs, to_unlock)
            if do_branch and not branches:
                log_error("No branch found at specified location.")
            if do_tree and base_tree is None and not saw_tree:
                log_error("No working tree found at specified location.")
            if do_repo or do_branch or do_tree:
                if do_repo:
                    note("Checking repository at '%s'."
                         % (repo.bzrdir.root_transport.base,))
                result = repo.check(None, callback_refs=needed_refs,
                    check_repo=do_repo)
                result.report_results(verbose)
        else:
            if do_tree:
                log_error("No working tree found at specified location.")
            if do_branch:
                log_error("No branch found at specified location.")
            if do_repo:
                log_error("No repository found at specified location.")
    finally:
        for thing in to_unlock:
            thing.unlock()
