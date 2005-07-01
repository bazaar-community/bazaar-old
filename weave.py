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

# TODO: Perhaps have copy method for Weave instances?

# XXX: If we do weaves this way, will a merge still behave the same
# way if it's done in a different order?  That's a pretty desirable
# property.

# TODO: How to write these to disk?  One option is cPickle, which
# would be fast but less friendly to C, and perhaps not portable.  Another is

# TODO: Nothing here so far assumes the lines are really \n newlines,
# rather than being split up in some other way.  We could accomodate
# binaries, perhaps by naively splitting on \n or perhaps using
# something like a rolling checksum.

# TODO: Perhaps track SHA-1 in the header for protection?  This would
# be redundant with it being stored in the inventory, but perhaps
# usefully so?

# TODO: Track version names as well as indexes. 

# TODO: Probably do transitive expansion when specifying parents?

# TODO: Separate out some code to read and write weaves.

# TODO: End marker for each version so we can stop reading?

# TODO: Check that no insertion occurs inside a deletion that was
# active in the version of the insertion.

# TODO: Perhaps a special slower check() method that verifies more
# nesting constraints and the MD5 of each version?



try:
    set
    frozenset
except NameError:
    from sets import Set, ImmutableSet
    set = Set
    frozenset = ImmutableSet
    del Set, ImmutableSet


class WeaveError(Exception):
    """Exception in processing weave"""


class WeaveFormatError(WeaveError):
    """Weave invariant violated"""
    

