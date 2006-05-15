# Copyright (C) 2004-2006 by Canonical Ltd

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

from StringIO import StringIO

from bzrlib.builtins import merge_changeset
from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.bzrdir import BzrDir
from bzrlib.errors import BzrError

from bzrlib.diff import internal_diff
from bzrlib.changeset.apply_changeset import install_changeset
from bzrlib.changeset.read_changeset import ChangesetTree, ChangesetReader
from bzrlib.changeset import serializer 
from bzrlib.merge import Merge3Merger
from bzrlib.workingtree import WorkingTree

class MockTree(object):
    def __init__(self):
        from bzrlib.inventory import RootEntry, ROOT_ID
        object.__init__(self)
        self.paths = {ROOT_ID: ""}
        self.ids = {"": ROOT_ID}
        self.contents = {}
        self.root = RootEntry(ROOT_ID)

    inventory = property(lambda x:x)

    def __iter__(self):
        return self.paths.iterkeys()

    def __getitem__(self, file_id):
        if file_id == self.root.file_id:
            return self.root
        else:
            return self.make_entry(file_id, self.paths[file_id])

    def parent_id(self, file_id):
        from os.path import dirname
        parent_dir = dirname(self.paths[file_id])
        if parent_dir == "":
            return None
        return self.ids[parent_dir]

    def iter_entries(self):
        for path, file_id in self.ids.iteritems():
            yield path, self[file_id]

    def get_file_kind(self, file_id):
        if file_id in self.contents:
            kind = 'file'
        else:
            kind = 'directory'
        return kind

    def make_entry(self, file_id, path):
        from os.path import basename
        from bzrlib.inventory import (InventoryEntry, InventoryFile
                                    , InventoryDirectory, InventoryLink)
        name = basename(path)
        kind = self.get_file_kind(file_id)
        parent_id = self.parent_id(file_id)
        text_sha_1, text_size = self.contents_stats(file_id)
        if kind == 'directory':
            ie = InventoryDirectory(file_id, name, parent_id)
        elif kind == 'file':
            ie = InventoryFile(file_id, name, parent_id)
        elif kind == 'symlink':
            ie = InventoryLink(file_id, name, parent_id)
        else:
            raise BzrError('unknown kind %r' % kind)
        ie.text_sha1 = text_sha_1
        ie.text_size = text_size
        return ie

    def add_dir(self, file_id, path):
        self.paths[file_id] = path
        self.ids[path] = file_id
    
    def add_file(self, file_id, path, contents):
        self.add_dir(file_id, path)
        self.contents[file_id] = contents

    def path2id(self, path):
        return self.ids.get(path)

    def id2path(self, file_id):
        return self.paths.get(file_id)

    def has_id(self, file_id):
        return self.id2path(file_id) is not None

    def get_file(self, file_id):
        result = StringIO()
        result.write(self.contents[file_id])
        result.seek(0,0)
        return result

    def contents_stats(self, file_id):
        from bzrlib.osutils import sha_file
        if file_id not in self.contents:
            return None, None
        text_sha1 = sha_file(self.get_file(file_id))
        return text_sha1, len(self.contents[file_id])


