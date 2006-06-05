# Copyright (C) 2006 Canonical Ltd

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

import os
import errno
from stat import S_ISREG

from bzrlib.errors import (DuplicateKey, MalformedTransform, NoSuchFile,
                           ReusingTransform, NotVersionedError, CantMoveRoot,
                           ExistingLimbo, ImmortalLimbo)
from bzrlib.inventory import InventoryEntry
from bzrlib.osutils import (file_kind, supports_executable, pathjoin, lexists,
                            delete_any)
from bzrlib.progress import DummyProgress, ProgressPhase
from bzrlib.trace import mutter, warning
import bzrlib.ui 


ROOT_PARENT = "root-parent"


def unique_add(map, key, value):
    if key in map:
        raise DuplicateKey(key=key)
    map[key] = value


class _TransformResults(object):
    def __init__(self, modified_paths):
        object.__init__(self)
        self.modified_paths = modified_paths


class TreeTransform(object):
    """Represent a tree transformation.
    
    This object is designed to support incremental generation of the transform,
    in any order.  
    
    It is easy to produce malformed transforms, but they are generally
    harmless.  Attempting to apply a malformed transform will cause an
    exception to be raised before any modifications are made to the tree.  

    Many kinds of malformed transforms can be corrected with the 
    resolve_conflicts function.  The remaining ones indicate programming error,
    such as trying to create a file with no path.

    Two sets of file creation methods are supplied.  Convenience methods are:
     * new_file
     * new_directory
     * new_symlink

    These are composed of the low-level methods:
     * create_path
     * create_file or create_directory or create_symlink
     * version_file
     * set_executability
    """
    def __init__(self, tree, pb=DummyProgress()):
        """Note: a write lock is taken on the tree.
        
        Use TreeTransform.finalize() to release the lock
        """
        object.__init__(self)
        self._tree = tree
        self._tree.lock_write()
        try:
            control_files = self._tree._control_files
            self._limbodir = control_files.controlfilename('limbo')
            try:
                os.mkdir(self._limbodir)
            except OSError, e:
                if e.errno == errno.EEXIST:
                    raise ExistingLimbo(self._limbodir)
        except: 
            self._tree.unlock()
            raise

        self._id_number = 0
        self._new_name = {}
        self._new_parent = {}
        self._new_contents = {}
        self._removed_contents = set()
        self._new_executability = {}
        self._new_id = {}
        self._non_present_ids = {}
        self._r_new_id = {}
        self._removed_id = set()
        self._tree_path_ids = {}
        self._tree_id_paths = {}
        self._realpaths = {}
        # Cache of realpath results, to speed up canonical_path
        self._relpaths = {}
        # Cache of relpath results, to speed up canonical_path
        self._new_root = self.trans_id_tree_file_id(tree.get_root_id())
        self.__done = False
        self._pb = pb

    def __get_root(self):
        return self._new_root

    root = property(__get_root)

    def finalize(self):
        """Release the working tree lock, if held, clean up limbo dir."""
        if self._tree is None:
            return
        try:
            for trans_id, kind in self._new_contents.iteritems():
                path = self._limbo_name(trans_id)
                if kind == "directory":
                    os.rmdir(path)
                else:
                    os.unlink(path)
            try:
                os.rmdir(self._limbodir)
            except OSError:
                # We don't especially care *why* the dir is immortal.
                raise ImmortalLimbo(self._limbodir)
        finally:
            self._tree.unlock()
            self._tree = None

    def _assign_id(self):
        """Produce a new tranform id"""
        new_id = "new-%s" % self._id_number
        self._id_number +=1
        return new_id

    def create_path(self, name, parent):
        """Assign a transaction id to a new path"""
        trans_id = self._assign_id()
        unique_add(self._new_name, trans_id, name)
        unique_add(self._new_parent, trans_id, parent)
        return trans_id

    def adjust_path(self, name, parent, trans_id):
        """Change the path that is assigned to a transaction id."""
        if trans_id == self._new_root:
            raise CantMoveRoot
        self._new_name[trans_id] = name
        self._new_parent[trans_id] = parent

    def adjust_root_path(self, name, parent):
        """Emulate moving the root by moving all children, instead.
        
        We do this by undoing the association of root's transaction id with the
        current tree.  This allows us to create a new directory with that
        transaction id.  We unversion the root directory and version the 
        physically new directory, and hope someone versions the tree root
        later.
        """
        old_root = self._new_root
        old_root_file_id = self.final_file_id(old_root)
        # force moving all children of root
        for child_id in self.iter_tree_children(old_root):
            if child_id != parent:
                self.adjust_path(self.final_name(child_id), 
                                 self.final_parent(child_id), child_id)
            file_id = self.final_file_id(child_id)
            if file_id is not None:
                self.unversion_file(child_id)
            self.version_file(file_id, child_id)
        
        # the physical root needs a new transaction id
        self._tree_path_ids.pop("")
        self._tree_id_paths.pop(old_root)
        self._new_root = self.trans_id_tree_file_id(self._tree.get_root_id())
        if parent == old_root:
            parent = self._new_root
        self.adjust_path(name, parent, old_root)
        self.create_directory(old_root)
        self.version_file(old_root_file_id, old_root)
        self.unversion_file(self._new_root)

    def trans_id_tree_file_id(self, inventory_id):
        """Determine the transaction id of a working tree file.
        
        This reflects only files that already exist, not ones that will be
        added by transactions.
        """
        path = self._tree.inventory.id2path(inventory_id)
        return self.trans_id_tree_path(path)

    def trans_id_file_id(self, file_id):
        """Determine or set the transaction id associated with a file ID.
        A new id is only created for file_ids that were never present.  If
        a transaction has been unversioned, it is deliberately still returned.
        (this will likely lead to an unversioned parent conflict.)
        """
        if file_id in self._r_new_id and self._r_new_id[file_id] is not None:
            return self._r_new_id[file_id]
        elif file_id in self._tree.inventory:
            return self.trans_id_tree_file_id(file_id)
        elif file_id in self._non_present_ids:
            return self._non_present_ids[file_id]
        else:
            trans_id = self._assign_id()
            self._non_present_ids[file_id] = trans_id
            return trans_id

    def canonical_path(self, path):
        """Get the canonical tree-relative path"""
        # don't follow final symlinks
        abs = self._tree.abspath(path)
        if abs in self._relpaths:
            return self._relpaths[abs]
        dirname, basename = os.path.split(abs)
        if dirname not in self._realpaths:
            self._realpaths[dirname] = os.path.realpath(dirname)
        dirname = self._realpaths[dirname]
        abs = pathjoin(dirname, basename)
        if dirname in self._relpaths:
            relpath = pathjoin(self._relpaths[dirname], basename)
            relpath = relpath.rstrip('/\\')
        else:
            relpath = self._tree.relpath(abs)
        self._relpaths[abs] = relpath
        return relpath

    def trans_id_tree_path(self, path):
        """Determine (and maybe set) the transaction ID for a tree path."""
        path = self.canonical_path(path)
        if path not in self._tree_path_ids:
            self._tree_path_ids[path] = self._assign_id()
            self._tree_id_paths[self._tree_path_ids[path]] = path
        return self._tree_path_ids[path]

    def get_tree_parent(self, trans_id):
        """Determine id of the parent in the tree."""
        path = self._tree_id_paths[trans_id]
        if path == "":
            return ROOT_PARENT
        return self.trans_id_tree_path(os.path.dirname(path))

    def create_file(self, contents, trans_id, mode_id=None):
        """Schedule creation of a new file.

        See also new_file.
        
        Contents is an iterator of strings, all of which will be written
        to the target destination.

        New file takes the permissions of any existing file with that id,
        unless mode_id is specified.
        """
        f = file(self._limbo_name(trans_id), 'wb')
        unique_add(self._new_contents, trans_id, 'file')
        for segment in contents:
            f.write(segment)
        f.close()
        self._set_mode(trans_id, mode_id, S_ISREG)

    def _set_mode(self, trans_id, mode_id, typefunc):
        """Set the mode of new file contents.
        The mode_id is the existing file to get the mode from (often the same
        as trans_id).  The operation is only performed if there's a mode match
        according to typefunc.
        """
        if mode_id is None:
            mode_id = trans_id
        try:
            old_path = self._tree_id_paths[mode_id]
        except KeyError:
            return
        try:
            mode = os.stat(old_path).st_mode
        except OSError, e:
            if e.errno == errno.ENOENT:
                return
            else:
                raise
        if typefunc(mode):
            os.chmod(self._limbo_name(trans_id), mode)

    def create_directory(self, trans_id):
        """Schedule creation of a new directory.
        
        See also new_directory.
        """
        os.mkdir(self._limbo_name(trans_id))
        unique_add(self._new_contents, trans_id, 'directory')

    def create_symlink(self, target, trans_id):
        """Schedule creation of a new symbolic link.

        target is a bytestring.
        See also new_symlink.
        """
        os.symlink(target, self._limbo_name(trans_id))
        unique_add(self._new_contents, trans_id, 'symlink')

    def cancel_creation(self, trans_id):
        """Cancel the creation of new file contents."""
        del self._new_contents[trans_id]
        delete_any(self._limbo_name(trans_id))

    def delete_contents(self, trans_id):
        """Schedule the contents of a path entry for deletion"""
        self.tree_kind(trans_id)
        self._removed_contents.add(trans_id)

    def cancel_deletion(self, trans_id):
        """Cancel a scheduled deletion"""
        self._removed_contents.remove(trans_id)

    def unversion_file(self, trans_id):
        """Schedule a path entry to become unversioned"""
        self._removed_id.add(trans_id)

    def delete_versioned(self, trans_id):
        """Delete and unversion a versioned file"""
        self.delete_contents(trans_id)
        self.unversion_file(trans_id)

    def set_executability(self, executability, trans_id):
        """Schedule setting of the 'execute' bit
        To unschedule, set to None
        """
        if executability is None:
            del self._new_executability[trans_id]
        else:
            unique_add(self._new_executability, trans_id, executability)

    def version_file(self, file_id, trans_id):
        """Schedule a file to become versioned."""
        assert file_id is not None
        unique_add(self._new_id, trans_id, file_id)
        unique_add(self._r_new_id, file_id, trans_id)

    def cancel_versioning(self, trans_id):
        """Undo a previous versioning of a file"""
        file_id = self._new_id[trans_id]
        del self._new_id[trans_id]
        del self._r_new_id[file_id]

    def new_paths(self):
        """Determine the paths of all new and changed files"""
        new_ids = set()
        fp = FinalPaths(self)
        for id_set in (self._new_name, self._new_parent, self._new_contents,
                       self._new_id, self._new_executability):
            new_ids.update(id_set)
        new_paths = [(fp.get_path(t), t) for t in new_ids]
        new_paths.sort()
        return new_paths

    def tree_kind(self, trans_id):
        """Determine the file kind in the working tree.

        Raises NoSuchFile if the file does not exist
        """
        path = self._tree_id_paths.get(trans_id)
        if path is None:
            raise NoSuchFile(None)
        try:
            return file_kind(self._tree.abspath(path))
        except OSError, e:
            if e.errno != errno.ENOENT:
                raise
            else:
                raise NoSuchFile(path)

    def final_kind(self, trans_id):
        """Determine the final file kind, after any changes applied.
        
        Raises NoSuchFile if the file does not exist/has no contents.
        (It is conceivable that a path would be created without the
        corresponding contents insertion command)
        """
        if trans_id in self._new_contents:
            return self._new_contents[trans_id]
        elif trans_id in self._removed_contents:
            raise NoSuchFile(None)
        else:
            return self.tree_kind(trans_id)

    def tree_file_id(self, trans_id):
        """Determine the file id associated with the trans_id in the tree"""
        try:
            path = self._tree_id_paths[trans_id]
        except KeyError:
            # the file is a new, unversioned file, or invalid trans_id
            return None
        # the file is old; the old id is still valid
        if self._new_root == trans_id:
            return self._tree.inventory.root.file_id
        return self._tree.inventory.path2id(path)

    def final_file_id(self, trans_id):
        """Determine the file id after any changes are applied, or None.
        
        None indicates that the file will not be versioned after changes are
        applied.
        """
        try:
            # there is a new id for this file
            assert self._new_id[trans_id] is not None
            return self._new_id[trans_id]
        except KeyError:
            if trans_id in self._removed_id:
                return None
        return self.tree_file_id(trans_id)

    def inactive_file_id(self, trans_id):
        """Return the inactive file_id associated with a transaction id.
        That is, the one in the tree or in non_present_ids.
        The file_id may actually be active, too.
        """
        file_id = self.tree_file_id(trans_id)
        if file_id is not None:
            return file_id
        for key, value in self._non_present_ids.iteritems():
            if value == trans_id:
                return key

    def final_parent(self, trans_id):
        """Determine the parent file_id, after any changes are applied.

        ROOT_PARENT is returned for the tree root.
        """
        try:
            return self._new_parent[trans_id]
        except KeyError:
            return self.get_tree_parent(trans_id)

    def final_name(self, trans_id):
        """Determine the final filename, after all changes are applied."""
        try:
            return self._new_name[trans_id]
        except KeyError:
            return os.path.basename(self._tree_id_paths[trans_id])

    def by_parent(self):
        """Return a map of parent: children for known parents.
        
        Only new paths and parents of tree files with assigned ids are used.
        """
        by_parent = {}
        items = list(self._new_parent.iteritems())
        items.extend((t, self.final_parent(t)) for t in 
                      self._tree_id_paths.keys())
        for trans_id, parent_id in items:
            if parent_id not in by_parent:
                by_parent[parent_id] = set()
            by_parent[parent_id].add(trans_id)
        return by_parent

    def path_changed(self, trans_id):
        """Return True if a trans_id's path has changed."""
        return trans_id in self._new_name or trans_id in self._new_parent

    def find_conflicts(self):
        """Find any violations of inventory or filesystem invariants"""
        if self.__done is True:
            raise ReusingTransform()
        conflicts = []
        # ensure all children of all existent parents are known
        # all children of non-existent parents are known, by definition.
        self._add_tree_children()
        by_parent = self.by_parent()
        conflicts.extend(self._unversioned_parents(by_parent))
        conflicts.extend(self._parent_loops())
        conflicts.extend(self._duplicate_entries(by_parent))
        conflicts.extend(self._duplicate_ids())
        conflicts.extend(self._parent_type_conflicts(by_parent))
        conflicts.extend(self._improper_versioning())
        conflicts.extend(self._executability_conflicts())
        conflicts.extend(self._overwrite_conflicts())
        return conflicts

    def _add_tree_children(self):
        """Add all the children of all active parents to the known paths.

        Active parents are those which gain children, and those which are
        removed.  This is a necessary first step in detecting conflicts.
        """
        parents = self.by_parent().keys()
        parents.extend([t for t in self._removed_contents if 
                        self.tree_kind(t) == 'directory'])
        for trans_id in self._removed_id:
            file_id = self.tree_file_id(trans_id)
            if self._tree.inventory[file_id].kind in ('directory', 
                                                      'root_directory'):
                parents.append(trans_id)

        for parent_id in parents:
            # ensure that all children are registered with the transaction
            list(self.iter_tree_children(parent_id))

    def iter_tree_children(self, parent_id):
        """Iterate through the entry's tree children, if any"""
        try:
            path = self._tree_id_paths[parent_id]
        except KeyError:
            return
        try:
            children = os.listdir(self._tree.abspath(path))
        except OSError, e:
            if e.errno != errno.ENOENT and e.errno != errno.ESRCH:
                raise
            return
            
        for child in children:
            childpath = joinpath(path, child)
            if self._tree.is_control_filename(childpath):
                continue
            yield self.trans_id_tree_path(childpath)

    def has_named_child(self, by_parent, parent_id, name):
        try:
            children = by_parent[parent_id]
        except KeyError:
            children = []
        for child in children:
            if self.final_name(child) == name:
                return True
        try:
            path = self._tree_id_paths[parent_id]
        except KeyError:
            return False
        childpath = joinpath(path, name)
        child_id = self._tree_path_ids.get(childpath)
        if child_id is None:
            return lexists(self._tree.abspath(childpath))
        else:
            if tt.final_parent(child_id) != parent_id:
                return False
            if child_id in tt._removed_contents:
                # XXX What about dangling file-ids?
                return False
            else:
                return True

    def _parent_loops(self):
        """No entry should be its own ancestor"""
        conflicts = []
        for trans_id in self._new_parent:
            seen = set()
            parent_id = trans_id
            while parent_id is not ROOT_PARENT:
                seen.add(parent_id)
                parent_id = self.final_parent(parent_id)
                if parent_id == trans_id:
                    conflicts.append(('parent loop', trans_id))
                if parent_id in seen:
                    break
        return conflicts

    def _unversioned_parents(self, by_parent):
        """If parent directories are versioned, children must be versioned."""
        conflicts = []
        for parent_id, children in by_parent.iteritems():
            if parent_id is ROOT_PARENT:
                continue
            if self.final_file_id(parent_id) is not None:
                continue
            for child_id in children:
                if self.final_file_id(child_id) is not None:
                    conflicts.append(('unversioned parent', parent_id))
                    break;
        return conflicts

    def _improper_versioning(self):
        """Cannot version a file with no contents, or a bad type.
        
        However, existing entries with no contents are okay.
        """
        conflicts = []
        for trans_id in self._new_id.iterkeys():
            try:
                kind = self.final_kind(trans_id)
            except NoSuchFile:
                conflicts.append(('versioning no contents', trans_id))
                continue
            if not InventoryEntry.versionable_kind(kind):
                conflicts.append(('versioning bad kind', trans_id, kind))
        return conflicts

    def _executability_conflicts(self):
        """Check for bad executability changes.
        
        Only versioned files may have their executability set, because
        1. only versioned entries can have executability under windows
        2. only files can be executable.  (The execute bit on a directory
           does not indicate searchability)
        """
        conflicts = []
        for trans_id in self._new_executability:
            if self.final_file_id(trans_id) is None:
                conflicts.append(('unversioned executability', trans_id))
            else:
                try:
                    non_file = self.final_kind(trans_id) != "file"
                except NoSuchFile:
                    non_file = True
                if non_file is True:
                    conflicts.append(('non-file executability', trans_id))
        return conflicts

    def _overwrite_conflicts(self):
        """Check for overwrites (not permitted on Win32)"""
        conflicts = []
        for trans_id in self._new_contents:
            try:
                self.tree_kind(trans_id)
            except NoSuchFile:
                continue
            if trans_id not in self._removed_contents:
                conflicts.append(('overwrite', trans_id,
                                 self.final_name(trans_id)))
        return conflicts

    def _duplicate_entries(self, by_parent):
        """No directory may have two entries with the same name."""
        conflicts = []
        for children in by_parent.itervalues():
            name_ids = [(self.final_name(t), t) for t in children]
            name_ids.sort()
            last_name = None
            last_trans_id = None
            for name, trans_id in name_ids:
                if name == last_name:
                    conflicts.append(('duplicate', last_trans_id, trans_id,
                    name))
                try:
                    kind = self.final_kind(trans_id)
                except NoSuchFile:
                    kind = None
                file_id = self.final_file_id(trans_id)
                if kind is not None or file_id is not None:
                    last_name = name
                    last_trans_id = trans_id
        return conflicts

    def _duplicate_ids(self):
        """Each inventory id may only be used once"""
        conflicts = []
        removed_tree_ids = set((self.tree_file_id(trans_id) for trans_id in
                                self._removed_id))
        active_tree_ids = set((f for f in self._tree.inventory if
                               f not in removed_tree_ids))
        for trans_id, file_id in self._new_id.iteritems():
            if file_id in active_tree_ids:
                old_trans_id = self.trans_id_tree_file_id(file_id)
                conflicts.append(('duplicate id', old_trans_id, trans_id))
        return conflicts

    def _parent_type_conflicts(self, by_parent):
        """parents must have directory 'contents'."""
        conflicts = []
        for parent_id, children in by_parent.iteritems():
            if parent_id is ROOT_PARENT:
                continue
            if not self._any_contents(children):
                continue
            for child in children:
                try:
                    self.final_kind(child)
                except NoSuchFile:
                    continue
            try:
                kind = self.final_kind(parent_id)
            except NoSuchFile:
                kind = None
            if kind is None:
                conflicts.append(('missing parent', parent_id))
            elif kind != "directory":
                conflicts.append(('non-directory parent', parent_id))
        return conflicts

    def _any_contents(self, trans_ids):
        """Return true if any of the trans_ids, will have contents."""
        for trans_id in trans_ids:
            try:
                kind = self.final_kind(trans_id)
            except NoSuchFile:
                continue
            return True
        return False
            
    def apply(self):
        """Apply all changes to the inventory and filesystem.
        
        If filesystem or inventory conflicts are present, MalformedTransform
        will be thrown.
        """
        conflicts = self.find_conflicts()
        if len(conflicts) != 0:
            raise MalformedTransform(conflicts=conflicts)
        limbo_inv = {}
        inv = self._tree.inventory
        child_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            child_pb.update('Apply phase', 0, 2)
            self._apply_removals(inv, limbo_inv)
            child_pb.update('Apply phase', 1, 2)
            modified_paths = self._apply_insertions(inv, limbo_inv)
        finally:
            child_pb.finished()
        self._tree._write_inventory(inv)
        self.__done = True
        self.finalize()
        return _TransformResults(modified_paths)

    def _limbo_name(self, trans_id):
        """Generate the limbo name of a file"""
        return pathjoin(self._limbodir, trans_id)

    def _apply_removals(self, inv, limbo_inv):
        """Perform tree operations that remove directory/inventory names.
        
        That is, delete files that are to be deleted, and put any files that
        need renaming into limbo.  This must be done in strict child-to-parent
        order.
        """
        tree_paths = list(self._tree_path_ids.iteritems())
        tree_paths.sort(reverse=True)
        child_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            for num, data in enumerate(tree_paths):
                path, trans_id = data
                child_pb.update('removing file', num, len(tree_paths))
                full_path = self._tree.abspath(path)
                if trans_id in self._removed_contents:
                    delete_any(full_path)
                elif trans_id in self._new_name or trans_id in \
                    self._new_parent:
                    try:
                        os.rename(full_path, self._limbo_name(trans_id))
                    except OSError, e:
                        if e.errno != errno.ENOENT:
                            raise
                if trans_id in self._removed_id:
                    if trans_id == self._new_root:
                        file_id = self._tree.inventory.root.file_id
                    else:
                        file_id = self.tree_file_id(trans_id)
                    del inv[file_id]
                elif trans_id in self._new_name or trans_id in self._new_parent:
                    file_id = self.tree_file_id(trans_id)
                    if file_id is not None:
                        limbo_inv[trans_id] = inv[file_id]
                        del inv[file_id]
        finally:
            child_pb.finished()

    def _apply_insertions(self, inv, limbo_inv):
        """Perform tree operations that insert directory/inventory names.
        
        That is, create any files that need to be created, and restore from
        limbo any files that needed renaming.  This must be done in strict
        parent-to-child order.
        """
        new_paths = self.new_paths()
        modified_paths = []
        child_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            for num, (path, trans_id) in enumerate(new_paths):
                child_pb.update('adding file', num, len(new_paths))
                try:
                    kind = self._new_contents[trans_id]
                except KeyError:
                    kind = contents = None
                if trans_id in self._new_contents or \
                    self.path_changed(trans_id):
                    full_path = self._tree.abspath(path)
                    try:
                        os.rename(self._limbo_name(trans_id), full_path)
                    except OSError, e:
                        # We may be renaming a dangling inventory id
                        if e.errno != errno.ENOENT:
                            raise
                    if trans_id in self._new_contents:
                        modified_paths.append(full_path)
                        del self._new_contents[trans_id]

                if trans_id in self._new_id:
                    if kind is None:
                        kind = file_kind(self._tree.abspath(path))
                    inv.add_path(path, kind, self._new_id[trans_id])
                elif trans_id in self._new_name or trans_id in\
                    self._new_parent:
                    entry = limbo_inv.get(trans_id)
                    if entry is not None:
                        entry.name = self.final_name(trans_id)
                        parent_path = os.path.dirname(path)
                        entry.parent_id = \
                            self._tree.inventory.path2id(parent_path)
                        inv.add(entry)

                # requires files and inventory entries to be in place
                if trans_id in self._new_executability:
                    self._set_executability(path, inv, trans_id)
        finally:
            child_pb.finished()
        return modified_paths

    def _set_executability(self, path, inv, trans_id):
        """Set the executability of versioned files """
        file_id = inv.path2id(path)
        new_executability = self._new_executability[trans_id]
        inv[file_id].executable = new_executability
        if supports_executable():
            abspath = self._tree.abspath(path)
            current_mode = os.stat(abspath).st_mode
            if new_executability:
                umask = os.umask(0)
                os.umask(umask)
                to_mode = current_mode | (0100 & ~umask)
                # Enable x-bit for others only if they can read it.
                if current_mode & 0004:
                    to_mode |= 0001 & ~umask
                if current_mode & 0040:
                    to_mode |= 0010 & ~umask
            else:
                to_mode = current_mode & ~0111
            os.chmod(abspath, to_mode)

    def _new_entry(self, name, parent_id, file_id):
        """Helper function to create a new filesystem entry."""
        trans_id = self.create_path(name, parent_id)
        if file_id is not None:
            self.version_file(file_id, trans_id)
        return trans_id

    def new_file(self, name, parent_id, contents, file_id=None, 
                 executable=None):
        """Convenience method to create files.
        
        name is the name of the file to create.
        parent_id is the transaction id of the parent directory of the file.
        contents is an iterator of bytestrings, which will be used to produce
        the file.
        :param file_id: The inventory ID of the file, if it is to be versioned.
        :param executable: Only valid when a file_id has been supplied.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        # TODO: rather than scheduling a set_executable call,
        # have create_file create the file with the right mode.
        self.create_file(contents, trans_id)
        if executable is not None:
            self.set_executability(executable, trans_id)
        return trans_id

    def new_directory(self, name, parent_id, file_id=None):
        """Convenience method to create directories.

        name is the name of the directory to create.
        parent_id is the transaction id of the parent directory of the
        directory.
        file_id is the inventory ID of the directory, if it is to be versioned.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        self.create_directory(trans_id)
        return trans_id 

    def new_symlink(self, name, parent_id, target, file_id=None):
        """Convenience method to create symbolic link.
        
        name is the name of the symlink to create.
        parent_id is the transaction id of the parent directory of the symlink.
        target is a bytestring of the target of the symlink.
        file_id is the inventory ID of the file, if it is to be versioned.
        """
        trans_id = self._new_entry(name, parent_id, file_id)
        self.create_symlink(target, trans_id)
        return trans_id

