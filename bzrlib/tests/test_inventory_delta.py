# Copyright (C) 2008, 2009 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for bzrlib.inventory_delta.

See doc/developer/inventory.txt for more information.
"""

from cStringIO import StringIO

from bzrlib import (
    errors,
    inventory,
    inventory_delta,
    )
from bzrlib.inventory import Inventory
from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCase

### DO NOT REFLOW THESE TEXTS. NEW LINES ARE SIGNIFICANT. ###
empty_lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: null:
versioned_root: true
tree_references: true
"""

root_only_lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: entry-version
versioned_root: true
tree_references: true
None\x00/\x00an-id\x00\x00a@e\xc3\xa5ample.com--2004\x00dir
"""


root_change_lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: entry-version
version: changed-root
versioned_root: true
tree_references: true
/\x00an-id\x00\x00different-version\x00dir
"""

corrupt_parent_lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: entry-version
version: changed-root
versioned_root: false
tree_references: false
/\x00an-id\x00\x00different-version\x00dir
"""

root_only_unversioned = """format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: entry-version
versioned_root: false
tree_references: false
None\x00/\x00TREE_ROOT\x00\x00null:\x00dir
"""

reference_lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: entry-version
versioned_root: true
tree_references: true
None\x00/\x00TREE_ROOT\x00\x00a@e\xc3\xa5ample.com--2004\x00dir
None\x00/foo\x00id\x00TREE_ROOT\x00changed\x00tree\x00subtree-version
"""

change_tree_lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: entry-version
version: change-tree
versioned_root: false
tree_references: false
/foo\x00id\x00TREE_ROOT\x00changed-twice\x00tree\x00subtree-version2
"""


class TestDeserialization(TestCase):
    """Test InventoryDeltaSerializer.parse_text_bytes."""

    def test_parse_no_bytes(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        err = self.assertRaises(
            errors.BzrError, serializer.parse_text_bytes, '')
        self.assertContainsRe(str(err), 'unknown format')

    def test_parse_bad_format(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes, 'format: foo\n')
        self.assertContainsRe(str(err), 'unknown format')

    def test_parse_no_parent(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes,
            'format: bzr inventory delta v1 (bzr 1.14)\n')
        self.assertContainsRe(str(err), 'missing parent: marker')

    def test_parse_no_version(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes,
            'format: bzr inventory delta v1 (bzr 1.14)\n'
            'parent: null:\n')
        self.assertContainsRe(str(err), 'missing version: marker')
            
    def test_parse_duplicate_key_errors(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        double_root_lines = \
"""format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: null:
versioned_root: true
tree_references: true
None\x00/\x00an-id\x00\x00a@e\xc3\xa5ample.com--2004\x00dir\x00\x00
None\x00/\x00an-id\x00\x00a@e\xc3\xa5ample.com--2004\x00dir\x00\x00
"""
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes, double_root_lines)
        self.assertContainsRe(str(err), 'duplicate file id')

    def test_parse_versioned_root_only(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=True)
        parse_result = serializer.parse_text_bytes(root_only_lines)
        expected_entry = inventory.make_entry(
            'directory', u'', None, 'an-id')
        expected_entry.revision = 'a@e\xc3\xa5ample.com--2004'
        self.assertEqual(
            ('null:', 'entry-version', True, True, 
             [(None, '/', 'an-id', expected_entry)]),
            parse_result)

    def test_parse_special_revid_not_valid_last_mod(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=False, tree_references=True)
        root_only_lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: null:
versioned_root: false
tree_references: true
None\x00/\x00TREE_ROOT\x00\x00null:\x00dir\x00\x00
"""
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes, root_only_lines)
        self.assertContainsRe(str(err), 'special revisionid found')

    def test_parse_versioned_root_versioned_disabled(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=False, tree_references=True)
        root_only_lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: null:
versioned_root: false
tree_references: true
None\x00/\x00TREE_ROOT\x00\x00a@e\xc3\xa5ample.com--2004\x00dir\x00\x00
"""
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes, root_only_lines)
        self.assertContainsRe(str(err), 'Versioned root found')

    def test_parse_unique_root_id_root_versioned_disabled(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=False, tree_references=True)
        root_only_lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: null:
versioned_root: false
tree_references: true
None\x00/\x00an-id\x00\x00null:\x00dir\x00\x00
"""
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes, root_only_lines)
        self.assertContainsRe(str(err), 'Versioned root found')

    def test_parse_unversioned_root_versioning_enabled(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=True)
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes, root_only_unversioned)
        self.assertContainsRe(
            str(err), 'serialized versioned_root flag is wrong: False')

    def test_parse_tree_when_disabled(self):
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=False)
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes, reference_lines)
        self.assertContainsRe(
            str(err), 'serialized tree_references flag is wrong: True')

    def test_parse_tree_when_header_disallows(self):
        # A deserializer that allows tree_references to be set or unset.
        serializer = inventory_delta.InventoryDeltaSerializer()
        # A serialised inventory delta with a header saying no tree refs, but
        # that has a tree ref in its content.
        lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: entry-version
