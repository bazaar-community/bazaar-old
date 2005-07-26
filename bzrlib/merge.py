from merge_core import merge_flex
from changeset import generate_changeset, ExceptionConflictHandler
from changeset import Inventory, Diff3Merge
from bzrlib import find_branch
import bzrlib.osutils
from bzrlib.errors import BzrCommandError
from bzrlib.diff import compare_trees
from trace import mutter, warning
import os.path
import tempfile
import shutil
import errno

class UnrelatedBranches(BzrCommandError):
    def __init__(self):
        msg = "Branches have no common ancestor, and no base revision"\
            " specified."
        BzrCommandError.__init__(self, msg)


class MergeConflictHandler(ExceptionConflictHandler):
    """Handle conflicts encountered while merging"""
    def __init__(self, dir, ignore_zero=False):
        ExceptionConflictHandler.__init__(self, dir)
        self.conflicts = 0
        self.ignore_zero = ignore_zero

    def copy(self, source, dest):
        """Copy the text and mode of a file
        :param source: The path of the file to copy
        :param dest: The distination file to create
        """
        s_file = file(source, "rb")
        d_file = file(dest, "wb")
        for line in s_file:
            d_file.write(line)
        os.chmod(dest, 0777 & os.stat(source).st_mode)

    def add_suffix(self, name, suffix, last_new_name=None):
        """Rename a file to append a suffix.  If the new name exists, the
        suffix is added repeatedly until a non-existant name is found

        :param name: The path of the file
        :param suffix: The suffix to append
        :param last_new_name: (used for recursive calls) the last name tried
        """
        if last_new_name is None:
            last_new_name = name
        new_name = last_new_name+suffix
        try:
            os.rename(name, new_name)
            return new_name
        except OSError, e:
            if e.errno != errno.EEXIST and e.errno != errno.ENOTEMPTY:
                raise
            return self.add_suffix(name, suffix, last_new_name=new_name)

    def conflict(self, text):
        warning(text)
        self.conflicts += 1
        

    def merge_conflict(self, new_file, this_path, base_path, other_path):
        """
        Handle diff3 conflicts by producing a .THIS, .BASE and .OTHER.  The
        main file will be a version with diff3 conflicts.
        :param new_file: Path to the output file with diff3 markers
        :param this_path: Path to the file text for the THIS tree
        :param base_path: Path to the file text for the BASE tree
        :param other_path: Path to the file text for the OTHER tree
        """
        self.add_suffix(this_path, ".THIS")
        self.copy(base_path, this_path+".BASE")
        self.copy(other_path, this_path+".OTHER")
        os.rename(new_file, this_path)
        self.conflict("Diff3 conflict encountered in %s" % this_path)

    def target_exists(self, entry, target, old_path):
        """Handle the case when the target file or dir exists"""
        moved_path = self.add_suffix(target, ".moved")
        self.conflict("Moved existing %s to %s" % (target, moved_path))

    def rmdir_non_empty(self, filename):
        """Handle the case where the dir to be removed still has contents"""
        self.conflict("Directory %s not removed because it is not empty"\
            % filename)
        return "skip"

    def finalize(self):
        if not self.ignore_zero:
            print "%d conflicts encountered.\n" % self.conflicts
            
class SourceFile(object):
    def __init__(self, path, id, present=None, isdir=None):
        self.path = path
        self.id = id
        self.present = present
        self.isdir = isdir
        self.interesting = True

    def __repr__(self):
        return "SourceFile(%s, %s)" % (self.path, self.id)

def get_tree(treespec, temp_root, label):
    location, revno = treespec
    branch = find_branch(location)
    if revno is None:
        base_tree = branch.working_tree()
    elif revno == -1:
        base_tree = branch.basis_tree()
    else:
        base_tree = branch.revision_tree(branch.lookup_revision(revno))
    temp_path = os.path.join(temp_root, label)
    os.mkdir(temp_path)
    return branch, MergeTree(base_tree, temp_path)


def abspath(tree, file_id):
    path = tree.inventory.id2path(file_id)
    if path == "":
        return "./."
    return "./" + path

def file_exists(tree, file_id):
    return tree.has_filename(tree.id2path(file_id))
    
def inventory_map(tree):
    inventory = {}
    for file_id in tree.inventory:
        path = abspath(tree, file_id)
        inventory[path] = SourceFile(path, file_id)
    return inventory


class MergeTree(object):
    def __init__(self, tree, tempdir):
        object.__init__(self)
        if hasattr(tree, "basedir"):
            self.root = tree.basedir
        else:
            self.root = None
        self.inventory = inventory_map(tree)
        self.tree = tree
        self.tempdir = tempdir
        os.mkdir(os.path.join(self.tempdir, "texts"))
        self.cached = {}

    def readonly_path(self, id):
        if id not in self.tree:
            return None
        if self.root is not None:
            return self.tree.abspath(self.tree.id2path(id))
        else:
            if self.tree.inventory[id].kind in ("directory", "root_directory"):
                return self.tempdir
            if not self.cached.has_key(id):
                path = os.path.join(self.tempdir, "texts", id)
                outfile = file(path, "wb")
                outfile.write(self.tree.get_file(id).read())
                assert(os.path.exists(path))
                self.cached[id] = path
            return self.cached[id]



