# Copyright (C) 2005, 2006, 2007, 2009 Canonical Ltd
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



"""Code to show logs of changes.

Various flavors of log can be produced:

* for one file, or the whole tree, and (not done yet) for
  files in a given directory

* in "verbose" mode with a description of what changed from one
  version to the next

* with file-ids and revision-ids shown

Logs are actually written out through an abstract LogFormatter
interface, which allows for different preferred formats.  Plugins can
register formats too.

Logs can be produced in either forward (oldest->newest) or reverse
(newest->oldest) order.

Logs can be filtered to show only revisions matching a particular
search string, or within a particular range of revisions.  The range
can be given as date/times, which are reduced to revisions before
calling in here.

In verbose mode we show a summary of what changed in each particular
revision.  Note that this is the delta for changes in that revision
relative to its left-most parent, not the delta relative to the last
logged revision.  So for example if you ask for a verbose log of
changes touching hello.c you will get a list of those revisions also
listing other things that were changed in the same revision, but not
all the changes since the previous revision that touched hello.c.
"""

import codecs
from cStringIO import StringIO
from itertools import (
    chain,
    izip,
    )
import re
import sys
from warnings import (
    warn,
    )

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """

from bzrlib import (
    config,
    diff,
    errors,
    repository as _mod_repository,
    revision as _mod_revision,
    revisionspec,
    trace,
    tsort,
    )
""")

from bzrlib import (
    registry,
    )
from bzrlib.osutils import (
    format_date,
    get_terminal_encoding,
    terminal_width,
    )


def find_touching_revisions(branch, file_id):
    """Yield a description of revisions which affect the file_id.

    Each returned element is (revno, revision_id, description)

    This is the list of revisions where the file is either added,
    modified, renamed or deleted.

    TODO: Perhaps some way to limit this to only particular revisions,
    or to traverse a non-mainline set of revisions?
    """
    last_ie = None
    last_path = None
    revno = 1
    for revision_id in branch.revision_history():
        this_inv = branch.repository.get_revision_inventory(revision_id)
        if file_id in this_inv:
            this_ie = this_inv[file_id]
            this_path = this_inv.id2path(file_id)
        else:
            this_ie = this_path = None

        # now we know how it was last time, and how it is in this revision.
        # are those two states effectively the same or not?

        if not this_ie and not last_ie:
            # not present in either
            pass
        elif this_ie and not last_ie:
            yield revno, revision_id, "added " + this_path
        elif not this_ie and last_ie:
            # deleted here
            yield revno, revision_id, "deleted " + last_path
        elif this_path != last_path:
            yield revno, revision_id, ("renamed %s => %s" % (last_path, this_path))
        elif (this_ie.text_size != last_ie.text_size
              or this_ie.text_sha1 != last_ie.text_sha1):
            yield revno, revision_id, "modified " + this_path

        last_ie = this_ie
        last_path = this_path
        revno += 1


def _enumerate_history(branch):
    rh = []
    revno = 1
    for rev_id in branch.revision_history():
        rh.append((revno, rev_id))
        revno += 1
    return rh


def show_log(branch,
             lf,
             specific_fileid=None,
             verbose=False,
             direction='reverse',
             start_revision=None,
             end_revision=None,
             search=None,
             limit=None,
             show_diff=False):
    """Write out human-readable log of commits to this branch.

    :param lf: The LogFormatter object showing the output.

    :param specific_fileid: If not None, list only the commits affecting the
        specified file, rather than all commits.

    :param verbose: If True show added/changed/deleted/renamed files.

    :param direction: 'reverse' (default) is latest to earliest; 'forward' is
        earliest to latest.

    :param start_revision: If not None, only show revisions >= start_revision

    :param end_revision: If not None, only show revisions <= end_revision

    :param search: If not None, only show revisions with matching commit
        messages

    :param limit: If set, shows only 'limit' revisions, all revisions are shown
        if None or 0.

    :param show_diff: If True, output a diff after each revision.
    """
    branch.lock_read()
    try:
        if getattr(lf, 'begin_log', None):
            lf.begin_log()

        _show_log(branch, lf, specific_fileid, verbose, direction,
                  start_revision, end_revision, search, limit, show_diff)

        if getattr(lf, 'end_log', None):
            lf.end_log()
    finally:
        branch.unlock()


def _show_log(branch,
             lf,
             specific_fileid=None,
             verbose=False,
             direction='reverse',
             start_revision=None,
             end_revision=None,
             search=None,
             limit=None,
             show_diff=False):
    """Worker function for show_log - see show_log."""
    if not isinstance(lf, LogFormatter):
        warn("not a LogFormatter instance: %r" % lf)
    if specific_fileid:
        trace.mutter('get log for file_id %r', specific_fileid)

    # Consult the LogFormatter about what it needs and can handle
    levels_to_display = lf.get_levels()
    generate_merge_revisions = levels_to_display != 1
    allow_single_merge_revision = True
    if not getattr(lf, 'supports_merge_revisions', False):
        allow_single_merge_revision = getattr(lf,
            'supports_single_merge_revision', False)
    generate_tags = getattr(lf, 'supports_tags', False)
    if generate_tags and branch.supports_tags():
        rev_tag_dict = branch.tags.get_reverse_tag_dict()
    else:
        rev_tag_dict = {}
    generate_delta = verbose and getattr(lf, 'supports_delta', False)
    generate_diff = show_diff and getattr(lf, 'supports_diff', False)

    # Find and print the interesting revisions
    repo = branch.repository
    log_count = 0
    revision_iterator = _create_log_revision_iterator(branch,
        start_revision, end_revision, direction, specific_fileid, search,
        generate_merge_revisions, allow_single_merge_revision,
        generate_delta, limited_output=limit > 0)
    for revs in revision_iterator:
        for (rev_id, revno, merge_depth), rev, delta in revs:
            # Note: 0 levels means show everything; merge_depth counts from 0
            if levels_to_display != 0 and merge_depth >= levels_to_display:
                continue
            if generate_diff:
                diff = _format_diff(repo, rev, rev_id, specific_fileid)
            else:
                diff = None
            lr = LogRevision(rev, revno, merge_depth, delta,
                             rev_tag_dict.get(rev_id), diff)
            lf.log_revision(lr)
            if limit:
                log_count += 1
                if log_count >= limit:
                    return


def _format_diff(repo, rev, rev_id, specific_fileid):
    if len(rev.parent_ids) == 0:
        ancestor_id = _mod_revision.NULL_REVISION
    else:
        ancestor_id = rev.parent_ids[0]
    tree_1 = repo.revision_tree(ancestor_id)
    tree_2 = repo.revision_tree(rev_id)
    if specific_fileid:
        specific_files = [tree_2.id2path(specific_fileid)]
    else:
        specific_files = None
    s = StringIO()
    diff.show_diff_trees(tree_1, tree_2, s, specific_files, old_label='',
        new_label='')
    return s.getvalue()


class _StartNotLinearAncestor(Exception):
    """Raised when a start revision is not found walking left-hand history."""


