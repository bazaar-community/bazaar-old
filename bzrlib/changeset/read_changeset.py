#!/usr/bin/env python
"""\
Read in a changeset output, and process it into a Changeset object.
"""

import os
import pprint
from cStringIO import StringIO
from sha import sha

from bzrlib.tree import Tree
from bzrlib.trace import mutter, warning
from bzrlib.testament import Testament
from bzrlib.errors import BzrError
from bzrlib.xml5 import serializer_v5
from bzrlib.osutils import sha_file, sha_string
from bzrlib.revision import Revision
from bzrlib.inventory import (Inventory, InventoryEntry,
                              InventoryDirectory, InventoryFile,
                              InventoryLink)

from bzrlib.changeset.common import (decode, get_header, header_str,
                                     testament_sha1)

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
    def __init__(self, revision_id):
        self.revision_id = revision_id
        self.sha1 = None
        self.committer = None
        self.date = None
        self.timestamp = None
        self.timezone = None
        self.inventory_sha1 = None
        self.inventory_has_revision = None

        self.parent_ids = None
        self.message = None
        self.properties = None

    def __str__(self):
        return pprint.pformat(self.__dict__)

    def as_revision(self):
        rev = Revision(revision_id=self.revision_id,
            committer=self.committer,
            timestamp=float(self.timestamp),
            timezone=int(self.timezone),
            inventory_sha1=self.inventory_sha1,
            message='\n'.join(self.message))

        if self.parent_ids:
            rev.parent_ids.extend(self.parent_ids)

        if self.properties:
            for property in self.properties:
                key_end = property.find(': ')
                assert key_end is not None
                key = property[:key_end].encode('utf-8')
                value = property[key_end+2:].encode('utf-8')
                rev.properties[key] = value

        return rev

class ChangesetInfo(object):
    """This contains the meta information. Stuff that allows you to
    recreate the revision or inventory XML.
    """
    def __init__(self):
        self.committer = None
        self.date = None
        self.message = None
        self.base = None
        self.base_sha1 = None

        # A list of RevisionInfo objects
        self.revisions = []

        self.actions = {}

        # The next entries are created during complete_info() and
        # other post-read functions.

        # A list of real Revision objects
        self.real_revisions = []

        self.timestamp = None
        self.timezone = None

    def __str__(self):
        return pprint.pformat(self.__dict__)

    def complete_info(self):
        """This makes sure that all information is properly
        split up, based on the assumptions that can be made
        when information is missing.
        """
        from bzrlib.changeset.common import unpack_highres_date
        # Put in all of the guessable information.
        if not self.timestamp and self.date:
            self.timestamp, self.timezone = unpack_highres_date(self.date)

        self.real_revisions = []
        for rev in self.revisions:
            if rev.timestamp is None:
                if rev.date is not None:
                    rev.timestamp, rev.timezone = \
                            unpack_highres_date(rev.date)
                else:
                    rev.timestamp = self.timestamp
                    rev.timezone = self.timezone
            if rev.message is None and self.message:
                rev.message = self.message
            if rev.committer is None and self.committer:
                rev.committer = self.committer
            self.real_revisions.append(rev.as_revision())

        if self.base is None and len(self.real_revisions) > 0:
            # When we don't have a base, then the real base
            # is the first parent of the first revision listed
            rev = self.real_revisions[0]
            self.base = self.get_base(rev)

    def get_base(self, revision):
        if len(revision.parent_ids) == 0:
            # There is no base listed, and
            # the lowest revision doesn't have a parent
            # so this is probably against the empty tree
            # and thus base truly is None
            return None
        else:
            return revision.parent_ids[0]

    def _get_target(self):
        """Return the target revision."""
        if len(self.real_revisions) > 0:
            return self.real_revisions[0].revision_id
        elif len(self.revisions) > 0:
            return self.revisions[0].revision_id
        return None

    target = property(_get_target, doc='The target revision id')

    def get_revision(self, revision_id):
        for r in self.real_revisions:
            if r.revision_id == revision_id:
                return r
        raise KeyError(revision_id)

    def get_revision_info(self, revision_id):
        for r in self.revisions:
            if r.revision_id == revision_id:
                return r
        raise KeyError(revision_id)


