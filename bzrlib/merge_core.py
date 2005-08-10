import changeset
from changeset import Inventory, apply_changeset, invert_dict
import os.path
from osutils import backup_file
from merge3 import Merge3

class ApplyMerge3:
    """Contents-change wrapper around merge3.Merge3"""
    def __init__(self, base_file, other_file):
        self.base_file = base_file
        self.other_file = other_file
 
    def __eq__(self, other):
        if not isinstance(other, ApplyMerge3):
            return False
        return (self.base_file == other.base_file and 
                self.other_file == other.other_file)

    def __ne__(self, other):
        return not (self == other)


    def apply(self, filename, conflict_handler, reverse=False):
        new_file = filename+".new" 
        if not reverse:
            base = self.base_file
            other = self.other_file
        else:
            base = self.other_file
            other = self.base_file
        m3 = Merge3(file(base, "rb").readlines(), 
                    file(filename, "rb").readlines(), 
                    file(other, "rb").readlines())

        new_conflicts = False
        output_file = file(new_file, "wb")
        start_marker = "!START OF MERGE CONFLICT!" + "I HOPE THIS IS UNIQUE"
        for line in m3.merge_lines(name_a = "TREE", name_b = "MERGE-SOURCE", 
                       start_marker=start_marker):
            if line.startswith(start_marker):
                new_conflicts = True
                output_file.write(line.replace(start_marker, '<<<<<<<<'))
            else:
                output_file.write(line)
        output_file.close()
        if not new_conflicts:
            os.chmod(new_file, os.stat(filename).st_mode)
            os.rename(new_file, filename)
            return
        else:
            conflict_handler.merge_conflict(new_file, filename, base, other)


class BackupBeforeChange:
    """Contents-change wrapper to back up file first"""
    def __init__(self, contents_change):
        self.contents_change = contents_change
 
    def __eq__(self, other):
        if not isinstance(other, BackupBeforeChange):
            return False
        return (self.contents_change == other.contents_change)

    def __ne__(self, other):
        return not (self == other)

    def apply(self, filename, conflict_handler, reverse=False):
        backup_file(filename)
        self.contents_change.apply(filename, conflict_handler, reverse)


class ThreewayInventory(object):
    def __init__(self, this_inventory, base_inventory, other_inventory):
        self.this = this_inventory
        self.base = base_inventory
        self.other = other_inventory
def invert_invent(inventory):
    invert_invent = {}
    for key, value in inventory.iteritems():
        invert_invent[value.id] = key
    return invert_invent

def make_inv(inventory):
    return Inventory(invert_invent(inventory))
        

def merge_flex(this, base, other, changeset_function, inventory_function,
               conflict_handler, merge_factory, interesting_ids):
    this_inventory = inventory_function(this)
    base_inventory = inventory_function(base)
    other_inventory = inventory_function(other)
    inventory = ThreewayInventory(make_inv(this_inventory),
                                  make_inv(base_inventory), 
                                  make_inv(other_inventory))
    cset = changeset_function(base, other, base_inventory, other_inventory, 
                              interesting_ids)
    new_cset = make_merge_changeset(cset, inventory, this, base, other, 
                                    conflict_handler, merge_factory)
    result = apply_changeset(new_cset, invert_invent(this_inventory),
                             this.root, conflict_handler, False)
    conflict_handler.finalize()
    return result

    

def make_merge_changeset(cset, inventory, this, base, other, 
                         conflict_handler, merge_factory):
    new_cset = changeset.Changeset()
    def get_this_contents(id):
        path = os.path.join(this.root, inventory.this.get_path(id))
        if os.path.isdir(path):
            return changeset.dir_create
        else:
            return changeset.FileCreate(file(path, "rb").read())

    for entry in cset.entries.itervalues():
        if entry.is_boring():
            new_cset.add_entry(entry)
        else:
            new_entry = make_merged_entry(entry, inventory, conflict_handler)
            new_contents = make_merged_contents(entry, this, base, other, 
                                                inventory, conflict_handler, 
                                                merge_factory)
            new_entry.contents_change = new_contents
            new_entry.metadata_change = make_merged_metadata(entry, base, other)
            new_cset.add_entry(new_entry)

    return new_cset