def _create_log_revision_iterator(branch, start_revision, end_revision,
    direction, specific_fileid, search, generate_merge_revisions,
    allow_single_merge_revision, generate_delta, limited_output=False):
    """Create a revision iterator for log.

    :param branch: The branch being logged.
    :param start_revision: If not None, only show revisions >= start_revision
    :param end_revision: If not None, only show revisions <= end_revision
    :param direction: 'reverse' (default) is latest to earliest; 'forward' is
        earliest to latest.
    :param specific_fileid: If not None, list only the commits affecting the
        specified file.
    :param search: If not None, only show revisions with matching commit
        messages.
    :param generate_merge_revisions: If False, show only mainline revisions.
    :param allow_single_merge_revision: If True, logging of a single
        revision off the mainline is to be allowed
    :param generate_delta: Whether to generate a delta for each revision.
    :param limited_output: if True, the user only wants a limited result

    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    start_rev_id, end_rev_id = _get_revision_limits(branch, start_revision,
        end_revision)

    # Decide how file-ids are matched: delta-filtering vs per-file graph.
    # Delta filtering allows revisions to be displayed incrementally
    # though the total time is much slower for huge repositories: log -v
    # is the *lower* performance bound. At least until the split
    # inventory format arrives, per-file-graph needs to remain the
    # default except in verbose mode. Delta filtering should give more
    # accurate results (e.g. inclusion of FILE deletions) so arguably
    # it should always be used in the future.
    use_deltas_for_matching = specific_fileid and generate_delta
    delayed_graph_generation = not specific_fileid and (
            start_rev_id or end_rev_id or limited_output)
    generate_merges = generate_merge_revisions or (specific_fileid and
        not use_deltas_for_matching)
    view_revisions = _calc_view_revisions(branch, start_rev_id, end_rev_id,
        direction, generate_merges, allow_single_merge_revision,
        delayed_graph_generation=delayed_graph_generation)
    search_deltas_for_fileids = None
    if use_deltas_for_matching:
        search_deltas_for_fileids = set([specific_fileid])
    elif specific_fileid:
        if not isinstance(view_revisions, list):
            view_revisions = list(view_revisions)
        view_revisions = _filter_revisions_touching_file_id(branch,
            specific_fileid, view_revisions,
            include_merges=generate_merge_revisions)
    return make_log_rev_iterator(branch, view_revisions, generate_delta,
        search, file_ids=search_deltas_for_fileids, direction=direction)


def _calc_view_revisions(branch, start_rev_id, end_rev_id, direction,
    generate_merge_revisions, allow_single_merge_revision,
    delayed_graph_generation=False):
    """Calculate the revisions to view.

    :return: An iterator of (revision_id, dotted_revno, merge_depth) tuples OR
             a list of the same tuples.
    """
    br_revno, br_rev_id = branch.last_revision_info()
    if br_revno == 0:
        return []

    # If a single revision is requested, check we can handle it
    generate_single_revision = (end_rev_id and start_rev_id == end_rev_id and
        (not generate_merge_revisions or not _has_merges(branch, end_rev_id)))
    if generate_single_revision:
        if end_rev_id == br_rev_id:
            # It's the tip
            return [(br_rev_id, br_revno, 0)]
        else:
            revno = branch.revision_id_to_dotted_revno(end_rev_id)
            if len(revno) > 1 and not allow_single_merge_revision:
                # It's a merge revision and the log formatter is
                # completely brain dead. This "feature" of allowing
                # log formatters incapable of displaying dotted revnos
                # ought to be deprecated IMNSHO. IGC 20091022
                raise errors.BzrCommandError('Selected log formatter only'
                    ' supports mainline revisions.')
            revno_str = '.'.join(str(n) for n in revno)
            return [(end_rev_id, revno_str, 0)]

    # If we only want to see linear revisions, we can iterate ...
    if not generate_merge_revisions:
        result = _linear_view_revisions(branch, start_rev_id, end_rev_id)
        # If a start limit was given and it's not obviously an
        # ancestor of the end limit, check it before outputting anything
        if direction == 'forward' or (start_rev_id
            and not _is_obvious_ancestor(branch, start_rev_id, end_rev_id)):
            try:
                result = list(result)
            except _StartNotLinearAncestor:
                raise errors.BzrCommandError('Start revision not found in'
                    ' left-hand history of end revision.')
        if direction == 'forward':
            result = reversed(list(result))
        return result

    # On large trees, generating the merge graph can take 30-60 seconds
    # so we delay doing it until a merge is detected, incrementally
    # returning initial (non-merge) revisions while we can.
    initial_revisions = []
    if delayed_graph_generation:
        try:
            for rev_id, revno, depth in \
                _linear_view_revisions(branch, start_rev_id, end_rev_id):
                if _has_merges(branch, rev_id):
                    end_rev_id = rev_id
                    break
                else:
                    initial_revisions.append((rev_id, revno, depth))
            else:
                # No merged revisions found
                if direction == 'reverse':
                    return initial_revisions
                elif direction == 'forward':
                    return reversed(initial_revisions)
                else:
                    raise ValueError('invalid direction %r' % direction)
        except _StartNotLinearAncestor:
            # A merge was never detected so the lower revision limit can't
            # be nested down somewhere
            raise errors.BzrCommandError('Start revision not found in'
                ' history of end revision.')

    # A log including nested merges is required. If the direction is reverse,
    # we rebase the initial merge depths so that the development line is
    # shown naturally, i.e. just like it is for linear logging. We can easily
    # make forward the exact opposite display, but showing the merge revisions
    # indented at the end seems slightly nicer in that case.
    view_revisions = chain(iter(initial_revisions),
        _graph_view_revisions(branch, start_rev_id, end_rev_id,
        rebase_initial_depths=direction == 'reverse'))
    if direction == 'reverse':
        return view_revisions
    elif direction == 'forward':
        # Forward means oldest first, adjusting for depth.
        view_revisions = reverse_by_depth(list(view_revisions))
        return _rebase_merge_depth(view_revisions)
    else:
        raise ValueError('invalid direction %r' % direction)


def _has_merges(branch, rev_id):
    """Does a revision have multiple parents or not?"""
    parents = branch.repository.get_parent_map([rev_id]).get(rev_id, [])
    return len(parents) > 1


def _is_obvious_ancestor(branch, start_rev_id, end_rev_id):
    """Is start_rev_id an obvious ancestor of end_rev_id?"""
    if start_rev_id and end_rev_id:
        start_dotted = branch.revision_id_to_dotted_revno(start_rev_id)
        end_dotted = branch.revision_id_to_dotted_revno(end_rev_id)
        if len(start_dotted) == 1 and len(end_dotted) == 1:
            # both on mainline
            return start_dotted[0] <= end_dotted[0]
        elif (len(start_dotted) == 3 and len(end_dotted) == 3 and
            start_dotted[0:1] == end_dotted[0:1]):
            # both on same development line
            return start_dotted[2] <= end_dotted[2]
        else:
            # not obvious
            return False
    return True


def _linear_view_revisions(branch, start_rev_id, end_rev_id):
    """Calculate a sequence of revisions to view, newest to oldest.

    :param start_rev_id: the lower revision-id
    :param end_rev_id: the upper revision-id
    :return: An iterator of (revision_id, dotted_revno, merge_depth) tuples.
    :raises _StartNotLinearAncestor: if a start_rev_id is specified but
      is not found walking the left-hand history
    """
    br_revno, br_rev_id = branch.last_revision_info()
    repo = branch.repository
    if start_rev_id is None and end_rev_id is None:
        cur_revno = br_revno
        for revision_id in repo.iter_reverse_revision_history(br_rev_id):
            yield revision_id, str(cur_revno), 0
            cur_revno -= 1
    else:
        if end_rev_id is None:
            end_rev_id = br_rev_id
        found_start = start_rev_id is None
        for revision_id in repo.iter_reverse_revision_history(end_rev_id):
            revno = branch.revision_id_to_dotted_revno(revision_id)
            revno_str = '.'.join(str(n) for n in revno)
            if not found_start and revision_id == start_rev_id:
                yield revision_id, revno_str, 0
                found_start = True
                break
            else:
                yield revision_id, revno_str, 0
        else:
            if not found_start:
                raise _StartNotLinearAncestor()


def _graph_view_revisions(branch, start_rev_id, end_rev_id,
    rebase_initial_depths=True):
    """Calculate revisions to view including merges, newest to oldest.

    :param branch: the branch
    :param start_rev_id: the lower revision-id
    :param end_rev_id: the upper revision-id
    :param rebase_initial_depth: should depths be rebased until a mainline
      revision is found?
    :return: An iterator of (revision_id, dotted_revno, merge_depth) tuples.
    """
    view_revisions = branch.iter_merge_sorted_revisions(
        start_revision_id=end_rev_id, stop_revision_id=start_rev_id,
        stop_rule="with-merges")
    if not rebase_initial_depths:
        for (rev_id, merge_depth, revno, end_of_merge
             ) in view_revisions:
            yield rev_id, '.'.join(map(str, revno)), merge_depth
    else:
        # We're following a development line starting at a merged revision.
        # We need to adjust depths down by the initial depth until we find
        # a depth less than it. Then we use that depth as the adjustment.
        # If and when we reach the mainline, depth adjustment ends.
        depth_adjustment = None
        for (rev_id, merge_depth, revno, end_of_merge
             ) in view_revisions:
            if depth_adjustment is None:
                depth_adjustment = merge_depth
            if depth_adjustment:
                if merge_depth < depth_adjustment:
                    depth_adjustment = merge_depth
                merge_depth -= depth_adjustment
            yield rev_id, '.'.join(map(str, revno)), merge_depth


def calculate_view_revisions(branch, start_revision, end_revision, direction,
        specific_fileid, generate_merge_revisions, allow_single_merge_revision):
    """Calculate the revisions to view.

    :return: An iterator of (revision_id, dotted_revno, merge_depth) tuples OR
             a list of the same tuples.
    """
    # This method is no longer called by the main code path.
    # It is retained for API compatibility and may be deprecated
    # soon. IGC 20090116
    start_rev_id, end_rev_id = _get_revision_limits(branch, start_revision,
        end_revision)
    view_revisions = list(_calc_view_revisions(branch, start_rev_id, end_rev_id,
        direction, generate_merge_revisions or specific_fileid,
        allow_single_merge_revision))
    if specific_fileid:
        view_revisions = _filter_revisions_touching_file_id(branch,
            specific_fileid, view_revisions,
            include_merges=generate_merge_revisions)
    return _rebase_merge_depth(view_revisions)


def _rebase_merge_depth(view_revisions):
    """Adjust depths upwards so the top level is 0."""
    # If either the first or last revision have a merge_depth of 0, we're done
    if view_revisions and view_revisions[0][2] and view_revisions[-1][2]:
        min_depth = min([d for r,n,d in view_revisions])
        if min_depth != 0:
            view_revisions = [(r,n,d-min_depth) for r,n,d in view_revisions]
    return view_revisions


def make_log_rev_iterator(branch, view_revisions, generate_delta, search,
        file_ids=None, direction='reverse'):
    """Create a revision iterator for log.

    :param branch: The branch being logged.
    :param view_revisions: The revisions being viewed.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param file_ids: If non empty, only revisions matching one or more of
      the file-ids are to be kept.
    :param direction: the direction in which view_revisions is sorted
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    # Convert view_revisions into (view, None, None) groups to fit with
    # the standard interface here.
    if type(view_revisions) == list:
        # A single batch conversion is faster than many incremental ones.
        # As we have all the data, do a batch conversion.
        nones = [None] * len(view_revisions)
        log_rev_iterator = iter([zip(view_revisions, nones, nones)])
    else:
        def _convert():
            for view in view_revisions:
                yield (view, None, None)
        log_rev_iterator = iter([_convert()])
    for adapter in log_adapters:
        # It would be nicer if log adapters were first class objects
        # with custom parameters. This will do for now. IGC 20090127
        if adapter == _make_delta_filter:
            log_rev_iterator = adapter(branch, generate_delta,
                search, log_rev_iterator, file_ids, direction)
        else:
            log_rev_iterator = adapter(branch, generate_delta,
                search, log_rev_iterator)
    return log_rev_iterator


