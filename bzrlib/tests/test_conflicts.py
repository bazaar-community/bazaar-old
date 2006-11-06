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


import os

from bzrlib import (
    bzrdir,
    conflicts,
    )
from bzrlib.tests import TestCaseWithTransport, TestCase
from bzrlib.branch import Branch
from bzrlib.conflicts import (MissingParent, ContentsConflict, TextConflict,
        PathConflict, DuplicateID, DuplicateEntry, ParentLoop, UnversionedParent,
        ConflictList, 
        restore)
from bzrlib.errors import NotConflicted


# TODO: Test commit with some added, and added-but-missing files
# RBC 20060124 is that not tested in test_commit.py ?

# The order of 'path' here is important - do not let it
# be a sorted list.
example_conflicts = ConflictList([ 
    MissingParent('Not deleting', 'pathg', 'idg'),
    ContentsConflict('patha', 'ida'), 
    TextConflict('patha'),
    PathConflict('pathb', 'pathc', 'idb'),
    DuplicateID('Unversioned existing file', 'pathc', 'pathc2', 'idc', 'idc'),
    DuplicateEntry('Moved existing file to',  'pathdd.moved', 'pathd', 'idd', 
                   None),
    ParentLoop('Cancelled move', 'pathe', 'path2e', None, 'id2e'),
    UnversionedParent('Versioned directory', 'pathf', 'idf'),
])


class TestConflicts(TestCaseWithTransport):

    def test_conflicts(self):
        """Conflicts are detected properly"""
        tree = self.make_branch_and_tree('.',
            format=bzrdir.BzrDirFormat6())
        b = tree.branch
        file('hello', 'w').write('hello world4')
        file('hello.THIS', 'w').write('hello world2')
        file('hello.BASE', 'w').write('hello world1')
        file('hello.OTHER', 'w').write('hello world3')
        file('hello.sploo.BASE', 'w').write('yellow world')
        file('hello.sploo.OTHER', 'w').write('yellow world2')
        self.assertEqual(len(list(tree.list_files())), 6)
        conflicts = tree.conflicts()
        self.assertEqual(len(conflicts), 2)
        self.assert_('hello' in conflicts[0].path)
        self.assert_('hello.sploo' in conflicts[1].path)
        restore('hello')
        restore('hello.sploo')
        self.assertEqual(len(tree.conflicts()), 0)
        self.assertFileEqual('hello world2', 'hello')
        assert not os.path.lexists('hello.sploo')
        self.assertRaises(NotConflicted, restore, 'hello')
        self.assertRaises(NotConflicted, restore, 'hello.sploo')

    def test_resolve_conflict_dir(self):
        tree = self.make_branch_and_tree('.')
        b = tree.branch
        file('hello', 'w').write('hello world4')
        tree.add('hello', 'q')
        file('hello.THIS', 'w').write('hello world2')
        file('hello.BASE', 'w').write('hello world1')
        os.mkdir('hello.OTHER')
        l = ConflictList([TextConflict('hello')])
        l.remove_files(tree)

    def test_auto_resolve(self):
        base = self.make_branch_and_tree('base')
        self.build_tree_contents([('base/hello', 'Hello')])
        base.add('hello', 'hello_id')
        base.commit('Hello')
        other = base.bzrdir.sprout('other').open_workingtree()
        self.build_tree_contents([('other/hello', 'hELLO')])
        other.commit('Case switch')
        this = base.bzrdir.sprout('this').open_workingtree()
        self.failUnlessExists('this/hello')
        self.build_tree_contents([('this/hello', 'Hello World')])
        this.commit('Add World')
        this.merge_from_branch(other.branch)
        self.assertEqual([TextConflict('hello', None, 'hello_id')], 
                         this.conflicts())
        conflicts.auto_resolve(this)
        self.assertEqual([TextConflict('hello', None, 'hello_id')], 
                         this.conflicts())
        self.build_tree_contents([('this/hello', '<<<<<<<')])
        conflicts.auto_resolve(this)
        self.assertEqual([TextConflict('hello', None, 'hello_id')], 
                         this.conflicts())
        self.build_tree_contents([('this/hello', '=======')])
        conflicts.auto_resolve(this)
        self.assertEqual([TextConflict('hello', None, 'hello_id')], 
                         this.conflicts())
        self.build_tree_contents([('this/hello', '\n>>>>>>>')])
        remaining, resolved = conflicts.auto_resolve(this)
        self.assertEqual([TextConflict('hello', None, 'hello_id')], 
                         this.conflicts())
        self.assertEqual([], resolved)
        self.build_tree_contents([('this/hello', 'hELLO wORLD')])
        remaining, resolved = conflicts.auto_resolve(this)
        self.assertEqual([], this.conflicts())
        self.assertEqual([TextConflict('hello', None, 'hello_id')], 
                         resolved)
        self.failIfExists('this/hello.BASE')


class TestConflictStanzas(TestCase):

    def test_stanza_roundtrip(self):
        # write and read our example stanza.
        stanza_iter = example_conflicts.to_stanzas()
        processed = ConflictList.from_stanzas(stanza_iter)
        for o,p in zip(processed, example_conflicts):
            self.assertEqual(o, p)

    def test_stanzification(self):
        for stanza in example_conflicts.to_stanzas():
            try:
                self.assertStartsWith(stanza['file_id'], 'id')
            except KeyError:
                pass
            self.assertStartsWith(stanza['path'], 'path')
            try:
                self.assertStartsWith(stanza['conflict_file_id'], 'id')
                self.assertStartsWith(stanza['conflict_file_path'], 'path')
            except KeyError:
                pass
