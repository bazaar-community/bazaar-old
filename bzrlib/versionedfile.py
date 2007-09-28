# Copyright (C) 2005, 2006 Canonical Ltd
#
# Authors:
#   Johan Rydberg <jrydberg@gnu.org>
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

"""Versioned text file storage api."""

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """

from bzrlib import (
    errors,
    osutils,
    multiparent,
    tsort,
    revision,
    ui,
    )
from bzrlib.transport.memory import MemoryTransport
""")

from cStringIO import StringIO

from bzrlib.inter import InterObject
from bzrlib.textmerge import TextMerge


class VersionedFile(object):
    """Versioned text file storage.
    
    A versioned file manages versions of line-based text files,
    keeping track of the originating version for each line.

    To clients the "lines" of the file are represented as a list of
    strings. These strings will typically have terminal newline
    characters, but this is not required.  In particular files commonly
    do not have a newline at the end of the file.

    Texts are identified by a version-id string.
    """

    def __init__(self, access_mode):
        self.finished = False
        self._access_mode = access_mode

    @staticmethod
    def check_not_reserved_id(version_id):
        revision.check_not_reserved_id(version_id)

    def copy_to(self, name, transport):
        """Copy this versioned file to name on transport."""
        raise NotImplementedError(self.copy_to)

    def versions(self):
        """Return a unsorted list of versions."""
        raise NotImplementedError(self.versions)

    def has_ghost(self, version_id):
        """Returns whether version is present as a ghost."""
        raise NotImplementedError(self.has_ghost)

    def has_version(self, version_id):
        """Returns whether version is present."""
        raise NotImplementedError(self.has_version)

    def add_lines(self, version_id, parents, lines, parent_texts=None,
        left_matching_blocks=None, nostore_sha=None, random_id=False,
        check_content=True):
        """Add a single text on top of the versioned file.

        Must raise RevisionAlreadyPresent if the new version is
        already present in file history.

        Must raise RevisionNotPresent if any of the given parents are
        not present in file history.

        :param lines: A list of lines. Each line must be a bytestring. And all
            of them except the last must be terminated with \n and contain no
            other \n's. The last line may either contain no \n's or a single
            terminated \n. If the lines list does meet this constraint the add
            routine may error or may succeed - but you will be unable to read
            the data back accurately. (Checking the lines have been split
            correctly is expensive and extremely unlikely to catch bugs so it
            is not done at runtime unless check_content is True.)
        :param parent_texts: An optional dictionary containing the opaque 
            representations of some or all of the parents of version_id to
            allow delta optimisations.  VERY IMPORTANT: the texts must be those
            returned by add_lines or data corruption can be caused.
        :param left_matching_blocks: a hint about which areas are common
            between the text and its left-hand-parent.  The format is
            the SequenceMatcher.get_matching_blocks format.
        :param nostore_sha: Raise ExistingContent and do not add the lines to
            the versioned file if the digest of the lines matches this.
        :param random_id: If True a random id has been selected rather than
            an id determined by some deterministic process such as a converter
            from a foreign VCS. When True the backend may choose not to check
            for uniqueness of the resulting key within the versioned file, so
            this should only be done when the result is expected to be unique
            anyway.
        :param check_content: If True, the lines supplied are verified to be
            bytestrings that are correctly formed lines.
        :return: The text sha1, the number of bytes in the text, and an opaque
                 representation of the inserted version which can be provided
                 back to future add_lines calls in the parent_texts dictionary.
        """
        version_id = osutils.safe_revision_id(version_id)
        parents = [osutils.safe_revision_id(v) for v in parents]
        self._check_write_ok()
        return self._add_lines(version_id, parents, lines, parent_texts,
            left_matching_blocks, nostore_sha, random_id, check_content)

    def _add_lines(self, version_id, parents, lines, parent_texts,
        left_matching_blocks, nostore_sha, random_id, check_content):
        """Helper to do the class specific add_lines."""
        raise NotImplementedError(self.add_lines)

    def add_lines_with_ghosts(self, version_id, parents, lines,
        parent_texts=None, nostore_sha=None, random_id=False,
        check_content=True):
        """Add lines to the versioned file, allowing ghosts to be present.
        
        This takes the same parameters as add_lines and returns the same.
        """
        version_id = osutils.safe_revision_id(version_id)
        parents = [osutils.safe_revision_id(v) for v in parents]
        self._check_write_ok()
        return self._add_lines_with_ghosts(version_id, parents, lines,
            parent_texts, nostore_sha, random_id, check_content)

    def _add_lines_with_ghosts(self, version_id, parents, lines, parent_texts,
        nostore_sha, random_id, check_content):
        """Helper to do class specific add_lines_with_ghosts."""
        raise NotImplementedError(self.add_lines_with_ghosts)

    def check(self, progress_bar=None):
        """Check the versioned file for integrity."""
        raise NotImplementedError(self.check)

    def _check_lines_not_unicode(self, lines):
        """Check that lines being added to a versioned file are not unicode."""
        for line in lines:
            if line.__class__ is not str:
                raise errors.BzrBadParameterUnicode("lines")

    def _check_lines_are_lines(self, lines):
        """Check that the lines really are full lines without inline EOL."""
        for line in lines:
            if '\n' in line[:-1]:
                raise errors.BzrBadParameterContainsNewline("lines")

    def _check_write_ok(self):
        """Is the versioned file marked as 'finished' ? Raise if it is."""
        if self.finished:
            raise errors.OutSideTransaction()
        if self._access_mode != 'w':
            raise errors.ReadOnlyObjectDirtiedError(self)

    def enable_cache(self):
        """Tell this versioned file that it should cache any data it reads.
        
        This is advisory, implementations do not have to support caching.
        """
        pass
    
    def clear_cache(self):
        """Remove any data cached in the versioned file object.

        This only needs to be supported if caches are supported
        """
        pass

    def clone_text(self, new_version_id, old_version_id, parents):
        """Add an identical text to old_version_id as new_version_id.

        Must raise RevisionNotPresent if the old version or any of the
        parents are not present in file history.

        Must raise RevisionAlreadyPresent if the new version is
        already present in file history."""
        new_version_id = osutils.safe_revision_id(new_version_id)
        old_version_id = osutils.safe_revision_id(old_version_id)
        parents = [osutils.safe_revision_id(v) for v in parents]
        self._check_write_ok()
        return self._clone_text(new_version_id, old_version_id, parents)

    def _clone_text(self, new_version_id, old_version_id, parents):
        """Helper function to do the _clone_text work."""
        raise NotImplementedError(self.clone_text)

    def create_empty(self, name, transport, mode=None):
        """Create a new versioned file of this exact type.

        :param name: the file name
        :param transport: the transport
        :param mode: optional file mode.
        """
        raise NotImplementedError(self.create_empty)

    def get_format_signature(self):
        """Get a text description of the data encoding in this file.
        
        :since: 0.90
        """
        raise NotImplementedError(self.get_format_signature)

    def make_mpdiffs(self, version_ids):
        """Create multiparent diffs for specified versions."""
        knit_versions = set()
        for version_id in version_ids:
            knit_versions.add(version_id)
            knit_versions.update(self.get_parents(version_id))
        lines = dict(zip(knit_versions,
            self._get_lf_split_line_list(knit_versions)))
        diffs = []
        for version_id in version_ids:
            target = lines[version_id]
            parents = [lines[p] for p in self.get_parents(version_id)]
            if len(parents) > 0:
                left_parent_blocks = self._extract_blocks(version_id,
                                                          parents[0], target)
            else:
                left_parent_blocks = None
            diffs.append(multiparent.MultiParent.from_lines(target, parents,
                         left_parent_blocks))
        return diffs

    def _extract_blocks(self, version_id, source, target):
        return None

    def add_mpdiffs(self, records):
        """Add mpdiffs to this VersionedFile.

        Records should be iterables of version, parents, expected_sha1,
        mpdiff. mpdiff should be a MultiParent instance.
        """
        # Does this need to call self._check_write_ok()? (IanC 20070919)
        vf_parents = {}
        mpvf = multiparent.MultiMemoryVersionedFile()
        versions = []
        for version, parent_ids, expected_sha1, mpdiff in records:
            versions.append(version)
            mpvf.add_diff(mpdiff, version, parent_ids)
        needed_parents = set()
        for version, parent_ids, expected_sha1, mpdiff in records:
            needed_parents.update(p for p in parent_ids
                                  if not mpvf.has_version(p))
        for parent_id, lines in zip(needed_parents,
                                 self._get_lf_split_line_list(needed_parents)):
            mpvf.add_version(lines, parent_id, [])
        for (version, parent_ids, expected_sha1, mpdiff), lines in\
            zip(records, mpvf.get_line_list(versions)):
            if len(parent_ids) == 1:
                left_matching_blocks = list(mpdiff.get_matching_blocks(0,
                    mpvf.get_diff(parent_ids[0]).num_lines()))
            else:
                left_matching_blocks = None
            _, _, version_text = self.add_lines(version, parent_ids, lines,
                vf_parents, left_matching_blocks=left_matching_blocks)
            vf_parents[version] = version_text
        for (version, parent_ids, expected_sha1, mpdiff), sha1 in\
             zip(records, self.get_sha1s(versions)):
            if expected_sha1 != sha1:
                raise errors.VersionedFileInvalidChecksum(version)

    def get_sha1(self, version_id):
        """Get the stored sha1 sum for the given revision.
        
        :param version_id: The name of the version to lookup
        """
        raise NotImplementedError(self.get_sha1)

    def get_sha1s(self, version_ids):
        """Get the stored sha1 sums for the given revisions.

        :param version_ids: The names of the versions to lookup
        :return: a list of sha1s in order according to the version_ids
        """
        raise NotImplementedError(self.get_sha1s)

    def get_suffixes(self):
        """Return the file suffixes associated with this versioned file."""
        raise NotImplementedError(self.get_suffixes)
    
    def get_text(self, version_id):
        """Return version contents as a text string.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        return ''.join(self.get_lines(version_id))
    get_string = get_text

    def get_texts(self, version_ids):
        """Return the texts of listed versions as a list of strings.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        return [''.join(self.get_lines(v)) for v in version_ids]

    def get_lines(self, version_id):
        """Return version contents as a sequence of lines.

        Raises RevisionNotPresent if version is not present in
        file history.
        """
        raise NotImplementedError(self.get_lines)

    def _get_lf_split_line_list(self, version_ids):
        return [StringIO(t).readlines() for t in self.get_texts(version_ids)]

    def get_ancestry(self, version_ids, topo_sorted=True):
        """Return a list of all ancestors of given version(s). This
        will not include the null revision.

        This list will not be topologically sorted if topo_sorted=False is
        passed.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history."""
        if isinstance(version_ids, basestring):
            version_ids = [version_ids]
        raise NotImplementedError(self.get_ancestry)
        
    def get_ancestry_with_ghosts(self, version_ids):
        """Return a list of all ancestors of given version(s). This
        will not include the null revision.

        Must raise RevisionNotPresent if any of the given versions are
        not present in file history.
        
        Ghosts that are known about will be included in ancestry list,
        but are not explicitly marked.
        """
        raise NotImplementedError(self.get_ancestry_with_ghosts)
        
    def get_graph(self, version_ids=None):
        """Return a graph from the versioned file. 
        
        Ghosts are not listed or referenced in the graph.
        :param version_ids: Versions to select.
                            None means retrieve all versions.
        """
        if version_ids is None:
            return dict(self.iter_parents(self.versions()))
        result = {}
        pending = set(osutils.safe_revision_id(v) for v in version_ids)
        while pending:
            this_iteration = pending
            pending = set()
            for version, parents in self.iter_parents(this_iteration):
                result[version] = parents
                for parent in parents:
                    if parent in result:
                        continue
                    pending.add(parent)
        return result

    def get_graph_with_ghosts(self):
        """Return a graph for the entire versioned file.
        
        Ghosts are referenced in parents list but are not
        explicitly listed.
        """
        raise NotImplementedError(self.get_graph_with_ghosts)

    def get_parents(self, version_id):
        """Return version names for parents of a version.

        Must raise RevisionNotPresent if version is not present in
        file history.
        """
        raise NotImplementedError(self.get_parents)

    def get_parents_with_ghosts(self, version_id):
        """Return version names for parents of version_id.

        Will raise RevisionNotPresent if version_id is not present
        in the history.

        Ghosts that are known about will be included in the parent list,
        but are not explicitly marked.
        """
        raise NotImplementedError(self.get_parents_with_ghosts)

    def annotate_iter(self, version_id):
        """Yield list of (version-id, line) pairs for the specified
        version.

        Must raise RevisionNotPresent if the given version is
        not present in file history.
        """
        raise NotImplementedError(self.annotate_iter)

    def annotate(self, version_id):
        return list(self.annotate_iter(version_id))

    def join(self, other, pb=None, msg=None, version_ids=None,
             ignore_missing=False):
        """Integrate versions from other into this versioned file.

        If version_ids is None all versions from other should be
        incorporated into this versioned file.

        Must raise RevisionNotPresent if any of the specified versions
        are not present in the other file's history unless ignore_missing
        is supplied in which case they are silently skipped.
        """
        self._check_write_ok()
        return InterVersionedFile.get(other, self).join(
            pb,
            msg,
            version_ids,
            ignore_missing)

    def iter_lines_added_or_present_in_versions(self, version_ids=None, 
                                                pb=None):
        """Iterate over the lines in the versioned file from version_ids.

        This may return lines from other versions, and does not return the
        specific version marker at this point. The api may be changed
        during development to include the version that the versioned file
        thinks is relevant, but given that such hints are just guesses,
        its better not to have it if we don't need it.

        If a progress bar is supplied, it may be used to indicate progress.
        The caller is responsible for cleaning up progress bars (because this
        is an iterator).

        NOTES: Lines are normalised: they will all have \n terminators.
               Lines are returned in arbitrary order.
        """
        raise NotImplementedError(self.iter_lines_added_or_present_in_versions)

    def iter_parents(self, version_ids):
        """Iterate through the parents for many version ids.

        :param version_ids: An iterable yielding version_ids.
        :return: An iterator that yields (version_id, parents). Requested 
            version_ids not present in the versioned file are simply skipped.
            The order is undefined, allowing for different optimisations in
            the underlying implementation.
        """
        for version_id in version_ids:
            try:
                yield version_id, tuple(self.get_parents(version_id))
            except errors.RevisionNotPresent:
                pass

    def transaction_finished(self):
        """The transaction that this file was opened in has finished.

        This records self.finished = True and should cause all mutating
        operations to error.
        """
        self.finished = True

    def plan_merge(self, ver_a, ver_b):
        """Return pseudo-annotation indicating how the two versions merge.

        This is computed between versions a and b and their common
        base.

        Weave lines present in none of them are skipped entirely.

        Legend:
        killed-base Dead in base revision
        killed-both Killed in each revision
        killed-a    Killed in a
        killed-b    Killed in b
        unchanged   Alive in both a and b (possibly created in both)
        new-a       Created in a
        new-b       Created in b
        ghost-a     Killed in a, unborn in b    
        ghost-b     Killed in b, unborn in a
        irrelevant  Not in either revision
        """
        raise NotImplementedError(VersionedFile.plan_merge)
        
    def weave_merge(self, plan, a_marker=TextMerge.A_MARKER,
                    b_marker=TextMerge.B_MARKER):
        return PlanWeaveMerge(plan, a_marker, b_marker).merge_lines()[0]

    def check_parents(self, revision_ids, get_text_version, file_id,
            parents_provider, repo_graph, get_inventory):
        result = {}
        from bzrlib.trace import mutter
        for num, revision_id in enumerate(revision_ids):
            text_revision = get_text_version(file_id, revision_id)
            if text_revision is None:
                continue
            # calculate the right parents for this version of this file
            parents_of_text_revision = parents_provider.get_parents(
                [text_revision])[0]
            parents_from_inventories = []
            for parent in parents_of_text_revision:
                if parent == 'null:':
                    continue
                try:
                    inventory = get_inventory(parent)
                except errors.RevisionNotPresent:
                    pass
                else:
                    introduced_in = inventory[file_id].revision
                    parents_from_inventories.append(introduced_in)
            del parent
            mutter('%r:%r introduced in: %r',
                   file_id, revision_id, parents_from_inventories)
            heads = set(repo_graph.heads(parents_from_inventories))
            mutter('    heads: %r', heads)
            new_parents = []
            for parent in parents_from_inventories:
                if parent in heads and parent not in new_parents:
                    new_parents.append(parent)
            mutter('    calculated parents: %r', new_parents)
            knit_parents = self.get_parents(text_revision)
            mutter('    knit parents: %r', knit_parents)
            if new_parents != knit_parents:
                result[revision_id] = (knit_parents, new_parents)
        mutter('    RESULT: %r', result)
        return result

    def find_bad_ancestors(self, revision_ids, get_text_version, file_id,
            parents_provider, repo_graph):
        """Search this versionedfile for ancestors that are not referenced.

        One possible deviation is if a text's parents are not a subset of its
        revision's parents' last-modified revisions.  This deviation prevents
        fileids_altered_by_revision_ids from correctly determining which
        revisions of each text need to be fetched.

        This method detects this case.

        :param revision_ids: The revisions to scan for deviations
        :param file_id: The file-id of the versionedfile to scan
        :param get_text_version: a callable that takes two arguments,
            file_id and a revision_id, and returns the id of text version of
            that file in that revision.
        :param parents_provider: An implementation of ParentsProvider to use
            for determining the revision graph's ancestry.
            _RevisionParentsProvider is recommended for this purpose.

        :returns: a dict mapping bad parents to a set of revisions they occur
            in.
        """
        result = {}
        from bzrlib.trace import mutter
        for num, revision_id in enumerate(revision_ids):

            #if revision_id == 'broken-revision-1-2': import pdb; pdb.set_trace()
            #if revision_id == 'broken-revision-1-2':
            #    result.setdefault('parent-1',set()).add('broken-revision-1-2')
            #    result.setdefault('parent-2',set()).add('broken-revision-1-2')
            text_revision = get_text_version(file_id, revision_id)
            if text_revision is None:
                continue

            file_parents = parents_provider.get_parents([text_revision])[0]
            revision_parents = set()
            for parent_id in file_parents:
                try:
                    revision_parents.add(get_text_version(file_id, parent_id))
                # Skip ghosts (this means they can't provide texts...)
                except errors.RevisionNotPresent:
                    continue
            # XXX:
            knit_parents = set(self.get_parents(text_revision))
            unreferenced = knit_parents.difference(revision_parents)
            for unreferenced_id in unreferenced:
                result.setdefault(unreferenced_id, set()).add(text_revision)

            correct_parents = tuple(repo_graph.heads(knit_parents))
            spurious_parents = knit_parents.difference(correct_parents)
            for spurious_parent in spurious_parents:
                result.setdefault(spurious_parent, set()).add(text_revision)
            # XXX: false positives
            #text_parents = self.get_parents(text_revision)
            #if text_parents != file_parents:
            #    for text_parent in text_parents:
            #        result.setdefault(text_parent, set()).add(text_revision)
        mutter('find_bad_ancestors: %r', result)
        return result