def make_merged_entry(entry, inventory, conflict_handler):
    from bzrlib.trace import mutter
    this_name = inventory.this.get_name(entry.id)
    this_parent = inventory.this.get_parent(entry.id)
    this_dir = inventory.this.get_dir(entry.id)
    if this_dir is None:
        this_dir = ""

    base_name = inventory.base.get_name(entry.id)
    base_parent = inventory.base.get_parent(entry.id)
    base_dir = inventory.base.get_dir(entry.id)
    if base_dir is None:
        base_dir = ""
    other_name = inventory.other.get_name(entry.id)
    other_parent = inventory.other.get_parent(entry.id)
    other_dir = inventory.base.get_dir(entry.id)
    if other_dir is None:
        other_dir = ""
    mutter("Dirs: this, base, other %r %r %r" % (this_dir, base_dir, other_dir))
    mutter("Names: this, base, other %r %r %r" % (this_name, base_name, other_name))
    if base_name == other_name:
        old_name = this_name
        new_name = this_name
    else:
        if this_name != base_name and this_name != other_name:
            conflict_handler.rename_conflict(entry.id, this_name, base_name,
                                             other_name)
        else:
            old_name = this_name
            new_name = other_name

    if base_parent == other_parent:
        old_parent = this_parent
        new_parent = this_parent
        old_dir = this_dir
        new_dir = this_dir
    else:
        if this_parent != base_parent and this_parent != other_parent:
            conflict_handler.move_conflict(entry.id, inventory)
        else:
            old_parent = this_parent
            old_dir = this_dir
            new_parent = other_parent
            new_dir = other_dir
    if old_name is not None and old_parent is not None:
        old_path = os.path.join(old_dir, old_name)
    else:
        old_path = None
    new_entry = changeset.ChangesetEntry(entry.id, old_parent, old_path)
    if new_name is not None and new_parent is not None:
        new_entry.new_path = os.path.join(new_dir, new_name)
    else:
        new_entry.new_path = None
    new_entry.new_parent = new_parent
    mutter(repr(new_entry))
    return new_entry


def make_merged_contents(entry, this, base, other, inventory, conflict_handler,
                         merge_factory):
    contents = entry.contents_change
    if contents is None:
        return None
    this_path = this.readonly_path(entry.id)
    def make_merge():
        if this_path is None:
            return conflict_handler.missing_for_merge(entry.id, inventory)
        base_path = base.readonly_path(entry.id)
        other_path = other.readonly_path(entry.id)    
        return merge_factory(base_path, other_path)

    if isinstance(contents, changeset.ReplaceContents):
        if contents.old_contents is None and contents.new_contents is None:
            return None
        if contents.new_contents is None:
            if this_path is not None and os.path.exists(this_path):
                return contents
            else:
                return None
        elif contents.old_contents is None:
            if this_path is None or not os.path.exists(this_path):
                return contents
            else:
                this_contents = file(this_path, "rb").read()
                if this_contents == contents.new_contents:
                    return None
                else:
                    other_path = other.readonly_path(entry.id)    
                    conflict_handler.new_contents_conflict(this_path, 
                                                           other_path)
        elif isinstance(contents.old_contents, changeset.FileCreate) and \
            isinstance(contents.new_contents, changeset.FileCreate):
            return make_merge()
        else:
            raise Exception("Unhandled merge scenario")

def make_merged_metadata(entry, base, other):
    if entry.metadata_change is not None:
        base_path = base.readonly_path(entry.id)
        other_path = other.readonly_path(entry.id)    
        return PermissionsMerge(base_path, other_path)
    