def merge(other_revision, base_revision,
          check_clean=True, ignore_zero=False,
          this_dir=None):
    """Merge changes into a tree.

    base_revision
        Base for three-way merge.
    other_revision
        Other revision for three-way merge.
    this_dir
        Directory to merge changes into; '.' by default.
    check_clean
        If true, this_dir must have no uncommitted changes before the
        merge begins.
    """
    tempdir = tempfile.mkdtemp(prefix="bzr-")
    try:
        if this_dir is None:
            this_dir = '.'
        this_branch = find_branch(this_dir)
        if check_clean:
            changes = compare_trees(this_branch.working_tree(), 
                                    this_branch.basis_tree(), False)
            if changes.has_changed():
                raise BzrCommandError("Working tree has uncommitted changes.")
        other_branch, other_tree = get_tree(other_revision, tempdir, "other")
        if base_revision == [None, None]:
            if other_revision[1] == -1:
                o_revno = None
            else:
                o_revno = other_revision[1]
            base_revno = this_branch.common_ancestor(other_branch, 
                                                     other_revno=o_revno)[0]
            if base_revno is None:
                raise UnrelatedBranches()
            base_revision = ['.', base_revno]
        base_branch, base_tree = get_tree(base_revision, tempdir, "base")
        merge_inner(this_branch, other_tree, base_tree, tempdir, 
                    ignore_zero=ignore_zero)
    finally:
        shutil.rmtree(tempdir)


def generate_cset_optimized(tree_a, tree_b, inventory_a, inventory_b):
    """Generate a changeset, using the text_id to mark really-changed files.
    This permits blazing comparisons when text_ids are present.  It also
    disables metadata comparison for files with identical texts.
    """ 
    for file_id in tree_a.tree.inventory:
        if file_id not in tree_b.tree.inventory:
            continue
        entry_a = tree_a.tree.inventory[file_id]
        entry_b = tree_b.tree.inventory[file_id]
        if (entry_a.kind, entry_b.kind) != ("file", "file"):
            continue
        if None in (entry_a.text_id, entry_b.text_id):
            continue
        if entry_a.text_id != entry_b.text_id:
            continue
        inventory_a[abspath(tree_a.tree, file_id)].interesting = False
        inventory_b[abspath(tree_b.tree, file_id)].interesting = False
    cset =  generate_changeset(tree_a, tree_b, inventory_a, inventory_b)
    for entry in cset.entries.itervalues():
        entry.metadata_change = None
    return cset


def merge_inner(this_branch, other_tree, base_tree, tempdir, 
                ignore_zero=False):
    this_tree = get_tree((this_branch.base, None), tempdir, "this")[1]

    def get_inventory(tree):
        return tree.inventory

    inv_changes = merge_flex(this_tree, base_tree, other_tree,
                             generate_cset_optimized, get_inventory,
                             MergeConflictHandler(base_tree.root,
                                                  ignore_zero=ignore_zero),
                             merge_factory=Diff3Merge)

    adjust_ids = []
    for id, path in inv_changes.iteritems():
        if path is not None:
            if path == '.':
                path = ''
            else:
                assert path.startswith('./')
            path = path[2:]
        adjust_ids.append((path, id))
    this_branch.set_inventory(regen_inventory(this_branch, this_tree.root, adjust_ids))


def regen_inventory(this_branch, root, new_entries):
    old_entries = this_branch.read_working_inventory()
    new_inventory = {}
    by_path = {}
    for file_id in old_entries:
        entry = old_entries[file_id]
        path = old_entries.id2path(file_id)
        new_inventory[file_id] = (path, file_id, entry.parent_id, entry.kind)
        by_path[path] = file_id
    
    deletions = 0
    insertions = 0
    new_path_list = []
    for path, file_id in new_entries:
        if path is None:
            del new_inventory[file_id]
            deletions += 1
        else:
            new_path_list.append((path, file_id))
            if file_id not in old_entries:
                insertions += 1
    # Ensure no file is added before its parent
    new_path_list.sort()
    for path, file_id in new_path_list:
        if path == '':
            parent = None
        else:
            parent = by_path[os.path.dirname(path)]
        kind = bzrlib.osutils.file_kind(os.path.join(root, path))
        new_inventory[file_id] = (path, file_id, parent, kind)
        by_path[path] = file_id 

    # Get a list in insertion order
    new_inventory_list = new_inventory.values()
    mutter ("""Inventory regeneration:
old length: %i insertions: %i deletions: %i new_length: %i"""\
        % (len(old_entries), insertions, deletions, len(new_inventory_list)))
    assert len(new_inventory_list) == len(old_entries) + insertions - deletions
    new_inventory_list.sort()
    return new_inventory_list