versioned_root: false
tree_references: false
None\x00/foo\x00id\x00TREE_ROOT\x00changed\x00tree\x00subtree-version
"""
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes, lines)
        self.assertContainsRe(str(err), 'Tree reference found')

    def test_parse_versioned_root_when_header_disallows(self):
        # A deserializer that allows tree_references to be set or unset.
        serializer = inventory_delta.InventoryDeltaSerializer()
        # A serialised inventory delta with a header saying no tree refs, but
        # that has a tree ref in its content.
        lines = """format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: entry-version
versioned_root: false
tree_references: false
None\x00/\x00TREE_ROOT\x00\x00a@e\xc3\xa5ample.com--2004\x00dir
"""
        err = self.assertRaises(errors.BzrError,
            serializer.parse_text_bytes, lines)
        self.assertContainsRe(str(err), 'Versioned root found')



class TestSerialization(TestCase):
    """Tests for InventoryDeltaSerializer.delta_to_lines."""

    def test_empty_delta_to_lines(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(True, True)
        self.assertEqual(StringIO(empty_lines).readlines(),
            serializer.delta_to_lines(NULL_REVISION, NULL_REVISION, delta))

    def test_root_only_to_lines(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry('directory', '', None, 'an-id')
        root.revision = 'a@e\xc3\xa5ample.com--2004'
        new_inv.add(root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=True)
        self.assertEqual(StringIO(root_only_lines).readlines(),
            serializer.delta_to_lines(NULL_REVISION, 'entry-version', delta))

    def test_unversioned_root(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry('directory', '', None, 'TREE_ROOT')
        new_inv.add(root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(False, False)
        self.assertEqual(StringIO(root_only_unversioned).readlines(),
            serializer.delta_to_lines(NULL_REVISION, 'entry-version', delta))

    def test_unversioned_non_root_errors(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry('directory', '', None, 'TREE_ROOT')
        root.revision = 'a@e\xc3\xa5ample.com--2004'
        new_inv.add(root)
        non_root = new_inv.make_entry('directory', 'foo', root.file_id, 'id')
        new_inv.add(non_root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=True)
        err = self.assertRaises(errors.BzrError,
            serializer.delta_to_lines, NULL_REVISION, 'entry-version', delta)
        self.assertEqual(str(err), 'no version for fileid id')

    def test_richroot_unversioned_root_errors(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry('directory', '', None, 'TREE_ROOT')
        new_inv.add(root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=True)
        err = self.assertRaises(errors.BzrError,
            serializer.delta_to_lines, NULL_REVISION, 'entry-version', delta)
        self.assertEqual(str(err), 'no version for fileid TREE_ROOT')

    def test_nonrichroot_versioned_root_errors(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry('directory', '', None, 'TREE_ROOT')
        root.revision = 'a@e\xc3\xa5ample.com--2004'
        new_inv.add(root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=False, tree_references=True)
        err = self.assertRaises(errors.BzrError,
            serializer.delta_to_lines, NULL_REVISION, 'entry-version', delta)
        self.assertEqual(str(err), 'Version present for / in TREE_ROOT')

    def test_nonrichroot_non_TREE_ROOT_id_errors(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry('directory', '', None, 'my-rich-root-id')
        new_inv.add(root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=False, tree_references=True)
        err = self.assertRaises(errors.BzrError,
            serializer.delta_to_lines, NULL_REVISION, 'entry-version', delta)
        self.assertEqual(
            str(err), 'file_id my-rich-root-id is not TREE_ROOT for /')

    def test_unknown_kind_errors(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry('directory', '', None, 'my-rich-root-id')
        root.revision = 'changed'
        new_inv.add(root)
        non_root = new_inv.make_entry('directory', 'foo', root.file_id, 'id')
        non_root.revision = 'changed'
        non_root.kind = 'strangelove'
        new_inv.add(non_root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(True, True)
        # we expect keyerror because there is little value wrapping this.
        # This test aims to prove that it errors more than how it errors.
        err = self.assertRaises(KeyError,
            serializer.delta_to_lines, NULL_REVISION, 'entry-version', delta)
        self.assertEqual(('strangelove',), err.args)

    def test_tree_reference_disabled(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry('directory', '', None, 'TREE_ROOT')
        root.revision = 'a@e\xc3\xa5ample.com--2004'
        new_inv.add(root)
        non_root = new_inv.make_entry(
            'tree-reference', 'foo', root.file_id, 'id')
        non_root.revision = 'changed'
        non_root.reference_revision = 'subtree-version'
        new_inv.add(non_root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=False)
        # we expect keyerror because there is little value wrapping this.
        # This test aims to prove that it errors more than how it errors.
        err = self.assertRaises(KeyError,
            serializer.delta_to_lines, NULL_REVISION, 'entry-version', delta)
        self.assertEqual(('tree-reference',), err.args)

    def test_tree_reference_enabled(self):
        old_inv = Inventory(None)
        new_inv = Inventory(None)
        root = new_inv.make_entry('directory', '', None, 'TREE_ROOT')
        root.revision = 'a@e\xc3\xa5ample.com--2004'
        new_inv.add(root)
        non_root = new_inv.make_entry(
            'tree-reference', 'foo', root.file_id, 'id')
        non_root.revision = 'changed'
        non_root.reference_revision = 'subtree-version'
        new_inv.add(non_root)
        delta = new_inv._make_delta(old_inv)
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=True)
        self.assertEqual(StringIO(reference_lines).readlines(),
            serializer.delta_to_lines(NULL_REVISION, 'entry-version', delta))

    def test_to_inventory_root_id_versioned_not_permitted(self):
        delta = [(None, '/', 'TREE_ROOT', inventory.make_entry(
            'directory', '', None, 'TREE_ROOT'))]
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=False, tree_references=True)
        self.assertRaises(
            errors.BzrError, serializer.delta_to_lines, 'old-version',
            'new-version', delta)

    def test_to_inventory_root_id_not_versioned(self):
        delta = [(None, '/', 'an-id', inventory.make_entry(
            'directory', '', None, 'an-id'))]
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=True)
        self.assertRaises(
            errors.BzrError, serializer.delta_to_lines, 'old-version',
            'new-version', delta)

    def test_to_inventory_has_tree_not_meant_to(self):
        make_entry = inventory.make_entry
        tree_ref = make_entry('tree-reference', 'foo', 'changed-in', 'ref-id')
        tree_ref.reference_revision = 'ref-revision'
        delta = [
            (None, '/', 'an-id',
             make_entry('directory', '', 'changed-in', 'an-id')),
            (None, '/foo', 'ref-id', tree_ref)
            # a file that followed the root move
            ]
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=True)
        self.assertRaises(errors.BzrError, serializer.delta_to_lines,
            'old-version', 'new-version', delta)

    def test_to_inventory_torture(self):
        def make_entry(kind, name, parent_id, file_id, **attrs):
            entry = inventory.make_entry(kind, name, parent_id, file_id)
            for name, value in attrs.items():
                setattr(entry, name, value)
            return entry
        # this delta is crafted to have all the following:
        # - deletes
        # - renamed roots
        # - deep dirs
        # - files moved after parent dir was renamed
        # - files with and without exec bit
        delta = [
            # new root:
            (None, '', 'new-root-id',
                make_entry('directory', '', None, 'new-root-id',
                    revision='changed-in')),
            # an old root:
            ('', 'old-root', 'TREE_ROOT',
                make_entry('directory', 'subdir-now', 'new-root-id',
                'TREE_ROOT', revision='moved-root')),
            # a file that followed the root move
            ('under-old-root', 'old-root/under-old-root', 'moved-id',
                make_entry('file', 'under-old-root', 'TREE_ROOT', 'moved-id',
                   revision='old-rev', executable=False, text_size=30,
                   text_sha1='some-sha')),
            # a deleted path
            ('old-file', None, 'deleted-id', None),
            # a tree reference moved to the new root
            ('ref', 'ref', 'ref-id',
                make_entry('tree-reference', 'ref', 'new-root-id', 'ref-id',
                    reference_revision='tree-reference-id',
                    revision='new-rev')),
            # a symlink now in a deep dir
            ('dir/link', 'old-root/dir/link', 'link-id',
                make_entry('symlink', 'link', 'deep-id', 'link-id',
                   symlink_target='target', revision='new-rev')),
            # a deep dir
            ('dir', 'old-root/dir', 'deep-id',
                make_entry('directory', 'dir', 'TREE_ROOT', 'deep-id',
                    revision='new-rev')),
            # a file with an exec bit set
            (None, 'configure', 'exec-id',
                make_entry('file', 'configure', 'new-root-id', 'exec-id',
                   executable=True, text_size=30, text_sha1='some-sha',
                   revision='old-rev')),
            ]
        serializer = inventory_delta.InventoryDeltaSerializer()
        serializer.require_flags(versioned_root=True, tree_references=True)
        lines = serializer.delta_to_lines(NULL_REVISION, 'something', delta)
        expected = """format: bzr inventory delta v1 (bzr 1.14)
