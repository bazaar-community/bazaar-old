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

from bzrlib.builtins import merge
from bzrlib.bzrdir import BzrDir
from bzrlib.bundle.apply_bundle import install_bundle, merge_bundle
from bzrlib.bundle.read_bundle import BundleTree, BundleReader
from bzrlib.bundle.serializer import write_bundle
from bzrlib.diff import internal_diff
from bzrlib.errors import BzrError, TestamentMismatch, NotABundle
from bzrlib.merge import Merge3Merger
from bzrlib.osutils import has_symlinks, sha_file
from bzrlib.tests import TestCaseInTempDir, TestCase, TestSkipped
from bzrlib.transform import TreeTransform
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
        if file_id not in self.contents:
            return None, None
        text_sha1 = sha_file(self.get_file(file_id))
        return text_sha1, len(self.contents[file_id])


class BTreeTester(TestCase):
    """A simple unittest tester for the BundleTree class."""

    def make_tree_1(self):
        mtree = MockTree()
        mtree.add_dir("a", "grandparent")
        mtree.add_dir("b", "grandparent/parent")
        mtree.add_file("c", "grandparent/parent/file", "Hello\n")
        mtree.add_dir("d", "grandparent/alt_parent")
        return BundleTree(mtree, ''), mtree
        
    def test_renames(self):
        """Ensure that file renames have the proper effect on children"""
        btree = self.make_tree_1()[0]
        self.assertEqual(btree.old_path("grandparent"), "grandparent")
        self.assertEqual(btree.old_path("grandparent/parent"), 
                         "grandparent/parent")
        self.assertEqual(btree.old_path("grandparent/parent/file"),
                         "grandparent/parent/file")

        self.assertEqual(btree.id2path("a"), "grandparent")
        self.assertEqual(btree.id2path("b"), "grandparent/parent")
        self.assertEqual(btree.id2path("c"), "grandparent/parent/file")

        self.assertEqual(btree.path2id("grandparent"), "a")
        self.assertEqual(btree.path2id("grandparent/parent"), "b")
        self.assertEqual(btree.path2id("grandparent/parent/file"), "c")

        assert btree.path2id("grandparent2") is None
        assert btree.path2id("grandparent2/parent") is None
        assert btree.path2id("grandparent2/parent/file") is None

        btree.note_rename("grandparent", "grandparent2")
        assert btree.old_path("grandparent") is None
        assert btree.old_path("grandparent/parent") is None
        assert btree.old_path("grandparent/parent/file") is None

        self.assertEqual(btree.id2path("a"), "grandparent2")
        self.assertEqual(btree.id2path("b"), "grandparent2/parent")
        self.assertEqual(btree.id2path("c"), "grandparent2/parent/file")

        self.assertEqual(btree.path2id("grandparent2"), "a")
        self.assertEqual(btree.path2id("grandparent2/parent"), "b")
        self.assertEqual(btree.path2id("grandparent2/parent/file"), "c")

        assert btree.path2id("grandparent") is None
        assert btree.path2id("grandparent/parent") is None
        assert btree.path2id("grandparent/parent/file") is None

        btree.note_rename("grandparent/parent", "grandparent2/parent2")
        self.assertEqual(btree.id2path("a"), "grandparent2")
        self.assertEqual(btree.id2path("b"), "grandparent2/parent2")
        self.assertEqual(btree.id2path("c"), "grandparent2/parent2/file")

        self.assertEqual(btree.path2id("grandparent2"), "a")
        self.assertEqual(btree.path2id("grandparent2/parent2"), "b")
        self.assertEqual(btree.path2id("grandparent2/parent2/file"), "c")

        assert btree.path2id("grandparent2/parent") is None
        assert btree.path2id("grandparent2/parent/file") is None

        btree.note_rename("grandparent/parent/file", 
                          "grandparent2/parent2/file2")
        self.assertEqual(btree.id2path("a"), "grandparent2")
        self.assertEqual(btree.id2path("b"), "grandparent2/parent2")
        self.assertEqual(btree.id2path("c"), "grandparent2/parent2/file2")

        self.assertEqual(btree.path2id("grandparent2"), "a")
        self.assertEqual(btree.path2id("grandparent2/parent2"), "b")
        self.assertEqual(btree.path2id("grandparent2/parent2/file2"), "c")

        assert btree.path2id("grandparent2/parent2/file") is None

    def test_moves(self):
        """Ensure that file moves have the proper effect on children"""
        btree = self.make_tree_1()[0]
        btree.note_rename("grandparent/parent/file", 
                          "grandparent/alt_parent/file")
        self.assertEqual(btree.id2path("c"), "grandparent/alt_parent/file")
        self.assertEqual(btree.path2id("grandparent/alt_parent/file"), "c")
        assert btree.path2id("grandparent/parent/file") is None

    def unified_diff(self, old, new):
        out = StringIO()
        internal_diff("old", old, "new", new, out)
        out.seek(0,0)
        return out.read()

    def make_tree_2(self):
        btree = self.make_tree_1()[0]
        btree.note_rename("grandparent/parent/file", 
                          "grandparent/alt_parent/file")
        assert btree.id2path("e") is None
        assert btree.path2id("grandparent/parent/file") is None
        btree.note_id("e", "grandparent/parent/file")
        return btree

    def test_adds(self):
        """File/inventory adds"""
        btree = self.make_tree_2()
        add_patch = self.unified_diff([], ["Extra cheese\n"])
        btree.note_patch("grandparent/parent/file", add_patch)
        btree.note_id('f', 'grandparent/parent/symlink', kind='symlink')
        btree.note_target('grandparent/parent/symlink', 'venus')
        self.adds_test(btree)

    def adds_test(self, btree):
        self.assertEqual(btree.id2path("e"), "grandparent/parent/file")
        self.assertEqual(btree.path2id("grandparent/parent/file"), "e")
        self.assertEqual(btree.get_file("e").read(), "Extra cheese\n")
        self.assertEqual(btree.get_symlink_target('f'), 'venus')

    def test_adds2(self):
        """File/inventory adds, with patch-compatibile renames"""
        btree = self.make_tree_2()
        btree.contents_by_id = False
        add_patch = self.unified_diff(["Hello\n"], ["Extra cheese\n"])
        btree.note_patch("grandparent/parent/file", add_patch)
        btree.note_id('f', 'grandparent/parent/symlink', kind='symlink')
        btree.note_target('grandparent/parent/symlink', 'venus')
        self.adds_test(btree)

    def make_tree_3(self):
        btree, mtree = self.make_tree_1()
        mtree.add_file("e", "grandparent/parent/topping", "Anchovies\n")
        btree.note_rename("grandparent/parent/file", 
                          "grandparent/alt_parent/file")
        btree.note_rename("grandparent/parent/topping", 
                          "grandparent/alt_parent/stopping")
        return btree

    def get_file_test(self, btree):
        self.assertEqual(btree.get_file("e").read(), "Lemon\n")
        self.assertEqual(btree.get_file("c").read(), "Hello\n")

    def test_get_file(self):
        """Get file contents"""
        btree = self.make_tree_3()
        mod_patch = self.unified_diff(["Anchovies\n"], ["Lemon\n"])
        btree.note_patch("grandparent/alt_parent/stopping", mod_patch)
        self.get_file_test(btree)

    def test_get_file2(self):
        """Get file contents, with patch-compatibile renames"""
        btree = self.make_tree_3()
        btree.contents_by_id = False
        mod_patch = self.unified_diff([], ["Lemon\n"])
        btree.note_patch("grandparent/alt_parent/stopping", mod_patch)
        mod_patch = self.unified_diff([], ["Hello\n"])
        btree.note_patch("grandparent/alt_parent/file", mod_patch)
        self.get_file_test(btree)

    def test_delete(self):
        "Deletion by bundle"
        btree = self.make_tree_1()[0]
        self.assertEqual(btree.get_file("c").read(), "Hello\n")
        btree.note_deletion("grandparent/parent/file")
        assert btree.id2path("c") is None
        assert btree.path2id("grandparent/parent/file") is None

    def sorted_ids(self, tree):
        ids = list(tree)
        ids.sort()
        return ids

    def test_iteration(self):
        """Ensure that iteration through ids works properly"""
        btree = self.make_tree_1()[0]
        self.assertEqual(self.sorted_ids(btree), ['a', 'b', 'c', 'd'])
        btree.note_deletion("grandparent/parent/file")
        btree.note_id("e", "grandparent/alt_parent/fool", kind="directory")
        btree.note_last_changed("grandparent/alt_parent/fool", 
                                "revisionidiguess")
        self.assertEqual(self.sorted_ids(btree), ['a', 'b', 'd', 'e'])