class ChangesetReader(object):
    """This class reads in a changeset from a file, and returns
    a Changeset object, which can then be applied against a tree.
    """
    def __init__(self, from_file):
        """Read in the changeset from the file.

        :param from_file: A file-like object (must have iterator support).
        """
        object.__init__(self)
        self.from_file = iter(from_file)
        self._next_line = None
        
        self.info = ChangesetInfo()
        # We put the actual inventory ids in the footer, so that the patch
        # is easier to read for humans.
        # Unfortunately, that means we need to read everything before we
        # can create a proper changeset.
        self._read()
        self._validate()

    def _read(self):
        self._read_header()
        while self._next_line is not None:
            self._read_revision_header()
            if self._next_line is None:
                break
            self._read_patches()
            self._read_footer()

    def _validate(self):
        """Make sure that the information read in makes sense
        and passes appropriate checksums.
        """
        # Fill in all the missing blanks for the revisions
        # and generate the real_revisions list.
        self.info.complete_info()

    def _validate_revision(self, inventory, revision_id):
        """Make sure all revision entries match their checksum."""

        # This is a mapping from each revision id to it's sha hash
        rev_to_sha1 = {}
        
        rev = self.info.get_revision(revision_id)
        rev_info = self.info.get_revision_info(revision_id)
        assert rev.revision_id == rev_info.revision_id
        assert rev.revision_id == revision_id
        sha1 = sha(Testament(rev, inventory).as_short_text()).hexdigest()
        if sha1 != rev_info.sha1:
            raise BzrError('Revision checksum mismatch.'
                ' For revision_id {%s} supplied sha1 (%s) != measured (%s)'
                % (rev.revision_id, rev_info.sha1, sha1))
        if rev_to_sha1.has_key(rev.revision_id):
            raise BzrError('Revision {%s} given twice in the list'
                    % (rev.revision_id))
        rev_to_sha1[rev.revision_id] = sha1

        # Now that we've checked all the sha1 sums, we can make sure that
        # at least for the small list we have, all of the references are
        # valid.
        ## TODO: Bring this back
        ## for rev in self.info.real_revisions:
        ##     for p_id in rev.parent_ids:
        ##         if p_id in rev_to_sha1:
        ##             if parent.revision_sha1 != rev_to_sha1[p_id]:
        ##                 raise BzrError('Parent revision checksum mismatch.'
        ##                         ' A parent was referenced with an'
        ##                         ' incorrect checksum'
        ##                         ': {%r} %s != %s' % (parent.revision_id,
        ##                                     parent.revision_sha1,
        ##                                     rev_to_sha1[parent.revision_id]))

    def _validate_references_from_repository(self, repository):
        """Now that we have a repository which should have some of the
        revisions we care about, go through and validate all of them
        that we can.
        """
        rev_to_sha = {}
        inv_to_sha = {}
        def add_sha(d, revision_id, sha1):
            if revision_id is None:
                if sha1 is not None:
                    raise BzrError('A Null revision should always'
                        'have a null sha1 hash')
                return
            if revision_id in d:
                # This really should have been validated as part
                # of _validate_revisions but lets do it again
                if sha1 != d[revision_id]:
                    raise BzrError('** Revision %r referenced with 2 different'
                            ' sha hashes %s != %s' % (revision_id,
                                sha1, d[revision_id]))
            else:
                d[revision_id] = sha1

        # All of the contained revisions were checked
        # in _validate_revisions
        checked = {}
        for rev_info in self.info.revisions:
            checked[rev_info.revision_id] = True
            add_sha(rev_to_sha, rev_info.revision_id, rev_info.sha1)
                
        for (rev, rev_info) in zip(self.info.real_revisions, self.info.revisions):
            add_sha(inv_to_sha, rev_info.revision_id, rev_info.inventory_sha1)

        count = 0
        missing = {}
        for revision_id, sha1 in rev_to_sha.iteritems():
            if repository.has_revision(revision_id):
                local_sha1 = testament_sha1(repository, revision_id)
                if sha1 != local_sha1:
                    raise BzrError('sha1 mismatch. For revision id {%s}' 
                            'local: %s, cset: %s' % (revision_id, local_sha1, sha1))
                else:
                    count += 1
            elif revision_id not in checked:
                missing[revision_id] = sha1

        for inv_id, sha1 in inv_to_sha.iteritems():
            if repository.has_revision(inv_id):
                # TODO: Currently branch.get_inventory_sha1() just returns the value
                # that is stored in the revision text. Which is *really* bogus, because
                # that means we aren't validating the actual text, just that we wrote 
                # and read the string. But for now, what the hell.
                local_sha1 = repository.get_inventory_sha1(inv_id)
                if sha1 != local_sha1:
                    raise BzrError('sha1 mismatch. For inventory id {%s}' 
                            'local: %s, cset: %s' % (inv_id, local_sha1, sha1))
                else:
                    count += 1

        if len(missing) > 0:
            # I don't know if this is an error yet
            warning('Not all revision hashes could be validated.'
                    ' Unable validate %d hashes' % len(missing))
        mutter('Verified %d sha hashes for the changeset.' % count)

    def _validate_inventory(self, inv, revision_id):
        """At this point we should have generated the ChangesetTree,
        so build up an inventory, and make sure the hashes match.
        """

        assert inv is not None

        # Now we should have a complete inventory entry.
        s = serializer_v5.write_inventory_to_string(inv)
        sha1 = sha_string(s)
        # Target revision is the last entry in the real_revisions list
        rev = self.info.get_revision(revision_id)
        assert rev.revision_id == revision_id
        if sha1 != rev.inventory_sha1:
            open(',,bogus-inv', 'wb').write(s)
            warning('Inventory sha hash mismatch for revision %s. %s'
                    ' != %s' % (revision_id, sha1, rev.inventory_sha1))

        
    def get_changeset(self, repository):
        """Return the meta information, and a Changeset tree which can
        be used to populate the local stores and working tree, respectively.
        """
        return self.info, self.revision_tree(repository, self.info.target)

    def revision_tree(self, repository, revision_id, base=None):
        revision = self.info.get_revision(revision_id)
        if revision_id == self.info.target:
            base = self.info.base
        else:
            base = self.info.get_base(revision)
        assert base != revision_id
        self._validate_references_from_repository(repository)
        revision_info = self.info.get_revision_info(revision_id)
        if revision_info.inventory_has_revision == 'yes':
            inventory_revision_id = revision_id
        else:
            inventory_revision_id = None
        cset_tree = ChangesetTree(repository.revision_tree(base), 
                                  inventory_revision_id)
        self._update_tree(cset_tree, revision_id)

        inv = cset_tree.inventory
        self._validate_inventory(inv, revision_id)
        self._validate_revision(inv, revision_id)

        return cset_tree

    def _next(self):
        """yield the next line, but secretly
        keep 1 extra line for peeking.
        """
        for line in self.from_file:
            last = self._next_line
            self._next_line = line
            if last is not None:
                #mutter('yielding line: %r' % last)
                yield last
        last = self._next_line
        self._next_line = None
        #mutter('yielding line: %r' % last)
        yield last

    def _read_header(self):
        """Read the bzr header"""
        header = get_header()
        found = False
        for line in self._next():
            if found:
                # not all mailers will keep trailing whitespace
                if line == '#\n':
                    line = '# \n'
                if (not line.startswith('# ') or not line.endswith('\n')
                        or decode(line[2:-1]) != header[0]):
                    raise MalformedHeader('Found a header, but it'
                        ' was improperly formatted')
                header.pop(0) # We read this line.
                if not header:
                    break # We found everything.
            elif (line.startswith('#') and line.endswith('\n')):
                line = decode(line[1:-1].strip())
                if line[:len(header_str)] == header_str:
                    if line == header[0]:
                        found = True
                    else:
                        raise MalformedHeader('Found what looks like'
                                ' a header, but did not match')
                    header.pop(0)
        else:
            raise MalformedHeader('Did not find an opening header')

    def _read_revision_header(self):
        for line in self._next():
            # The bzr header is terminated with a blank line
            # which does not start with '#'
            if line is None or line == '\n':
                break
            self._handle_next(line)

    def _read_next_entry(self, line, indent=1):
        """Read in a key-value pair
        """
        if not line.startswith('#'):
            raise MalformedHeader('Bzr header did not start with #')
        line = decode(line[1:-1]) # Remove the '#' and '\n'
        if line[:indent] == ' '*indent:
            line = line[indent:]
        if not line:
            return None, None# Ignore blank lines

        loc = line.find(': ')
        if loc != -1:
            key = line[:loc]
            value = line[loc+2:]
            if not value:
                value = self._read_many(indent=indent+2)
        elif line[-1:] == ':':
            key = line[:-1]
            value = self._read_many(indent=indent+2)
        else:
            raise MalformedHeader('While looking for key: value pairs,'
                    ' did not find the colon %r' % (line))

        key = key.replace(' ', '_')
        #mutter('found %s: %s' % (key, value))
        return key, value

    def _handle_next(self, line):
        if line is None:
            return
        key, value = self._read_next_entry(line, indent=1)
        mutter('_handle_next %r => %r' % (key, value))
        if key is None:
            return

        if key == 'revision_id':
            self._read_revision(value)
        else:
            revision_info = self.info.revisions[-1]
            if hasattr(revision_info, key):
                if getattr(revision_info, key) is None:
                    setattr(revision_info, key, value)
                else:
                    raise MalformedHeader('Duplicated Key: %s' % key)
            else:
                # What do we do with a key we don't recognize
                raise MalformedHeader('Unknown Key: "%s"' % key)
        
    def _read_many(self, indent):
        """If a line ends with no entry, that means that it should be
        followed with multiple lines of values.

        This detects the end of the list, because it will be a line that
        does not start properly indented.
        """
        values = []
        start = '#' + (' '*indent)

        if self._next_line is None or self._next_line[:len(start)] != start:
            return values

        for line in self._next():
            values.append(decode(line[len(start):-1]))
            if self._next_line is None or self._next_line[:len(start)] != start:
                break
        return values

    def _read_one_patch(self):
        """Read in one patch, return the complete patch, along with
        the next line.

        :return: action, lines, do_continue
        """
        #mutter('_read_one_patch: %r' % self._next_line)
        # Peek and see if there are no patches
        if self._next_line is None or self._next_line.startswith('#'):
            return None, [], False

        first = True
        lines = []
        for line in self._next():
            if first:
                if not line.startswith('==='):
                    raise MalformedPatches('The first line of all patches'
                        ' should be a bzr meta line "==="'
                        ': %r' % line)
                action = decode(line[4:-1])
            if self._next_line is not None and self._next_line.startswith('==='):
                return action, lines, True
            elif self._next_line is None or self._next_line.startswith('#'):
                return action, lines, False

            if first:
                first = False
            else:
                lines.append(line)

        return action, lines, False
            
    def _read_patches(self):
        do_continue = True
        revision_actions = []
        while do_continue:
            action, lines, do_continue = self._read_one_patch()
            if action is not None:
                revision_actions.append((action, lines))
        if self.info.revisions[-1].revision_id not in self.info.actions:
            self.info.actions[self.info.revisions[-1].revision_id] = \
                revision_actions

    def _read_revision(self, revision_id):
        """Revision entries have extra information associated.
        """
        rev_info = RevisionInfo(revision_id)
        start = '#    '
        for line in self._next():
            key,value = self._read_next_entry(line, indent=1)
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

            if self._next_line is None or not self._next_line.startswith(start):
                break

        self.info.revisions.append(rev_info)

    def _read_footer(self):
        """Read the rest of the meta information.

        :param first_line:  The previous step iterates past what it
                            can handle. That extra line is given here.
        """
        for line in self._next():
            self._handle_next(line)
            if self._next_line is None or not self._next_line.startswith('#'):
                break

    def _update_tree(self, cset_tree, revision_id):
        """This fills out a ChangesetTree based on the information
        that was read in.

        :param cset_tree: A ChangesetTree to update with the new information.
        """

        def get_rev_id(info, file_id, kind):
            if info is not None:
                if not info.startswith('last-changed:'):
                    raise BzrError("Last changed revision should start with 'last-changed:'"
                        ': %r' % info)
                changed_revision_id = decode(info[13:])
            elif cset_tree._last_changed.has_key(file_id):
                return cset_tree._last_changed[file_id]
            else:
                changed_revision_id = revision_id
            cset_tree.note_last_changed(file_id, changed_revision_id)
            return changed_revision_id

        def renamed(kind, extra, lines):
            info = extra.split(' // ')
            if len(info) < 2:
                raise BzrError('renamed action lines need both a from and to'
                        ': %r' % extra)
            old_path = info[0]
            if info[1].startswith('=> '):
                new_path = info[1][3:]
            else:
                new_path = info[1]

            file_id = cset_tree.path2id(old_path)
            if len(info) > 2:
                revision = get_rev_id(info[2], file_id, kind)
            else:
                revision = get_rev_id(None, file_id, kind)
            cset_tree.note_rename(old_path, new_path)
            if lines:
                cset_tree.note_patch(new_path, ''.join(lines))

        def removed(kind, extra, lines):
            info = extra.split(' // ')
            if len(info) > 1:
                # TODO: in the future we might allow file ids to be
                # given for removed entries
                raise BzrError('removed action lines should only have the path'
                        ': %r' % extra)
            path = info[0]
            cset_tree.note_deletion(path)

        def added(kind, extra, lines):
            info = extra.split(' // ')
            if len(info) <= 1:
                raise BzrError('add action lines require the path and file id'
                        ': %r' % extra)
            elif len(info) > 3:
                raise BzrError('add action lines have fewer than 3 entries.'
                        ': %r' % extra)
            path = info[0]
            if not info[1].startswith('file-id:'):
                raise BzrError('The file-id should follow the path for an add'
                        ': %r' % extra)
            file_id = info[1][8:]

            cset_tree.note_id(file_id, path, kind)
            if len(info) > 2:
                revision = get_rev_id(info[2], file_id, kind)
            else:
                revision = get_rev_id(None, file_id, kind)
            if kind == 'directory':
                return
            cset_tree.note_patch(path, ''.join(lines))

        def modified(kind, extra, lines):
            info = extra.split(' // ')
            if len(info) < 1:
                raise BzrError('modified action lines have at least'
                        'the path in them: %r' % extra)
            path = info[0]

            file_id = cset_tree.path2id(path)
            if len(info) > 1:
                revision = get_rev_id(info[1], file_id, kind)
            else:
                revision = get_rev_id(None, file_id, kind)
            cset_tree.note_patch(path, ''.join(lines))
            

        valid_actions = {
            'renamed':renamed,
            'removed':removed,
            'added':added,
            'modified':modified
        }
        for action_line, lines in self.info.actions[revision_id]:
            first = action_line.find(' ')
            if first == -1:
                raise BzrError('Bogus action line'
                        ' (no opening space): %r' % action_line)
            second = action_line.find(' ', first+1)
            if second == -1:
                raise BzrError('Bogus action line'
                        ' (missing second space): %r' % action_line)
            action = action_line[:first]
            kind = action_line[first+1:second]
            if kind not in ('file', 'directory'):
                raise BzrError('Bogus action line'
                        ' (invalid object kind %r): %r' % (kind, action_line))
            extra = action_line[second+1:]

            if action not in valid_actions:
                raise BzrError('Bogus action line'
                        ' (unrecognized action): %r' % action_line)
            valid_actions[action](kind, extra, lines)