class PlanWeaveMerge(TextMerge):
    """Weave merge that takes a plan as its input.
    
    This exists so that VersionedFile.plan_merge is implementable.
    Most callers will want to use WeaveMerge instead.
    """

    def __init__(self, plan, a_marker=TextMerge.A_MARKER,
                 b_marker=TextMerge.B_MARKER):
        TextMerge.__init__(self, a_marker, b_marker)
        self.plan = plan

    def _merge_struct(self):
        lines_a = []
        lines_b = []
        ch_a = ch_b = False

        def outstanding_struct():
            if not lines_a and not lines_b:
                return
            elif ch_a and not ch_b:
                # one-sided change:
                yield(lines_a,)
            elif ch_b and not ch_a:
                yield (lines_b,)
            elif lines_a == lines_b:
                yield(lines_a,)
            else:
                yield (lines_a, lines_b)
       
        # We previously considered either 'unchanged' or 'killed-both' lines
        # to be possible places to resynchronize.  However, assuming agreement
        # on killed-both lines may be too aggressive. -- mbp 20060324
        for state, line in self.plan:
            if state == 'unchanged':
                # resync and flush queued conflicts changes if any
                for struct in outstanding_struct():
                    yield struct
                lines_a = []
                lines_b = []
                ch_a = ch_b = False
                
            if state == 'unchanged':
                if line:
                    yield ([line],)
            elif state == 'killed-a':
                ch_a = True
                lines_b.append(line)
            elif state == 'killed-b':
                ch_b = True
                lines_a.append(line)
            elif state == 'new-a':
                ch_a = True
                lines_a.append(line)
            elif state == 'new-b':
                ch_b = True
                lines_b.append(line)
            else:
                assert state in ('irrelevant', 'ghost-a', 'ghost-b', 
                                 'killed-base', 'killed-both'), state
        for struct in outstanding_struct():
            yield struct