class PermissionsMerge(object):
    def __init__(self, base_path, other_path):
        self.base_path = base_path
        self.other_path = other_path

    def apply(self, filename, conflict_handler, reverse=False):
        if not reverse:
            base = self.base_path
            other = self.other_path
        else:
            base = self.other_path
            other = self.base_path
        base_stat = os.stat(base).st_mode
        other_stat = os.stat(other).st_mode
        this_stat = os.stat(filename).st_mode
        if base_stat &0777 == other_stat &0777:
            return
        elif this_stat &0777 == other_stat &0777:
            return
        elif this_stat &0777 == base_stat &0777:
            os.chmod(filename, other_stat)
        else:
            conflict_handler.permission_conflict(filename, base, other)


import unittest
import tempfile
import shutil
class MergeTree(object):
    def __init__(self, dir):
        self.dir = dir;
        os.mkdir(dir)
        self.inventory = {'0': ""}
    
    def child_path(self, parent, name):
        return os.path.join(self.inventory[parent], name)

    def add_file(self, id, parent, name, contents, mode):
        path = self.child_path(parent, name)
        full_path = self.abs_path(path)
        assert not os.path.exists(full_path)
        file(full_path, "wb").write(contents)
        os.chmod(self.abs_path(path), mode)
        self.inventory[id] = path

    def remove_file(self, id):
        os.unlink(self.full_path(id))
        del self.inventory[id]

    def add_dir(self, id, parent, name, mode):
        path = self.child_path(parent, name)
        full_path = self.abs_path(path)
        assert not os.path.exists(full_path)
        os.mkdir(self.abs_path(path))
        os.chmod(self.abs_path(path), mode)
        self.inventory[id] = path

    def abs_path(self, path):
        return os.path.join(self.dir, path)

    def full_path(self, id):
        try:
            tree_path = self.inventory[id]
        except KeyError:
            return None
        return self.abs_path(tree_path)

    def readonly_path(self, id):
        return self.full_path(id)

    def change_path(self, id, path):
        new = os.path.join(self.dir, self.inventory[id])
        os.rename(self.abs_path(self.inventory[id]), self.abs_path(path))
        self.inventory[id] = path