def joinpath(parent, child):
    """Join tree-relative paths, handling the tree root specially"""
    if parent is None or parent == "":
        return child
    else:
        return pathjoin(parent, child)


class FinalPaths(object):
    """Make path calculation cheap by memoizing paths.

    The underlying tree must not be manipulated between calls, or else
    the results will likely be incorrect.
    """
    def __init__(self, transform):
        object.__init__(self)
        self._known_paths = {}
        self.transform = transform

    def _determine_path(self, trans_id):
        if trans_id == self.transform.root:
            return ""
        name = self.transform.final_name(trans_id)
        parent_id = self.transform.final_parent(trans_id)
        if parent_id == self.transform.root:
            return name
        else:
            return pathjoin(self.get_path(parent_id), name)

    def get_path(self, trans_id):
        """Find the final path associated with a trans_id"""
        if trans_id not in self._known_paths:
            self._known_paths[trans_id] = self._determine_path(trans_id)
        return self._known_paths[trans_id]

def topology_sorted_ids(tree):
    """Determine the topological order of the ids in a tree"""
    file_ids = list(tree)
    file_ids.sort(key=tree.id2path)
    return file_ids

def build_tree(tree, wt):
    """Create working tree for a branch, using a Transaction."""
    file_trans_id = {}
    top_pb = bzrlib.ui.ui_factory.nested_progress_bar()
    pp = ProgressPhase("Build phase", 2, top_pb)
    tt = TreeTransform(wt)
    try:
        pp.next_phase()
        file_trans_id[wt.get_root_id()] = tt.trans_id_tree_file_id(wt.get_root_id())
        file_ids = topology_sorted_ids(tree)
        pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            for num, file_id in enumerate(file_ids):
                pb.update("Building tree", num, len(file_ids))
                entry = tree.inventory[file_id]
                if entry.parent_id is None:
                    continue
                if entry.parent_id not in file_trans_id:
                    raise repr(entry.parent_id)
                parent_id = file_trans_id[entry.parent_id]
                file_trans_id[file_id] = new_by_entry(tt, entry, parent_id, 
                                                      tree)
        finally:
            pb.finished()
        pp.next_phase()
        tt.apply()
    finally:
        tt.finalize()
        top_pb.finished()

