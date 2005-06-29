#!/usr/bin/env python
"""\
Read in a changeset output, and process it into a Changeset object.
"""

import bzrlib, bzrlib.changeset
import pprint
import common

class BadChangeset(Exception): pass
class MalformedHeader(BadChangeset): pass
class MalformedPatches(BadChangeset): pass
class MalformedFooter(BadChangeset): pass

def _unescape(name):
    """Now we want to find the filename effected.
    Unfortunately the filename is written out as
    repr(filename), which means that it surrounds
    the name with quotes which may be single or double
    (single is preferred unless there is a single quote in
    the filename). And some characters will be escaped.

    TODO:   There has to be some pythonic way of undo-ing the
            representation of a string rather than using eval.
    """
    delimiter = name[0]
    if name[-1] != delimiter:
        raise BadChangeset('Could not properly parse the'
                ' filename: %r' % name)
    # We need to handle escaped hexadecimals too.
    return name[1:-1].replace('\"', '"').replace("\'", "'")

class RevisionInfo(object):
    """Gets filled out for each revision object that is read.
    """
    def __init__(self, rev_id):
        self.rev_id = rev_id
        self.sha1 = None
        self.committer = None
        self.timestamp = None
        self.timezone = None
        self.inventory_id = None
        self.inventory_sha1 = None

        self.parents = None
        self.message = None

    def __str__(self):
        return pprint.pformat(self.__dict__)

    def as_revision(self):
        from bzrlib.revision import Revision, RevisionReference
        rev = Revision(revision_id=self.rev_id,
            committer=self.committer,
            timestamp=float(self.timestamp),
            timezone=int(self.timezone),
            inventory_id=self.inventory_id,
            inventory_sha1=self.inventory_sha1,
            message='\n'.join(self.message))

        for parent in self.parents:
            rev_id, sha1 = parent.split('\t')
            rev.parents.append(RevisionReference(rev_id, sha1))

        return rev