class Weave(object):
    """weave - versioned text file storage.
    
    A Weave manages versions of line-based text files, keeping track
    of the originating version for each line.

    To clients the "lines" of the file are represented as a list of strings.
    These strings  will typically have terminal newline characters, but
    this is not required.  In particular files commonly do not have a newline
    at the end of the file.

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
    integer version index.  There is no replace operator, only deletes
    and inserts.

    Constraints/notes:

    * A later version can delete lines that were introduced by any
      number of ancestor versions; this implies that deletion
      instructions can span insertion blocks without regard to the
      insertion block's nesting.

    * Similarly, deletions need not be properly nested with regard to
      each other, because they might have been generated by
      independent revisions.

    * Insertions are always made by inserting a new bracketed block
      into a single point in the previous weave.  This implies they
      can nest but not overlap, and the nesting must always have later
      insertions on the inside.

    * It doesn't seem very useful to have an active insertion
      inside an inactive insertion, but it might happen.
      
    * Therefore, all instructions are always"considered"; that
      is passed onto and off the stack.  An outer inactive block
      doesn't disable an inner block.

    * Lines are enabled if the most recent enclosing insertion is
      active and none of the enclosing deletions are active.

    * There is no point having a deletion directly inside its own
      insertion; you might as well just not write it.  And there
      should be no way to get an earlier version deleting a later
      version.

    _l
        Text of the weave. 

    _v
        List of versions, indexed by index number.

        For each version we store the set (included_versions), which
        lists the previous versions also considered active; the
        versions included in those versions are included transitively.
        So new versions created from nothing list []; most versions
        have a single entry; some have more.

    _sha1s
        List of hex SHA-1 of each version, or None if not recorded.
    """
    def __init__(self):
        self._l = []
        self._v = []
        self._sha1s = []


    def __eq__(self, other):
        if not isinstance(other, Weave):
            return False
        return self._v == other._v \
               and self._l == other._l
    

    def __ne__(self, other):
        return not self.__eq__(other)

        
    def add(self, parents, text):
        """Add a single text on top of the weave.
  
        Returns the index number of the newly added version.

        parents
            List or set of parent version numbers.  This must normally include
            the parents and the parent's parents, or wierd things might happen.

        text
            Sequence of lines to be added in the new version."""
        ## self._check_versions(parents)
        ## self._check_lines(text)
        idx = len(self._v)

        import sha
        s = sha.new()
        for l in text:
            s.update(l)
        sha1 = s.hexdigest()
        del s

        if parents:
            delta = self._delta(self.inclusions(parents), text)

            # offset gives the number of lines that have been inserted
            # into the weave up to the current point; if the original edit instruction
            # says to change line A then we actually change (A+offset)
            offset = 0

            for i1, i2, newlines in delta:
                assert 0 <= i1
                assert i1 <= i2
                assert i2 <= len(self._l)

                # the deletion and insertion are handled separately.
                # first delete the region.
                if i1 != i2:
                    self._l.insert(i1+offset, ('[', idx))
                    self._l.insert(i2+offset+1, (']', idx))
                    offset += 2
                    # is this OK???

                if newlines:
                    # there may have been a deletion spanning up to
                    # i2; we want to insert after this region to make sure
                    # we don't destroy ourselves
                    i = i2 + offset
                    self._l[i:i] = [('{', idx)] \
                                   + newlines \
                                   + [('}', idx)]
                    offset += 2 + len(newlines)

            self._addversion(parents)
        else:
            # special case; adding with no parents revision; can do this
            # more quickly by just appending unconditionally
            self._l.append(('{', idx))
            self._l += text
            self._l.append(('}', idx))

            self._addversion(None)

        self._sha1s.append(sha1)
            
        return idx


    def inclusions(self, versions):
        """Expand out everything included by versions."""
        i = set(versions)
        for v in versions:
            i.update(self._v[v])
        return i


    def _addversion(self, parents):
        if parents:
            self._v.append(frozenset(parents))
        else:
            self._v.append(frozenset())


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


    def annotate_iter(self, version):
        """Yield list of (index-id, line) pairs for the specified version.

        The index indicates when the line originated in the weave."""
        included = self.inclusions([version])
        for origin, lineno, text in self._extract(included):
            yield origin, text


    def _extract(self, included):
        """Yield annotation of lines in included set.

        Yields a sequence of tuples (origin, lineno, text), where
        origin is the origin version, lineno the index in the weave,
        and text the text of the line.

        The set typically but not necessarily corresponds to a version.
        """
        istack = []          # versions for which an insertion block is current

        dset = set()         # versions for which a deletion block is current

        isactive = None

        lineno = 0         # line of weave, 0-based

        # TODO: Probably only need to put included revisions in the istack

        # TODO: Could split this into two functions, one that updates
        # the stack and the other that processes the results -- but
        # I'm not sure it's really needed.

        # TODO: In fact, I think we only need to store the *count* of
        # active insertions and deletions, and we can maintain that by
        # just by just counting as we go along.

        WFE = WeaveFormatError
        
        for l in self._l:
            if isinstance(l, tuple):
                isactive = None         # recalculate
                c, v = l
                if c == '{':
                    if istack and (istack[-1] >= v):
                        raise WFE("improperly nested insertions %d>=%d on line %d" 
                                  % (istack[-1], v, lineno))
                    istack.append(v)
                elif c == '}':
                    try:
                        oldv = istack.pop()
                    except IndexError:
                        raise WFE("unmatched close of insertion %d on line %d"
                                  % (v, lineno))
                    if oldv != v:
                        raise WFE("mismatched close of insertion %d!=%d on line %d"
                                  % (oldv, v, lineno))
                elif c == '[':
                    # block deleted in v
                    if v in dset:
                        raise WFE("repeated deletion marker for version %d on line %d"
                                  % (v, lineno))
                    if istack:
                        if istack[-1] == v:
                            raise WFE("version %d deletes own text on line %d"
                                      % (v, lineno))
                        dset.add(v)
                elif c == ']':
                    if v in dset:
                        dset.remove(v)
                    else:
                        raise WFE("unmatched close of deletion %d on line %d"
                                  % (v, lineno))
                else:
                    raise WFE("invalid processing instruction %r on line %d"
                              % (l, lineno))
            else:
                assert isinstance(l, basestring)
                if not istack:
                    raise WFE("literal at top level on line %d"
                              % lineno)
                if isactive == None:
                    isactive = (istack[-1] in included) \
                               and not included.intersection(dset)
                if isactive:
                    origin = istack[-1]
                    yield origin, lineno, l
            lineno += 1

        if istack:
            raise WFE("unclosed insertion blocks at end of weave",
                                   istack)
        if dset:
            raise WFE("unclosed deletion blocks at end of weave",
                                   dset)


    def get_iter(self, version):
        """Yield lines for the specified version."""
        for origin, lineno, line in self._extract(self.inclusions([version])):
            yield line


    def get(self, index):
        return list(self.get_iter(index))


    def merge_iter(self, included):
        """Return composed version of multiple included versions."""
        included = frozenset(included)
        for origin, lineno, text in self._extract(included):
            yield text


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
                    raise WeaveFormatError("invalid included version %d for index %d"
                                               % (vi, index))
                if vi in included:
                    raise WeaveFormatError("repeated included version %d for index %d"
                                               % (vi, index))
                included.add(vi)



    def _delta(self, included, lines):
        """Return changes from basis to new revision.

        The old text for comparison is the union of included revisions.

        This is used in inserting a new text.

        Delta is returned as a sequence of
        (weave1, weave2, newlines).

        This indicates that weave1:weave2 of the old weave should be
        replaced by the sequence of lines in newlines.  Note that
        these line numbers are positions in the total weave and don't
        correspond to the lines in any extracted version, or even the
        extracted union of included versions.

        If line1=line2, this is a pure insert; if newlines=[] this is a
        pure delete.  (Similar to difflib.)
        """
        # basis a list of (origin, lineno, line)
        basis_lineno = []
        basis_lines = []
        for origin, lineno, line in self._extract(included):
            basis_lineno.append(lineno)
            basis_lines.append(line)

        # add a sentinal, because we can also match against the final line
        basis_lineno.append(len(self._l))

        # XXX: which line of the weave should we really consider
        # matches the end of the file?  the current code says it's the
        # last line of the weave?

        from difflib import SequenceMatcher
        s = SequenceMatcher(None, basis_lines, lines)

        # TODO: Perhaps return line numbers from composed weave as well?

        for tag, i1, i2, j1, j2 in s.get_opcodes():
            ##print tag, i1, i2, j1, j2

            if tag == 'equal':
                continue

            # i1,i2 are given in offsets within basis_lines; we need to map them
            # back to offsets within the entire weave
            real_i1 = basis_lineno[i1]
            real_i2 = basis_lineno[i2]

            assert 0 <= j1
            assert j1 <= j2
            assert j2 <= len(lines)

            yield real_i1, real_i2, lines[j1:j2]