class MergeBuilder(object):
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="BaZing")
        self.base = MergeTree(os.path.join(self.dir, "base"))
        self.this = MergeTree(os.path.join(self.dir, "this"))
        self.other = MergeTree(os.path.join(self.dir, "other"))
        
        self.cset = changeset.Changeset()
        self.cset.add_entry(changeset.ChangesetEntry("0", 
                                                     changeset.NULL_ID, "./."))
    def get_cset_path(self, parent, name):
        if name is None:
            assert (parent is None)
            return None
        return os.path.join(self.cset.entries[parent].path, name)

    def add_file(self, id, parent, name, contents, mode):
        self.base.add_file(id, parent, name, contents, mode)
        self.this.add_file(id, parent, name, contents, mode)
        self.other.add_file(id, parent, name, contents, mode)
        path = self.get_cset_path(parent, name)
        self.cset.add_entry(changeset.ChangesetEntry(id, parent, path))

    def remove_file(self, id, base=False, this=False, other=False):
        for option, tree in ((base, self.base), (this, self.this), 
                             (other, self.other)):
            if option:
                tree.remove_file(id)
            if other or base:
                change = self.cset.entries[id].contents_change
                assert isinstance(change, changeset.ReplaceContents)
                if other:
                    change.new_contents=None
                if base:
                    change.old_contents=None
                if change.old_contents is None and change.new_contents is None:
                    change = None


    def add_dir(self, id, parent, name, mode):
        path = self.get_cset_path(parent, name)
        self.base.add_dir(id, parent, name, mode)
        self.cset.add_entry(changeset.ChangesetEntry(id, parent, path))
        self.this.add_dir(id, parent, name, mode)
        self.other.add_dir(id, parent, name, mode)


    def change_name(self, id, base=None, this=None, other=None):
        if base is not None:
            self.change_name_tree(id, self.base, base)
            self.cset.entries[id].name = base

        if this is not None:
            self.change_name_tree(id, self.this, this)

        if other is not None:
            self.change_name_tree(id, self.other, other)
            self.cset.entries[id].new_name = other

    def change_parent(self, id, base=None, this=None, other=None):
        if base is not None:
            self.change_parent_tree(id, self.base, base)
            self.cset.entries[id].parent = base
            self.cset.entries[id].dir = self.cset.entries[base].path

        if this is not None:
            self.change_parent_tree(id, self.this, this)

        if other is not None:
            self.change_parent_tree(id, self.other, other)
            self.cset.entries[id].new_parent = other
            self.cset.entries[id].new_dir = \
                self.cset.entries[other].new_path

    def change_contents(self, id, base=None, this=None, other=None):
        if base is not None:
            self.change_contents_tree(id, self.base, base)

        if this is not None:
            self.change_contents_tree(id, self.this, this)

        if other is not None:
            self.change_contents_tree(id, self.other, other)

        if base is not None or other is not None:
            old_contents = file(self.base.full_path(id)).read()
            new_contents = file(self.other.full_path(id)).read()
            contents = changeset.ReplaceFileContents(old_contents, 
                                                     new_contents)
            self.cset.entries[id].contents_change = contents

    def change_perms(self, id, base=None, this=None, other=None):
        if base is not None:
            self.change_perms_tree(id, self.base, base)

        if this is not None:
            self.change_perms_tree(id, self.this, this)

        if other is not None:
            self.change_perms_tree(id, self.other, other)

        if base is not None or other is not None:
            old_perms = os.stat(self.base.full_path(id)).st_mode &077
            new_perms = os.stat(self.other.full_path(id)).st_mode &077
            contents = changeset.ChangeUnixPermissions(old_perms, 
                                                       new_perms)
            self.cset.entries[id].metadata_change = contents

    def change_name_tree(self, id, tree, name):
        new_path = tree.child_path(self.cset.entries[id].parent, name)
        tree.change_path(id, new_path)

    def change_parent_tree(self, id, tree, parent):
        new_path = tree.child_path(parent, self.cset.entries[id].name)
        tree.change_path(id, new_path)

    def change_contents_tree(self, id, tree, contents):
        path = tree.full_path(id)
        mode = os.stat(path).st_mode
        file(path, "w").write(contents)
        os.chmod(path, mode)

    def change_perms_tree(self, id, tree, mode):
        os.chmod(tree.full_path(id), mode)

    def merge_changeset(self, merge_factory):
        all_inventory = ThreewayInventory(Inventory(self.this.inventory),
                                          Inventory(self.base.inventory), 
                                          Inventory(self.other.inventory))
        conflict_handler = changeset.ExceptionConflictHandler(self.this.dir)
        return make_merge_changeset(self.cset, all_inventory, self.this,
                                    self.base, self.other, conflict_handler,
                                    merge_factory)

    def apply_inv_change(self, inventory_change, orig_inventory):
        orig_inventory_by_path = {}
        for file_id, path in orig_inventory.iteritems():
            orig_inventory_by_path[path] = file_id

        def parent_id(file_id):
            try:
                parent_dir = os.path.dirname(orig_inventory[file_id])
            except:
                print file_id
                raise
            if parent_dir == "":
                return None
            return orig_inventory_by_path[parent_dir]
        
        def new_path(file_id):
            if inventory_change.has_key(file_id):
                return inventory_change[file_id]
            else:
                parent = parent_id(file_id)
                if parent is None:
                    return orig_inventory[file_id]
                dirname = new_path(parent)
                return os.path.join(dirname, orig_inventory[file_id])

        new_inventory = {}
        for file_id in orig_inventory.iterkeys():
            path = new_path(file_id)
            if path is None:
                continue
            new_inventory[file_id] = path

        for file_id, path in inventory_change.iteritems():
            if orig_inventory.has_key(file_id):
                continue
            new_inventory[file_id] = path
        return new_inventory

        

    def apply_changeset(self, cset, conflict_handler=None, reverse=False):
        inventory_change = changeset.apply_changeset(cset,
                                                     self.this.inventory,
                                                     self.this.dir,
                                                     conflict_handler, reverse)
        self.this.inventory =  self.apply_inv_change(inventory_change, 
                                                     self.this.inventory)

                    
        

        
    def cleanup(self):
        shutil.rmtree(self.dir)


