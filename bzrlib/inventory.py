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

# FIXME: This refactoring of the workingtree code doesn't seem to keep
# the WorkingTree's copy of the inventory in sync with the branch.  The
# branch modifies its working inventory when it does a commit to make
# missing files permanently removed.

# TODO: Maybe also keep the full path of the entry, and the children?
# But those depend on its position within a particular inventory, and
# it would be nice not to need to hold the backpointer here.

# This should really be an id randomly assigned when the tree is
# created, but it's not for now.
ROOT_ID = "TREE_ROOT"

from copy import deepcopy

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import collections
import os
import re
import tarfile

import bzrlib
from bzrlib import (
    chk_map,
    errors,
    generate_ids,
    osutils,
    symbol_versioning,
    workingtree,
    )
""")

from bzrlib.errors import (
    BzrCheckError,
    BzrError,
    )
from bzrlib.symbol_versioning import deprecated_in, deprecated_method
from bzrlib.trace import mutter


class InventoryEntry(object):
    """Description of a versioned file.

    An InventoryEntry has the following fields, which are also
    present in the XML inventory-entry element:

    file_id

    name
        (within the parent directory)

    parent_id
        file_id of the parent directory, or ROOT_ID

    revision
        the revision_id in which this variation of this file was
        introduced.

    executable
        Indicates that this file should be executable on systems
        that support it.

    text_sha1
        sha-1 of the text of the file

    text_size
        size in bytes of the text of the file

    (reading a version 4 tree created a text_id field.)

    >>> i = Inventory()
    >>> i.path2id('')
    'TREE_ROOT'
    >>> i.add(InventoryDirectory('123', 'src', ROOT_ID))
    InventoryDirectory('123', 'src', parent_id='TREE_ROOT', revision=None)
    >>> i.add(InventoryFile('2323', 'hello.c', parent_id='123'))
    InventoryFile('2323', 'hello.c', parent_id='123', sha1=None, len=None, revision=None)
    >>> shouldbe = {0: '', 1: 'src', 2: 'src/hello.c'}
    >>> for ix, j in enumerate(i.iter_entries()):
    ...   print (j[0] == shouldbe[ix], j[1])
    ...
    (True, InventoryDirectory('TREE_ROOT', u'', parent_id=None, revision=None))
    (True, InventoryDirectory('123', 'src', parent_id='TREE_ROOT', revision=None))
    (True, InventoryFile('2323', 'hello.c', parent_id='123', sha1=None, len=None, revision=None))
    >>> i.add(InventoryFile('2324', 'bye.c', '123'))
    InventoryFile('2324', 'bye.c', parent_id='123', sha1=None, len=None, revision=None)
    >>> i.add(InventoryDirectory('2325', 'wibble', '123'))
    InventoryDirectory('2325', 'wibble', parent_id='123', revision=None)
    >>> i.path2id('src/wibble')
    '2325'
    >>> '2325' in i
    True
    >>> i.add(InventoryFile('2326', 'wibble.c', '2325'))
    InventoryFile('2326', 'wibble.c', parent_id='2325', sha1=None, len=None, revision=None)
    >>> i['2326']
    InventoryFile('2326', 'wibble.c', parent_id='2325', sha1=None, len=None, revision=None)
    >>> for path, entry in i.iter_entries():
    ...     print path
    ...
    <BLANKLINE>
    src
    src/bye.c
    src/hello.c
    src/wibble
    src/wibble/wibble.c
    >>> i.id2path('2326')
    'src/wibble/wibble.c'
    """

    # Constants returned by describe_change()
    #
    # TODO: These should probably move to some kind of FileChangeDescription
    # class; that's like what's inside a TreeDelta but we want to be able to
    # generate them just for one file at a time.
    RENAMED = 'renamed'
    MODIFIED_AND_RENAMED = 'modified and renamed'

    __slots__ = []

    def detect_changes(self, old_entry):
        """Return a (text_modified, meta_modified) from this to old_entry.

        _read_tree_state must have been called on self and old_entry prior to
        calling detect_changes.
        """
        return False, False

    def _diff(self, text_diff, from_label, tree, to_label, to_entry, to_tree,
             output_to, reverse=False):
        """Perform a diff between two entries of the same kind."""

    def parent_candidates(self, previous_inventories):
        """Find possible per-file graph parents.

        This is currently defined by:
         - Select the last changed revision in the parent inventory.
         - Do deal with a short lived bug in bzr 0.8's development two entries
           that have the same last changed but different 'x' bit settings are
           changed in-place.
        """
        # revision:ie mapping for each ie found in previous_inventories.
        candidates = {}
        # identify candidate head revision ids.
        for inv in previous_inventories:
            if self.file_id in inv:
                ie = inv[self.file_id]
                if ie.revision in candidates:
                    # same revision value in two different inventories:
                    # correct possible inconsistencies:
                    #     * there was a bug in revision updates with 'x' bit
                    #       support.
                    try:
                        if candidates[ie.revision].executable != ie.executable:
                            candidates[ie.revision].executable = False
                            ie.executable = False
                    except AttributeError:
                        pass
                else:
                    # add this revision as a candidate.
                    candidates[ie.revision] = ie
        return candidates

    @deprecated_method(deprecated_in((1, 6, 0)))
    def get_tar_item(self, root, dp, now, tree):
        """Get a tarfile item and a file stream for its content."""
        item = tarfile.TarInfo(osutils.pathjoin(root, dp).encode('utf8'))
        # TODO: would be cool to actually set it to the timestamp of the
        # revision it was last changed
        item.mtime = now
        fileobj = self._put_in_tar(item, tree)
        return item, fileobj

    def has_text(self):
        """Return true if the object this entry represents has textual data.

        Note that textual data includes binary content.

        Also note that all entries get weave files created for them.
        This attribute is primarily used when upgrading from old trees that
        did not have the weave index for all inventory entries.
        """
        return False

    def __init__(self, file_id, name, parent_id, text_id=None):
        """Create an InventoryEntry

        The filename must be a single component, relative to the
        parent directory; it cannot be a whole path or relative name.

        >>> e = InventoryFile('123', 'hello.c', ROOT_ID)
        >>> e.name
        'hello.c'
        >>> e.file_id
        '123'
        >>> e = InventoryFile('123', 'src/hello.c', ROOT_ID)
        Traceback (most recent call last):
        InvalidEntryName: Invalid entry name: src/hello.c
        """
        if '/' in name or '\\' in name:
            raise errors.InvalidEntryName(name=name)
        self.executable = False
        self.revision = None
        self.text_sha1 = None
        self.text_size = None
        self.file_id = file_id
        self.name = name
        self.text_id = text_id
        self.parent_id = parent_id
        self.symlink_target = None
        self.reference_revision = None

    def kind_character(self):
        """Return a short kind indicator useful for appending to names."""
        raise BzrError('unknown kind %r' % self.kind)

    known_kinds = ('file', 'directory', 'symlink')

    def _put_in_tar(self, item, tree):
        """populate item for stashing in a tar, and return the content stream.

        If no content is available, return None.
        """
        raise BzrError("don't know how to export {%s} of kind %r" %
                       (self.file_id, self.kind))

    @deprecated_method(deprecated_in((1, 6, 0)))
    def put_on_disk(self, dest, dp, tree):
        """Create a representation of self on disk in the prefix dest.

        This is a template method - implement _put_on_disk in subclasses.
        """
        fullpath = osutils.pathjoin(dest, dp)
        self._put_on_disk(fullpath, tree)
        # mutter("  export {%s} kind %s to %s", self.file_id,
        #         self.kind, fullpath)

    def _put_on_disk(self, fullpath, tree):
        """Put this entry onto disk at fullpath, from tree tree."""
        raise BzrError("don't know how to export {%s} of kind %r" % (self.file_id, self.kind))

    def sorted_children(self):
        return sorted(self.children.items())

    @staticmethod
    def versionable_kind(kind):
        return (kind in ('file', 'directory', 'symlink', 'tree-reference'))

    def check(self, checker, rev_id, inv, tree):
        """Check this inventory entry is intact.

        This is a template method, override _check for kind specific
        tests.

        :param checker: Check object providing context for the checks;
             can be used to find out what parts of the repository have already
             been checked.
        :param rev_id: Revision id from which this InventoryEntry was loaded.
             Not necessarily the last-changed revision for this file.
        :param inv: Inventory from which the entry was loaded.
        :param tree: RevisionTree for this entry.
        """
        if self.parent_id is not None:
            if not inv.has_id(self.parent_id):
                raise BzrCheckError('missing parent {%s} in inventory for revision {%s}'
                        % (self.parent_id, rev_id))
        self._check(checker, rev_id, tree)

    def _check(self, checker, rev_id, tree):
        """Check this inventory entry for kind specific errors."""
        raise BzrCheckError('unknown entry kind %r in revision {%s}' %
                            (self.kind, rev_id))

    def copy(self):
        """Clone this inventory entry."""
        raise NotImplementedError

    @staticmethod
    def describe_change(old_entry, new_entry):
        """Describe the change between old_entry and this.

        This smells of being an InterInventoryEntry situation, but as its
        the first one, we're making it a static method for now.

        An entry with a different parent, or different name is considered
        to be renamed. Reparenting is an internal detail.
        Note that renaming the parent does not trigger a rename for the
        child entry itself.
        """
        # TODO: Perhaps return an object rather than just a string
        if old_entry is new_entry:
            # also the case of both being None
            return 'unchanged'
        elif old_entry is None:
            return 'added'
        elif new_entry is None:
            return 'removed'
        if old_entry.kind != new_entry.kind:
            return 'modified'
        text_modified, meta_modified = new_entry.detect_changes(old_entry)
        if text_modified or meta_modified:
            modified = True
        else:
            modified = False
        # TODO 20060511 (mbp, rbc) factor out 'detect_rename' here.
        if old_entry.parent_id != new_entry.parent_id:
            renamed = True
        elif old_entry.name != new_entry.name:
            renamed = True
        else:
            renamed = False
        if renamed and not modified:
            return InventoryEntry.RENAMED
        if modified and not renamed:
            return 'modified'
        if modified and renamed:
            return InventoryEntry.MODIFIED_AND_RENAMED
        return 'unchanged'

    def __repr__(self):
        return ("%s(%r, %r, parent_id=%r, revision=%r)"
                % (self.__class__.__name__,
                   self.file_id,
                   self.name,
                   self.parent_id,
                   self.revision))

    def __eq__(self, other):
        if other is self:
            # For the case when objects are cached
            return True
        if not isinstance(other, InventoryEntry):
            return NotImplemented

        return ((self.file_id == other.file_id)
                and (self.name == other.name)
                and (other.symlink_target == self.symlink_target)
                and (self.text_sha1 == other.text_sha1)
                and (self.text_size == other.text_size)
                and (self.text_id == other.text_id)
                and (self.parent_id == other.parent_id)
                and (self.kind == other.kind)
                and (self.revision == other.revision)
                and (self.executable == other.executable)
                and (self.reference_revision == other.reference_revision)
                )

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        raise ValueError('not hashable')

    def _unchanged(self, previous_ie):
        """Has this entry changed relative to previous_ie.

        This method should be overridden in child classes.
        """
        compatible = True
        # different inv parent
        if previous_ie.parent_id != self.parent_id:
            compatible = False
        # renamed
        elif previous_ie.name != self.name:
            compatible = False
        elif previous_ie.kind != self.kind:
            compatible = False
        return compatible

    def _read_tree_state(self, path, work_tree):
        """Populate fields in the inventory entry from the given tree.

        Note that this should be modified to be a noop on virtual trees
        as all entries created there are prepopulated.
        """
        # TODO: Rather than running this manually, we should check the
        # working sha1 and other expensive properties when they're
        # first requested, or preload them if they're already known
        pass            # nothing to do by default

    def _forget_tree_state(self):
        pass


class RootEntry(InventoryEntry):

    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', 'children', 'executable',
                 'revision', 'symlink_target', 'reference_revision']

    def _check(self, checker, rev_id, tree):
        """See InventoryEntry._check"""

    def __init__(self, file_id):
        self.file_id = file_id
        self.children = {}
        self.kind = 'directory'
        self.parent_id = None
        self.name = u''
        self.revision = None
        symbol_versioning.warn('RootEntry is deprecated as of bzr 0.10.'
                               '  Please use InventoryDirectory instead.',
                               DeprecationWarning, stacklevel=2)

    def __eq__(self, other):
        if not isinstance(other, RootEntry):
            return NotImplemented

        return (self.file_id == other.file_id) \
               and (self.children == other.children)


class InventoryDirectory(InventoryEntry):
    """A directory in an inventory."""

    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', 'children', 'executable',
                 'revision', 'symlink_target', 'reference_revision']

    def _check(self, checker, rev_id, tree):
        """See InventoryEntry._check"""
        if self.text_sha1 is not None or self.text_size is not None or self.text_id is not None:
            raise BzrCheckError('directory {%s} has text in revision {%s}'
                                % (self.file_id, rev_id))

    def copy(self):
        other = InventoryDirectory(self.file_id, self.name, self.parent_id)
        other.revision = self.revision
        # note that children are *not* copied; they're pulled across when
        # others are added
        return other

    def __init__(self, file_id, name, parent_id):
        super(InventoryDirectory, self).__init__(file_id, name, parent_id)
        self.children = {}
        self.kind = 'directory'

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return '/'

    def _put_in_tar(self, item, tree):
        """See InventoryEntry._put_in_tar."""
        item.type = tarfile.DIRTYPE
        fileobj = None
        item.name += '/'
        item.size = 0
        item.mode = 0755
        return fileobj

    def _put_on_disk(self, fullpath, tree):
        """See InventoryEntry._put_on_disk."""
        os.mkdir(fullpath)


class InventoryFile(InventoryEntry):
    """A file in an inventory."""

    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', 'children', 'executable',
                 'revision', 'symlink_target', 'reference_revision']

    def _check(self, checker, tree_revision_id, tree):
        """See InventoryEntry._check"""
        key = (self.file_id, self.revision)
        if key in checker.checked_texts:
            prev_sha = checker.checked_texts[key]
            if prev_sha != self.text_sha1:
                raise BzrCheckError(
                    'mismatched sha1 on {%s} in {%s} (%s != %s) %r' %
                    (self.file_id, tree_revision_id, prev_sha, self.text_sha1,
                     t))
            else:
                checker.repeated_text_cnt += 1
                return

        mutter('check version {%s} of {%s}', tree_revision_id, self.file_id)
        checker.checked_text_cnt += 1
        # We can't check the length, because Weave doesn't store that
        # information, and the whole point of looking at the weave's
        # sha1sum is that we don't have to extract the text.
        if (self.text_sha1 != tree._repository.texts.get_sha1s([key])[key]):
            raise BzrCheckError('text {%s} version {%s} wrong sha1' % key)
        checker.checked_texts[key] = self.text_sha1

    def copy(self):
        other = InventoryFile(self.file_id, self.name, self.parent_id)
        other.executable = self.executable
        other.text_id = self.text_id
        other.text_sha1 = self.text_sha1
        other.text_size = self.text_size
        other.revision = self.revision
        return other

    def detect_changes(self, old_entry):
        """See InventoryEntry.detect_changes."""
        text_modified = (self.text_sha1 != old_entry.text_sha1)
        meta_modified = (self.executable != old_entry.executable)
        return text_modified, meta_modified

    def _diff(self, text_diff, from_label, tree, to_label, to_entry, to_tree,
             output_to, reverse=False):
        """See InventoryEntry._diff."""
        from bzrlib.diff import DiffText
        from_file_id = self.file_id
        if to_entry:
            to_file_id = to_entry.file_id
        else:
            to_file_id = None
        if reverse:
            to_file_id, from_file_id = from_file_id, to_file_id
            tree, to_tree = to_tree, tree
            from_label, to_label = to_label, from_label
        differ = DiffText(tree, to_tree, output_to, 'utf-8', '', '',
                          text_diff)
        return differ.diff_text(from_file_id, to_file_id, from_label, to_label)

    def has_text(self):
        """See InventoryEntry.has_text."""
        return True

    def __init__(self, file_id, name, parent_id):
        super(InventoryFile, self).__init__(file_id, name, parent_id)
        self.kind = 'file'

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ''

    def _put_in_tar(self, item, tree):
        """See InventoryEntry._put_in_tar."""
        item.type = tarfile.REGTYPE
        fileobj = tree.get_file(self.file_id)
        item.size = self.text_size
        if tree.is_executable(self.file_id):
            item.mode = 0755
        else:
            item.mode = 0644
        return fileobj

    def _put_on_disk(self, fullpath, tree):
        """See InventoryEntry._put_on_disk."""
        osutils.pumpfile(tree.get_file(self.file_id), file(fullpath, 'wb'))
        if tree.is_executable(self.file_id):
            os.chmod(fullpath, 0755)

    def _read_tree_state(self, path, work_tree):
        """See InventoryEntry._read_tree_state."""
        self.text_sha1 = work_tree.get_file_sha1(self.file_id, path=path)
        # FIXME: 20050930 probe for the text size when getting sha1
        # in _read_tree_state
        self.executable = work_tree.is_executable(self.file_id, path=path)

    def __repr__(self):
        return ("%s(%r, %r, parent_id=%r, sha1=%r, len=%s, revision=%s)"
                % (self.__class__.__name__,
                   self.file_id,
                   self.name,
                   self.parent_id,
                   self.text_sha1,
                   self.text_size,
                   self.revision))

    def _forget_tree_state(self):
        self.text_sha1 = None

    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super(InventoryFile, self)._unchanged(previous_ie)
        if self.text_sha1 != previous_ie.text_sha1:
            compatible = False
        else:
            # FIXME: 20050930 probe for the text size when getting sha1
            # in _read_tree_state
            self.text_size = previous_ie.text_size
        if self.executable != previous_ie.executable:
            compatible = False
        return compatible


class InventoryLink(InventoryEntry):
    """A file in an inventory."""

    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', 'children', 'executable',
                 'revision', 'symlink_target', 'reference_revision']

    def _check(self, checker, rev_id, tree):
        """See InventoryEntry._check"""
        if self.text_sha1 is not None or self.text_size is not None or self.text_id is not None:
            raise BzrCheckError('symlink {%s} has text in revision {%s}'
                    % (self.file_id, rev_id))
        if self.symlink_target is None:
            raise BzrCheckError('symlink {%s} has no target in revision {%s}'
                    % (self.file_id, rev_id))

    def copy(self):
        other = InventoryLink(self.file_id, self.name, self.parent_id)
        other.symlink_target = self.symlink_target
        other.revision = self.revision
        return other

    def detect_changes(self, old_entry):
        """See InventoryEntry.detect_changes."""
        # FIXME: which _modified field should we use ? RBC 20051003
        text_modified = (self.symlink_target != old_entry.symlink_target)
        if text_modified:
            mutter("    symlink target changed")
        meta_modified = False
        return text_modified, meta_modified

    def _diff(self, text_diff, from_label, tree, to_label, to_entry, to_tree,
             output_to, reverse=False):
        """See InventoryEntry._diff."""
        from bzrlib.diff import DiffSymlink
        old_target = self.symlink_target
        if to_entry is not None:
            new_target = to_entry.symlink_target
        else:
            new_target = None
        if not reverse:
            old_tree = tree
            new_tree = to_tree
        else:
            old_tree = to_tree
            new_tree = tree
            new_target, old_target = old_target, new_target
        differ = DiffSymlink(old_tree, new_tree, output_to)
        return differ.diff_symlink(old_target, new_target)

    def __init__(self, file_id, name, parent_id):
        super(InventoryLink, self).__init__(file_id, name, parent_id)
        self.kind = 'symlink'

    def kind_character(self):
        """See InventoryEntry.kind_character."""
        return ''

    def _put_in_tar(self, item, tree):
        """See InventoryEntry._put_in_tar."""
        item.type = tarfile.SYMTYPE
        fileobj = None
        item.size = 0
        item.mode = 0755
        item.linkname = self.symlink_target
        return fileobj

    def _put_on_disk(self, fullpath, tree):
        """See InventoryEntry._put_on_disk."""
        try:
            os.symlink(self.symlink_target, fullpath)
        except OSError,e:
            raise BzrError("Failed to create symlink %r -> %r, error: %s" % (fullpath, self.symlink_target, e))

    def _read_tree_state(self, path, work_tree):
        """See InventoryEntry._read_tree_state."""
        self.symlink_target = work_tree.get_symlink_target(self.file_id)

    def _forget_tree_state(self):
        self.symlink_target = None

    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super(InventoryLink, self)._unchanged(previous_ie)
        if self.symlink_target != previous_ie.symlink_target:
            compatible = False
        return compatible


class TreeReference(InventoryEntry):

    kind = 'tree-reference'

    def __init__(self, file_id, name, parent_id, revision=None,
                 reference_revision=None):
        InventoryEntry.__init__(self, file_id, name, parent_id)
        self.revision = revision
        self.reference_revision = reference_revision

    def copy(self):
        return TreeReference(self.file_id, self.name, self.parent_id,
                             self.revision, self.reference_revision)

    def _read_tree_state(self, path, work_tree):
        """Populate fields in the inventory entry from the given tree.
        """
        self.reference_revision = work_tree.get_reference_revision(
            self.file_id, path)

    def _forget_tree_state(self):
        self.reference_revision = None

    def _unchanged(self, previous_ie):
        """See InventoryEntry._unchanged."""
        compatible = super(TreeReference, self)._unchanged(previous_ie)
        if self.reference_revision != previous_ie.reference_revision:
            compatible = False
        return compatible


class CommonInventory(object):
    """Basic inventory logic, defined in terms of primitives like has_id."""

    def __contains__(self, file_id):
        """True if this entry contains a file with given id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile('123', 'foo.c', ROOT_ID))
        InventoryFile('123', 'foo.c', parent_id='TREE_ROOT', sha1=None, len=None, revision=None)
        >>> '123' in inv
        True
        >>> '456' in inv
        False

        Note that this method along with __iter__ are not encouraged for use as
        they are less clear than specific query methods - they may be rmeoved
        in the future.
        """
        return self.has_id(file_id)

    def id2path(self, file_id):
        """Return as a string the path to file_id.

        >>> i = Inventory()
        >>> e = i.add(InventoryDirectory('src-id', 'src', ROOT_ID))
        >>> e = i.add(InventoryFile('foo-id', 'foo.c', parent_id='src-id'))
        >>> print i.id2path('foo-id')
        src/foo.c
        """
        # get all names, skipping root
        return '/'.join(reversed(
            [parent.name for parent in
             self._iter_file_id_parents(file_id)][:-1]))

    def iter_entries(self, from_dir=None):
        """Return (path, entry) pairs, in order by name."""
        if from_dir is None:
            if self.root is None:
                return
            from_dir = self.root
            yield '', self.root
        elif isinstance(from_dir, basestring):
            from_dir = self[from_dir]

        # unrolling the recursive called changed the time from
        # 440ms/663ms (inline/total) to 116ms/116ms
        children = from_dir.children.items()
        children.sort()
        children = collections.deque(children)
        stack = [(u'', children)]
        while stack:
            from_dir_relpath, children = stack[-1]

            while children:
                name, ie = children.popleft()

                # we know that from_dir_relpath never ends in a slash
                # and 'f' doesn't begin with one, we can do a string op, rather
                # than the checks of pathjoin(), though this means that all paths
                # start with a slash
                path = from_dir_relpath + '/' + name

                yield path[1:], ie

                if ie.kind != 'directory':
                    continue

                # But do this child first
                new_children = ie.children.items()
                new_children.sort()
                new_children = collections.deque(new_children)
                stack.append((path, new_children))
                # Break out of inner loop, so that we start outer loop with child
                break
            else:
                # if we finished all children, pop it off the stack
                stack.pop()

    def iter_entries_by_dir(self, from_dir=None, specific_file_ids=None,
        yield_parents=False):
        """Iterate over the entries in a directory first order.

        This returns all entries for a directory before returning
        the entries for children of a directory. This is not
        lexicographically sorted order, and is a hybrid between
        depth-first and breadth-first.

        :param yield_parents: If True, yield the parents from the root leading
            down to specific_file_ids that have been requested. This has no
            impact if specific_file_ids is None.
        :return: This yields (path, entry) pairs
        """
        if specific_file_ids and not isinstance(specific_file_ids, set):
            specific_file_ids = set(specific_file_ids)
        # TODO? Perhaps this should return the from_dir so that the root is
        # yielded? or maybe an option?
        if from_dir is None:
            if self.root is None:
                return
            # Optimize a common case
            if (not yield_parents and specific_file_ids is not None and
                len(specific_file_ids) == 1):
                file_id = list(specific_file_ids)[0]
                if file_id in self:
                    yield self.id2path(file_id), self[file_id]
                return
            from_dir = self.root
            if (specific_file_ids is None or yield_parents or
                self.root.file_id in specific_file_ids):
                yield u'', self.root
        elif isinstance(from_dir, basestring):
            from_dir = self[from_dir]

        if specific_file_ids is not None:
            # TODO: jam 20070302 This could really be done as a loop rather
            #       than a bunch of recursive calls.
            parents = set()
            byid = self
            def add_ancestors(file_id):
                if file_id not in byid:
                    return
                parent_id = byid[file_id].parent_id
                if parent_id is None:
                    return
                if parent_id not in parents:
                    parents.add(parent_id)
                    add_ancestors(parent_id)
            for file_id in specific_file_ids:
                add_ancestors(file_id)
        else:
            parents = None

        stack = [(u'', from_dir)]
        while stack:
            cur_relpath, cur_dir = stack.pop()

            child_dirs = []
            for child_name, child_ie in sorted(cur_dir.children.iteritems()):

                child_relpath = cur_relpath + child_name

                if (specific_file_ids is None or
                    child_ie.file_id in specific_file_ids or
                    (yield_parents and child_ie.file_id in parents)):
                    yield child_relpath, child_ie

                if child_ie.kind == 'directory':
                    if parents is None or child_ie.file_id in parents:
                        child_dirs.append((child_relpath+'/', child_ie))
            stack.extend(reversed(child_dirs))

    def _make_delta(self, old):
        """Make an inventory delta from two inventories."""
        old_ids = set(old)
        new_ids = set(self)
        adds = new_ids - old_ids
        deletes = old_ids - new_ids
        common = old_ids.intersection(new_ids)
        delta = []
        for file_id in deletes:
            delta.append((old.id2path(file_id), None, file_id, None))
        for file_id in adds:
            delta.append((None, self.id2path(file_id), file_id, self[file_id]))
        for file_id in common:
            if old[file_id] != self[file_id]:
                delta.append((old.id2path(file_id), self.id2path(file_id),
                    file_id, self[file_id]))
        return delta

    def _get_mutable_inventory(self):
        """Returns a mutable copy of the object.

        Some inventories are immutable, yet working trees, for example, needs
        to mutate exisiting inventories instead of creating a new one.
        """
        raise NotImplementedError(self._get_mutable_inventory)

    def make_entry(self, kind, name, parent_id, file_id=None):
        """Simple thunk to bzrlib.inventory.make_entry."""
        return make_entry(kind, name, parent_id, file_id)

    def entries(self):
        """Return list of (path, ie) for all entries except the root.

        This may be faster than iter_entries.
        """
        accum = []
        def descend(dir_ie, dir_path):
            kids = dir_ie.children.items()
            kids.sort()
            for name, ie in kids:
                child_path = osutils.pathjoin(dir_path, name)
                accum.append((child_path, ie))
                if ie.kind == 'directory':
                    descend(ie, child_path)

        descend(self.root, u'')
        return accum

    def directories(self):
        """Return (path, entry) pairs for all directories, including the root.
        """
        accum = []
        def descend(parent_ie, parent_path):
            accum.append((parent_path, parent_ie))

            kids = [(ie.name, ie) for ie in parent_ie.children.itervalues() if ie.kind == 'directory']
            kids.sort()

            for name, child_ie in kids:
                child_path = osutils.pathjoin(parent_path, name)
                descend(child_ie, child_path)
        descend(self.root, u'')
        return accum


class Inventory(CommonInventory):
    """Inventory of versioned files in a tree.

    This describes which file_id is present at each point in the tree,
    and possibly the SHA-1 or other information about the file.
    Entries can be looked up either by path or by file_id.

    The inventory represents a typical unix file tree, with
    directories containing files and subdirectories.  We never store
    the full path to a file, because renaming a directory implicitly
    moves all of its contents.  This class internally maintains a
    lookup tree that allows the children under a directory to be
    returned quickly.

    InventoryEntry objects must not be modified after they are
    inserted, other than through the Inventory API.

    >>> inv = Inventory()
    >>> inv.add(InventoryFile('123-123', 'hello.c', ROOT_ID))
    InventoryFile('123-123', 'hello.c', parent_id='TREE_ROOT', sha1=None, len=None, revision=None)
    >>> inv['123-123'].name
    'hello.c'

    May be treated as an iterator or set to look up file ids:

    >>> bool(inv.path2id('hello.c'))
    True
    >>> '123-123' in inv
    True

    May also look up by name:

    >>> [x[0] for x in inv.iter_entries()]
    ['', u'hello.c']
    >>> inv = Inventory('TREE_ROOT-12345678-12345678')
    >>> inv.add(InventoryFile('123-123', 'hello.c', ROOT_ID))
    Traceback (most recent call last):
    BzrError: parent_id {TREE_ROOT} not in inventory
    >>> inv.add(InventoryFile('123-123', 'hello.c', 'TREE_ROOT-12345678-12345678'))
    InventoryFile('123-123', 'hello.c', parent_id='TREE_ROOT-12345678-12345678', sha1=None, len=None, revision=None)
    """
    def __init__(self, root_id=ROOT_ID, revision_id=None):
        """Create or read an inventory.

        If a working directory is specified, the inventory is read
        from there.  If the file is specified, read from that. If not,
        the inventory is created empty.

        The inventory is created with a default root directory, with
        an id of None.
        """
        if root_id is not None:
            self._set_root(InventoryDirectory(root_id, u'', None))
        else:
            self.root = None
            self._byid = {}
        self.revision_id = revision_id

    def __repr__(self):
        return "<Inventory object at %x, contents=%r>" % (id(self), self._byid)

    def apply_delta(self, delta):
        """Apply a delta to this inventory.

        :param delta: A list of changes to apply. After all the changes are
            applied the final inventory must be internally consistent, but it
            is ok to supply changes which, if only half-applied would have an
            invalid result - such as supplying two changes which rename two
            files, 'A' and 'B' with each other : [('A', 'B', 'A-id', a_entry),
            ('B', 'A', 'B-id', b_entry)].

            Each change is a tuple, of the form (old_path, new_path, file_id,
            new_entry).

            When new_path is None, the change indicates the removal of an entry
            from the inventory and new_entry will be ignored (using None is
            appropriate). If new_path is not None, then new_entry must be an
            InventoryEntry instance, which will be incorporated into the
            inventory (and replace any existing entry with the same file id).

            When old_path is None, the change indicates the addition of
            a new entry to the inventory.

            When neither new_path nor old_path are None, the change is a
            modification to an entry, such as a rename, reparent, kind change
            etc.

            The children attribute of new_entry is ignored. This is because
            this method preserves children automatically across alterations to
            the parent of the children, and cases where the parent id of a
            child is changing require the child to be passed in as a separate
            change regardless. E.g. in the recursive deletion of a directory -
            the directory's children must be included in the delta, or the
            final inventory will be invalid.
        """
        children = {}
        # Remove all affected items which were in the original inventory,
        # starting with the longest paths, thus ensuring parents are examined
        # after their children, which means that everything we examine has no
        # modified children remaining by the time we examine it.
        for old_path, file_id in sorted(((op, f) for op, np, f, e in delta
                                        if op is not None), reverse=True):
            if file_id not in self:
                # adds come later
                continue
            # Preserve unaltered children of file_id for later reinsertion.
            file_id_children = getattr(self[file_id], 'children', {})
            if len(file_id_children):
                children[file_id] = file_id_children
            # Remove file_id and the unaltered children. If file_id is not
            # being deleted it will be reinserted back later.
            self.remove_recursive_id(file_id)
        # Insert all affected which should be in the new inventory, reattaching
        # their children if they had any. This is done from shortest path to
        # longest, ensuring that items which were modified and whose parents in
        # the resulting inventory were also modified, are inserted after their
        # parents.
        for new_path, new_entry in sorted((np, e) for op, np, f, e in
                                          delta if np is not None):
            if new_entry.kind == 'directory':
                # Pop the child which to allow detection of children whose
                # parents were deleted and which were not reattached to a new
                # parent.
                replacement = InventoryDirectory(new_entry.file_id,
                    new_entry.name, new_entry.parent_id)
                replacement.revision = new_entry.revision
                replacement.children = children.pop(replacement.file_id, {})
                new_entry = replacement
            self.add(new_entry)
        if len(children):
            # Get the parent id that was deleted
            parent_id, children = children.popitem()
            raise errors.InconsistentDelta("<deleted>", parent_id,
                "The file id was deleted but its children were not deleted.")

    def _set_root(self, ie):
        self.root = ie
        self._byid = {self.root.file_id: self.root}

    def copy(self):
        # TODO: jam 20051218 Should copy also copy the revision_id?
        entries = self.iter_entries()
        if self.root is None:
            return Inventory(root_id=None)
        other = Inventory(entries.next()[1].file_id)
        other.root.revision = self.root.revision
        # copy recursively so we know directories will be added before
        # their children.  There are more efficient ways than this...
        for path, entry in entries:
            other.add(entry.copy())
        return other

    def _get_mutable_inventory(self):
        """See CommonInventory._get_mutable_inventory."""
        return deepcopy(self)

    def __iter__(self):
        return iter(self._byid)

    def __len__(self):
        """Returns number of entries."""
        return len(self._byid)

    def __getitem__(self, file_id):
        """Return the entry for given file_id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile('123123', 'hello.c', ROOT_ID))
        InventoryFile('123123', 'hello.c', parent_id='TREE_ROOT', sha1=None, len=None, revision=None)
        >>> inv['123123'].name
        'hello.c'
        """
        try:
            return self._byid[file_id]
        except KeyError:
            # really we're passing an inventory, not a tree...
            raise errors.NoSuchId(self, file_id)

    def get_file_kind(self, file_id):
        return self._byid[file_id].kind

    def get_child(self, parent_id, filename):
        return self[parent_id].children.get(filename)

    def _add_child(self, entry):
        """Add an entry to the inventory, without adding it to its parent"""
        if entry.file_id in self._byid:
            raise BzrError("inventory already contains entry with id {%s}" %
                           entry.file_id)
        self._byid[entry.file_id] = entry
        for child in getattr(entry, 'children', {}).itervalues():
            self._add_child(child)
        return entry

    def add(self, entry):
        """Add entry to inventory.

        To add  a file to a branch ready to be committed, use Branch.add,
        which calls this.

        Returns the new entry object.
        """
        if entry.file_id in self._byid:
            raise errors.DuplicateFileId(entry.file_id,
                                         self._byid[entry.file_id])

        if entry.parent_id is None:
            self.root = entry
        else:
            try:
                parent = self._byid[entry.parent_id]
            except KeyError:
                raise BzrError("parent_id {%s} not in inventory" %
                               entry.parent_id)

            if entry.name in parent.children:
                raise BzrError("%s is already versioned" %
                        osutils.pathjoin(self.id2path(parent.file_id),
                        entry.name).encode('utf-8'))
            parent.children[entry.name] = entry
        return self._add_child(entry)

    def add_path(self, relpath, kind, file_id=None, parent_id=None):
        """Add entry from a path.

        The immediate parent must already be versioned.

        Returns the new entry object."""

        parts = osutils.splitpath(relpath)

        if len(parts) == 0:
            if file_id is None:
                file_id = generate_ids.gen_root_id()
            self.root = InventoryDirectory(file_id, '', None)
            self._byid = {self.root.file_id: self.root}
            return self.root
        else:
            parent_path = parts[:-1]
            parent_id = self.path2id(parent_path)
            if parent_id is None:
                raise errors.NotVersionedError(path=parent_path)
        ie = make_entry(kind, parts[-1], parent_id, file_id)
        return self.add(ie)

    def __delitem__(self, file_id):
        """Remove entry by id.

        >>> inv = Inventory()
        >>> inv.add(InventoryFile('123', 'foo.c', ROOT_ID))
        InventoryFile('123', 'foo.c', parent_id='TREE_ROOT', sha1=None, len=None, revision=None)
        >>> '123' in inv
        True
        >>> del inv['123']
        >>> '123' in inv
        False
        """
        ie = self[file_id]
        del self._byid[file_id]
        if ie.parent_id is not None:
            del self[ie.parent_id].children[ie.name]

    def __eq__(self, other):
        """Compare two sets by comparing their contents.

        >>> i1 = Inventory()
        >>> i2 = Inventory()
        >>> i1 == i2
        True
        >>> i1.add(InventoryFile('123', 'foo', ROOT_ID))
        InventoryFile('123', 'foo', parent_id='TREE_ROOT', sha1=None, len=None, revision=None)
        >>> i1 == i2
        False
        >>> i2.add(InventoryFile('123', 'foo', ROOT_ID))
        InventoryFile('123', 'foo', parent_id='TREE_ROOT', sha1=None, len=None, revision=None)
        >>> i1 == i2
        True
        """
        if not isinstance(other, Inventory):
            return NotImplemented

        return self._byid == other._byid

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        raise ValueError('not hashable')

    def _iter_file_id_parents(self, file_id):
        """Yield the parents of file_id up to the root."""
        while file_id is not None:
            try:
                ie = self._byid[file_id]
            except KeyError:
                raise errors.NoSuchId(tree=None, file_id=file_id)
            yield ie
            file_id = ie.parent_id

    def get_idpath(self, file_id):
        """Return a list of file_ids for the path to an entry.

        The list contains one element for each directory followed by
        the id of the file itself.  So the length of the returned list
        is equal to the depth of the file in the tree, counting the
        root directory as depth 1.
        """
        p = []
        for parent in self._iter_file_id_parents(file_id):
            p.insert(0, parent.file_id)
        return p

    def path2id(self, name):
        """Walk down through directories to return entry of last component.

        names may be either a list of path components, or a single
        string, in which case it is automatically split.

        This returns the entry of the last component in the path,
        which may be either a file or a directory.

        Returns None IFF the path is not found.
        """
        if isinstance(name, basestring):
            name = osutils.splitpath(name)

        # mutter("lookup path %r" % name)

        parent = self.root
        if parent is None:
            return None
        for f in name:
            try:
                children = getattr(parent, 'children', None)
                if children is None:
                    return None
                cie = children[f]
                parent = cie
            except KeyError:
                # or raise an error?
                return None

        return parent.file_id

    def has_filename(self, names):
        return bool(self.path2id(names))

    def has_id(self, file_id):
        return (file_id in self._byid)

    def _make_delta(self, old):
        """Make an inventory delta from two inventories."""
        old_getter = getattr(old, '_byid', old)
        new_getter = self._byid
        old_ids = set(old_getter)
        new_ids = set(new_getter)
        adds = new_ids - old_ids
        deletes = old_ids - new_ids
        if not adds and not deletes:
            common = new_ids
        else:
            common = old_ids.intersection(new_ids)
        delta = []
        for file_id in deletes:
            delta.append((old.id2path(file_id), None, file_id, None))
        for file_id in adds:
            delta.append((None, self.id2path(file_id), file_id, self[file_id]))
        for file_id in common:
            new_ie = new_getter[file_id]
            old_ie = old_getter[file_id]
            # If xml_serializer returns the cached InventoryEntries (rather
            # than always doing .copy()), inlining the 'is' check saves 2.7M
            # calls to __eq__.  Under lsprof this saves 20s => 6s.
            # It is a minor improvement without lsprof.
            if old_ie is new_ie or old_ie == new_ie:
                continue
            else:
                delta.append((old.id2path(file_id), self.id2path(file_id),
                              file_id, new_ie))
        return delta

    def remove_recursive_id(self, file_id):
        """Remove file_id, and children, from the inventory.

        :param file_id: A file_id to remove.
        """
        to_find_delete = [self._byid[file_id]]
        to_delete = []
        while to_find_delete:
            ie = to_find_delete.pop()
            to_delete.append(ie.file_id)
            if ie.kind == 'directory':
                to_find_delete.extend(ie.children.values())
        for file_id in reversed(to_delete):
            ie = self[file_id]
            del self._byid[file_id]
        if ie.parent_id is not None:
            del self[ie.parent_id].children[ie.name]
        else:
            self.root = None

    def rename(self, file_id, new_parent_id, new_name):
        """Move a file within the inventory.

        This can change either the name, or the parent, or both.

        This does not move the working file.
        """
        new_name = ensure_normalized_name(new_name)
        if not is_valid_name(new_name):
            raise BzrError("not an acceptable filename: %r" % new_name)

        new_parent = self._byid[new_parent_id]
        if new_name in new_parent.children:
            raise BzrError("%r already exists in %r" % (new_name, self.id2path(new_parent_id)))

        new_parent_idpath = self.get_idpath(new_parent_id)
        if file_id in new_parent_idpath:
            raise BzrError("cannot move directory %r into a subdirectory of itself, %r"
                    % (self.id2path(file_id), self.id2path(new_parent_id)))

        file_ie = self._byid[file_id]
        old_parent = self._byid[file_ie.parent_id]

        # TODO: Don't leave things messed up if this fails

        del old_parent.children[file_ie.name]
        new_parent.children[new_name] = file_ie

        file_ie.name = new_name
        file_ie.parent_id = new_parent_id

    def is_root(self, file_id):
        return self.root is not None and file_id == self.root.file_id


class CHKInventory(CommonInventory):
    """An inventory persisted in a CHK store.

    By design, a CHKInventory is immutable so many of the methods
    supported by Inventory - add, rename, apply_delta, etc - are *not*
    supported. To create a new CHKInventory, use create_by_apply_delta()
    or from_inventory(), say.

    Internally, a CHKInventory has one or two CHKMaps:

    * id_to_entry - a map from (file_id,) => InventoryEntry as bytes
    * parent_id_basename_to_file_id - a map from (parent_id, basename_utf8)
        => file_id as bytes

    The second map is optional and not present in early CHkRepository's.

    No caching is performed: every method call or item access will perform
    requests to the storage layer. As such, keep references to objects you
    want to reuse.
    """

    def __init__(self, search_key_name):
        CommonInventory.__init__(self)
        self._entry_cache = {}
        self._search_key_name = search_key_name

    def _entry_to_bytes(self, entry):
        """Serialise entry as a single bytestring.

        :param Entry: An inventory entry.
        :return: A bytestring for the entry.

        The BNF:
        ENTRY ::= FILE | DIR | SYMLINK | TREE
        FILE ::= "file: " COMMON SEP SHA SEP SIZE SEP EXECUTABLE
        DIR ::= "dir: " COMMON
        SYMLINK ::= "symlink: " COMMON SEP TARGET_UTF8
        TREE ::= "tree: " COMMON REFERENCE_REVISION
        COMMON ::= FILE_ID SEP PARENT_ID SEP NAME_UTF8 SEP REVISION
        SEP ::= "\n"
        """
        if entry.parent_id is not None:
            parent_str = entry.parent_id
        else:
            parent_str = ''
        name_str = entry.name.encode("utf8")
        if entry.kind == 'file':
            if entry.executable:
                exec_str = "Y"
            else:
                exec_str = "N"
            return "file: %s\n%s\n%s\n%s\n%s\n%d\n%s" % (
                entry.file_id, parent_str, name_str, entry.revision,
                entry.text_sha1, entry.text_size, exec_str)
        elif entry.kind == 'directory':
            return "dir: %s\n%s\n%s\n%s" % (
                entry.file_id, parent_str, name_str, entry.revision)
        elif entry.kind == 'symlink':
            return "symlink: %s\n%s\n%s\n%s\n%s" % (
                entry.file_id, parent_str, name_str, entry.revision,
                entry.symlink_target.encode("utf8"))
        elif entry.kind == 'tree-reference':
            return "tree: %s\n%s\n%s\n%s\n%s" % (
                entry.file_id, parent_str, name_str, entry.revision,
                entry.reference_revision)
        else:
            raise ValueError("unknown kind %r" % entry.kind)

    def _bytes_to_entry(self, bytes):
        """Deserialise a serialised entry."""
        sections = bytes.split('\n')
        if sections[0].startswith("file: "):
            result = InventoryFile(sections[0][6:],
                sections[2].decode('utf8'),
                sections[1])
            result.text_sha1 = sections[4]
            result.text_size = int(sections[5])
            result.executable = sections[6] == "Y"
        elif sections[0].startswith("dir: "):
            result = CHKInventoryDirectory(sections[0][5:],
                sections[2].decode('utf8'),
                sections[1], self)
        elif sections[0].startswith("symlink: "):
            result = InventoryLink(sections[0][9:],
                sections[2].decode('utf8'),
                sections[1])
            result.symlink_target = sections[4]
        elif sections[0].startswith("tree: "):
            result = TreeReference(sections[0][6:],
                sections[2].decode('utf8'),
                sections[1])
            result.reference_revision = sections[4]
        else:
            raise ValueError("Not a serialised entry %r" % bytes)
        result.revision = sections[3]
        if result.parent_id == '':
            result.parent_id = None
        self._entry_cache[result.file_id] = result
        return result

    def _get_mutable_inventory(self):
        """See CommonInventory._get_mutable_inventory."""
        entries = self.iter_entries()
        if self.root_id is not None:
            entries.next()
        inv = Inventory(self.root_id, self.revision_id)
        for path, inv_entry in entries:
            inv.add(inv_entry)
        return inv

    def create_by_apply_delta(self, inventory_delta, new_revision_id):
        """Create a new CHKInventory by applying inventory_delta to this one.

        :param inventory_delta: The inventory delta to apply. See
            Inventory.apply_delta for details.
        :param new_revision_id: The revision id of the resulting CHKInventory.
        :return: The new CHKInventory.
        """
        result = CHKInventory(self._search_key_name)
        search_key_func = chk_map.search_key_registry.get(self._search_key_name)
        self.id_to_entry._ensure_root()
        maximum_size = self.id_to_entry._root_node.maximum_size
        result.revision_id = new_revision_id
        result.id_to_entry = chk_map.CHKMap(
            self.id_to_entry._store,
            self.id_to_entry.key(),
            search_key_func=search_key_func)
        result.id_to_entry._ensure_root()
        result.id_to_entry._root_node.set_maximum_size(maximum_size)
        if self.parent_id_basename_to_file_id is not None:
            result.parent_id_basename_to_file_id = chk_map.CHKMap(
                self.parent_id_basename_to_file_id._store,
                self.parent_id_basename_to_file_id.key(),
                search_key_func=search_key_func)
            result.parent_id_basename_to_file_id._ensure_root()
            self.parent_id_basename_to_file_id._ensure_root()
            result_p_id_root = result.parent_id_basename_to_file_id._root_node
            p_id_root = self.parent_id_basename_to_file_id._root_node
            result_p_id_root.set_maximum_size(p_id_root.maximum_size)
            result_p_id_root._key_width = p_id_root._key_width
            parent_id_basename_delta = []
        else:
            result.parent_id_basename_to_file_id = None
        result.root_id = self.root_id
        id_to_entry_delta = []
        for old_path, new_path, file_id, entry in inventory_delta:
            # file id changes
            if new_path == '':
                result.root_id = file_id
            if new_path is None:
                # Make a delete:
                new_key = None
                new_value = None
            else:
                new_key = (file_id,)
                new_value = result._entry_to_bytes(entry)
            if old_path is None:
                old_key = None
            else:
                old_key = (file_id,)
            id_to_entry_delta.append((old_key, new_key, new_value))
            if result.parent_id_basename_to_file_id is not None:
                # parent_id, basename changes
                if old_path is None:
                    old_key = None
                else:
                    old_entry = self[file_id]
                    old_key = self._parent_id_basename_key(old_entry)
                if new_path is None:
                    new_key = None
                    new_value = None
                else:
                    new_key = self._parent_id_basename_key(entry)
                    new_value = file_id
                if old_key != new_key:
                    # If the two keys are the same, the value will be unchanged
                    # as its always the file id.
                    parent_id_basename_delta.append((old_key, new_key, new_value))
        result.id_to_entry.apply_delta(id_to_entry_delta)
        if result.parent_id_basename_to_file_id is not None:
            result.parent_id_basename_to_file_id.apply_delta(parent_id_basename_delta)
        return result

    @classmethod
    def deserialise(klass, chk_store, bytes, expected_revision_id):
        """Deserialise a CHKInventory.

        :param chk_store: A CHK capable VersionedFiles instance.
        :param bytes: The serialised bytes.
        :param expected_revision_id: The revision ID we think this inventory is
            for.
        :return: A CHKInventory
        """
        lines = bytes.splitlines()
        if lines[0] != 'chkinventory:':
            raise ValueError("not a serialised CHKInventory: %r" % bytes)
        revision_id = lines[1][13:]
        root_id = lines[2][9:]
        if lines[3].startswith('search_key_name:'):
            search_key_name = lines[3][17:]
            next = 4
        else:
            search_key_name = 'plain'
            next = 3
        result = CHKInventory(search_key_name)
        result.revision_id = revision_id
        result.root_id = root_id
        search_key_func = chk_map.search_key_registry.get(
                            result._search_key_name)
        if lines[next].startswith('parent_id_basename_to_file_id:'):
            result.parent_id_basename_to_file_id = chk_map.CHKMap(
                chk_store, (lines[next][31:],),
                search_key_func=search_key_func)
            next += 1
        else:
            result.parent_id_basename_to_file_id = None

        result.id_to_entry = chk_map.CHKMap(chk_store, (lines[next][13:],),
                                            search_key_func=search_key_func)
        if (result.revision_id,) != expected_revision_id:
            raise ValueError("Mismatched revision id and expected: %r, %r" %
                (result.revision_id, expected_revision_id))
        return result

    @classmethod
    def from_inventory(klass, chk_store, inventory, maximum_size=0,
        parent_id_basename_index=False, search_key_name='plain'):
        """Create a CHKInventory from an existing inventory.

        The content of inventory is copied into the chk_store, and a
        CHKInventory referencing that is returned.

        :param chk_store: A CHK capable VersionedFiles instance.
        :param inventory: The inventory to copy.
        :param maximum_size: The CHKMap node size limit.
        :param parent_id_basename_index: If True create and use a
            parent_id,basename->file_id index.
        :param search_key_name: The identifier for the search key function
        """
        result = CHKInventory(search_key_name)
        result.revision_id = inventory.revision_id
        result.root_id = inventory.root.file_id
        search_key_func = chk_map.search_key_registry.get(search_key_name)
        result.id_to_entry = chk_map.CHKMap(chk_store, None, search_key_func)
        result.id_to_entry._root_node.set_maximum_size(maximum_size)
        file_id_delta = []
        if parent_id_basename_index:
            result.parent_id_basename_to_file_id = chk_map.CHKMap(chk_store,
                None, search_key_func)
            result.parent_id_basename_to_file_id._root_node.set_maximum_size(
                maximum_size)
            result.parent_id_basename_to_file_id._root_node._key_width = 2
            parent_id_delta = []
        else:
            result.parent_id_basename_to_file_id = None
        for path, entry in inventory.iter_entries():
            file_id_delta.append((None, (entry.file_id,),
                result._entry_to_bytes(entry)))
            if parent_id_basename_index:
                parent_id_delta.append(
                    (None, result._parent_id_basename_key(entry),
                     entry.file_id))
        result.id_to_entry.apply_delta(file_id_delta)
        if parent_id_basename_index:
            result.parent_id_basename_to_file_id.apply_delta(parent_id_delta)
        return result

    def _parent_id_basename_key(self, entry):
        """Create a key for a entry in a parent_id_basename_to_file_id index."""
        if entry.parent_id is not None:
            parent_id = entry.parent_id
        else:
            parent_id = ''
        return parent_id, entry.name.encode('utf8')

    def __getitem__(self, file_id):
        """map a single file_id -> InventoryEntry."""
        result = self._entry_cache.get(file_id, None)
        if result is not None:
            return result
        try:
            return self._bytes_to_entry(
                self.id_to_entry.iteritems([(file_id,)]).next()[1])
        except StopIteration:
            # really we're passing an inventory, not a tree...
            raise errors.NoSuchId(self, file_id)

    def has_id(self, file_id):
        # Perhaps have an explicit 'contains' method on CHKMap ?
        if self._entry_cache.get(file_id, None) is not None:
            return True
        return len(list(self.id_to_entry.iteritems([(file_id,)]))) == 1

    def is_root(self, file_id):
        return file_id == self.root_id

    def _iter_file_id_parents(self, file_id):
        """Yield the parents of file_id up to the root."""
        while file_id is not None:
            try:
                ie = self[file_id]
            except KeyError:
                raise errors.NoSuchId(tree=self, file_id=file_id)
            yield ie
            file_id = ie.parent_id

    def __iter__(self):
        """Iterate over the entire inventory contents; size-of-tree - beware!."""
        for key, _ in self.id_to_entry.iteritems():
            yield key[-1]

    def iter_changes(self, basis):
        """Generate a Tree.iter_changes change list between this and basis.

        :param basis: Another CHKInventory.
        :return: An iterator over the changes between self and basis, as per
            tree.iter_changes().
        """
        # We want: (file_id, (path_in_source, path_in_target),
        # changed_content, versioned, parent, name, kind,
        # executable)
        for key, basis_value, self_value in \
            self.id_to_entry.iter_changes(basis.id_to_entry):
            file_id = key[0]
            if basis_value is not None:
                basis_entry = basis._bytes_to_entry(basis_value)
                path_in_source = basis.id2path(file_id)
                basis_parent = basis_entry.parent_id
                basis_name = basis_entry.name
                basis_executable = basis_entry.executable
            else:
                path_in_source = None
                basis_parent = None
                basis_name = None
                basis_executable = None
            if self_value is not None:
                self_entry = self._bytes_to_entry(self_value)
                path_in_target = self.id2path(file_id)
                self_parent = self_entry.parent_id
                self_name = self_entry.name
                self_executable = self_entry.executable
            else:
                path_in_target = None
                self_parent = None
                self_name = None
                self_executable = None
            if basis_value is None:
                # add
                kind = (None, self_entry.kind)
                versioned = (False, True)
            elif self_value is None:
                # delete
                kind = (basis_entry.kind, None)
                versioned = (True, False)
            else:
                kind = (basis_entry.kind, self_entry.kind)
                versioned = (True, True)
            changed_content = False
            if kind[0] != kind[1]:
                changed_content = True
            elif kind[0] == 'file':
                if (self_entry.text_size != basis_entry.text_size or
                    self_entry.text_sha1 != basis_entry.text_sha1):
                    changed_content = True
            elif kind[0] == 'symlink':
                if self_entry.symlink_target != basis_entry.symlink_target:
                    changed_content = True
            elif kind[0] == 'tree-reference':
                if (self_entry.reference_revision !=
                    basis_entry.reference_revision):
                    changed_content = True
            parent = (basis_parent, self_parent)
            name = (basis_name, self_name)
            executable = (basis_executable, self_executable)
            if (not changed_content
                and parent[0] == parent[1]
                and name[0] == name[1]
                and executable[0] == executable[1]):
                # Could happen when only the revision changed for a directory
                # for instance.
                continue
            yield (file_id, (path_in_source, path_in_target), changed_content,
                versioned, parent, name, kind, executable)

    def __len__(self):
        """Return the number of entries in the inventory."""
        return len(self.id_to_entry)

    def _make_delta(self, old):
        """Make an inventory delta from two inventories."""
        if type(old) != CHKInventory:
            return CommonInventory._make_delta(self, old)
        delta = []
        for key, old_value, self_value in \
            self.id_to_entry.iter_changes(old.id_to_entry):
            file_id = key[0]
            if old_value is not None:
                old_path = old.id2path(file_id)
            else:
                old_path = None
            if self_value is not None:
                entry = self._bytes_to_entry(self_value)
                self._entry_cache[file_id] = entry
                new_path = self.id2path(file_id)
            else:
                entry = None
                new_path = None
            delta.append((old_path, new_path, file_id, entry))
        return delta

    def path2id(self, name):
        """Walk down through directories to return entry of last component.

        names may be either a list of path components, or a single
        string, in which case it is automatically split.

        This returns the entry of the last component in the path,
        which may be either a file or a directory.

        Returns None IFF the path is not found.
        """
        if isinstance(name, basestring):
            name = osutils.splitpath(name)

        # mutter("lookup path %r" % name)

        parent = self.root
        if parent is None:
            return None
        for f in name:
            try:
                children = getattr(parent, 'children', None)
                if children is None:
                    return None
                cie = children[f]
                parent = cie
            except KeyError:
                # or raise an error?
                return None
        return parent.file_id

    def to_lines(self):
        """Serialise the inventory to lines."""
        lines = ["chkinventory:\n"]
        lines.append("revision_id: %s\n" % self.revision_id)
        lines.append("root_id: %s\n" % self.root_id)
        if self._search_key_name != 'plain':
            lines.append('search_key_name: %s\n' % (self._search_key_name,))
        if self.parent_id_basename_to_file_id is not None:
            lines.append('parent_id_basename_to_file_id: %s\n' %
                self.parent_id_basename_to_file_id.key())
        lines.append("id_to_entry: %s\n" % self.id_to_entry.key())
        return lines

    @property
    def root(self):
        """Get the root entry."""
        return self[self.root_id]


class CHKInventoryDirectory(InventoryDirectory):
    """A directory in an inventory."""

    __slots__ = ['text_sha1', 'text_size', 'file_id', 'name', 'kind',
                 'text_id', 'parent_id', '_children', 'executable',
                 'revision', 'symlink_target', 'reference_revision',
                 '_chk_inventory']

    def __init__(self, file_id, name, parent_id, chk_inventory):
        # Don't call InventoryDirectory.__init__ - it isn't right for this
        # class.
        InventoryEntry.__init__(self, file_id, name, parent_id)
        self._children = None
        self.kind = 'directory'
        self._chk_inventory = chk_inventory

    @property
    def children(self):
        """Access the list of children of this inventory.

        With a parent_id_basename_to_file_id index, loads all the children,
        without loads the entire index. Without is bad. A more sophisticated
        proxy object might be nice, to allow partial loading of children as
        well when specific names are accessed. (So path traversal can be
        written in the obvious way but not examine siblings.).
        """
        if self._children is not None:
            return self._children
        if self._chk_inventory.parent_id_basename_to_file_id is None:
            # Slow path - read the entire inventory looking for kids.
            result = {}
            for file_id, bytes in self._chk_inventory.id_to_entry.iteritems():
                entry = self._chk_inventory._bytes_to_entry(bytes)
                if entry.parent_id == self.file_id:
                    result[entry.name] = entry
            self._children = result
            return result
        result = {}
        # XXX: Todo - use proxy objects for the children rather than loading
        # all when the attribute is referenced.
        parent_id_index = self._chk_inventory.parent_id_basename_to_file_id
        child_ids = set()
        for (parent_id, name_utf8), file_id in parent_id_index.iteritems(
            key_filter=[(self.file_id,)]):
            child_ids.add((file_id,))
        cached = set()
        for file_id in child_ids:
            entry = self._chk_inventory._entry_cache.get(file_id, None)
            if entry is not None:
                result[entry.name] = entry
                cached.add(file_id)
        child_ids.difference_update(cached)
        # populate; todo: do by name
        id_to_entry = self._chk_inventory.id_to_entry
        for file_id, bytes in id_to_entry.iteritems(child_ids):
            entry = self._chk_inventory._bytes_to_entry(bytes)
            result[entry.name] = entry
            self._chk_inventory._entry_cache[file_id] = entry
        self._children = result
        return result


entry_factory = {
    'directory': InventoryDirectory,
    'file': InventoryFile,
    'symlink': InventoryLink,
    'tree-reference': TreeReference
}

def make_entry(kind, name, parent_id, file_id=None):
    """Create an inventory entry.

    :param kind: the type of inventory entry to create.
    :param name: the basename of the entry.
    :param parent_id: the parent_id of the entry.
    :param file_id: the file_id to use. if None, one will be created.
    """
    if file_id is None:
        file_id = generate_ids.gen_file_id(name)
    name = ensure_normalized_name(name)
    try:
        factory = entry_factory[kind]
    except KeyError:
        raise BzrError("unknown kind %r" % kind)
    return factory(file_id, name, parent_id)


def ensure_normalized_name(name):
    """Normalize name.

    :raises InvalidNormalization: When name is not normalized, and cannot be
        accessed on this platform by the normalized path.
    :return: The NFC normalised version of name.
    """
    #------- This has been copied to bzrlib.dirstate.DirState.add, please
    # keep them synchronised.
    # we dont import normalized_filename directly because we want to be
    # able to change the implementation at runtime for tests.
    norm_name, can_access = osutils.normalized_filename(name)
    if norm_name != name:
        if can_access:
            return norm_name
        else:
            # TODO: jam 20060701 This would probably be more useful
            #       if the error was raised with the full path
            raise errors.InvalidNormalization(name)
    return name


_NAME_RE = None

def is_valid_name(name):
    global _NAME_RE
    if _NAME_RE is None:
        _NAME_RE = re.compile(r'^[^/\\]+$')

    return bool(_NAME_RE.match(name))
