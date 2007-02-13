# Copyright (C) 2005 Canonical Ltd
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

"""Tree classes, representing directory at point in time.
"""

import os
from cStringIO import StringIO

import bzrlib
from bzrlib import (
    delta,
    osutils,
    symbol_versioning,
    )
from bzrlib.decorators import needs_read_lock
from bzrlib.errors import BzrError, BzrCheckError
from bzrlib import errors
from bzrlib.inventory import Inventory
from bzrlib.inter import InterObject
from bzrlib.osutils import fingerprint_file
import bzrlib.revision
from bzrlib.trace import mutter, note


class Tree(object):
    """Abstract file tree.

    There are several subclasses:
    
    * `WorkingTree` exists as files on disk editable by the user.

    * `RevisionTree` is a tree as recorded at some point in the past.

    Trees contain an `Inventory` object, and also know how to retrieve
    file texts mentioned in the inventory, either from a working
    directory or from a store.

    It is possible for trees to contain files that are not described
    in their inventory or vice versa; for this use `filenames()`.

    Trees can be compared, etc, regardless of whether they are working
    trees or versioned trees.
    """
    
    def changes_from(self, other, want_unchanged=False, specific_files=None,
        extra_trees=None, require_versioned=False, include_root=False):
        """Return a TreeDelta of the changes from other to this tree.

        :param other: A tree to compare with.
        :param specific_files: An optional list of file paths to restrict the
            comparison to. When mapping filenames to ids, all matches in all
            trees (including optional extra_trees) are used, and all children of
            matched directories are included.
        :param want_unchanged: An optional boolean requesting the inclusion of
            unchanged entries in the result.
        :param extra_trees: An optional list of additional trees to use when
            mapping the contents of specific_files (paths) to file_ids.
        :param require_versioned: An optional boolean (defaults to False). When
            supplied and True all the 'specific_files' must be versioned, or
            a PathsNotVersionedError will be thrown.

        The comparison will be performed by an InterTree object looked up on 
        self and other.
        """
        # Martin observes that Tree.changes_from returns a TreeDelta and this
        # may confuse people, because the class name of the returned object is
        # a synonym of the object referenced in the method name.
        return InterTree.get(other, self).compare(
            want_unchanged=want_unchanged,
            specific_files=specific_files,
            extra_trees=extra_trees,
            require_versioned=require_versioned,
            include_root=include_root
            )

    def _iter_changes(self, from_tree, include_unchanged=False, 
                     specific_file_ids=None, pb=None):
        intertree = InterTree.get(from_tree, self)
        return intertree._iter_changes(from_tree, self, include_unchanged, 
                                       specific_file_ids, pb)
    
    def conflicts(self):
        """Get a list of the conflicts in the tree.

        Each conflict is an instance of bzrlib.conflicts.Conflict.
        """
        return []

    def get_parent_ids(self):
        """Get the parent ids for this tree. 

        :return: a list of parent ids. [] is returned to indicate
        a tree with no parents.
        :raises: BzrError if the parents are not known.
        """
        raise NotImplementedError(self.get_parent_ids)
    
    def has_filename(self, filename):
        """True if the tree has given filename."""
        raise NotImplementedError()

    def has_id(self, file_id):
        return self.inventory.has_id(file_id)

    __contains__ = has_id

    def has_or_had_id(self, file_id):
        if file_id == self.inventory.root.file_id:
            return True
        return self.inventory.has_id(file_id)

    def __iter__(self):
        return iter(self.inventory)

    def id2path(self, file_id):
        return self.inventory.id2path(file_id)

    def is_control_filename(self, filename):
        """True if filename is the name of a control file in this tree.
        
        :param filename: A filename within the tree. This is a relative path
        from the root of this tree.

        This is true IF and ONLY IF the filename is part of the meta data
        that bzr controls in this tree. I.E. a random .bzr directory placed
        on disk will not be a control file for this tree.
        """
        return self.bzrdir.is_control_filename(filename)

    @needs_read_lock
    def iter_entries_by_dir(self, specific_file_ids=None):
        """Walk the tree in 'by_dir' order.

        This will yield each entry in the tree as a (path, entry) tuple. The
        order that they are yielded is: the contents of a directory are 
        preceeded by the parent of a directory, and all the contents of a 
        directory are grouped together.
        """
        return self.inventory.iter_entries_by_dir(
            specific_file_ids=specific_file_ids)

    def kind(self, file_id):
        raise NotImplementedError("subclasses must implement kind")

    def _comparison_data(self, entry, path):
        """Return a tuple of kind, executable, stat_value for a file.

        entry may be None if there is no inventory entry for the file, but
        path must always be supplied.

        kind is None if there is no file present (even if an inventory id is
        present).  executable is False for non-file entries.
        """
        raise NotImplementedError(self._comparison_data)

    def _file_size(self, entry, stat_value):
        raise NotImplementedError(self._file_size)

    def _get_inventory(self):
        return self._inventory
    
    def get_file(self, file_id):
        """Return a file object for the file file_id in the tree."""
        raise NotImplementedError(self.get_file)
    
    def get_file_by_path(self, path):
        return self.get_file(self._inventory.path2id(path))

    def annotate_iter(self, file_id):
        """Return an iterator of revision_id, line tuples

        For working trees (and mutable trees in general), the special
        revision_id 'current:' will be used for lines that are new in this
        tree, e.g. uncommitted changes.
        :param file_id: The file to produce an annotated version from
        """
        raise NotImplementedError(self.annotate_iter)

    inventory = property(_get_inventory,
                         doc="Inventory of this Tree")

    def _check_retrieved(self, ie, f):
        if not __debug__:
            return  
        fp = fingerprint_file(f)
        f.seek(0)
        
        if ie.text_size is not None:
            if ie.text_size != fp['size']:
                raise BzrError("mismatched size for file %r in %r" % (ie.file_id, self._store),
                        ["inventory expects %d bytes" % ie.text_size,
                         "file is actually %d bytes" % fp['size'],
                         "store is probably damaged/corrupt"])

        if ie.text_sha1 != fp['sha1']:
            raise BzrError("wrong SHA-1 for file %r in %r" % (ie.file_id, self._store),
                    ["inventory expects %s" % ie.text_sha1,
                     "file is actually %s" % fp['sha1'],
                     "store is probably damaged/corrupt"])

    def path2id(self, path):
        """Return the id for path in this tree."""
        return self._inventory.path2id(path)

    def print_file(self, file_id):
        """Print file with id `file_id` to stdout."""
        import sys
        sys.stdout.write(self.get_file_text(file_id))

    def lock_read(self):
        pass

    def revision_tree(self, revision_id):
        """Obtain a revision tree for the revision revision_id.

        The intention of this method is to allow access to possibly cached
        tree data. Implementors of this method should raise NoSuchRevision if
        the tree is not locally available, even if they could obtain the 
        tree via a repository or some other means. Callers are responsible 
        for finding the ultimate source for a revision tree.

        :param revision_id: The revision_id of the requested tree.
        :return: A Tree.
        :raises: NoSuchRevision if the tree cannot be obtained.
        """
        raise errors.NoSuchRevisionInTree(self, revision_id)

    def unknowns(self):
        """What files are present in this tree and unknown.
        
        :return: an iterator over the unknown files.
        """
        return iter([])

    def unlock(self):
        pass

    def filter_unversioned_files(self, paths):
        """Filter out paths that are not versioned.

        :return: set of paths.
        """
        # NB: we specifically *don't* call self.has_filename, because for
        # WorkingTrees that can indicate files that exist on disk but that 
        # are not versioned.
        pred = self.inventory.has_filename
        return set((p for p in paths if not pred(p)))

    def walkdirs(self, prefix=""):
        """Walk the contents of this tree from path down.

        This yields all the data about the contents of a directory at a time.
        After each directory has been yielded, if the caller has mutated the
        list to exclude some directories, they are then not descended into.
        
        The data yielded is of the form:
        ((directory-relpath, directory-path-from-root, directory-fileid),
        [(relpath, basename, kind, lstat, path_from_tree_root, file_id, 
          versioned_kind), ...]),
         - directory-relpath is the containing dirs relpath from prefix
         - directory-path-from-root is the containing dirs path from /
         - directory-fileid is the id of the directory if it is versioned.
         - relpath is the relative path within the subtree being walked.
         - basename is the basename
         - kind is the kind of the file now. If unknonwn then the file is not
           present within the tree - but it may be recorded as versioned. See
           versioned_kind.
         - lstat is the stat data *if* the file was statted.
         - path_from_tree_root is the path from the root of the tree.
         - file_id is the file_id is the entry is versioned.
         - versioned_kind is the kind of the file as last recorded in the 
           versioning system. If 'unknown' the file is not versioned.
        One of 'kind' and 'versioned_kind' must not be 'unknown'.

        :param prefix: Start walking from prefix within the tree rather than
        at the root. This allows one to walk a subtree but get paths that are
        relative to a tree rooted higher up.
        :return: an iterator over the directory data.
        """
        raise NotImplementedError(self.walkdirs)