class CTreeTester(TestCase):
    """A simple unittest tester for the ChangesetTree class."""

    def make_tree_1(self):
        mtree = MockTree()
        mtree.add_dir("a", "grandparent")
        mtree.add_dir("b", "grandparent/parent")
        mtree.add_file("c", "grandparent/parent/file", "Hello\n")
        mtree.add_dir("d", "grandparent/alt_parent")
        return ChangesetTree(mtree, ''), mtree
        
    def test_renames(self):
        """Ensure that file renames have the proper effect on children"""
        ctree = self.make_tree_1()[0]
        self.assertEqual(ctree.old_path("grandparent"), "grandparent")
        self.assertEqual(ctree.old_path("grandparent/parent"), "grandparent/parent")
        self.assertEqual(ctree.old_path("grandparent/parent/file"),
            "grandparent/parent/file")

        self.assertEqual(ctree.id2path("a"), "grandparent")
        self.assertEqual(ctree.id2path("b"), "grandparent/parent")
        self.assertEqual(ctree.id2path("c"), "grandparent/parent/file")

        self.assertEqual(ctree.path2id("grandparent"), "a")
        self.assertEqual(ctree.path2id("grandparent/parent"), "b")
        self.assertEqual(ctree.path2id("grandparent/parent/file"), "c")

        assert ctree.path2id("grandparent2") is None
        assert ctree.path2id("grandparent2/parent") is None
        assert ctree.path2id("grandparent2/parent/file") is None

        ctree.note_rename("grandparent", "grandparent2")
        assert ctree.old_path("grandparent") is None
        assert ctree.old_path("grandparent/parent") is None
        assert ctree.old_path("grandparent/parent/file") is None

        self.assertEqual(ctree.id2path("a"), "grandparent2")
        self.assertEqual(ctree.id2path("b"), "grandparent2/parent")
        self.assertEqual(ctree.id2path("c"), "grandparent2/parent/file")

        self.assertEqual(ctree.path2id("grandparent2"), "a")
        self.assertEqual(ctree.path2id("grandparent2/parent"), "b")
        self.assertEqual(ctree.path2id("grandparent2/parent/file"), "c")

        assert ctree.path2id("grandparent") is None
        assert ctree.path2id("grandparent/parent") is None
        assert ctree.path2id("grandparent/parent/file") is None

        ctree.note_rename("grandparent/parent", "grandparent2/parent2")
        self.assertEqual(ctree.id2path("a"), "grandparent2")
        self.assertEqual(ctree.id2path("b"), "grandparent2/parent2")
        self.assertEqual(ctree.id2path("c"), "grandparent2/parent2/file")

        self.assertEqual(ctree.path2id("grandparent2"), "a")
        self.assertEqual(ctree.path2id("grandparent2/parent2"), "b")
        self.assertEqual(ctree.path2id("grandparent2/parent2/file"), "c")

        assert ctree.path2id("grandparent2/parent") is None
        assert ctree.path2id("grandparent2/parent/file") is None

        ctree.note_rename("grandparent/parent/file", 
                          "grandparent2/parent2/file2")
        self.assertEqual(ctree.id2path("a"), "grandparent2")
        self.assertEqual(ctree.id2path("b"), "grandparent2/parent2")
        self.assertEqual(ctree.id2path("c"), "grandparent2/parent2/file2")

        self.assertEqual(ctree.path2id("grandparent2"), "a")
        self.assertEqual(ctree.path2id("grandparent2/parent2"), "b")
        self.assertEqual(ctree.path2id("grandparent2/parent2/file2"), "c")

        assert ctree.path2id("grandparent2/parent2/file") is None

    def test_moves(self):
        """Ensure that file moves have the proper effect on children"""
        ctree = self.make_tree_1()[0]
        ctree.note_rename("grandparent/parent/file", 
                          "grandparent/alt_parent/file")
        self.assertEqual(ctree.id2path("c"), "grandparent/alt_parent/file")
        self.assertEqual(ctree.path2id("grandparent/alt_parent/file"), "c")
        assert ctree.path2id("grandparent/parent/file") is None

    def unified_diff(self, old, new):
        out = StringIO()
        internal_diff("old", old, "new", new, out)
        out.seek(0,0)
        return out.read()

    def make_tree_2(self):
        ctree = self.make_tree_1()[0]
        ctree.note_rename("grandparent/parent/file", 
                          "grandparent/alt_parent/file")
        assert ctree.id2path("e") is None
        assert ctree.path2id("grandparent/parent/file") is None
        ctree.note_id("e", "grandparent/parent/file")
        return ctree

    def test_adds(self):
        """File/inventory adds"""
        ctree = self.make_tree_2()
        add_patch = self.unified_diff([], ["Extra cheese\n"])
        ctree.note_patch("grandparent/parent/file", add_patch)
        self.adds_test(ctree)

    def adds_test(self, ctree):
        self.assertEqual(ctree.id2path("e"), "grandparent/parent/file")
        self.assertEqual(ctree.path2id("grandparent/parent/file"), "e")
        self.assertEqual(ctree.get_file("e").read(), "Extra cheese\n")

    def test_adds2(self):
        """File/inventory adds, with patch-compatibile renames"""
        ctree = self.make_tree_2()
        ctree.contents_by_id = False
        add_patch = self.unified_diff(["Hello\n"], ["Extra cheese\n"])
        ctree.note_patch("grandparent/parent/file", add_patch)
        self.adds_test(ctree)

    def make_tree_3(self):
        ctree, mtree = self.make_tree_1()
        mtree.add_file("e", "grandparent/parent/topping", "Anchovies\n")
        ctree.note_rename("grandparent/parent/file", 
                          "grandparent/alt_parent/file")
        ctree.note_rename("grandparent/parent/topping", 
                          "grandparent/alt_parent/stopping")
        return ctree

    def get_file_test(self, ctree):
        self.assertEqual(ctree.get_file("e").read(), "Lemon\n")
        self.assertEqual(ctree.get_file("c").read(), "Hello\n")

    def test_get_file(self):
        """Get file contents"""
        ctree = self.make_tree_3()
        mod_patch = self.unified_diff(["Anchovies\n"], ["Lemon\n"])
        ctree.note_patch("grandparent/alt_parent/stopping", mod_patch)
        self.get_file_test(ctree)

    def test_get_file2(self):
        """Get file contents, with patch-compatibile renames"""
        ctree = self.make_tree_3()
        ctree.contents_by_id = False
        mod_patch = self.unified_diff([], ["Lemon\n"])
        ctree.note_patch("grandparent/alt_parent/stopping", mod_patch)
        mod_patch = self.unified_diff([], ["Hello\n"])
        ctree.note_patch("grandparent/alt_parent/file", mod_patch)
        self.get_file_test(ctree)

    def test_delete(self):
        "Deletion by changeset"
        ctree = self.make_tree_1()[0]
        self.assertEqual(ctree.get_file("c").read(), "Hello\n")
        ctree.note_deletion("grandparent/parent/file")
        assert ctree.id2path("c") is None
        assert ctree.path2id("grandparent/parent/file") is None

    def sorted_ids(self, tree):
        ids = list(tree)
        ids.sort()
        return ids

    def test_iteration(self):
        """Ensure that iteration through ids works properly"""
        ctree = self.make_tree_1()[0]
        self.assertEqual(self.sorted_ids(ctree), ['a', 'b', 'c', 'd'])
        ctree.note_deletion("grandparent/parent/file")
        ctree.note_id("e", "grandparent/alt_parent/fool", kind="directory")
        ctree.note_last_changed("e", "revisionidiguess")
        self.assertEqual(self.sorted_ids(ctree), ['a', 'b', 'd', 'e'])


