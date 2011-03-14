# Copyright (C) 2010 Canonical Ltd
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

"""Merge logic for changelog_merge plugin."""

import difflib

from bzrlib import merge
from bzrlib import debug
from bzrlib.merge3 import Merge3
from bzrlib.trace import mutter


def changelog_entries(lines):
    """Return a list of changelog entries.

    :param lines: lines of a changelog file.
    :returns: list of entries.  Each entry is a tuple of lines.
    """
    entries = []
    for line in lines:
        if line[0] not in (' ', '\t', '\n'):
            # new entry
            entries.append([line])
        else:
            try:
                entry = entries[-1]
            except IndexError:
                # Cope with leading blank lines.
                entries.append([])
                entry = entries[-1]
            entry.append(line)
    return map(tuple, entries)


def entries_to_lines(entries):
    """Turn a list of entries into a flat iterable of lines."""
    for entry in entries:
        for line in entry:
            yield line


class ChangeLogMerger(merge.ConfigurableFileMerger):
    """Merge GNU-format ChangeLog files."""

    name_prefix = "changelog"

    def get_filepath(self, params, tree):
        """Calculate the path to the file in a tree.

        This is overridden to return just the basename, rather than full path,
        so that e.g. if the config says ``changelog_merge_files = ChangeLog``,
        then all ChangeLog files in the tree will match (not just one in the
        root of the tree).
        
        :param params: A MergeHookParams describing the file to merge
        :param tree: a Tree, e.g. self.merger.this_tree.
        """
        return tree.inventory[params.file_id].name

    def merge_text(self, params):
        """Merge changelog changes.

         * new entries from other will float to the top
         * edits to older entries are preserved
        """
        # Transform files into lists of changelog entries
        this_entries = changelog_entries(params.this_lines)
        other_entries = changelog_entries(params.other_lines)
        base_entries = changelog_entries(params.base_lines)
        try:
            result_entries = merge_entries(
                base_entries, this_entries, other_entries)
        except EntryConflict:
            return 'not_applicable' # XXX: generating a nice conflict file
                                    # would be better
        # Transform the merged elements back into real blocks of lines.
        return 'success', entries_to_lines(result_entries)


class EntryConflict(Exception):
    pass


def merge_entries_old(base_entries, this_entries, other_entries):
    # Determine which entries have been added by other (compared to base)
    base_entries = frozenset(base_entries)
    new_in_other = [
        entry for entry in other_entries if entry not in base_entries]
    # Prepend them to the entries in this
    result_entries = new_in_other + this_entries
    return result_entries


def default_guess_edits(new_entries, deleted_entries, entry_as_str=''.join):
    # This algorithm does O(N^2 * logN) SequenceMatcher.ratio() calls, which is
    # pretty bad, but it shouldn't be used very often.
    deleted_entries_as_strs = [
        entry_as_str(entry) for entry in deleted_entries]
    new_entries_as_strs = [
        entry_as_str(entry) for entry in new_entries]
    result_new = list(new_entries)
    result_deleted = list(deleted_entries)
    result_edits = []
    sm = difflib.SequenceMatcher()
    CUTOFF = 0.8
    while True:
        best = None
        best_score = None
        for new_entry in new_entries:
            new_entry_as_str = entry_as_str(new_entry)
            sm.set_seq1(new_entry_as_str)
            for old_entry_as_str in deleted_entries_as_strs:
                sm.set_seq2(old_entry_as_str)
                score = sm.ratio()
                if score > CUTOFF:
                    if best_score is None or score > best_score:
                        best = new_entry_as_str, old_entry_as_str
                        best_score = score
        if best is not None:
            del_index = deleted_entries_as_strs.index(best[1])
            new_index = new_entries_as_strs.index(best[0])
            result_edits.append(
                (result_deleted[del_index], result_new[new_index]))
            del deleted_entries_as_strs[del_index], result_deleted[del_index]
            del new_entries_as_strs[new_index], result_new[new_index]
        else:
            break
    return result_new, result_deleted, result_edits


def merge_entries_new(base_entries, this_entries, other_entries,
        guess_edits=default_guess_edits):
    m3 = Merge3(base_entries, this_entries, other_entries,
        allow_objects=True)
    result_entries = []
    at_top = True
    for group in m3.merge_groups():
        if 'changelog_merge' in debug.debug_flags:
            mutter('merge group:\n%r', group)
        group_kind = group[0]
        if group_kind == 'conflict':
            _, base, this, other = group
            # Find additions
            new_in_other = [
                entry for entry in other if entry not in base]
            # Find deletions
            deleted_in_other = [
                entry for entry in base if entry not in other]
            if at_top and deleted_in_other:
                # Magic!  Compare deletions and additions to try spot edits
                new_in_other, deleted_in_other, edits_in_other = guess_edits(
                    new_in_other, deleted_in_other)
            else:
                # Changes not made at the top are always preserved as is, no
                # need to try distinguish edits from adds and deletes.
                edits_in_other = []
            if 'changelog_merge' in debug.debug_flags:
                mutter('at_top: %r', at_top)
                mutter('new_in_other: %r', new_in_other)
                mutter('deleted_in_other: %r', deleted_in_other)
                mutter('edits_in_other: %r', edits_in_other)
            # Apply deletes and edits
            updated_this = [
                entry for entry in this if entry not in deleted_in_other]
            for old_entry, new_entry in edits_in_other:
                try:
                    index = updated_this.index(old_entry)
                except ValueError:
                    # edited entry no longer present in this!  Just give up and
                    # declare a conflict.
                    raise EntryConflict()
                updated_this[index] = new_entry
            if 'changelog_merge' in debug.debug_flags:
                mutter('updated_this: %r', updated_this)
            if at_top:
                # Float new entries from other to the top
                result_entries = new_in_other + result_entries
            else:
                result_entries.extend(new_in_other)
            result_entries.extend(updated_this)
        else: # unchanged, same, a, or b.
            lines = group[1]
            result_entries.extend(lines)
        at_top = False
    return result_entries


merge_entries = merge_entries_new