class EmptyTree(Tree):

    def __init__(self):
        self._inventory = Inventory(root_id=None)
        symbol_versioning.warn('EmptyTree is deprecated as of bzr 0.9 please'
                               ' use repository.revision_tree instead.',
                               DeprecationWarning, stacklevel=2)

    def get_parent_ids(self):
        return []

    def get_symlink_target(self, file_id):
        return None

    def has_filename(self, filename):
        return False

    def kind(self, file_id):
        assert self._inventory[file_id].kind == "directory"
        return "directory"

    def list_files(self, include_root=False):
        return iter([])
    
    def __contains__(self, file_id):
        return (file_id in self._inventory)

    def get_file_sha1(self, file_id, path=None, stat_value=None):
        return None


######################################################################
# diff

# TODO: Merge these two functions into a single one that can operate
# on either a whole tree or a set of files.

# TODO: Return the diff in order by filename, not by category or in
# random order.  Can probably be done by lock-stepping through the
# filenames from both trees.


def file_status(filename, old_tree, new_tree):
    """Return single-letter status, old and new names for a file.

    The complexity here is in deciding how to represent renames;
    many complex cases are possible.
    """
    old_inv = old_tree.inventory
    new_inv = new_tree.inventory
    new_id = new_inv.path2id(filename)
    old_id = old_inv.path2id(filename)

    if not new_id and not old_id:
        # easy: doesn't exist in either; not versioned at all
        if new_tree.is_ignored(filename):
            return 'I', None, None
        else:
            return '?', None, None
    elif new_id:
        # There is now a file of this name, great.
        pass
    else:
        # There is no longer a file of this name, but we can describe
        # what happened to the file that used to have
        # this name.  There are two possibilities: either it was
        # deleted entirely, or renamed.
        assert old_id
        if new_inv.has_id(old_id):
            return 'X', old_inv.id2path(old_id), new_inv.id2path(old_id)
        else:
            return 'D', old_inv.id2path(old_id), None

    # if the file_id is new in this revision, it is added
    if new_id and not old_inv.has_id(new_id):
        return 'A'

    # if there used to be a file of this name, but that ID has now
    # disappeared, it is deleted
    if old_id and not new_inv.has_id(old_id):
        return 'D'

    return 'wtf?'

    