parent: null:
version: something
versioned_root: true
tree_references: true
/\x00/old-root\x00TREE_ROOT\x00new-root-id\x00moved-root\x00dir
/dir\x00/old-root/dir\x00deep-id\x00TREE_ROOT\x00new-rev\x00dir
/dir/link\x00/old-root/dir/link\x00link-id\x00deep-id\x00new-rev\x00link\x00target
/old-file\x00None\x00deleted-id\x00\x00null:\x00deleted\x00\x00
/ref\x00/ref\x00ref-id\x00new-root-id\x00new-rev\x00tree\x00tree-reference-id
/under-old-root\x00/old-root/under-old-root\x00moved-id\x00TREE_ROOT\x00old-rev\x00file\x0030\x00\x00some-sha
None\x00/\x00new-root-id\x00\x00changed-in\x00dir
None\x00/configure\x00exec-id\x00new-root-id\x00old-rev\x00file\x0030\x00Y\x00some-sha
"""
        serialized = ''.join(lines)
        self.assertIsInstance(serialized, str)
        self.assertEqual(expected, serialized)


class TestContent(TestCase):
    """Test serialization of the content part of a line."""

    def test_dir(self):
        entry = inventory.make_entry('directory', 'a dir', None)
        self.assertEqual('dir', inventory_delta._directory_content(entry))

    def test_file_0_short_sha(self):
        file_entry = inventory.make_entry('file', 'a file', None, 'file-id')
        file_entry.text_sha1 = ''
        file_entry.text_size = 0
        self.assertEqual('file\x000\x00\x00',
            inventory_delta._file_content(file_entry))

    def test_file_10_foo(self):
        file_entry = inventory.make_entry('file', 'a file', None, 'file-id')
        file_entry.text_sha1 = 'foo'
        file_entry.text_size = 10
        self.assertEqual('file\x0010\x00\x00foo',
            inventory_delta._file_content(file_entry))

    def test_file_executable(self):
        file_entry = inventory.make_entry('file', 'a file', None, 'file-id')
        file_entry.executable = True
        file_entry.text_sha1 = 'foo'
        file_entry.text_size = 10
        self.assertEqual('file\x0010\x00Y\x00foo',
            inventory_delta._file_content(file_entry))

    def test_file_without_size(self):
        file_entry = inventory.make_entry('file', 'a file', None, 'file-id')
        file_entry.text_sha1 = 'foo'
        self.assertRaises(errors.BzrError,
            inventory_delta._file_content, file_entry)

    def test_file_without_sha1(self):
        file_entry = inventory.make_entry('file', 'a file', None, 'file-id')
        file_entry.text_size = 10
        self.assertRaises(errors.BzrError,
            inventory_delta._file_content, file_entry)

    def test_link_empty_target(self):
        entry = inventory.make_entry('symlink', 'a link', None)
        entry.symlink_target = ''
        self.assertEqual('link\x00',
            inventory_delta._link_content(entry))

    def test_link_unicode_target(self):
        entry = inventory.make_entry('symlink', 'a link', None)
        entry.symlink_target = ' \xc3\xa5'.decode('utf8')
        self.assertEqual('link\x00 \xc3\xa5',
            inventory_delta._link_content(entry))

    def test_link_space_target(self):
        entry = inventory.make_entry('symlink', 'a link', None)
        entry.symlink_target = ' '
        self.assertEqual('link\x00 ',
            inventory_delta._link_content(entry))

    def test_link_no_target(self):
        entry = inventory.make_entry('symlink', 'a link', None)
        self.assertRaises(errors.BzrError,
            inventory_delta._link_content, entry)

    def test_reference_null(self):
        entry = inventory.make_entry('tree-reference', 'a tree', None)
        entry.reference_revision = NULL_REVISION
        self.assertEqual('tree\x00null:',
            inventory_delta._reference_content(entry))

    def test_reference_revision(self):
        entry = inventory.make_entry('tree-reference', 'a tree', None)
        entry.reference_revision = 'foo@\xc3\xa5b-lah'
        self.assertEqual('tree\x00foo@\xc3\xa5b-lah',
            inventory_delta._reference_content(entry))

    def test_reference_no_reference(self):
        entry = inventory.make_entry('tree-reference', 'a tree', None)
        self.assertRaises(errors.BzrError,
            inventory_delta._reference_content, entry)