def new_by_entry(tt, entry, parent_id, tree):
    """Create a new file according to its inventory entry"""
    name = entry.name
    kind = entry.kind
    if kind == 'file':
        contents = tree.get_file(entry.file_id).readlines()
        executable = tree.is_executable(entry.file_id)
        return tt.new_file(name, parent_id, contents, entry.file_id, 
                           executable)
    elif kind == 'directory':
        return tt.new_directory(name, parent_id, entry.file_id)
    elif kind == 'symlink':
        target = tree.get_symlink_target(entry.file_id)
        return tt.new_symlink(name, parent_id, target, entry.file_id)

def create_by_entry(tt, entry, tree, trans_id, lines=None, mode_id=None):
    """Create new file contents according to an inventory entry."""
    if entry.kind == "file":
        if lines == None:
            lines = tree.get_file(entry.file_id).readlines()
        tt.create_file(lines, trans_id, mode_id=mode_id)
    elif entry.kind == "symlink":
        tt.create_symlink(tree.get_symlink_target(entry.file_id), trans_id)
    elif entry.kind == "directory":
        tt.create_directory(trans_id)

def create_entry_executability(tt, entry, trans_id):
    """Set the executability of a trans_id according to an inventory entry"""
    if entry.kind == "file":
        tt.set_executability(entry.executable, trans_id)