class WeaveMerge(PlanWeaveMerge):
    """Weave merge that takes a VersionedFile and two versions as its input."""

    def __init__(self, versionedfile, ver_a, ver_b, 
        a_marker=PlanWeaveMerge.A_MARKER, b_marker=PlanWeaveMerge.B_MARKER):
        plan = versionedfile.plan_merge(ver_a, ver_b)
        PlanWeaveMerge.__init__(self, plan, a_marker, b_marker)


class InterVersionedFile(InterObject):
    """This class represents operations taking place between two VersionedFiles.

    Its instances have methods like join, and contain
    references to the source and target versionedfiles these operations can be 
    carried out on.

    Often we will provide convenience methods on 'versionedfile' which carry out
    operations with another versionedfile - they will always forward to
    InterVersionedFile.get(other).method_name(parameters).
    """

    _optimisers = []
    """The available optimised InterVersionedFile types."""

    def join(self, pb=None, msg=None, version_ids=None, ignore_missing=False):
        """Integrate versions from self.source into self.target.

        If version_ids is None all versions from source should be
        incorporated into this versioned file.

        Must raise RevisionNotPresent if any of the specified versions
        are not present in the other file's history unless ignore_missing is 
        supplied in which case they are silently skipped.
        """
        # the default join: 
        # - if the target is empty, just add all the versions from 
        #   source to target, otherwise:
        # - make a temporary versioned file of type target
        # - insert the source content into it one at a time
        # - join them
        if not self.target.versions():
            target = self.target
        else:
            # Make a new target-format versioned file. 
            temp_source = self.target.create_empty("temp", MemoryTransport())
            target = temp_source
        version_ids = self._get_source_version_ids(version_ids, ignore_missing)
        graph = self.source.get_graph(version_ids)
        order = tsort.topo_sort(graph.items())
        pb = ui.ui_factory.nested_progress_bar()
        parent_texts = {}
        try:
            # TODO for incremental cross-format work:
            # make a versioned file with the following content:
            # all revisions we have been asked to join
            # all their ancestors that are *not* in target already.
            # the immediate parents of the above two sets, with 
            # empty parent lists - these versions are in target already
            # and the incorrect version data will be ignored.
            # TODO: for all ancestors that are present in target already,
            # check them for consistent data, this requires moving sha1 from
            # 
            # TODO: remove parent texts when they are not relevant any more for 
            # memory pressure reduction. RBC 20060313
            # pb.update('Converting versioned data', 0, len(order))
            for index, version in enumerate(order):
                pb.update('Converting versioned data', index, len(order))
                _, _, parent_text = target.add_lines(version,
                                               self.source.get_parents(version),
                                               self.source.get_lines(version),
                                               parent_texts=parent_texts)
                parent_texts[version] = parent_text
            
            # this should hit the native code path for target
            if target is not self.target:
                return self.target.join(temp_source,
                                        pb,
                                        msg,
                                        version_ids,
                                        ignore_missing)
        finally:
            pb.finished()

    def _get_source_version_ids(self, version_ids, ignore_missing):
        """Determine the version ids to be used from self.source.

        :param version_ids: The caller-supplied version ids to check. (None 
                            for all). If None is in version_ids, it is stripped.
        :param ignore_missing: if True, remove missing ids from the version 
                               list. If False, raise RevisionNotPresent on
                               a missing version id.
        :return: A set of version ids.
        """
        if version_ids is None:
            # None cannot be in source.versions
            return set(self.source.versions())
        else:
            version_ids = [osutils.safe_revision_id(v) for v in version_ids]
            if ignore_missing:
                return set(self.source.versions()).intersection(set(version_ids))
            else:
                new_version_ids = set()
                for version in version_ids:
                    if version is None:
                        continue
                    if not self.source.has_version(version):
                        raise errors.RevisionNotPresent(version, str(self.source))
                    else:
                        new_version_ids.add(version)
                return new_version_ids