class ChangesetInfo(object):
    """This is the intermediate class that gets filled out as
    the file is read.
    """
    def __init__(self):
        self.committer = None
        self.date = None
        self.message = None
        self.base = None
        self.base_sha1 = None

        self.revisions = []

        self.timestamp = None
        self.timezone = None

        self.tree_root_id = None
        self.file_ids = None
        self.old_file_ids = None

        self.actions = [] #this is the list of things that happened
        self.id2path = {} # A mapping from file id to path name
        self.path2id = {} # The reverse mapping
        self.id2parent = {} # A mapping from a given id to it's parent id

        self.old_id2path = {}
        self.old_path2id = {}
        self.old_id2parent = {}

    def __str__(self):
        return pprint.pformat(self.__dict__)

    def create_maps(self):
        """Go through the individual id sections, and generate the 
        id2path and path2id maps.
        """
        # Rather than use an empty path, the changeset code seems 
        # to like to use "./." for the tree root.
        self.id2path[self.tree_root_id] = './.'
        self.path2id['./.'] = self.tree_root_id
        self.id2parent[self.tree_root_id] = bzrlib.changeset.NULL_ID
        self.old_id2path = self.id2path.copy()
        self.old_path2id = self.path2id.copy()
        self.old_id2parent = self.id2parent.copy()

        if self.file_ids:
            for info in self.file_ids:
                path, f_id, parent_id = info.split('\t')
                self.id2path[f_id] = path
                self.path2id[path] = f_id
                self.id2parent[f_id] = parent_id
        if self.old_file_ids:
            for info in self.old_file_ids:
                path, f_id, parent_id = info.split('\t')
                self.old_id2path[f_id] = path
                self.old_path2id[path] = f_id
                self.old_id2parent[f_id] = parent_id

    def get_changeset(self):
        """Create a changeset from the data contained within."""
        from bzrlib.changeset import Changeset, ChangesetEntry, \
            PatchApply, ReplaceContents
        cset = Changeset()
        
        entry = ChangesetEntry(self.tree_root_id, 
                bzrlib.changeset.NULL_ID, './.')
        cset.add_entry(entry)
        for info, lines in self.actions:
            parts = info.split(' ')
            action = parts[0]
            kind = parts[1]
            extra = ' '.join(parts[2:])
            if action == 'renamed':
                old_path, new_path = extra.split(' => ')
                old_path = _unescape(old_path)
                new_path = _unescape(new_path)

                new_id = self.path2id[new_path]
                old_id = self.old_path2id[old_path]
                assert old_id == new_id

                new_parent = self.id2parent[new_id]
                old_parent = self.old_id2parent[old_id]

                entry = ChangesetEntry(old_id, old_parent, old_path)
                entry.new_path = new_path
                entry.new_parent = new_parent
                if lines:
                    entry.contents_change = PatchApply(''.join(lines))
            elif action == 'removed':
                old_path = _unescape(extra)
                old_id = self.old_path2id[old_path]
                old_parent = self.old_id2parent[old_id]
                entry = ChangesetEntry(old_id, old_parent, old_path)
                entry.new_path = None
                entry.new_parent = None
                if lines:
                    # Technically a removed should be a ReplaceContents()
                    # Where you need to have the old contents
                    # But at most we have a remove style patch.
                    #entry.contents_change = ReplaceContents()
                    pass
            elif action == 'added':
                new_path = _unescape(extra)
                new_id = self.path2id[new_path]
                new_parent = self.id2parent[new_id]
                entry = ChangesetEntry(new_id, new_parent, new_path)
                entry.path = None
                entry.parent = None
                if lines:
                    # Technically an added should be a ReplaceContents()
                    # Where you need to have the old contents
                    # But at most we have an add style patch.
                    #entry.contents_change = ReplaceContents()
                    entry.contents_change = PatchApply(''.join(lines))
            elif action == 'modified':
                new_path = _unescape(extra)
                new_id = self.path2id[new_path]
                new_parent = self.id2parent[new_id]
                entry = ChangesetEntry(new_id, new_parent, new_path)
                entry.path = None
                entry.parent = None
                if lines:
                    # Technically an added should be a ReplaceContents()
                    # Where you need to have the old contents
                    # But at most we have an add style patch.
                    #entry.contents_change = ReplaceContents()
                    entry.contents_change = PatchApply(''.join(lines))
            else:
                raise BadChangeset('Unrecognized action: %r' % action)
            cset.add_entry(entry)
        return cset