def weave_info(filename, out):
    """Show some text information about the weave."""
    from weavefile import read_weave
    wf = file(filename, 'rb')
    w = read_weave(wf)
    # FIXME: doesn't work on pipes
    weave_size = wf.tell()
    print >>out, "weave file size %d bytes" % weave_size
    print >>out, "weave contains %d versions" % len(w._v)

    total = 0
    print ' %8s %8s %8s' % ('version', 'lines', 'bytes')
    print ' -------- -------- --------'
    for i in range(len(w._v)):
        text = w.get(i)
        lines = len(text)
        bytes = sum((len(a) for a in text))
        print ' %8d %8d %8d' % (i, lines, bytes)
        total += bytes

    print >>out, "versions total %d bytes" % total
    print >>out, "compression ratio %.3f" % (float(total)/float(weave_size))
    


def main(argv):
    import sys
    import os
    from weavefile import write_weave_v1, read_weave_v1
    cmd = argv[1]
    if cmd == 'add':
        w = read_weave_v1(file(argv[2], 'rb'))
        # at the moment, based on everything in the file
        parents = set(range(len(w._v)))
        lines = sys.stdin.readlines()
        ver = w.add(parents, lines)
        write_weave_v1(w, file(argv[2], 'wb'))
        print 'added %d' % ver
    elif cmd == 'init':
        fn = argv[2]
        if os.path.exists(fn):
            raise IOError("file exists")
        w = Weave()
        write_weave_v1(w, file(fn, 'wb'))
    elif cmd == 'get':
        w = read_weave_v1(file(argv[2], 'rb'))
        sys.stdout.writelines(w.getiter(int(argv[3])))
    elif cmd == 'annotate':
        w = read_weave_v1(file(argv[2], 'rb'))
        # newline is added to all lines regardless; too hard to get
        # reasonable formatting otherwise
        lasto = None
        for origin, text in w.annotate(int(argv[3])):
            text = text.rstrip('\r\n')
            if origin == lasto:
                print '      | %s' % (text)
            else:
                print '%5d | %s' % (origin, text)
                lasto = origin
    elif cmd == 'info':
        weave_info(argv[2], sys.stdout)
    else:
        raise ValueError('unknown command %r' % cmd)
    

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