class CSetTester(TestCaseInTempDir):

    def get_valid_cset(self, base_rev_id, rev_id,
            auto_commit=False, checkout_dir=None,
            message=None):
        """Create a changeset from base_rev_id -> rev_id in built-in branch.
        Make sure that the text generated is valid, and that it
        can be applied against the base, and generate the same information.
        
        :return: The in-memory changeset
        """
        from cStringIO import StringIO
        from bzrlib.changeset.gen_changeset import show_changeset
        from bzrlib.changeset.read_changeset import read_changeset

        cset_txt = StringIO()
        base_ancestry = set(self.b1.repository.get_ancestry(base_rev_id))
        rev_ids = [r for r in self.b1.repository.get_ancestry(rev_id) if r
                   not in base_ancestry]
        serializer.write(self.b1.repository, reversed(rev_ids), cset_txt)
        cset_txt.seek(0)
        self.assertEqual(cset_txt.readline(), '# Bazaar changeset v0.7\n')
        self.assertEqual(cset_txt.readline(), '#\n')

        rev = self.b1.repository.get_revision(rev_id)
        self.assertEqual(cset_txt.readline().decode('utf-8'),
                u'# revision id: %s\n' % rev.revision_id)

        open(',,cset', 'wb').write(cset_txt.getvalue())
        cset_txt.seek(0)
        # This should also validate the generate changeset
        cset = ChangesetReader(cset_txt)
        for cset_rev in cset.info.real_revisions:
            # These really should have already been checked in read_changeset
            # since it computes the sha1 hash for the revision, which
            # only will match if everything is okay, but lets be
            # explicit about it
            branch_rev = self.b1.repository.get_revision(cset_rev.revision_id)
            for a in ('inventory_sha1', 'revision_id', 'parent_ids',
                      'timestamp', 'timezone', 'message', 'committer', 
                      'parent_ids', 'properties'):
                self.assertEqual(getattr(branch_rev, a), getattr(cset_rev, a))
            self.assertEqual(len(branch_rev.parent_ids), len(cset_rev.parent_ids))

        self.valid_apply_changeset(base_rev_id, cset,
                auto_commit=auto_commit, checkout_dir=checkout_dir)

        return cset

    def get_checkout(self, rev_id, checkout_dir=None):
        """Get a new tree, with the specified revision in it.
        """
        from bzrlib.branch import Branch
        import tempfile

        if checkout_dir is None:
            checkout_dir = tempfile.mkdtemp(prefix='test-branch-', dir='.')
        else:
            import os
            if not os.path.exists(checkout_dir):
                os.mkdir(checkout_dir)
        tree = BzrDir.create_standalone_workingtree(checkout_dir)
        s = StringIO()
        ancestors = [a for a in self.b1.repository.get_ancestry(rev_id) if
                     a is not None]
        serializer.write(self.b1.repository, ancestors, s)
        s.seek(0)
        install_changeset(tree.branch.repository, ChangesetReader(s))
        for ancestor in ancestors:
            old = self.b1.repository.revision_tree(ancestor)
            new = tree.branch.repository.revision_tree(ancestor)
            for inventory_id in old:
                try:
                    old_file = old.get_file(inventory_id)
                except:
                    continue
                if old_file is None:
                    continue
                self.assertEqual(old_file.read(),
                                 new.get_file(inventory_id).read())
        if rev_id is not None:
            rh = self.b1.revision_history()
            tree.branch.set_revision_history(rh[:rh.index(rev_id)+1])
            tree.update()
        return tree

    def valid_apply_changeset(self, base_rev_id, reader,
            auto_commit=False, checkout_dir=None):
        """Get the base revision, apply the changes, and make
        sure everything matches the builtin branch.
        """
        from bzrlib.changeset.apply_changeset import _apply_cset

        to_tree = self.get_checkout(base_rev_id, checkout_dir=checkout_dir)
        repository = to_tree.branch.repository
        self.assertIs(repository.has_revision(base_rev_id), True)
        info = reader.info
        for rev in info.real_revisions:
            self.assert_(not repository.has_revision(rev.revision_id),
                'Revision {%s} present before applying changeset' 
                % rev.revision_id)
        merge_changeset(reader, to_tree, True, Merge3Merger, False, False)

        for rev in info.real_revisions:
            self.assert_(repository.has_revision(rev.revision_id),
                'Missing revision {%s} after applying changeset' 
                % rev.revision_id)

        self.assert_(to_tree.branch.repository.has_revision(info.target))
        # Do we also want to verify that all the texts have been added?

        self.assert_(info.target in to_tree.pending_merges())


        rev = info.real_revisions[-1]
        base_tree = self.b1.repository.revision_tree(rev.revision_id)
        to_tree = to_tree.branch.repository.revision_tree(rev.revision_id)
        
        # TODO: make sure the target tree is identical to base tree
        #       we might also check the working tree.

        base_files = list(base_tree.list_files())
        to_files = list(to_tree.list_files())
        self.assertEqual(len(base_files), len(to_files))
        self.assertEqual(base_files, to_files)

        for path, status, kind, fileid, entry in base_files:
            # Check that the meta information is the same
            self.assertEqual(base_tree.get_file_size(fileid),
                    to_tree.get_file_size(fileid))
            self.assertEqual(base_tree.get_file_sha1(fileid),
                    to_tree.get_file_sha1(fileid))
            # Check that the contents are the same
            # This is pretty expensive
            # self.assertEqual(base_tree.get_file(fileid).read(),
            #         to_tree.get_file(fileid).read())

    def test_changeset(self):

        import os, sys
        pjoin = os.path.join

        self.tree1 = BzrDir.create_standalone_workingtree('b1')
        self.b1 = self.tree1.branch

        open(pjoin('b1/one'), 'wb').write('one\n')
        self.tree1.add('one')
        self.tree1.commit('add one', rev_id='a@cset-0-1')

        cset = self.get_valid_cset(None, 'a@cset-0-1')
        cset = self.get_valid_cset(None, 'a@cset-0-1',
                message='With a specialized message')

        # Make sure we can handle files with spaces, tabs, other
        # bogus characters
        self.build_tree([
                'b1/with space.txt'
                , 'b1/dir/'
                , 'b1/dir/filein subdir.c'
                , 'b1/dir/WithCaps.txt'
                , 'b1/dir/trailing space '
                , 'b1/sub/'
                , 'b1/sub/sub/'
                , 'b1/sub/sub/nonempty.txt'
                # Tabs are not valid in filenames on windows
                #'b1/with\ttab.txt'
                ])
        open('b1/sub/sub/emptyfile.txt', 'wb').close()
        open('b1/dir/nolastnewline.txt', 'wb').write('bloop')
        self.tree1.add([
                'with space.txt'
                , 'dir'
                , 'dir/filein subdir.c'
                , 'dir/WithCaps.txt'
                , 'dir/trailing space '
                , 'dir/nolastnewline.txt'
                , 'sub'
                , 'sub/sub'
                , 'sub/sub/nonempty.txt'
                , 'sub/sub/emptyfile.txt'
                ])
        self.tree1.commit('add whitespace', rev_id='a@cset-0-2')

        cset = self.get_valid_cset('a@cset-0-1', 'a@cset-0-2')
        ##cset = self.get_valid_cset('a@cset-0-1', 'a@cset-0-2', auto_commit=True)

        # Check a rollup changeset
        cset = self.get_valid_cset(None, 'a@cset-0-2')
        ##cset = self.get_valid_cset(None, 'a@cset-0-2', auto_commit=True)

        # Now delete entries
        self.tree1.remove(
                ['sub/sub/nonempty.txt'
                , 'sub/sub/emptyfile.txt'
                , 'sub/sub'
                ])
        self.tree1.commit('removed', rev_id='a@cset-0-3')
        
        cset = self.get_valid_cset('a@cset-0-2', 'a@cset-0-3')
        ##cset = self.get_valid_cset('a@cset-0-2', 'a@cset-0-3', auto_commit=True)
        # Check a rollup changeset
        cset = self.get_valid_cset(None, 'a@cset-0-3')
        ##cset = self.get_valid_cset(None, 'a@cset-0-3', auto_commit=True)


        # Now move the directory
        self.tree1.rename_one('dir', 'sub/dir')
        self.tree1.commit('rename dir', rev_id='a@cset-0-4')

        cset = self.get_valid_cset('a@cset-0-3', 'a@cset-0-4')
        # Check a rollup changeset
        cset = self.get_valid_cset(None, 'a@cset-0-4')
        ##cset = self.get_valid_cset(None, 'a@cset-0-4', auto_commit=True)
        ##cset = self.get_valid_cset('a@cset-0-1', 'a@cset-0-4', auto_commit=True)
        ##cset = self.get_valid_cset('a@cset-0-2', 'a@cset-0-4', auto_commit=True)
        ##cset = self.get_valid_cset('a@cset-0-3', 'a@cset-0-4', auto_commit=True)

        # Modified files
        open('b1/sub/dir/WithCaps.txt', 'ab').write('\nAdding some text\n')
        open('b1/sub/dir/trailing space ', 'ab').write('\nAdding some\nDOS format lines\n')
        open('b1/sub/dir/nolastnewline.txt', 'ab').write('\n')
        self.tree1.rename_one('sub/dir/trailing space ', 
                              'sub/ start and end space ')
        self.tree1.commit('Modified files', rev_id='a@cset-0-5')
        cset = self.get_valid_cset('a@cset-0-4', 'a@cset-0-5')
        ##cset = self.get_valid_cset('a@cset-0-4', 'a@cset-0-5', auto_commit=True)
        ##cset = self.get_valid_cset(None, 'a@cset-0-5', auto_commit=True)

        # Handle international characters
        f = open(u'b1/with Dod\xe9', 'wb')
        f.write((u'A file\n'
            u'With international man of mystery\n'
            u'William Dod\xe9\n').encode('utf-8'))
        self.tree1.add([u'with Dod\xe9'])
        # BUG: (sort of) You must set verbose=False, so that python doesn't try
        #       and print the name of William Dode as part of the commit
        self.tree1.commit(u'i18n commit from William Dod\xe9', 
                          rev_id='a@cset-0-6', committer=u'William Dod\xe9',
                          verbose=False)
        cset = self.get_valid_cset('a@cset-0-5', 'a@cset-0-6')
        ##cset = self.get_valid_cset('a@cset-0-5', 'a@cset-0-6', auto_commit=True)
        ##cset = self.get_valid_cset(None, 'a@cset-0-6', auto_commit=True)