class MergeTest(unittest.TestCase):
    def test_change_name(self):
        """Test renames"""
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "hello1", 0755)
        builder.change_name("1", other="name2")
        builder.add_file("2", "0", "name3", "hello2", 0755)
        builder.change_name("2", base="name4")
        builder.add_file("3", "0", "name5", "hello3", 0755)
        builder.change_name("3", this="name6")
        cset = builder.merge_changeset(ApplyMerge3)
        assert(cset.entries["2"].is_boring())
        assert(cset.entries["1"].name == "name1")
        assert(cset.entries["1"].new_name == "name2")
        assert(cset.entries["3"].is_boring())
        for tree in (builder.this, builder.other, builder.base):
            assert(tree.dir != builder.dir and 
                   tree.dir.startswith(builder.dir))
            for path in tree.inventory.itervalues():
                fullpath = tree.abs_path(path)
                assert(fullpath.startswith(tree.dir))
                assert(not path.startswith(tree.dir))
                assert os.path.exists(fullpath)
        builder.apply_changeset(cset)
        builder.cleanup()
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "hello1", 0644)
        builder.change_name("1", other="name2", this="name3")
        self.assertRaises(changeset.RenameConflict, 
                          builder.merge_changeset, ApplyMerge3)
        builder.cleanup()
        
    def test_file_moves(self):
        """Test moves"""
        builder = MergeBuilder()
        builder.add_dir("1", "0", "dir1", 0755)
        builder.add_dir("2", "0", "dir2", 0755)
        builder.add_file("3", "1", "file1", "hello1", 0644)
        builder.add_file("4", "1", "file2", "hello2", 0644)
        builder.add_file("5", "1", "file3", "hello3", 0644)
        builder.change_parent("3", other="2")
        assert(Inventory(builder.other.inventory).get_parent("3") == "2")
        builder.change_parent("4", this="2")
        assert(Inventory(builder.this.inventory).get_parent("4") == "2")
        builder.change_parent("5", base="2")
        assert(Inventory(builder.base.inventory).get_parent("5") == "2")
        cset = builder.merge_changeset(ApplyMerge3)
        for id in ("1", "2", "4", "5"):
            assert(cset.entries[id].is_boring())
        assert(cset.entries["3"].parent == "1")
        assert(cset.entries["3"].new_parent == "2")
        builder.apply_changeset(cset)
        builder.cleanup()

        builder = MergeBuilder()
        builder.add_dir("1", "0", "dir1", 0755)
        builder.add_dir("2", "0", "dir2", 0755)
        builder.add_dir("3", "0", "dir3", 0755)
        builder.add_file("4", "1", "file1", "hello1", 0644)
        builder.change_parent("4", other="2", this="3")
        self.assertRaises(changeset.MoveConflict, 
                          builder.merge_changeset, ApplyMerge3)
        builder.cleanup()

    def test_contents_merge(self):
        """Test merge3 merging"""
        self.do_contents_test(ApplyMerge3)

    def test_contents_merge2(self):
        """Test diff3 merging"""
        self.do_contents_test(changeset.Diff3Merge)

    def test_contents_merge3(self):
        """Test diff3 merging"""
        def backup_merge(base_file, other_file):
            return BackupBeforeChange(ApplyMerge3(base_file, other_file))
        builder = self.contents_test_success(backup_merge)
        def backup_exists(file_id):
            return os.path.exists(builder.this.full_path(file_id)+"~")
        assert backup_exists("1")
        assert backup_exists("2")
        assert not backup_exists("3")
        builder.cleanup()

    def do_contents_test(self, merge_factory):
        """Test merging with specified ContentsChange factory"""
        builder = self.contents_test_success(merge_factory)
        builder.cleanup()
        self.contents_test_conflicts(merge_factory)

    def contents_test_success(self, merge_factory):
        from inspect import isclass
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_contents("1", other="text4")
        builder.add_file("2", "0", "name3", "text2", 0655)
        builder.change_contents("2", base="text5")
        builder.add_file("3", "0", "name5", "text3", 0744)
        builder.change_contents("3", this="text6")
        cset = builder.merge_changeset(merge_factory)
        assert(cset.entries["1"].contents_change is not None)
        if isclass(merge_factory):
            assert(isinstance(cset.entries["1"].contents_change,
                          merge_factory))
            assert(isinstance(cset.entries["2"].contents_change,
                          merge_factory))
        assert(cset.entries["3"].is_boring())
        builder.apply_changeset(cset)
        assert(file(builder.this.full_path("1"), "rb").read() == "text4" )
        assert(file(builder.this.full_path("2"), "rb").read() == "text2" )
        assert(os.stat(builder.this.full_path("1")).st_mode &0777 == 0755)
        assert(os.stat(builder.this.full_path("2")).st_mode &0777 == 0655)
        assert(os.stat(builder.this.full_path("3")).st_mode &0777 == 0744)
        return builder

    def contents_test_conflicts(self, merge_factory):
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_contents("1", other="text4", this="text3")
        cset = builder.merge_changeset(merge_factory)
        self.assertRaises(changeset.MergeConflict, builder.apply_changeset,
                          cset)
        builder.cleanup()

        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_contents("1", other="text4", base="text3")
        builder.remove_file("1", base=True)
        self.assertRaises(changeset.NewContentsConflict,
                          builder.merge_changeset, merge_factory)
        builder.cleanup()

        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_contents("1", other="text4", base="text3")
        builder.remove_file("1", this=True)
        self.assertRaises(changeset.MissingForMerge, builder.merge_changeset, 
                          merge_factory)
        builder.cleanup()

    def test_perms_merge(self):
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_perms("1", other=0655)
        builder.add_file("2", "0", "name2", "text2", 0755)
        builder.change_perms("2", base=0655)
        builder.add_file("3", "0", "name3", "text3", 0755)
        builder.change_perms("3", this=0655)
        cset = builder.merge_changeset(ApplyMerge3)
        assert(cset.entries["1"].metadata_change is not None)
        assert(isinstance(cset.entries["1"].metadata_change,
                          PermissionsMerge))
        assert(isinstance(cset.entries["2"].metadata_change,
                          PermissionsMerge))
        assert(cset.entries["3"].is_boring())
        builder.apply_changeset(cset)
        assert(os.stat(builder.this.full_path("1")).st_mode &0777 == 0655)
        assert(os.stat(builder.this.full_path("2")).st_mode &0777 == 0755)
        assert(os.stat(builder.this.full_path("3")).st_mode &0777 == 0655)
        builder.cleanup();
        builder = MergeBuilder()
        builder.add_file("1", "0", "name1", "text1", 0755)
        builder.change_perms("1", other=0655, base=0555)
        cset = builder.merge_changeset(ApplyMerge3)
        self.assertRaises(changeset.MergePermissionConflict, 
                     builder.apply_changeset, cset)
        builder.cleanup()

def test():        
    changeset_suite = unittest.makeSuite(MergeTest, 'test_')
    runner = unittest.TextTestRunner()
    runner.run(changeset_suite)
        
if __name__ == "__main__":
    test()