def find_interesting(working_tree, target_tree, filenames):
    """Find the ids corresponding to specified filenames."""
    if not filenames:
        interesting_ids = None
    else:
        interesting_ids = set()
        for tree_path in filenames:
            not_found = True
            for tree in (working_tree, target_tree):
                file_id = tree.inventory.path2id(tree_path)
                if file_id is not None:
                    interesting_ids.add(file_id)
                    not_found = False
            if not_found:
                raise NotVersionedError(path=tree_path)
    return interesting_ids


def change_entry(tt, file_id, working_tree, target_tree, 
                 trans_id_file_id, backups, trans_id, by_parent):
    """Replace a file_id's contents with those from a target tree."""
    e_trans_id = trans_id_file_id(file_id)
    entry = target_tree.inventory[file_id]
    has_contents, contents_mod, meta_mod, = _entry_changes(file_id, entry, 
                                                           working_tree)
    if contents_mod:
        mode_id = e_trans_id
        if has_contents:
            if not backups:
                tt.delete_contents(e_trans_id)
            else:
                parent_trans_id = trans_id_file_id(entry.parent_id)
                backup_name = get_backup_name(entry, by_parent,
                                              parent_trans_id, tt)
                tt.adjust_path(backup_name, parent_trans_id, e_trans_id)
                tt.unversion_file(e_trans_id)
                e_trans_id = tt.create_path(entry.name, parent_trans_id)
                tt.version_file(file_id, e_trans_id)
                trans_id[file_id] = e_trans_id
        create_by_entry(tt, entry, target_tree, e_trans_id, mode_id=mode_id)
        create_entry_executability(tt, entry, e_trans_id)

    elif meta_mod:
        tt.set_executability(entry.executable, e_trans_id)
    if tt.final_name(e_trans_id) != entry.name:
        adjust_path  = True
    else:
        parent_id = tt.final_parent(e_trans_id)
        parent_file_id = tt.final_file_id(parent_id)
        if parent_file_id != entry.parent_id:
            adjust_path = True
        else:
            adjust_path = False
    if adjust_path:
        parent_trans_id = trans_id_file_id(entry.parent_id)
        tt.adjust_path(entry.name, parent_trans_id, e_trans_id)