class CSetTester(TestCaseInTempDir):

    def get_valid_bundle(self, base_rev_id, rev_id, checkout_dir=None,
                         message=None):
        """Create a bundle from base_rev_id -> rev_id in built-in branch.
        Make sure that the text generated is valid, and that it
        can be applied against the base, and generate the same information.
        
        :return: The in-memory bundle 
        """
        from cStringIO import StringIO

        bundle_txt = StringIO()
        rev_ids = write_bundle(self.b1.repository, rev_id, base_rev_id, 
                               bundle_txt)
        bundle_txt.seek(0)
        self.assertEqual(bundle_txt.readline(), 
                         '# Bazaar revision bundle v0.7\n')
        self.assertEqual(bundle_txt.readline(), '#\n')

        rev = self.b1.repository.get_revision(rev_id)
        self.assertEqual(bundle_txt.readline().decode('utf-8'),
                         u'# message:\n')

        open(',,bundle', 'wb').write(bundle_txt.getvalue())
        bundle_txt.seek(0)
        # This should also validate the generated bundle 
        bundle = BundleReader(bundle_txt)
        repository = self.b1.repository
        for bundle_rev in bundle.info.real_revisions:
            # These really should have already been checked when we read the
            # bundle, since it computes the sha1 hash for the revision, which
            # only will match if everything is okay, but lets be explicit about
            # it
            branch_rev = repository.get_revision(bundle_rev.revision_id)
            for a in ('inventory_sha1', 'revision_id', 'parent_ids',
                      'timestamp', 'timezone', 'message', 'committer', 
                      'parent_ids', 'properties'):
                self.assertEqual(getattr(branch_rev, a), 
                                 getattr(bundle_rev, a))
            self.assertEqual(len(branch_rev.parent_ids), 
                             len(bundle_rev.parent_ids))
        self.assertEqual(rev_ids, 
                         [r.revision_id for r in bundle.info.real_revisions])
        self.valid_apply_bundle(base_rev_id, bundle,
                                   checkout_dir=checkout_dir)

        return bundle

    def get_invalid_bundle(self, base_rev_id, rev_id):
        """Create a bundle from base_rev_id -> rev_id in built-in branch.
        Munge the text so that it's invalid.
        
        :return: The in-memory bundle
        """
        from cStringIO import StringIO

        bundle_txt = StringIO()
        rev_ids = write_bundle(self.b1.repository, rev_id, base_rev_id, 
                               bundle_txt)
        bundle_txt.seek(0)
        open(',,bundle', 'wb').write(bundle_txt.getvalue())
        bundle_txt.seek(0)
        new_text = bundle_txt.getvalue().replace('executable:no', 
                                               'executable:yes')
        bundle_txt = StringIO(new_text)
        bundle = BundleReader(bundle_txt)
        self.valid_apply_bundle(base_rev_id, bundle)
        return bundle 

    def test_non_bundle(self):
        self.assertRaises(NotABundle, BundleReader, StringIO('#!/bin/sh\n'))

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
        ancestors = write_bundle(self.b1.repository, rev_id, None, s)
        s.seek(0)
        assert isinstance(s.getvalue(), str), (
            "Bundle isn't a bytestring:\n %s..." % repr(s.getvalue())[:40])
        install_bundle(tree.branch.repository, BundleReader(s))
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

    def valid_apply_bundle(self, base_rev_id, reader, checkout_dir=None):
        """Get the base revision, apply the changes, and make
        sure everything matches the builtin branch.
        """
        to_tree = self.get_checkout(base_rev_id, checkout_dir=checkout_dir)
        repository = to_tree.branch.repository
        self.assertIs(repository.has_revision(base_rev_id), True)
        info = reader.info
        for rev in info.real_revisions:
            self.assert_(not repository.has_revision(rev.revision_id),
                'Revision {%s} present before applying bundle' 
                % rev.revision_id)
        merge_bundle(reader, to_tree, True, Merge3Merger, False, False)

        for rev in info.real_revisions:
            self.assert_(repository.has_revision(rev.revision_id),
                'Missing revision {%s} after applying bundle' 
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
        for base_file, to_file in zip(base_files, to_files):
            self.assertEqual(base_file, to_file)

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

    def test_bundle(self):

        import os, sys
        pjoin = os.path.join

        self.tree1 = BzrDir.create_standalone_workingtree('b1')
        self.b1 = self.tree1.branch

        open(pjoin('b1/one'), 'wb').write('one\n')
        self.tree1.add('one')
        self.tree1.commit('add one', rev_id='a@cset-0-1')

        bundle = self.get_valid_bundle(None, 'a@cset-0-1')
        bundle = self.get_valid_bundle(None, 'a@cset-0-1',
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
        tt = TreeTransform(self.tree1)
        tt.new_file('executable', tt.root, '#!/bin/sh\n', 'exe-1', True)
        tt.apply()
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

        bundle = self.get_valid_bundle('a@cset-0-1', 'a@cset-0-2')

        # Check a rollup bundle 
        bundle = self.get_valid_bundle(None, 'a@cset-0-2')

        # Now delete entries
        self.tree1.remove(
                ['sub/sub/nonempty.txt'
                , 'sub/sub/emptyfile.txt'
                , 'sub/sub'
                ])
        tt = TreeTransform(self.tree1)
        trans_id = tt.trans_id_tree_file_id('exe-1')
        tt.set_executability(False, trans_id)
        tt.apply()
        self.tree1.commit('removed', rev_id='a@cset-0-3')
        
        bundle = self.get_valid_bundle('a@cset-0-2', 'a@cset-0-3')
        self.assertRaises(TestamentMismatch, self.get_invalid_bundle, 
                          'a@cset-0-2', 'a@cset-0-3')
        # Check a rollup bundle 
        bundle = self.get_valid_bundle(None, 'a@cset-0-3')


        # Now move the directory
        self.tree1.rename_one('dir', 'sub/dir')
        self.tree1.commit('rename dir', rev_id='a@cset-0-4')

        bundle = self.get_valid_bundle('a@cset-0-3', 'a@cset-0-4')
        # Check a rollup bundle 
        bundle = self.get_valid_bundle(None, 'a@cset-0-4')

        # Modified files
        open('b1/sub/dir/WithCaps.txt', 'ab').write('\nAdding some text\n')
        open('b1/sub/dir/trailing space ', 'ab').write('\nAdding some\nDOS format lines\n')
        open('b1/sub/dir/nolastnewline.txt', 'ab').write('\n')
        self.tree1.rename_one('sub/dir/trailing space ', 
                              'sub/ start and end space ')
        self.tree1.commit('Modified files', rev_id='a@cset-0-5')
        bundle = self.get_valid_bundle('a@cset-0-4', 'a@cset-0-5')

        # Handle international characters
        try:
            f = open(u'b1/with Dod\xe9', 'wb')
        except UnicodeEncodeError:
            raise TestSkipped("Filesystem doesn't support unicode")
        f.write((u'A file\n'
            u'With international man of mystery\n'
            u'William Dod\xe9\n').encode('utf-8'))
        self.tree1.add([u'with Dod\xe9'])
        # BUG: (sort of) You must set verbose=False, so that python doesn't try
        #       and print the name of William Dode as part of the commit
        self.tree1.commit(u'i18n commit from William Dod\xe9', 
                          rev_id='a@cset-0-6', committer=u'William Dod\xe9',
                          verbose=False)
        bundle = self.get_valid_bundle('a@cset-0-5', 'a@cset-0-6')
        self.tree1.rename_one('sub/dir/WithCaps.txt', 'temp')
        self.tree1.rename_one('with space.txt', 'WithCaps.txt')
        self.tree1.rename_one('temp', 'with space.txt')
        self.tree1.commit(u'swap filenames', rev_id='a@cset-0-7',
                          verbose=False)
        bundle = self.get_valid_bundle('a@cset-0-6', 'a@cset-0-7')
        other = self.get_checkout('a@cset-0-6')
        other.rename_one('sub/dir/nolastnewline.txt', 'sub/nolastnewline.txt')
        other.commit('rename file', rev_id='a@cset-0-7b')
        merge([other.basedir, -1], [None, None], this_dir=self.tree1.basedir)
        self.tree1.commit(u'Merge', rev_id='a@cset-0-8',
                          verbose=False)
        bundle = self.get_valid_bundle('a@cset-0-7', 'a@cset-0-8')

    def test_symlink_bundle(self):
        if not has_symlinks():
            raise TestSkipped("No symlink support")
        self.tree1 = BzrDir.create_standalone_workingtree('b1')
        self.b1 = self.tree1.branch
        tt = TreeTransform(self.tree1)
        tt.new_symlink('link', tt.root, 'bar/foo', 'link-1')
        tt.apply()
        self.tree1.commit('add symlink', rev_id='l@cset-0-1')
        self.get_valid_bundle(None, 'l@cset-0-1')
        tt = TreeTransform(self.tree1)
        trans_id = tt.trans_id_tree_file_id('link-1')
        tt.adjust_path('link2', tt.root, trans_id)
        tt.delete_contents(trans_id)
        tt.create_symlink('mars', trans_id)
        tt.apply()
        self.tree1.commit('rename and change symlink', rev_id='l@cset-0-2')
        self.get_valid_bundle('l@cset-0-1', 'l@cset-0-2')
        tt = TreeTransform(self.tree1)
        trans_id = tt.trans_id_tree_file_id('link-1')
        tt.delete_contents(trans_id)
        tt.create_symlink('jupiter', trans_id)
        tt.apply()
        self.tree1.commit('just change symlink target', rev_id='l@cset-0-3')
        self.get_valid_bundle('l@cset-0-2', 'l@cset-0-3')
        tt = TreeTransform(self.tree1)
        trans_id = tt.trans_id_tree_file_id('link-1')
        tt.delete_contents(trans_id)
        tt.apply()
        self.tree1.commit('Delete symlink', rev_id='l@cset-0-4')
        self.get_valid_bundle('l@cset-0-3', 'l@cset-0-4')

    def test_binary_bundle(self):
        self.tree1 = BzrDir.create_standalone_workingtree('b1')
        self.b1 = self.tree1.branch
        tt = TreeTransform(self.tree1)
        tt.new_file('file', tt.root, '\x00\xff', 'binary-1')
        tt.new_file('file2', tt.root, '\x00\xff', 'binary-2')
        tt.apply()
        self.tree1.commit('add binary', rev_id='b@cset-0-1')
        self.get_valid_bundle(None, 'b@cset-0-1')
        tt = TreeTransform(self.tree1)
        trans_id = tt.trans_id_tree_file_id('binary-1')
        tt.delete_contents(trans_id)
        tt.apply()
        self.tree1.commit('delete binary', rev_id='b@cset-0-2')
        self.get_valid_bundle('b@cset-0-1', 'b@cset-0-2')
        tt = TreeTransform(self.tree1)
        trans_id = tt.trans_id_tree_file_id('binary-2')
        tt.adjust_path('file3', tt.root, trans_id)
        tt.delete_contents(trans_id)
        tt.create_file('filecontents\x00', trans_id)
        tt.apply()
        self.tree1.commit('rename and modify binary', rev_id='b@cset-0-3')
        self.get_valid_bundle('b@cset-0-2', 'b@cset-0-3')
        tt = TreeTransform(self.tree1)
        trans_id = tt.trans_id_tree_file_id('binary-2')
        tt.delete_contents(trans_id)
        tt.create_file('\x00filecontents', trans_id)
        tt.apply()
        self.tree1.commit('just modify binary', rev_id='b@cset-0-4')
        self.get_valid_bundle('b@cset-0-3', 'b@cset-0-4')

    def test_last_modified(self):
        self.tree1 = BzrDir.create_standalone_workingtree('b1')
        self.b1 = self.tree1.branch
        tt = TreeTransform(self.tree1)
        tt.new_file('file', tt.root, 'file', 'file')
        tt.apply()
        self.tree1.commit('create file', rev_id='a@lmod-0-1')

        tt = TreeTransform(self.tree1)
        trans_id = tt.trans_id_tree_file_id('file')
        tt.delete_contents(trans_id)
        tt.create_file('file2', trans_id)
        tt.apply()
        self.tree1.commit('modify text', rev_id='a@lmod-0-2a')

        other = self.get_checkout('a@lmod-0-1')
        tt = TreeTransform(other)
        trans_id = tt.trans_id_tree_file_id('file')
        tt.delete_contents(trans_id)
        tt.create_file('file2', trans_id)
        tt.apply()
        other.commit('modify text in another tree', rev_id='a@lmod-0-2b')
        merge([other.basedir, -1], [None, None], this_dir=self.tree1.basedir)
        self.tree1.commit(u'Merge', rev_id='a@lmod-0-3',
                          verbose=False)
        self.tree1.commit(u'Merge', rev_id='a@lmod-0-4')
        bundle = self.get_valid_bundle('a@lmod-0-2a', 'a@lmod-0-4')

    def test_hide_history(self):
        import os, sys
        pjoin = os.path.join

        self.tree1 = BzrDir.create_standalone_workingtree('b1')
        self.b1 = self.tree1.branch

        open(pjoin('b1/one'), 'wb').write('one\n')
        self.tree1.add('one')
        self.tree1.commit('add file', rev_id='a@cset-0-1')
        open(pjoin('b1/one'), 'wb').write('two\n')
        self.tree1.commit('modify', rev_id='a@cset-0-2')
        open(pjoin('b1/one'), 'wb').write('three\n')
        self.tree1.commit('modify', rev_id='a@cset-0-3')
        bundle_file = StringIO()
        rev_ids = write_bundle(self.tree1.branch.repository, 'a@cset-0-3',
                               'a@cset-0-1', bundle_file)
        self.assertNotContainsRe(bundle_file.getvalue(), 'two')
        self.assertContainsRe(bundle_file.getvalue(), 'one')
        self.assertContainsRe(bundle_file.getvalue(), 'three')