class ChangesetReader(object):
    """This class reads in a changeset from a file, and returns
    a Changeset object, which can then be applied against a tree.
    """
    def __init__(self, from_file):
        """Read in the changeset from the file.

        :param from_file: A file-like object (must have iterator support).
        """
        object.__init__(self)
        self.from_file = from_file
        self._next_line = None
        
        self.info = ChangesetInfo()
        # We put the actual inventory ids in the footer, so that the patch
        # is easier to read for humans.
        # Unfortunately, that means we need to read everything before we
        # can create a proper changeset.
        self._read_header()
        self._read_patches()
        self._read_footer()

    def _next(self):
        """yield the next line, but secretly
        keep 1 extra line for peeking.
        """
        for line in self.from_file:
            last = self._next_line
            self._next_line = line
            if last is not None:
                yield last

    def get_info(self):
        """Create the actual changeset object.
        """
        self.info.create_maps()
        return self.info

    def _read_header(self):
        """Read the bzr header"""
        header = common.get_header()
        found = False
        for line in self._next():
            if found:
                if (line[:2] != '# ' or line[-1:] != '\n'
                        or line[2:-1] != header[0]):
                    raise MalformedHeader('Found a header, but it'
                        ' was improperly formatted')
                header.pop(0) # We read this line.
                if not header:
                    break # We found everything.
            elif (line[:1] == '#' and line[-1:] == '\n'):
                line = line[1:-1].strip()
                if line[:len(common.header_str)] == common.header_str:
                    if line == header[0]:
                        found = True
                    else:
                        raise MalformedHeader('Found what looks like'
                                ' a header, but did not match')
                    header.pop(0)
        else:
            raise MalformedHeader('Did not find an opening header')

        for line in self._next():
            # The bzr header is terminated with a blank line
            # which does not start with '#'
            if line == '\n':
                break
            self._handle_next(line)

    def _read_next_entry(self, line, indent=1):
        """Read in a key-value pair
        """
        if line[:1] != '#':
            raise MalformedHeader('Bzr header did not start with #')
        line = line[1:-1] # Remove the '#' and '\n'
        if line[:indent] == ' '*indent:
            line = line[indent:]
        if not line:
            return None, None# Ignore blank lines

        loc = line.find(': ')
        if loc != -1:
            key = line[:loc]
            value = line[loc+2:]
            if not value:
                value = self._read_many(indent=indent+3)
        elif line[-1:] == ':':
            key = line[:-1]
            value = self._read_many(indent=indent+3)
        else:
            raise MalformedHeader('While looking for key: value pairs,'
                    ' did not find the colon %r' % (line))

        key = key.replace(' ', '_')
        return key, value

    def _handle_next(self, line):
        key, value = self._read_next_entry(line, indent=1)
        if key is None:
            return

        if key == 'revision':
            self._read_revision(value)
        elif hasattr(self.info, key):
            if getattr(self.info, key) is None:
                setattr(self.info, key, value)
            else:
                raise MalformedHeader('Duplicated Key: %s' % key)
        else:
            # What do we do with a key we don't recognize
            raise MalformedHeader('Unknown Key: %s' % key)
        
    def _read_many(self, indent):
        """If a line ends with no entry, that means that it should be
        followed with multiple lines of values.

        This detects the end of the list, because it will be a line that
        does not start properly indented.
        """
        values = []
        start = '#' + (' '*indent)

        if self._next_line[:len(start)] != start:
            return values

        for line in self._next():
            values.append(line[len(start):-1])
            if self._next_line[:len(start)] != start:
                break
        return values

    def _read_one_patch(self):
        """Read in one patch, return the complete patch, along with
        the next line.

        :return: action, lines, do_continue
        """
        # Peek and see if there are no patches
        if self._next_line[:1] == '#':
            return None, [], False

        line = self._next().next()
        if line[:3] != '***':
            raise MalformedPatches('The first line of all patches'
                ' should be a bzr meta line "***"')
        action = line[4:-1]

        lines = []
        for line in self._next():
            lines.append(line)

            if self._next_line[:3] == '***':
                return action, lines, True
            elif self._next_line[:1] == '#':
                return action, lines, False
        return action, lines, False
            
    def _read_patches(self):
        do_continue = True
        while do_continue:
            action, lines, do_continue = self._read_one_patch()
            if action is not None:
                self.info.actions.append((action, lines))

    def _read_revision(self, rev_id):
        """Revision entries have extra information associated.
        """
        rev_info = RevisionInfo(rev_id)
        start = '#    '
        for line in self._next():
            key,value = self._read_next_entry(line, indent=4)
            #if key is None:
            #    continue
            if hasattr(rev_info, key):
                if getattr(rev_info, key) is None:
                    setattr(rev_info, key, value)
                else:
                    raise MalformedHeader('Duplicated Key: %s' % key)
            else:
                # What do we do with a key we don't recognize
                raise MalformedHeader('Unknown Key: %s' % key)

            if self._next_line[:len(start)] != start:
                break

        self.info.revisions.append(rev_info)

    def _read_footer(self):
        """Read the rest of the meta information.

        :param first_line:  The previous step iterates past what it
                            can handle. That extra line is given here.
        """
        line = self._next().next()
        if line != '# BEGIN BZR FOOTER\n':
            raise MalformedFooter('Footer did not begin with BEGIN BZR FOOTER')

        for line in self._next():
            if line == '# END BZR FOOTER\n':
                return
            self._handle_next(line)

def read_changeset(from_file):
    """Read in a changeset from a filelike object (must have "readline" support), and
    parse it into a Changeset object.
    """
    cr = ChangesetReader(from_file)
    info = cr.get_info()
    return info

if __name__ == '__main__':
    import sys
    print read_changeset(sys.stdin)