def get_backup_name(entry, by_parent, parent_trans_id, tt):
    """Produce a backup-style name that appears to be available"""
    def name_gen():
        counter = 1
        while True:
            yield "%s.~%d~" % (entry.name, counter)
            counter += 1
    for name in name_gen():
        if not tt.has_named_child(by_parent, parent_trans_id, name):
            return name

def _entry_changes(file_id, entry, working_tree):
    """Determine in which ways the inventory entry has changed.

    Returns booleans: has_contents, content_mod, meta_mod
    has_contents means there are currently contents, but they differ
    contents_mod means contents need to be modified
    meta_mod means the metadata needs to be modified
    """
    cur_entry = working_tree.inventory[file_id]
    try:
        working_kind = working_tree.kind(file_id)
        has_contents = True
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise
        has_contents = False
        contents_mod = True
        meta_mod = False
    if has_contents is True:
        real_e_kind = entry.kind
        if real_e_kind == 'root_directory':
            real_e_kind = 'directory'
        if real_e_kind != working_kind:
            contents_mod, meta_mod = True, False
        else:
            cur_entry._read_tree_state(working_tree.id2path(file_id), 
                                       working_tree)
            contents_mod, meta_mod = entry.detect_changes(cur_entry)
            cur_entry._forget_tree_state()
    return has_contents, contents_mod, meta_mod