def read_changeset(from_file, repository):
    """Read in a changeset from a iterable object (such as a file object)

    :param from_file: A file-like object to read the changeset information.
    :param repository: This will be used to build the changeset tree, it needs
                       to contain the base of the changeset. (Which you
                       probably won't know about until after the changeset is
                       parsed.)
    """
    cr = ChangesetReader(from_file)
    return cr.get_changeset(repository)

class ChangesetTree(Tree):
    def __init__(self, base_tree, revision_id):
        self.base_tree = base_tree
        self._renamed = {} # Mapping from old_path => new_path
        self._renamed_r = {} # new_path => old_path
        self._new_id = {} # new_path => new_id
        self._new_id_r = {} # new_id => new_path
        self._kinds = {} # new_id => kind
        self._last_changed = {} # new_id => revision_id
        self.patches = {}
        self.deleted = []
        self.contents_by_id = True
        self.revision_id = revision_id
        self._inventory = None

    def __str__(self):
        return pprint.pformat(self.__dict__)

    def note_rename(self, old_path, new_path):
        """A file/directory has been renamed from old_path => new_path"""
        assert not self._renamed.has_key(old_path)
        assert not self._renamed_r.has_key(new_path)
        self._renamed[new_path] = old_path
        self._renamed_r[old_path] = new_path

    def note_id(self, new_id, new_path, kind='file'):
        """Files that don't exist in base need a new id."""
        self._new_id[new_path] = new_id
        self._new_id_r[new_id] = new_path
        self._kinds[new_id] = kind

    def note_last_changed(self, file_id, revision_id):
        if (self._last_changed.has_key(file_id)
                and self._last_changed[file_id] != revision_id):
            raise BzrError('Mismatched last-changed revision for file_id {%s}'
                    ': %s != %s' % (file_id,
                                    self._last_changed[file_id],
                                    revision_id))
        self._last_changed[file_id] = revision_id

    def note_patch(self, new_path, patch):
        """There is a patch for a given filename."""
        self.patches[new_path] = patch

    def note_deletion(self, old_path):
        """The file at old_path has been deleted."""
        self.deleted.append(old_path)

    def old_path(self, new_path):
        """Get the old_path (path in the base_tree) for the file at new_path"""
        assert new_path[:1] not in ('\\', '/')
        old_path = self._renamed.get(new_path)
        if old_path is not None:
            return old_path
        dirname,basename = os.path.split(new_path)
        # dirname is not '' doesn't work, because
        # dirname may be a unicode entry, and is
        # requires the objects to be identical
        if dirname != '':
            old_dir = self.old_path(dirname)
            if old_dir is None:
                old_path = None
            else:
                old_path = os.path.join(old_dir, basename)
        else:
            old_path = new_path
        #If the new path wasn't in renamed, the old one shouldn't be in
        #renamed_r
        if self._renamed_r.has_key(old_path):
            return None
        return old_path 

    def new_path(self, old_path):
        """Get the new_path (path in the target_tree) for the file at old_path
        in the base tree.
        """
        assert old_path[:1] not in ('\\', '/')
        new_path = self._renamed_r.get(old_path)
        if new_path is not None:
            return new_path
        if self._renamed.has_key(new_path):
            return None
        dirname,basename = os.path.split(old_path)
        if dirname != '':
            new_dir = self.new_path(dirname)
            if new_dir is None:
                new_path = None
            else:
                new_path = os.path.join(new_dir, basename)
        else:
            new_path = old_path
        #If the old path wasn't in renamed, the new one shouldn't be in
        #renamed_r
        if self._renamed.has_key(new_path):
            return None
        return new_path 

    def path2id(self, path):
        """Return the id of the file present at path in the target tree."""
        file_id = self._new_id.get(path)
        if file_id is not None:
            return file_id
        old_path = self.old_path(path)
        if old_path is None:
            return None
        if old_path in self.deleted:
            return None
        if hasattr(self.base_tree, 'path2id'):
            return self.base_tree.path2id(old_path)
        else:
            return self.base_tree.inventory.path2id(old_path)

    def id2path(self, file_id):
        """Return the new path in the target tree of the file with id file_id"""
        path = self._new_id_r.get(file_id)
        if path is not None:
            return path
        old_path = self.base_tree.id2path(file_id)
        if old_path is None:
            return None
        if old_path in self.deleted:
            return None
        return self.new_path(old_path)

    def old_contents_id(self, file_id):
        """Return the id in the base_tree for the given file_id,
        or None if the file did not exist in base.

        FIXME:  Something doesn't seem right here. It seems like this function
                should always either return None or file_id. Even if
                you are doing the by-path lookup, you are doing a
                id2path lookup, just to do the reverse path2id lookup.

        Notice that you're doing the path2id on a different tree!
        """
        if self.contents_by_id:
            if self.base_tree.has_id(file_id):
                return file_id
            else:
                return None
        new_path = self.id2path(file_id)
        return self.base_tree.path2id(new_path)
        
    def get_file(self, file_id):
        """Return a file-like object containing the new contents of the
        file given by file_id.

        TODO:   It might be nice if this actually generated an entry
                in the text-store, so that the file contents would
                then be cached.
        """
        base_id = self.old_contents_id(file_id)
        if base_id is not None:
            patch_original = self.base_tree.get_file(base_id)
        else:
            patch_original = None
        file_patch = self.patches.get(self.id2path(file_id))
        if file_patch is None:
            if (patch_original is None and 
                self.get_kind(file_id) == 'directory'):
                return StringIO()
            assert patch_original is not None, "None: %s" % file_id
            return patch_original

        assert not file_patch.startswith('\\'), \
            'Malformed patch for %s, %r' % (file_id, file_patch)
        return patched_file(file_patch, patch_original)

    def get_kind(self, file_id):
        if file_id in self._kinds:
            return self._kinds[file_id]
        return self.base_tree.inventory[file_id].kind

    def get_last_changed(self, file_id):
        if file_id in self._last_changed:
            return self._last_changed[file_id]
        return self.base_tree.inventory[file_id].revision

    def get_size_and_sha1(self, file_id):
        """Return the size and sha1 hash of the given file id.
        If the file was not locally modified, this is extracted
        from the base_tree. Rather than re-reading the file.
        """
        new_path = self.id2path(file_id)
        if new_path is None:
            return None, None
        if new_path not in self.patches:
            # If the entry does not have a patch, then the
            # contents must be the same as in the base_tree
            ie = self.base_tree.inventory[file_id]
            if ie.text_size is None:
                return ie.text_size, ie.text_sha1
            return int(ie.text_size), ie.text_sha1
        fileobj = self.get_file(file_id)
        content = fileobj.read()
        return len(content), sha_string(content)


    def _get_inventory(self):
        """Build up the inventory entry for the ChangesetTree.

        This need to be called before ever accessing self.inventory
        """
        from os.path import dirname, basename

        assert self.base_tree is not None
        base_inv = self.base_tree.inventory
        root_id = base_inv.root.file_id
        try:
            # New inventories have a unique root_id
            inv = Inventory(root_id, self.revision_id)
        except TypeError:
            inv = Inventory(revision_id=self.revision_id)

        def add_entry(file_id):
            path = self.id2path(file_id)
            if path is None:
                return
            parent_path = dirname(path)
            if parent_path == u'':
                parent_id = root_id
            else:
                parent_id = self.path2id(parent_path)

            kind = self.get_kind(file_id)
            revision_id = self.get_last_changed(file_id)

            name = basename(path)
            if kind == 'directory':
                ie = InventoryDirectory(file_id, name, parent_id)
            elif kind == 'file':
                ie = InventoryFile(file_id, name, parent_id)
            elif kind == 'symlink':
                ie = InventoryLink(file_id, name, parent_id)
            ie.revision = revision_id

            if kind == 'directory':
                ie.text_size, ie.text_sha1 = None, None
            else:
                ie.text_size, ie.text_sha1 = self.get_size_and_sha1(file_id)
            if (ie.text_size is None) and (kind != 'directory'):
                raise BzrError('Got a text_size of None for file_id %r' % file_id)
            inv.add(ie)

        sorted_entries = self.sorted_path_id()
        for path, file_id in sorted_entries:
            if file_id == inv.root.file_id:
                continue
            add_entry(file_id)

        return inv

    # Have to overload the inherited inventory property
    # because _get_inventory is only called in the parent.
    # Reading the docs, property() objects do not use
    # overloading, they use the function as it was defined
    # at that instant
    inventory = property(_get_inventory)

    def __iter__(self):
        for path, entry in self.inventory.iter_entries():
            yield entry.file_id

    def sorted_path_id(self):
        paths = []
        for result in self._new_id.iteritems():
            paths.append(result)
        for id in self.base_tree:
            path = self.id2path(id)
            if path is None:
                continue
            paths.append((path, id))
        paths.sort()
        return paths

def patched_file(file_patch, original):
    """Produce a file-like object with the patched version of a text"""
    from bzrlib.patches import iter_patched
    from bzrlib.iterablefile import IterableFile
    if file_patch == "":
        return IterableFile(())
    return IterableFile(iter_patched(original, file_patch.splitlines(True)))
    
