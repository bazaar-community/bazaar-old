# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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

import sys

from bzrlib import (
    delta as _mod_delta,
    osutils,
    tree,
    tsort,
    revision as _mod_revision,
    )
from bzrlib.diff import _raise_if_nonexistent
import bzrlib.errors as errors
from bzrlib.log import line_log
from bzrlib.osutils import is_inside_any
from bzrlib.symbol_versioning import (deprecated_function,
        )
from bzrlib.trace import warning

# TODO: when showing single-line logs, truncate to the width of the terminal
# if known, but only if really going to the terminal (not into a file)


def show_tree_status(wt, show_unchanged=None,
                     specific_files=None,
                     show_ids=False,
                     to_file=None,
                     show_pending=True,
                     revision=None,
                     short=False,
                     versioned=False):
    """Display summary of changes.

    By default this compares the working tree to a previous revision. 
    If the revision argument is given, summarizes changes between the 
    working tree and another, or between two revisions.

    The result is written out as Unicode and to_file should be able 
    to encode that.

    If showing the status of a working tree, extra information is included
    about unknown files, conflicts, and pending merges.

    :param show_unchanged: Deprecated parameter. If set, includes unchanged 
        files.
    :param specific_files: If set, a list of filenames whose status should be
        shown.  It is an error to give a filename that is not in the working 
        tree, or in the working inventory or in the basis inventory.
    :param show_ids: If set, includes each file's id.
    :param to_file: If set, write to this file (default stdout.)
    :param show_pending: If set, write pending merges.
    :param revision: If None the compare latest revision with working tree
        If not None it must be a RevisionSpec list.
        If one revision show compared it with working tree.
        If two revisions show status between first and second.
    :param short: If True, gives short SVN-style status lines.
    :param versioned: If True, only shows versioned files.
    """
    if show_unchanged is not None:
        warn("show_status_trees with show_unchanged has been deprecated "
             "since bzrlib 0.9", DeprecationWarning, stacklevel=2)

    if to_file is None:
        to_file = sys.stdout
    
    wt.lock_read()
    try:
        new_is_working_tree = True
        if revision is None:
            if wt.last_revision() != wt.branch.last_revision():
                warning("working tree is out of date, run 'bzr update'")
            new = wt
            old = new.basis_tree()
        elif len(revision) > 0:
            try:
                rev_id = revision[0].in_history(wt.branch).rev_id
                old = wt.branch.repository.revision_tree(rev_id)
            except errors.NoSuchRevision, e:
                raise errors.BzrCommandError(str(e))
            if (len(revision) > 1) and (revision[1].spec is not None):
                try:
                    rev_id = revision[1].in_history(wt.branch).rev_id
                    new = wt.branch.repository.revision_tree(rev_id)
                    new_is_working_tree = False
                except errors.NoSuchRevision, e:
                    raise errors.BzrCommandError(str(e))
            else:
                new = wt
        old.lock_read()
        new.lock_read()
        try:
            _raise_if_nonexistent(specific_files, old, new)
            want_unversioned = not versioned
            if short:
                changes = new._iter_changes(old, show_unchanged, specific_files,
                    require_versioned=False, want_unversioned=want_unversioned)
                reporter = _mod_delta._ChangeReporter(output_file=to_file,
                    unversioned_filter=new.is_ignored)
                _mod_delta.report_changes(changes, reporter)
            else:
                delta = new.changes_from(old, want_unchanged=show_unchanged,
                                      specific_files=specific_files,
                                      want_unversioned=want_unversioned)
                # filter out unknown files. We may want a tree method for
                # this
                delta.unversioned = [unversioned for unversioned in
                    delta.unversioned if not new.is_ignored(unversioned[0])]
                delta.show(to_file,
                           show_ids=show_ids,
                           show_unchanged=show_unchanged,
                           short_status=False)
            # show the new conflicts only for now. XXX: get them from the
            # delta.
            conflicts = new.conflicts()
            if specific_files is not None:
                conflicts = conflicts.select_conflicts(new, specific_files,
                    ignore_misses=True, recurse=True)[1]
            if len(conflicts) > 0 and not short:
                to_file.write("conflicts:\n")
            for conflict in conflicts:
                if short:
                    prefix = 'C  '
                else:
                    prefix = ' '
                to_file.write("%s %s\n" % (prefix, conflict))
            if new_is_working_tree and show_pending:
                show_pending_merges(new, to_file, short)
        finally:
            old.unlock()
            new.unlock()
    finally:
        wt.unlock()

def show_pending_merges(new, to_file, short=False):
    """Write out a display of pending merges in a working tree."""
    parents = new.get_parent_ids()
    if len(parents) < 2:
        return
    pending = parents[1:]
    branch = new.branch
    last_revision = parents[0]
    if not short:
        to_file.write('pending merges:\n')
    ignore = set([None, last_revision, _mod_revision.NULL_REVISION])
    graph = branch.repository.get_graph()
    for merge in pending:
        # Find all of the revisions in the merge source, which are not in the
        # last committed revision.
        # We don't care about last_extra
        last_extra, merge_extra = graph.find_difference(last_revision, merge)
        # Now that we have the revisions, we need to sort them to get a proper
        # listing. We want to sort in reverse topological order (which
        # MergeSorter gives us). MergeSorter requires that there are no
        # dangling references, though, so clean up the graph to point to only
        # present nodes.
        merge_extra.discard(_mod_revision.NULL_REVISION)
        merged_graph = {}
        for merge, parents in zip(merge_extra, graph.get_parents(merge_extra)):
            if parents is None: # The revision does not exist in the repository
                merged_graph[merge] = []
            else:
                merged_graph[merge] = [p for p in parents if p in merge_extra]
        sorter = tsort.MergeSorter(merged_graph, merge)
        # Get a handle to all of the revisions we will need
        width = osutils.terminal_width()
        try:
            revisions = dict((rev.revision_id, rev) for rev in
                             branch.repository.get_revisions(merge_extra))
        except errors.NoSuchRevision:
            # If we are missing a revision, just print out the revision id
            if short:
                prefix = 'P  '
            else:
                prefix = ' '
            to_file.write(prefix + ' ' + merge)
            to_file.write('\n')
        else:
            rev_id_iterator = sorter.iter_topo_order()
            num, first, depth, eom = rev_id_iterator.next()
            assert first == merge
            m_revision = revisions[merge]
            if short:
                prefix = 'P  '
            else:
                prefix = ' '
            to_file.write(prefix + ' ' + line_log(m_revision, width - 4))
            to_file.write('\n')
            for num, mmerge, depth, eom in rev_id_iterator:
                if mmerge in ignore:
                    continue
                mm_revision = revisions[mmerge]
                if short:
                    prefix = 'P.  '
                else:
                    prefix = '   '
                to_file.write(prefix + ' ' + line_log(mm_revision, width - 5))
                to_file.write('\n')
        ignore.update(merge_extra)