def revert(working_tree, target_tree, filenames, backups=False, 
           pb=DummyProgress()):
    """Revert a working tree's contents to those of a target tree."""
    interesting_ids = find_interesting(working_tree, target_tree, filenames)
    def interesting(file_id):
        return interesting_ids is None or file_id in interesting_ids

    tt = TreeTransform(working_tree, pb)
    try:
        merge_modified = working_tree.merge_modified()
        trans_id = {}
        def trans_id_file_id(file_id):
            try:
                return trans_id[file_id]
            except KeyError:
                return tt.trans_id_tree_file_id(file_id)

        pp = ProgressPhase("Revert phase", 4, pb)
        pp.next_phase()
        sorted_interesting = [i for i in topology_sorted_ids(target_tree) if
                              interesting(i)]
        child_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            by_parent = tt.by_parent()
            for id_num, file_id in enumerate(sorted_interesting):
                child_pb.update("Reverting file", id_num+1, 
                                len(sorted_interesting))
                if file_id not in working_tree.inventory:
                    entry = target_tree.inventory[file_id]
                    parent_id = trans_id_file_id(entry.parent_id)
                    e_trans_id = new_by_entry(tt, entry, parent_id, target_tree)
                    trans_id[file_id] = e_trans_id
                else:
                    backup_this = backups
                    if file_id in merge_modified:
                        backup_this = False
                        del merge_modified[file_id]
                    change_entry(tt, file_id, working_tree, target_tree, 
                                 trans_id_file_id, backup_this, trans_id,
                                 by_parent)
        finally:
            child_pb.finished()
        pp.next_phase()
        wt_interesting = [i for i in working_tree.inventory if interesting(i)]
        child_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            for id_num, file_id in enumerate(wt_interesting):
                child_pb.update("New file check", id_num+1, 
                                len(sorted_interesting))
                if file_id not in target_tree:
                    trans_id = tt.trans_id_tree_file_id(file_id)
                    tt.unversion_file(trans_id)
                    if file_id in merge_modified:
                        tt.delete_contents(trans_id)
                        del merge_modified[file_id]
        finally:
            child_pb.finished()
        pp.next_phase()
        child_pb = bzrlib.ui.ui_factory.nested_progress_bar()
        try:
            raw_conflicts = resolve_conflicts(tt, child_pb)
        finally:
            child_pb.finished()
        conflicts = cook_conflicts(raw_conflicts, tt)
        for conflict in conflicts:
            warning(conflict)
        pp.next_phase()
        tt.apply()
        working_tree.set_merge_modified({})
    finally:
        tt.finalize()
        pb.clear()
    return conflicts