def _make_search_filter(branch, generate_delta, search, log_rev_iterator):
    """Create a filtered iterator of log_rev_iterator matching on a regex.

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    if search is None:
        return log_rev_iterator
    # Compile the search now to get early errors.
    try:
        searchRE = re.compile(search, re.IGNORECASE)
        searchRE.search("")
    except:
        raise errors.BzrCommandError('Invalid regular expression: %r'
            % (search,))
    return _filter_message_re(searchRE, log_rev_iterator)


def _filter_message_re(searchRE, log_rev_iterator):
    for revs in log_rev_iterator:
        new_revs = []
        for (rev_id, revno, merge_depth), rev, delta in revs:
            if searchRE.search(rev.message):
                new_revs.append(((rev_id, revno, merge_depth), rev, delta))
        yield new_revs


def _make_delta_filter(branch, generate_delta, search, log_rev_iterator,
    fileids=None, direction='reverse'):
    """Add revision deltas to a log iterator if needed.

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :param fileids: If non empty, only revisions matching one or more of
      the file-ids are to be kept.
    :param direction: the direction in which view_revisions is sorted
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    if not generate_delta and not fileids:
        return log_rev_iterator
    return _generate_deltas(branch.repository, log_rev_iterator,
        generate_delta, fileids, direction)