def find_renames(old_inv, new_inv):
    for file_id in old_inv:
        if file_id not in new_inv:
            continue
        old_name = old_inv.id2path(file_id)
        new_name = new_inv.id2path(file_id)
        if old_name != new_name:
            yield (old_name, new_name)
            

def find_ids_across_trees(filenames, trees, require_versioned=True):
    """Find the ids corresponding to specified filenames.
    
    All matches in all trees will be used, and all children of matched
    directories will be used.

    :param filenames: The filenames to find file_ids for
    :param trees: The trees to find file_ids within
    :param require_versioned: if true, all specified filenames must occur in
    at least one tree.
    :return: a set of file ids for the specified filenames and their children.
    """
    if not filenames:
        return None
    specified_ids = _find_filename_ids_across_trees(filenames, trees, 
                                                    require_versioned)
    return _find_children_across_trees(specified_ids, trees)


def _find_filename_ids_across_trees(filenames, trees, require_versioned):
    """Find the ids corresponding to specified filenames.
    
    All matches in all trees will be used.

    :param filenames: The filenames to find file_ids for
    :param trees: The trees to find file_ids within
    :param require_versioned: if true, all specified filenames must occur in
    at least one tree.
    :return: a set of file ids for the specified filenames
    """
    not_versioned = []
    interesting_ids = set()
    for tree_path in filenames:
        not_found = True
        for tree in trees:
            file_id = tree.inventory.path2id(tree_path)
            if file_id is not None:
                interesting_ids.add(file_id)
                not_found = False
        if not_found:
            not_versioned.append(tree_path)
    if len(not_versioned) > 0 and require_versioned:
        raise errors.PathsNotVersionedError(not_versioned)
    return interesting_ids