def resolve_conflicts(tt, pb=DummyProgress()):
    """Make many conflict-resolution attempts, but die if they fail"""
    new_conflicts = set()
    try:
        for n in range(10):
            pb.update('Resolution pass', n+1, 10)
            conflicts = tt.find_conflicts()
            if len(conflicts) == 0:
                return new_conflicts
            new_conflicts.update(conflict_pass(tt, conflicts))
        raise MalformedTransform(conflicts=conflicts)
    finally:
        pb.clear()


def conflict_pass(tt, conflicts):
    """Resolve some classes of conflicts."""
    new_conflicts = set()
    for c_type, conflict in ((c[0], c) for c in conflicts):
        if c_type == 'duplicate id':
            tt.unversion_file(conflict[1])
            new_conflicts.add((c_type, 'Unversioned existing file',
                               conflict[1], conflict[2], ))
        elif c_type == 'duplicate':
            # files that were renamed take precedence
            new_name = tt.final_name(conflict[1])+'.moved'
            final_parent = tt.final_parent(conflict[1])
            if tt.path_changed(conflict[1]):
                tt.adjust_path(new_name, final_parent, conflict[2])
                new_conflicts.add((c_type, 'Moved existing file to', 
                                   conflict[2], conflict[1]))
            else:
                tt.adjust_path(new_name, final_parent, conflict[1])
                new_conflicts.add((c_type, 'Moved existing file to', 
                                  conflict[1], conflict[2]))
        elif c_type == 'parent loop':
            # break the loop by undoing one of the ops that caused the loop
            cur = conflict[1]
            while not tt.path_changed(cur):
                cur = tt.final_parent(cur)
            new_conflicts.add((c_type, 'Cancelled move', cur,
                               tt.final_parent(cur),))
            tt.adjust_path(tt.final_name(cur), tt.get_tree_parent(cur), cur)
            
        elif c_type == 'missing parent':
            trans_id = conflict[1]
            try:
                tt.cancel_deletion(trans_id)
                new_conflicts.add((c_type, 'Not deleting', trans_id))
            except KeyError:
                tt.create_directory(trans_id)
                new_conflicts.add((c_type, 'Created directory.', trans_id))
        elif c_type == 'unversioned parent':
            tt.version_file(tt.inactive_file_id(conflict[1]), conflict[1])
            new_conflicts.add((c_type, 'Versioned directory', conflict[1]))
    return new_conflicts


def cook_conflicts(raw_conflicts, tt):
    """Generate a list of cooked conflicts, sorted by file path"""
    from bzrlib.conflicts import Conflict
    conflict_iter = iter_cook_conflicts(raw_conflicts, tt)
    return sorted(conflict_iter, key=Conflict.sort_key)


def iter_cook_conflicts(raw_conflicts, tt):
    from bzrlib.conflicts import Conflict
    fp = FinalPaths(tt)
    for conflict in raw_conflicts:
        c_type = conflict[0]
        action = conflict[1]
        modified_path = fp.get_path(conflict[2])
        modified_id = tt.final_file_id(conflict[2])
        if len(conflict) == 3:
            yield Conflict.factory(c_type, action=action, path=modified_path,
                                     file_id=modified_id)
             
        else:
            conflicting_path = fp.get_path(conflict[3])
            conflicting_id = tt.final_file_id(conflict[3])
            yield Conflict.factory(c_type, action=action, path=modified_path,
                                   file_id=modified_id, 
                                   conflict_path=conflicting_path,
                                   conflict_file_id=conflicting_id)
