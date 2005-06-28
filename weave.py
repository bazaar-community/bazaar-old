#! /usr/bin/python

# Copyright (C) 2005 Canonical Ltd

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

# Author: Martin Pool <mbp@canonical.com>


"""Weave - storage of related text file versions"""

# TODO: Perhaps have copy and comparison methods of Weave instances?


class VerInfo(object):
    """Information about a version in a Weave."""
    included = frozenset()
    def __init__(self, included=None):
        if included:
            self.included = frozenset(included)

    def __repr__(self):
        s = self.__class__.__name__ + '('
        if self.included:
            s += 'included=%r' % (list(self.included))
        s += ')'
        return s


class Weave(object):
    """weave - versioned text file storage.
    
    A Weave manages versions of line-based text files, keeping track of the
    originating version for each line.

    Texts can be identified in either of two ways:

    * a nonnegative index number.

    * a version-id string.

    Typically the index number will be valid only inside this weave and
    the version-id is used to reference it in the larger world.

    The weave is represented as a list mixing edit instructions and
    literal text.  Each entry in _l can be either a string (or
    unicode), or a tuple.  If a string, it means that the given line
    should be output in the currently active revisions.

    If a tuple, it gives a processing instruction saying in which
    revisions the enclosed lines are active.  The tuple has the form
    (instruction, version).

    The instruction can be '{' or '}' for an insertion block, and '['
    and ']' for a deletion block respectively.  The version is the
    integer version index.

    Constraints:

    * A later version can delete lines that were introduced by any
      number of ancestor versions; this implies that deletion
      instructions can span insertion blocks without regard to the
      insertion block's nesting.

    * Similarly, deletions need not be properly nested.


    _l
        Text of the weave. 

    _v
        List of versions, indexed by index number.

        For each version we store the tuple (included_versions), which
        lists the previous versions also considered active.
    """
    def __init__(self):
        self._l = []
        self._v = []

        
    def add(self, parents, text):
        """Add a single text on top of the weave.
  
        Returns the index number of the newly added version.

        parents
            List or set of parent version numbers.

        text
            Sequence of lines to be added in the new version."""
        self._check_versions(parents)
        self._check_lines(text)

        idx = len(self._v)

        if parents:
            parents = frozenset(parents)
            delta = self._delta(parents, text)

            # offset gives the number of lines that have been inserted
            # into the weave up to the current point; if the original edit instruction
            # says to change line A then we actually change (A+offset)
            offset = 0

            for i1, i2, newlines in delta:
                assert 0 <= i1
                assert i1 <= i2
                assert i2 <= len(self._l)
                
                if i1 != i2:
                    raise NotImplementedError("can't handle replacing weave [%d:%d] yet"
                                              % (i1, i2))

                self._l.insert(i1 + offset, ('{', idx))
                i = i1 + offset + 1
                self._l[i:i] = newlines
                self._l.insert(i + 1, ('}', idx))
                offset += 2 + len(newlines)

            self._v.append(VerInfo(parents))
        else:
            # special case; adding with no parents revision; can do this
            # more quickly by just appending unconditionally
            self._l.append(('{', idx))
            self._l += text
            self._l.append(('}', idx))

            self._v.append(VerInfo())
            
        return idx


    def _check_lines(self, text):
        if not isinstance(text, list):
            raise ValueError("text should be a list, not %s" % type(text))

        for l in text:
            if not isinstance(l, basestring):
                raise ValueError("text line should be a string or unicode, not %s" % type(l))
        


    def _check_versions(self, indexes):
        """Check everything in the sequence of indexes is valid"""
        for i in indexes:
            try:
                self._v[i]
            except IndexError:
                raise IndexError("invalid version number %r" % i)

    
    def annotate(self, index):
        return list(self.annotate_iter(index))


    def annotate_iter(self, index):
        """Yield list of (index-id, line) pairs for the specified version.

        The index indicates when the line originated in the weave."""
        try:
            vi = self._v[index]
        except IndexError:
            raise IndexError('version index %d out of range' % index)
        included = set(vi.included)
        included.add(index)
        for origin, lineno, text in self._extract(included):
            yield origin, text


    def _extract(self, included):
        """Yield annotation of lines in included set.

        Yields a sequence of tuples (origin, lineno, text), where
        origin is the origin version, lineno the index in the weave,
        and text the text of the line.

        The set typically but not necessarily corresponds to a version.
        """
        stack = []
        isactive = False
        lineno = 0
        
        for l in self._l:
            if isinstance(l, tuple):
                c, v = l
                if c == '{':
                    stack.append(l)
                    isactive = (v in included)
                elif c == '}':
                    oldc, oldv = stack.pop()
                    assert oldc == '{'
                    assert oldv == v
                    isactive = stack and (stack[-1][1] in included)
                else:
                    raise ValueError("invalid processing instruction %r" % (l,))
            else:
                assert isinstance(l, basestring)
                if isactive:
                    origin = stack[-1][1]
                    yield origin, lineno, l
            lineno += 1

        if stack:
            raise ValueError("unclosed blocks at end of weave",
                             stack)


    def getiter(self, index):
        """Yield lines for the specified version."""
        for origin, line in self.annotate_iter(index):
            yield line


    def get(self, index):
        return list(self.getiter(index))


    def dump(self, to_file):
        from pprint import pprint
        print >>to_file, "Weave._l = ",
        pprint(self._l, to_file)
        print >>to_file, "Weave._v = ",
        pprint(self._v, to_file)


    def check(self):
        for vers_info in self._v:
            included = set()
            for vi in vers_info[0]:
                if vi < 0 or vi >= index:
                    raise ValueError("invalid included version %d for index %d"
                                     % (vi, index))
                if vi in included:
                    raise ValueError("repeated included version %d for index %d"
                                     % (vi, index))
                included.add(vi)



    def _delta(self, included, lines):
        """Return changes from basis to new revision.

        The old text for comparison is the union of included revisions.

        This is used in inserting a new text.

        Delta is returned as a sequence of (line1, line2, newlines),
        indicating that line1 through line2 of the old weave should be
        replaced by the sequence of lines in newlines.  Note that
        these line numbers are positions in the total weave and don't
        correspond to the lines in any extracted version, or even the
        extracted union of included versions.

        If line1=line2, this is a pure insert; if newlines=[] this is a
        pure delete.  (Similar to difflib.)
        """

        self._check_versions(included)

        ##from pprint import pprint

        # first get basis for comparison
        # basis holds (lineno, origin, line)
        basis = []

        ##print 'my lines:'
        ##pprint(self._l)

        basis = list(self._extract(included))

        # now make a parallel list with only the text, to pass to the differ
        basis_lines = [line for (origin, lineno, line) in basis]

        # add a sentinal, because we can also match against the final line
        basis.append((len(self._l), None))

        # XXX: which line of the weave should we really consider matches the end of the file?
        # the current code says it's the last line of the weave?

        from difflib import SequenceMatcher
        s = SequenceMatcher(None, basis_lines, lines)

        ##print 'basis sequence:'
        ##pprint(basis)

        for tag, i1, i2, j1, j2 in s.get_opcodes():
            ##print tag, i1, i2, j1, j2

            if tag == 'equal':
                continue

            # i1,i2 are given in offsets within basis_lines; we need to map them
            # back to offsets within the entire weave
            real_i1 = basis[i1][0]
            real_i2 = basis[i2][0]

            assert 0 <= j1
            assert j1 <= j2
            assert j2 <= len(lines)

            yield real_i1, real_i2, lines[j1:j2]