def _generate_deltas(repository, log_rev_iterator, always_delta, fileids,
    direction):
    """Create deltas for each batch of revisions in log_rev_iterator.

    If we're only generating deltas for the sake of filtering against
    file-ids, we stop generating deltas once all file-ids reach the
    appropriate life-cycle point. If we're receiving data newest to
    oldest, then that life-cycle point is 'add', otherwise it's 'remove'.
    """
    check_fileids = fileids is not None and len(fileids) > 0
    if check_fileids:
        fileid_set = set(fileids)
        if direction == 'reverse':
            stop_on = 'add'
        else:
            stop_on = 'remove'
    else:
        fileid_set = None
    for revs in log_rev_iterator:
        # If we were matching against fileids and we've run out,
        # there's nothing left to do
        if check_fileids and not fileid_set:
            return
        revisions = [rev[1] for rev in revs]
        deltas = repository.get_deltas_for_revisions(revisions)
        new_revs = []
        for rev, delta in izip(revs, deltas):
            if check_fileids:
                if not _delta_matches_fileids(delta, fileid_set, stop_on):
                    continue
                elif not always_delta:
                    # Delta was created just for matching - ditch it
                    # Note: It would probably be a better UI to return
                    # a delta filtered by the file-ids, rather than
                    # None at all. That functional enhancement can
                    # come later ...
                    delta = None
            new_revs.append((rev[0], rev[1], delta))
        yield new_revs


def _delta_matches_fileids(delta, fileids, stop_on='add'):
    """Check is a delta matches one of more file-ids.

    :param fileids: a set of fileids to match against.
    :param stop_on: either 'add' or 'remove' - take file-ids out of the
      fileids set once their add or remove entry is detected respectively
    """
    if not fileids:
        return False
    result = False
    for item in delta.added:
        if item[1] in fileids:
            if stop_on == 'add':
                fileids.remove(item[1])
            result = True
    for item in delta.removed:
        if item[1] in fileids:
            if stop_on == 'delete':
                fileids.remove(item[1])
            result = True
    if result:
        return True
    for l in (delta.modified, delta.renamed, delta.kind_changed):
        for item in l:
            if item[1] in fileids:
                return True
    return False