def _find_children_across_trees(specified_ids, trees):
    """Return a set including specified ids and their children
    
    All matches in all trees will be used.

    :param trees: The trees to find file_ids within
    :return: a set containing all specified ids and their children 
    """
    interesting_ids = set(specified_ids)
    pending = interesting_ids
    # now handle children of interesting ids
    # we loop so that we handle all children of each id in both trees
    while len(pending) > 0:
        new_pending = set()
        for file_id in pending:
            for tree in trees:
                if file_id not in tree:
                    continue
                entry = tree.inventory[file_id]
                for child in getattr(entry, 'children', {}).itervalues():
                    if child.file_id not in interesting_ids:
                        new_pending.add(child.file_id)
        interesting_ids.update(new_pending)
        pending = new_pending
    return interesting_ids


class InterTree(InterObject):
    """This class represents operations taking place between two Trees.

    Its instances have methods like 'compare' and contain references to the
    source and target trees these operations are to be carried out on.

    clients of bzrlib should not need to use InterTree directly, rather they
    should use the convenience methods on Tree such as 'Tree.compare()' which
    will pass through to InterTree as appropriate.
    """

    _optimisers = []

    @needs_read_lock
    def compare(self, want_unchanged=False, specific_files=None,
        extra_trees=None, require_versioned=False, include_root=False):
        """Return the changes from source to target.

        :return: A TreeDelta.
        :param specific_files: An optional list of file paths to restrict the
            comparison to. When mapping filenames to ids, all matches in all
            trees (including optional extra_trees) are used, and all children of
            matched directories are included.
        :param want_unchanged: An optional boolean requesting the inclusion of
            unchanged entries in the result.
        :param extra_trees: An optional list of additional trees to use when
            mapping the contents of specific_files (paths) to file_ids.
        :param require_versioned: An optional boolean (defaults to False). When
            supplied and True all the 'specific_files' must be versioned, or
            a PathsNotVersionedError will be thrown.
        """
        # NB: show_status depends on being able to pass in non-versioned files and
        # report them as unknown
        trees = (self.source, self.target)
        if extra_trees is not None:
            trees = trees + tuple(extra_trees)
        specific_file_ids = find_ids_across_trees(specific_files,
            trees, require_versioned=require_versioned)
        if specific_files and not specific_file_ids:
            # All files are unversioned, so just return an empty delta
            # _compare_trees would think we want a complete delta
            return delta.TreeDelta()
        return delta._compare_trees(self.source, self.target, want_unchanged,
            specific_file_ids, include_root)

    def _iter_changes(self, from_tree, to_tree, include_unchanged, 
                      specific_file_ids, pb):
        """Generate an iterator of changes between trees.

        A tuple is returned:
        (file_id, path, changed_content, versioned, parent, name, kind,
         executable)

        Path is relative to the to_tree.  changed_content is True if the file's
        content has changed.  This includes changes to its kind, and to
        a symlink's target.

        versioned, parent, name, kind, executable are tuples of (from, to).
        If a file is missing in a tree, its kind is None.

        Iteration is done in parent-to-child order, relative to the to_tree.
        """
        to_paths = {}
        from_entries_by_dir = list(from_tree.inventory.iter_entries_by_dir(
            specific_file_ids=specific_file_ids))
        from_data = dict((e.file_id, (p, e)) for p, e in from_entries_by_dir)
        to_entries_by_dir = list(to_tree.inventory.iter_entries_by_dir(
            specific_file_ids=specific_file_ids))
        num_entries = len(from_entries_by_dir) + len(to_entries_by_dir)
        entry_count = 0
        for to_path, to_entry in to_entries_by_dir:
            file_id = to_entry.file_id
            to_paths[file_id] = to_path
            entry_count += 1
            changed_content = False
            from_path, from_entry = from_data.get(file_id, (None, None))
            from_versioned = (from_entry is not None)
            if from_entry is not None:
                from_versioned = True
                from_name = from_entry.name
                from_parent = from_entry.parent_id
                from_kind, from_executable, from_stat = \
                    from_tree._comparison_data(from_entry, from_path)
                entry_count += 1
            else:
                from_versioned = False
                from_kind = None
                from_parent = None
                from_name = None
                from_executable = None
            versioned = (from_versioned, True)
            to_kind, to_executable, to_stat = \
                to_tree._comparison_data(to_entry, to_path)
            kind = (from_kind, to_kind)
            if kind[0] != kind[1]:
                changed_content = True
            elif from_kind == 'file':
                from_size = from_tree._file_size(from_entry, from_stat)
                to_size = to_tree._file_size(to_entry, to_stat)
                if from_size != to_size:
                    changed_content = True
                elif (from_tree.get_file_sha1(file_id, from_path, from_stat) !=
                    to_tree.get_file_sha1(file_id, to_path, to_stat)):
                    changed_content = True
            elif from_kind == 'symlink':
                if (from_tree.get_symlink_target(file_id) != 
                    to_tree.get_symlink_target(file_id)):
                    changed_content = True
            parent = (from_parent, to_entry.parent_id)
            name = (from_name, to_entry.name)
            executable = (from_executable, to_executable)
            if pb is not None:
                pb.update('comparing files', entry_count, num_entries)
            if (changed_content is not False or versioned[0] != versioned[1] 
                or parent[0] != parent[1] or name[0] != name[1] or 
                executable[0] != executable[1] or include_unchanged):
                yield (file_id, to_path, changed_content, versioned, parent,
                       name, kind, executable)

        def get_to_path(from_entry):
            if from_entry.parent_id is None:
                to_path = ''
            else:
                if from_entry.parent_id not in to_paths:
                    get_to_path(from_tree.inventory[from_entry.parent_id])
                to_path = osutils.pathjoin(to_paths[from_entry.parent_id],
                                           from_entry.name)
            to_paths[from_entry.file_id] = to_path
            return to_path

        for path, from_entry in from_entries_by_dir:
            file_id = from_entry.file_id
            if file_id in to_paths:
                continue
            to_path = get_to_path(from_entry)
            entry_count += 1
            if pb is not None:
                pb.update('comparing files', entry_count, num_entries)
            versioned = (True, False)
            parent = (from_entry.parent_id, None)
            name = (from_entry.name, None)
            from_kind, from_executable, stat_value = \
                from_tree._comparison_data(from_entry, path)
            kind = (from_kind, None)
            executable = (from_executable, None)
            changed_content = True
            # the parent's path is necessarily known at this point.
            yield(file_id, to_path, changed_content, versioned, parent,
                  name, kind, executable)


# This was deprecated before 0.12, but did not have an official warning
@symbol_versioning.deprecated_function(symbol_versioning.zero_twelve)
def RevisionTree(*args, **kwargs):
    """RevisionTree has moved to bzrlib.revisiontree.RevisionTree()

    Accessing it as bzrlib.tree.RevisionTree has been deprecated as of
    bzr 0.12.
    """
    from bzrlib.revisiontree import RevisionTree as _RevisionTree
    return _RevisionTree(*args, **kwargs)
 