def _make_revision_objects(branch, generate_delta, search, log_rev_iterator):
    """Extract revision objects from the repository

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    repository = branch.repository
    for revs in log_rev_iterator:
        # r = revision_id, n = revno, d = merge depth
        revision_ids = [view[0] for view, _, _ in revs]
        revisions = repository.get_revisions(revision_ids)
        revs = [(rev[0], revision, rev[2]) for rev, revision in
            izip(revs, revisions)]
        yield revs


def _make_batch_filter(branch, generate_delta, search, log_rev_iterator):
    """Group up a single large batch into smaller ones.

    :param branch: The branch being logged.
    :param generate_delta: Whether to generate a delta for each revision.
    :param search: A user text search string.
    :param log_rev_iterator: An input iterator containing all revisions that
        could be displayed, in lists.
    :return: An iterator over lists of ((rev_id, revno, merge_depth), rev,
        delta).
    """
    repository = branch.repository
    num = 9
    for batch in log_rev_iterator:
        batch = iter(batch)
        while True:
            step = [detail for _, detail in zip(range(num), batch)]
            if len(step) == 0:
                break
            yield step
            num = min(int(num * 1.5), 200)


def _get_revision_limits(branch, start_revision, end_revision):
    """Get and check revision limits.

    :param  branch: The branch containing the revisions.

    :param  start_revision: The first revision to be logged.
            For backwards compatibility this may be a mainline integer revno,
            but for merge revision support a RevisionInfo is expected.

    :param  end_revision: The last revision to be logged.
            For backwards compatibility this may be a mainline integer revno,
            but for merge revision support a RevisionInfo is expected.

    :return: (start_rev_id, end_rev_id) tuple.
    """
    branch_revno, branch_rev_id = branch.last_revision_info()
    start_rev_id = None
    if start_revision is None:
        start_revno = 1
    else:
        if isinstance(start_revision, revisionspec.RevisionInfo):
            start_rev_id = start_revision.rev_id
            start_revno = start_revision.revno or 1
        else:
            branch.check_real_revno(start_revision)
            start_revno = start_revision
            start_rev_id = branch.get_rev_id(start_revno)

    end_rev_id = None
    if end_revision is None:
        end_revno = branch_revno
    else:
        if isinstance(end_revision, revisionspec.RevisionInfo):
            end_rev_id = end_revision.rev_id
            end_revno = end_revision.revno or branch_revno
        else:
            branch.check_real_revno(end_revision)
            end_revno = end_revision
            end_rev_id = branch.get_rev_id(end_revno)

    if branch_revno != 0:
        if (start_rev_id == _mod_revision.NULL_REVISION
            or end_rev_id == _mod_revision.NULL_REVISION):
            raise errors.BzrCommandError('Logging revision 0 is invalid.')
        if start_revno > end_revno:
            raise errors.BzrCommandError("Start revision must be older than "
                                         "the end revision.")
    return (start_rev_id, end_rev_id)


def _get_mainline_revs(branch, start_revision, end_revision):
    """Get the mainline revisions from the branch.

    Generates the list of mainline revisions for the branch.

    :param  branch: The branch containing the revisions.

    :param  start_revision: The first revision to be logged.
            For backwards compatibility this may be a mainline integer revno,
            but for merge revision support a RevisionInfo is expected.

    :param  end_revision: The last revision to be logged.
            For backwards compatibility this may be a mainline integer revno,
            but for merge revision support a RevisionInfo is expected.

    :return: A (mainline_revs, rev_nos, start_rev_id, end_rev_id) tuple.
    """
    branch_revno, branch_last_revision = branch.last_revision_info()
    if branch_revno == 0:
        return None, None, None, None

    # For mainline generation, map start_revision and end_revision to
    # mainline revnos. If the revision is not on the mainline choose the
    # appropriate extreme of the mainline instead - the extra will be
    # filtered later.
    # Also map the revisions to rev_ids, to be used in the later filtering
    # stage.
    start_rev_id = None
    if start_revision is None:
        start_revno = 1
    else:
        if isinstance(start_revision, revisionspec.RevisionInfo):
            start_rev_id = start_revision.rev_id
            start_revno = start_revision.revno or 1
        else:
            branch.check_real_revno(start_revision)
            start_revno = start_revision

    end_rev_id = None
    if end_revision is None:
        end_revno = branch_revno
    else:
        if isinstance(end_revision, revisionspec.RevisionInfo):
            end_rev_id = end_revision.rev_id
            end_revno = end_revision.revno or branch_revno
        else:
            branch.check_real_revno(end_revision)
            end_revno = end_revision

    if ((start_rev_id == _mod_revision.NULL_REVISION)
        or (end_rev_id == _mod_revision.NULL_REVISION)):
        raise errors.BzrCommandError('Logging revision 0 is invalid.')
    if start_revno > end_revno:
        raise errors.BzrCommandError("Start revision must be older than "
                                     "the end revision.")

    if end_revno < start_revno:
        return None, None, None, None
    cur_revno = branch_revno
    rev_nos = {}
    mainline_revs = []
    for revision_id in branch.repository.iter_reverse_revision_history(
                        branch_last_revision):
        if cur_revno < start_revno:
            # We have gone far enough, but we always add 1 more revision
            rev_nos[revision_id] = cur_revno
            mainline_revs.append(revision_id)
            break
        if cur_revno <= end_revno:
            rev_nos[revision_id] = cur_revno
            mainline_revs.append(revision_id)
        cur_revno -= 1
    else:
        # We walked off the edge of all revisions, so we add a 'None' marker
        mainline_revs.append(None)

    mainline_revs.reverse()

    # override the mainline to look like the revision history.
    return mainline_revs, rev_nos, start_rev_id, end_rev_id


def _filter_revision_range(view_revisions, start_rev_id, end_rev_id):
    """Filter view_revisions based on revision ranges.

    :param view_revisions: A list of (revision_id, dotted_revno, merge_depth)
            tuples to be filtered.

    :param start_rev_id: If not NONE specifies the first revision to be logged.
            If NONE then all revisions up to the end_rev_id are logged.

    :param end_rev_id: If not NONE specifies the last revision to be logged.
            If NONE then all revisions up to the end of the log are logged.

    :return: The filtered view_revisions.
    """
    # This method is no longer called by the main code path.
    # It may be removed soon. IGC 20090127
    if start_rev_id or end_rev_id:
        revision_ids = [r for r, n, d in view_revisions]
        if start_rev_id:
            start_index = revision_ids.index(start_rev_id)
        else:
            start_index = 0
        if start_rev_id == end_rev_id:
            end_index = start_index
        else:
            if end_rev_id:
                end_index = revision_ids.index(end_rev_id)
            else:
                end_index = len(view_revisions) - 1
        # To include the revisions merged into the last revision,
        # extend end_rev_id down to, but not including, the next rev
        # with the same or lesser merge_depth
        end_merge_depth = view_revisions[end_index][2]
        try:
            for index in xrange(end_index+1, len(view_revisions)+1):
                if view_revisions[index][2] <= end_merge_depth:
                    end_index = index - 1
                    break
        except IndexError:
            # if the search falls off the end then log to the end as well
            end_index = len(view_revisions) - 1
        view_revisions = view_revisions[start_index:end_index+1]
    return view_revisions


def _filter_revisions_touching_file_id(branch, file_id, view_revisions,
    include_merges=True):
    r"""Return the list of revision ids which touch a given file id.

    The function filters view_revisions and returns a subset.
    This includes the revisions which directly change the file id,
    and the revisions which merge these changes. So if the
    revision graph is::
        A-.
        |\ \
        B C E
        |/ /
        D |
        |\|
        | F
        |/
        G

    And 'C' changes a file, then both C and D will be returned. F will not be
    returned even though it brings the changes to C into the branch starting
    with E. (Note that if we were using F as the tip instead of G, then we
    would see C, D, F.)

    This will also be restricted based on a subset of the mainline.

    :param branch: The branch where we can get text revision information.

    :param file_id: Filter out revisions that do not touch file_id.

    :param view_revisions: A list of (revision_id, dotted_revno, merge_depth)
        tuples. This is the list of revisions which will be filtered. It is
        assumed that view_revisions is in merge_sort order (i.e. newest
        revision first ).

    :param include_merges: include merge revisions in the result or not

    :return: A list of (revision_id, dotted_revno, merge_depth) tuples.
    """
    # Lookup all possible text keys to determine which ones actually modified
    # the file.
    text_keys = [(file_id, rev_id) for rev_id, revno, depth in view_revisions]
    # Looking up keys in batches of 1000 can cut the time in half, as well as
    # memory consumption. GraphIndex *does* like to look for a few keys in
    # parallel, it just doesn't like looking for *lots* of keys in parallel.
    # TODO: This code needs to be re-evaluated periodically as we tune the
    #       indexing layer. We might consider passing in hints as to the known
    #       access pattern (sparse/clustered, high success rate/low success
    #       rate). This particular access is clustered with a low success rate.
    get_parent_map = branch.repository.texts.get_parent_map
    modified_text_revisions = set()
    chunk_size = 1000
    for start in xrange(0, len(text_keys), chunk_size):
        next_keys = text_keys[start:start + chunk_size]
        # Only keep the revision_id portion of the key
        modified_text_revisions.update(
            [k[1] for k in get_parent_map(next_keys)])
    del text_keys, next_keys

    result = []
    # Track what revisions will merge the current revision, replace entries
    # with 'None' when they have been added to result
    current_merge_stack = [None]
    for info in view_revisions:
        rev_id, revno, depth = info
        if depth == len(current_merge_stack):
            current_merge_stack.append(info)
        else:
            del current_merge_stack[depth + 1:]
            current_merge_stack[-1] = info

        if rev_id in modified_text_revisions:
            # This needs to be logged, along with the extra revisions
            for idx in xrange(len(current_merge_stack)):
                node = current_merge_stack[idx]
                if node is not None:
                    if include_merges or node[2] == 0:
                        result.append(node)
                        current_merge_stack[idx] = None
    return result


def get_view_revisions(mainline_revs, rev_nos, branch, direction,
                       include_merges=True):
    """Produce an iterator of revisions to show
    :return: an iterator of (revision_id, revno, merge_depth)
    (if there is no revno for a revision, None is supplied)
    """
    # This method is no longer called by the main code path.
    # It is retained for API compatibility and may be deprecated
    # soon. IGC 20090127
    if not include_merges:
        revision_ids = mainline_revs[1:]
        if direction == 'reverse':
            revision_ids.reverse()
        for revision_id in revision_ids:
            yield revision_id, str(rev_nos[revision_id]), 0
        return
    graph = branch.repository.get_graph()
    # This asks for all mainline revisions, which means we only have to spider
    # sideways, rather than depth history. That said, its still size-of-history
    # and should be addressed.
    # mainline_revisions always includes an extra revision at the beginning, so
    # don't request it.
    parent_map = dict(((key, value) for key, value in
        graph.iter_ancestry(mainline_revs[1:]) if value is not None))
    # filter out ghosts; merge_sort errors on ghosts.
    rev_graph = _mod_repository._strip_NULL_ghosts(parent_map)
    merge_sorted_revisions = tsort.merge_sort(
        rev_graph,
        mainline_revs[-1],
        mainline_revs,
        generate_revno=True)

    if direction == 'forward':
        # forward means oldest first.
        merge_sorted_revisions = reverse_by_depth(merge_sorted_revisions)
    elif direction != 'reverse':
        raise ValueError('invalid direction %r' % direction)

    for (sequence, rev_id, merge_depth, revno, end_of_merge
         ) in merge_sorted_revisions:
        yield rev_id, '.'.join(map(str, revno)), merge_depth


def reverse_by_depth(merge_sorted_revisions, _depth=0):
    """Reverse revisions by depth.

    Revisions with a different depth are sorted as a group with the previous
    revision of that depth.  There may be no topological justification for this,
    but it looks much nicer.
    """
    # Add a fake revision at start so that we can always attach sub revisions
    merge_sorted_revisions = [(None, None, _depth)] + merge_sorted_revisions
    zd_revisions = []
    for val in merge_sorted_revisions:
        if val[2] == _depth:
            # Each revision at the current depth becomes a chunk grouping all
            # higher depth revisions.
            zd_revisions.append([val])
        else:
            zd_revisions[-1].append(val)
    for revisions in zd_revisions:
        if len(revisions) > 1:
            # We have higher depth revisions, let reverse them locally
            revisions[1:] = reverse_by_depth(revisions[1:], _depth + 1)
    zd_revisions.reverse()
    result = []
    for chunk in zd_revisions:
        result.extend(chunk)
    if _depth == 0:
        # Top level call, get rid of the fake revisions that have been added
        result = [r for r in result if r[0] is not None and r[1] is not None]
    return result


class LogRevision(object):
    """A revision to be logged (by LogFormatter.log_revision).

    A simple wrapper for the attributes of a revision to be logged.
    The attributes may or may not be populated, as determined by the
    logging options and the log formatter capabilities.
    """

    def __init__(self, rev=None, revno=None, merge_depth=0, delta=None,
                 tags=None, diff=None):
        self.rev = rev
        self.revno = str(revno)
        self.merge_depth = merge_depth
        self.delta = delta
        self.tags = tags
        self.diff = diff


class LogFormatter(object):
    """Abstract class to display log messages.

    At a minimum, a derived class must implement the log_revision method.

    If the LogFormatter needs to be informed of the beginning or end of
    a log it should implement the begin_log and/or end_log hook methods.

    A LogFormatter should define the following supports_XXX flags
    to indicate which LogRevision attributes it supports:

    - supports_delta must be True if this log formatter supports delta.
        Otherwise the delta attribute may not be populated.  The 'delta_format'
        attribute describes whether the 'short_status' format (1) or the long
        one (2) should be used.

    - supports_merge_revisions must be True if this log formatter supports
        merge revisions.  If not, and if supports_single_merge_revision is
        also not True, then only mainline revisions will be passed to the
        formatter.

    - preferred_levels is the number of levels this formatter defaults to.
        The default value is zero meaning display all levels.
        This value is only relevant if supports_merge_revisions is True.

    - supports_single_merge_revision must be True if this log formatter
        supports logging only a single merge revision.  This flag is
        only relevant if supports_merge_revisions is not True.

    - supports_tags must be True if this log formatter supports tags.
        Otherwise the tags attribute may not be populated.

    - supports_diff must be True if this log formatter supports diffs.
        Otherwise the diff attribute may not be populated.

    Plugins can register functions to show custom revision properties using
    the properties_handler_registry. The registered function
    must respect the following interface description:
        def my_show_properties(properties_dict):
            # code that returns a dict {'name':'value'} of the properties
            # to be shown
    """
    preferred_levels = 0

    def __init__(self, to_file, show_ids=False, show_timezone='original',
                 delta_format=None, levels=None):
        """Create a LogFormatter.

        :param to_file: the file to output to
        :param show_ids: if True, revision-ids are to be displayed
        :param show_timezone: the timezone to use
        :param delta_format: the level of delta information to display
          or None to leave it u to the formatter to decide
        :param levels: the number of levels to display; None or -1 to
          let the log formatter decide.
        """
        self.to_file = to_file
        # 'exact' stream used to show diff, it should print content 'as is'
        # and should not try to decode/encode it to unicode to avoid bug #328007
        self.to_exact_file = getattr(to_file, 'stream', to_file)
        self.show_ids = show_ids
        self.show_timezone = show_timezone
        if delta_format is None:
            # Ensures backward compatibility
            delta_format = 2 # long format
        self.delta_format = delta_format
        self.levels = levels

    def get_levels(self):
        """Get the number of levels to display or 0 for all."""
        if getattr(self, 'supports_merge_revisions', False):
            if self.levels is None or self.levels == -1:
                return self.preferred_levels
            else:
                return self.levels
        return 1

    def log_revision(self, revision):
        """Log a revision.

        :param  revision:   The LogRevision to be logged.
        """
        raise NotImplementedError('not implemented in abstract base')

    def short_committer(self, rev):
        name, address = config.parse_username(rev.committer)
        if name:
            return name
        return address

    def short_author(self, rev):
        name, address = config.parse_username(rev.get_apparent_authors()[0])
        if name:
            return name
        return address

    def show_properties(self, revision, indent):
        """Displays the custom properties returned by each registered handler.

        If a registered handler raises an error it is propagated.
        """
        for key, handler in properties_handler_registry.iteritems():
            for key, value in handler(revision).items():
                self.to_file.write(indent + key + ': ' + value + '\n')

    def show_diff(self, to_file, diff, indent):
        for l in diff.rstrip().split('\n'):
            to_file.write(indent + '%s\n' % (l,))


class LongLogFormatter(LogFormatter):

    supports_merge_revisions = True
    supports_delta = True
    supports_tags = True
    supports_diff = True

    def log_revision(self, revision):
        """Log a revision, either merged or not."""
        indent = '    ' * revision.merge_depth
        to_file = self.to_file
        to_file.write(indent + '-' * 60 + '\n')
        if revision.revno is not None:
            to_file.write(indent + 'revno: %s\n' % (revision.revno,))
        if revision.tags:
            to_file.write(indent + 'tags: %s\n' % (', '.join(revision.tags)))
        if self.show_ids:
            to_file.write(indent + 'revision-id: ' + revision.rev.revision_id)
            to_file.write('\n')
            for parent_id in revision.rev.parent_ids:
                to_file.write(indent + 'parent: %s\n' % (parent_id,))
        self.show_properties(revision.rev, indent)

        committer = revision.rev.committer
        authors = revision.rev.get_apparent_authors()
        if authors != [committer]:
            to_file.write(indent + 'author: %s\n' % (", ".join(authors),))
        to_file.write(indent + 'committer: %s\n' % (committer,))

        branch_nick = revision.rev.properties.get('branch-nick', None)
        if branch_nick is not None:
            to_file.write(indent + 'branch nick: %s\n' % (branch_nick,))

        date_str = format_date(revision.rev.timestamp,
                               revision.rev.timezone or 0,
                               self.show_timezone)
        to_file.write(indent + 'timestamp: %s\n' % (date_str,))

        to_file.write(indent + 'message:\n')
        if not revision.rev.message:
            to_file.write(indent + '  (no message)\n')
        else:
            message = revision.rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                to_file.write(indent + '  %s\n' % (l,))
        if revision.delta is not None:
            # We don't respect delta_format for compatibility
            revision.delta.show(to_file, self.show_ids, indent=indent,
                                short_status=False)
        if revision.diff is not None:
            to_file.write(indent + 'diff:\n')
            # Note: we explicitly don't indent the diff (relative to the
            # revision information) so that the output can be fed to patch -p0
            self.show_diff(self.to_exact_file, revision.diff, indent)


class ShortLogFormatter(LogFormatter):

    supports_merge_revisions = True
    preferred_levels = 1
    supports_delta = True
    supports_tags = True
    supports_diff = True

    def __init__(self, *args, **kwargs):
        super(ShortLogFormatter, self).__init__(*args, **kwargs)
        self.revno_width_by_depth = {}

    def log_revision(self, revision):
        # We need two indents: one per depth and one for the information
        # relative to that indent. Most mainline revnos are 5 chars or
        # less while dotted revnos are typically 11 chars or less. Once
        # calculated, we need to remember the offset for a given depth
        # as we might be starting from a dotted revno in the first column
        # and we want subsequent mainline revisions to line up.
        depth = revision.merge_depth
        indent = '    ' * depth
        revno_width = self.revno_width_by_depth.get(depth)
        if revno_width is None:
            if revision.revno.find('.') == -1:
                # mainline revno, e.g. 12345
                revno_width = 5
            else:
                # dotted revno, e.g. 12345.10.55
                revno_width = 11
            self.revno_width_by_depth[depth] = revno_width
        offset = ' ' * (revno_width + 1)

        to_file = self.to_file
        is_merge = ''
        if len(revision.rev.parent_ids) > 1:
            is_merge = ' [merge]'
        tags = ''
        if revision.tags:
            tags = ' {%s}' % (', '.join(revision.tags))
        to_file.write(indent + "%*s %s\t%s%s%s\n" % (revno_width,
                revision.revno, self.short_author(revision.rev),
                format_date(revision.rev.timestamp,
                            revision.rev.timezone or 0,
                            self.show_timezone, date_fmt="%Y-%m-%d",
                            show_offset=False),
                tags, is_merge))
        self.show_properties(revision.rev, indent+offset)
        if self.show_ids:
            to_file.write(indent + offset + 'revision-id:%s\n'
                          % (revision.rev.revision_id,))
        if not revision.rev.message:
            to_file.write(indent + offset + '(no message)\n')
        else:
            message = revision.rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                to_file.write(indent + offset + '%s\n' % (l,))

        if revision.delta is not None:
            revision.delta.show(to_file, self.show_ids, indent=indent + offset,
                                short_status=self.delta_format==1)
        if revision.diff is not None:
            self.show_diff(self.to_exact_file, revision.diff, '      ')
        to_file.write('\n')


class LineLogFormatter(LogFormatter):

    supports_merge_revisions = True
    preferred_levels = 1
    supports_tags = True

    def __init__(self, *args, **kwargs):
        super(LineLogFormatter, self).__init__(*args, **kwargs)
        self._max_chars = terminal_width() - 1

    def truncate(self, str, max_len):
        if len(str) <= max_len:
            return str
        return str[:max_len-3]+'...'

    def date_string(self, rev):
        return format_date(rev.timestamp, rev.timezone or 0,
                           self.show_timezone, date_fmt="%Y-%m-%d",
                           show_offset=False)

    def message(self, rev):
        if not rev.message:
            return '(no message)'
        else:
            return rev.message

    def log_revision(self, revision):
        indent = '  ' * revision.merge_depth
        self.to_file.write(self.log_string(revision.revno, revision.rev,
            self._max_chars, revision.tags, indent))
        self.to_file.write('\n')

    def log_string(self, revno, rev, max_chars, tags=None, prefix=''):
        """Format log info into one string. Truncate tail of string
        :param  revno:      revision number or None.
                            Revision numbers counts from 1.
        :param  rev:        revision object
        :param  max_chars:  maximum length of resulting string
        :param  tags:       list of tags or None
        :param  prefix:     string to prefix each line
        :return:            formatted truncated string
        """
        out = []
        if revno:
            # show revno only when is not None
            out.append("%s:" % revno)
        out.append(self.truncate(self.short_author(rev), 20))
        out.append(self.date_string(rev))
        if len(rev.parent_ids) > 1:
            out.append('[merge]')
        if tags:
            tag_str = '{%s}' % (', '.join(tags))
            out.append(tag_str)
        out.append(rev.get_summary())
        return self.truncate(prefix + " ".join(out).rstrip('\n'), max_chars)


class GnuChangelogLogFormatter(LogFormatter):

    supports_merge_revisions = True
    supports_delta = True

    def log_revision(self, revision):
        """Log a revision, either merged or not."""
        to_file = self.to_file

        date_str = format_date(revision.rev.timestamp,
                               revision.rev.timezone or 0,
                               self.show_timezone,
                               date_fmt='%Y-%m-%d',
                               show_offset=False)
        committer_str = revision.rev.committer.replace (' <', '  <')
        to_file.write('%s  %s\n\n' % (date_str,committer_str))

        if revision.delta is not None and revision.delta.has_changed():
            for c in revision.delta.added + revision.delta.removed + revision.delta.modified:
                path, = c[:1]
                to_file.write('\t* %s:\n' % (path,))
            for c in revision.delta.renamed:
                oldpath,newpath = c[:2]
                # For renamed files, show both the old and the new path
                to_file.write('\t* %s:\n\t* %s:\n' % (oldpath,newpath))
            to_file.write('\n')

        if not revision.rev.message:
            to_file.write('\tNo commit message\n')
        else:
            message = revision.rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                to_file.write('\t%s\n' % (l.lstrip(),))
            to_file.write('\n')


def line_log(rev, max_chars):
    lf = LineLogFormatter(None)
    return lf.log_string(None, rev, max_chars)


class LogFormatterRegistry(registry.Registry):
    """Registry for log formatters"""

    def make_formatter(self, name, *args, **kwargs):
        """Construct a formatter from arguments.

        :param name: Name of the formatter to construct.  'short', 'long' and
            'line' are built-in.
        """
        return self.get(name)(*args, **kwargs)

    def get_default(self, branch):
        return self.get(branch.get_config().log_format())


log_formatter_registry = LogFormatterRegistry()


log_formatter_registry.register('short', ShortLogFormatter,
                                'Moderately short log format')
log_formatter_registry.register('long', LongLogFormatter,
                                'Detailed log format')
log_formatter_registry.register('line', LineLogFormatter,
                                'Log format with one line per revision')
log_formatter_registry.register('gnu-changelog', GnuChangelogLogFormatter,
                                'Format used by GNU ChangeLog files')


def register_formatter(name, formatter):
    log_formatter_registry.register(name, formatter)


def log_formatter(name, *args, **kwargs):
    """Construct a formatter from arguments.

    name -- Name of the formatter to construct; currently 'long', 'short' and
        'line' are supported.
    """
    try:
        return log_formatter_registry.make_formatter(name, *args, **kwargs)
    except KeyError:
        raise errors.BzrCommandError("unknown log formatter: %r" % name)


def show_one_log(revno, rev, delta, verbose, to_file, show_timezone):
    # deprecated; for compatibility
    lf = LongLogFormatter(to_file=to_file, show_timezone=show_timezone)
    lf.show(revno, rev, delta)


def show_changed_revisions(branch, old_rh, new_rh, to_file=None,
                           log_format='long'):
    """Show the change in revision history comparing the old revision history to the new one.

    :param branch: The branch where the revisions exist
    :param old_rh: The old revision history
    :param new_rh: The new revision history
    :param to_file: A file to write the results to. If None, stdout will be used
    """
    if to_file is None:
        to_file = codecs.getwriter(get_terminal_encoding())(sys.stdout,
            errors='replace')
    lf = log_formatter(log_format,
                       show_ids=False,
                       to_file=to_file,
                       show_timezone='original')

    # This is the first index which is different between
    # old and new
    base_idx = None
    for i in xrange(max(len(new_rh),
                        len(old_rh))):
        if (len(new_rh) <= i
            or len(old_rh) <= i
            or new_rh[i] != old_rh[i]):
            base_idx = i
            break

    if base_idx is None:
        to_file.write('Nothing seems to have changed\n')
        return
    ## TODO: It might be nice to do something like show_log
    ##       and show the merged entries. But since this is the
    ##       removed revisions, it shouldn't be as important
    if base_idx < len(old_rh):
        to_file.write('*'*60)
        to_file.write('\nRemoved Revisions:\n')
        for i in range(base_idx, len(old_rh)):
            rev = branch.repository.get_revision(old_rh[i])
            lr = LogRevision(rev, i+1, 0, None)
            lf.log_revision(lr)
        to_file.write('*'*60)
        to_file.write('\n\n')
    if base_idx < len(new_rh):
        to_file.write('Added Revisions:\n')
        show_log(branch,
                 lf,
                 None,
                 verbose=False,
                 direction='forward',
                 start_revision=base_idx+1,
                 end_revision=len(new_rh),
                 search=None)


def get_history_change(old_revision_id, new_revision_id, repository):
    """Calculate the uncommon lefthand history between two revisions.

    :param old_revision_id: The original revision id.
    :param new_revision_id: The new revision id.
    :param repository: The repository to use for the calculation.

    return old_history, new_history
    """
    old_history = []
    old_revisions = set()
    new_history = []
    new_revisions = set()
    new_iter = repository.iter_reverse_revision_history(new_revision_id)
    old_iter = repository.iter_reverse_revision_history(old_revision_id)
    stop_revision = None
    do_old = True
    do_new = True
    while do_new or do_old:
        if do_new:
            try:
                new_revision = new_iter.next()
            except StopIteration:
                do_new = False
            else:
                new_history.append(new_revision)
                new_revisions.add(new_revision)
                if new_revision in old_revisions:
                    stop_revision = new_revision
                    break
        if do_old:
            try:
                old_revision = old_iter.next()
            except StopIteration:
                do_old = False
            else:
                old_history.append(old_revision)
                old_revisions.add(old_revision)
                if old_revision in new_revisions:
                    stop_revision = old_revision
                    break
    new_history.reverse()
    old_history.reverse()
    if stop_revision is not None:
        new_history = new_history[new_history.index(stop_revision) + 1:]
        old_history = old_history[old_history.index(stop_revision) + 1:]
    return old_history, new_history


def show_branch_change(branch, output, old_revno, old_revision_id):
    """Show the changes made to a branch.

    :param branch: The branch to show changes about.
    :param output: A file-like object to write changes to.
    :param old_revno: The revno of the old tip.
    :param old_revision_id: The revision_id of the old tip.
    """
    new_revno, new_revision_id = branch.last_revision_info()
    old_history, new_history = get_history_change(old_revision_id,
                                                  new_revision_id,
                                                  branch.repository)
    if old_history == [] and new_history == []:
        output.write('Nothing seems to have changed\n')
        return

    log_format = log_formatter_registry.get_default(branch)
    lf = log_format(show_ids=False, to_file=output, show_timezone='original')
    if old_history != []:
        output.write('*'*60)
        output.write('\nRemoved Revisions:\n')
        show_flat_log(branch.repository, old_history, old_revno, lf)
        output.write('*'*60)
        output.write('\n\n')
    if new_history != []:
        output.write('Added Revisions:\n')
        start_revno = new_revno - len(new_history) + 1
        show_log(branch, lf, None, verbose=False, direction='forward',
                 start_revision=start_revno,)


def show_flat_log(repository, history, last_revno, lf):
    """Show a simple log of the specified history.

    :param repository: The repository to retrieve revisions from.
    :param history: A list of revision_ids indicating the lefthand history.
    :param last_revno: The revno of the last revision_id in the history.
    :param lf: The log formatter to use.
    """
    start_revno = last_revno - len(history) + 1
    revisions = repository.get_revisions(history)
    for i, rev in enumerate(revisions):
        lr = LogRevision(rev, i + last_revno, 0, None)
        lf.log_revision(lr)


def _get_fileid_to_log(revision, tree, b, fp):
    """Find the file-id to log for a file path in a revision range.

    :param revision: the revision range as parsed on the command line
    :param tree: the working tree, if any
    :param b: the branch
    :param fp: file path
    """
    if revision is None:
        if tree is None:
            tree = b.basis_tree()
        file_id = tree.path2id(fp)
        if file_id is None:
            # go back to when time began
            try:
                rev1 = b.get_rev_id(1)
            except errors.NoSuchRevision:
                # No history at all
                file_id = None
            else:
                tree = b.repository.revision_tree(rev1)
                file_id = tree.path2id(fp)

    elif len(revision) == 1:
        # One revision given - file must exist in it
        tree = revision[0].as_tree(b)
        file_id = tree.path2id(fp)

    elif len(revision) == 2:
        # Revision range given. Get the file-id from the end tree.
        # If that fails, try the start tree.
        rev_id = revision[1].as_revision_id(b)
        if rev_id is None:
            tree = b.basis_tree()
        else:
            tree = revision[1].as_tree(b)
        file_id = tree.path2id(fp)
        if file_id is None:
            rev_id = revision[0].as_revision_id(b)
            if rev_id is None:
                rev1 = b.get_rev_id(1)
                tree = b.repository.revision_tree(rev1)
            else:
                tree = revision[0].as_tree(b)
            file_id = tree.path2id(fp)
    else:
        raise errors.BzrCommandError(
            'bzr log --revision takes one or two values.')
    return file_id


properties_handler_registry = registry.Registry()
properties_handler_registry.register_lazy("foreign",
                                          "bzrlib.foreign",
                                          "show_foreign_properties")


# adapters which revision ids to log are filtered. When log is called, the
# log_rev_iterator is adapted through each of these factory methods.
# Plugins are welcome to mutate this list in any way they like - as long
# as the overall behaviour is preserved. At this point there is no extensible
# mechanism for getting parameters to each factory method, and until there is
# this won't be considered a stable api.
log_adapters = [
    # core log logic
    _make_batch_filter,
    # read revision objects
    _make_revision_objects,
    # filter on log messages
    _make_search_filter,
    # generate deltas for things we will show
    _make_delta_filter
    ]
