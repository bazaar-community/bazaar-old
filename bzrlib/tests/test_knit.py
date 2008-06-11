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

"""Tests for Knit data structure"""

from cStringIO import StringIO
import difflib
import gzip
import sha
import sys

from bzrlib import (
    errors,
    generate_ids,
    knit,
    pack,
    )
from bzrlib.errors import (
    RevisionAlreadyPresent,
    KnitHeaderError,
    RevisionNotPresent,
    NoSuchFile,
    )
from bzrlib.index import *
from bzrlib.knit import (
    AnnotatedKnitContent,
    DATA_SUFFIX,
    INDEX_SUFFIX,
    KnitContent,
    KnitGraphIndex,
    KnitVersionedFile,
    KnitPlainFactory,
    KnitAnnotateFactory,
    _KnitAccess,
    _KnitData,
    _KnitIndex,
    make_file_knit,
    _PackAccess,
    PlainKnitContent,
    _StreamAccess,
    _StreamIndex,
    WeaveToKnit,
    KnitSequenceMatcher,
    )
from bzrlib.osutils import split_lines
from bzrlib.symbol_versioning import one_four
from bzrlib.tests import (
    Feature,
    TestCase,
    TestCaseWithMemoryTransport,
    TestCaseWithTransport,
    )
from bzrlib.transport import get_transport
from bzrlib.transport.memory import MemoryTransport
from bzrlib.tuned_gzip import GzipFile
from bzrlib.util import bencode
from bzrlib.weave import Weave


class _CompiledKnitFeature(Feature):

    def _probe(self):
        try:
            import bzrlib._knit_load_data_c
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._knit_load_data_c'

CompiledKnitFeature = _CompiledKnitFeature()


class KnitContentTestsMixin(object):

    def test_constructor(self):
        content = self._make_content([])

    def test_text(self):
        content = self._make_content([])
        self.assertEqual(content.text(), [])

        content = self._make_content([("origin1", "text1"), ("origin2", "text2")])
        self.assertEqual(content.text(), ["text1", "text2"])

    def test_copy(self):
        content = self._make_content([("origin1", "text1"), ("origin2", "text2")])
        copy = content.copy()
        self.assertIsInstance(copy, content.__class__)
        self.assertEqual(copy.annotate(), content.annotate())

    def assertDerivedBlocksEqual(self, source, target, noeol=False):
        """Assert that the derived matching blocks match real output"""
        source_lines = source.splitlines(True)
        target_lines = target.splitlines(True)
        def nl(line):
            if noeol and not line.endswith('\n'):
                return line + '\n'
            else:
                return line
        source_content = self._make_content([(None, nl(l)) for l in source_lines])
        target_content = self._make_content([(None, nl(l)) for l in target_lines])
        line_delta = source_content.line_delta(target_content)
        delta_blocks = list(KnitContent.get_line_delta_blocks(line_delta,
            source_lines, target_lines))
        matcher = KnitSequenceMatcher(None, source_lines, target_lines)
        matcher_blocks = list(list(matcher.get_matching_blocks()))
        self.assertEqual(matcher_blocks, delta_blocks)

    def test_get_line_delta_blocks(self):
        self.assertDerivedBlocksEqual('a\nb\nc\n', 'q\nc\n')
        self.assertDerivedBlocksEqual(TEXT_1, TEXT_1)
        self.assertDerivedBlocksEqual(TEXT_1, TEXT_1A)
        self.assertDerivedBlocksEqual(TEXT_1, TEXT_1B)
        self.assertDerivedBlocksEqual(TEXT_1B, TEXT_1A)
        self.assertDerivedBlocksEqual(TEXT_1A, TEXT_1B)
        self.assertDerivedBlocksEqual(TEXT_1A, '')
        self.assertDerivedBlocksEqual('', TEXT_1A)
        self.assertDerivedBlocksEqual('', '')
        self.assertDerivedBlocksEqual('a\nb\nc', 'a\nb\nc\nd')

    def test_get_line_delta_blocks_noeol(self):
        """Handle historical knit deltas safely

        Some existing knit deltas don't consider the last line to differ
        when the only difference whether it has a final newline.

        New knit deltas appear to always consider the last line to differ
        in this case.
        """
        self.assertDerivedBlocksEqual('a\nb\nc', 'a\nb\nc\nd\n', noeol=True)
        self.assertDerivedBlocksEqual('a\nb\nc\nd\n', 'a\nb\nc', noeol=True)
        self.assertDerivedBlocksEqual('a\nb\nc\n', 'a\nb\nc', noeol=True)
        self.assertDerivedBlocksEqual('a\nb\nc', 'a\nb\nc\n', noeol=True)


class TestPlainKnitContent(TestCase, KnitContentTestsMixin):

    def _make_content(self, lines):
        annotated_content = AnnotatedKnitContent(lines)
        return PlainKnitContent(annotated_content.text(), 'bogus')

    def test_annotate(self):
        content = self._make_content([])
        self.assertEqual(content.annotate(), [])

        content = self._make_content([("origin1", "text1"), ("origin2", "text2")])
        self.assertEqual(content.annotate(),
            [("bogus", "text1"), ("bogus", "text2")])

    def test_line_delta(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        self.assertEqual(content1.line_delta(content2),
            [(1, 2, 2, ["a", "c"])])

    def test_line_delta_iter(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        it = content1.line_delta_iter(content2)
        self.assertEqual(it.next(), (1, 2, 2, ["a", "c"]))
        self.assertRaises(StopIteration, it.next)


class TestAnnotatedKnitContent(TestCase, KnitContentTestsMixin):

    def _make_content(self, lines):
        return AnnotatedKnitContent(lines)

    def test_annotate(self):
        content = self._make_content([])
        self.assertEqual(content.annotate(), [])

        content = self._make_content([("origin1", "text1"), ("origin2", "text2")])
        self.assertEqual(content.annotate(),
            [("origin1", "text1"), ("origin2", "text2")])

    def test_line_delta(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        self.assertEqual(content1.line_delta(content2),
            [(1, 2, 2, [("", "a"), ("", "c")])])

    def test_line_delta_iter(self):
        content1 = self._make_content([("", "a"), ("", "b")])
        content2 = self._make_content([("", "a"), ("", "a"), ("", "c")])
        it = content1.line_delta_iter(content2)
        self.assertEqual(it.next(), (1, 2, 2, [("", "a"), ("", "c")]))
        self.assertRaises(StopIteration, it.next)


class MockTransport(object):

    def __init__(self, file_lines=None):
        self.file_lines = file_lines
        self.calls = []
        # We have no base directory for the MockTransport
        self.base = ''

    def get(self, filename):
        if self.file_lines is None:
            raise NoSuchFile(filename)
        else:
            return StringIO("\n".join(self.file_lines))

    def readv(self, relpath, offsets):
        fp = self.get(relpath)
        for offset, size in offsets:
            fp.seek(offset)
            yield offset, fp.read(size)

    def __getattr__(self, name):
        def queue_call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return queue_call


class KnitRecordAccessTestsMixin(object):
    """Tests for getting and putting knit records."""

    def assertAccessExists(self, access):
        """Ensure the data area for access has been initialised/exists."""
        raise NotImplementedError(self.assertAccessExists)

    def test_add_raw_records(self):
        """Add_raw_records adds records retrievable later."""
        access = self.get_access()
        memos = access.add_raw_records([10], '1234567890')
        self.assertEqual(['1234567890'], list(access.get_raw_records(memos)))
 
    def test_add_several_raw_records(self):
        """add_raw_records with many records and read some back."""
        access = self.get_access()
        memos = access.add_raw_records([10, 2, 5], '12345678901234567')
        self.assertEqual(['1234567890', '12', '34567'],
            list(access.get_raw_records(memos)))
        self.assertEqual(['1234567890'],
            list(access.get_raw_records(memos[0:1])))
        self.assertEqual(['12'],
            list(access.get_raw_records(memos[1:2])))
        self.assertEqual(['34567'],
            list(access.get_raw_records(memos[2:3])))
        self.assertEqual(['1234567890', '34567'],
            list(access.get_raw_records(memos[0:1] + memos[2:3])))

    def test_create(self):
        """create() should make a file on disk."""
        access = self.get_access()
        access.create()
        self.assertAccessExists(access)

    def test_open_file(self):
        """open_file never errors."""
        access = self.get_access()
        access.open_file()


class TestKnitKnitAccess(TestCaseWithMemoryTransport, KnitRecordAccessTestsMixin):
    """Tests for the .kndx implementation."""

    def assertAccessExists(self, access):
        self.assertNotEqual(None, access.open_file())

    def get_access(self):
        """Get a .knit style access instance."""
        access = _KnitAccess(self.get_transport(), "foo.knit", None, None,
            False, False)
        return access
    

class TestPackKnitAccess(TestCaseWithMemoryTransport, KnitRecordAccessTestsMixin):
    """Tests for the pack based access."""

    def assertAccessExists(self, access):
        # as pack based access has no backing unless an index maps data, this
        # is a no-op.
        pass

    def get_access(self):
        return self._get_access()[0]

    def _get_access(self, packname='packfile', index='FOO'):
        transport = self.get_transport()
        def write_data(bytes):
            transport.append_bytes(packname, bytes)
        writer = pack.ContainerWriter(write_data)
        writer.begin()
        indices = {index:(transport, packname)}
        access = _PackAccess(indices, writer=(writer, index))
        return access, writer

    def test_read_from_several_packs(self):
        access, writer = self._get_access()
        memos = []
        memos.extend(access.add_raw_records([10], '1234567890'))
        writer.end()
        access, writer = self._get_access('pack2', 'FOOBAR')
        memos.extend(access.add_raw_records([5], '12345'))
        writer.end()
        access, writer = self._get_access('pack3', 'BAZ')
        memos.extend(access.add_raw_records([5], 'alpha'))
        writer.end()
        transport = self.get_transport()
        access = _PackAccess({"FOO":(transport, 'packfile'),
            "FOOBAR":(transport, 'pack2'),
            "BAZ":(transport, 'pack3')})
        self.assertEqual(['1234567890', '12345', 'alpha'],
            list(access.get_raw_records(memos)))
        self.assertEqual(['1234567890'],
            list(access.get_raw_records(memos[0:1])))
        self.assertEqual(['12345'],
            list(access.get_raw_records(memos[1:2])))
        self.assertEqual(['alpha'],
            list(access.get_raw_records(memos[2:3])))
        self.assertEqual(['1234567890', 'alpha'],
            list(access.get_raw_records(memos[0:1] + memos[2:3])))

    def test_set_writer(self):
        """The writer should be settable post construction."""
        access = _PackAccess({})
        transport = self.get_transport()
        packname = 'packfile'
        index = 'foo'
        def write_data(bytes):
            transport.append_bytes(packname, bytes)
        writer = pack.ContainerWriter(write_data)
        writer.begin()
        access.set_writer(writer, index, (transport, packname))
        memos = access.add_raw_records([10], '1234567890')
        writer.end()
        self.assertEqual(['1234567890'], list(access.get_raw_records(memos)))


class LowLevelKnitDataTests(TestCase):

    def create_gz_content(self, text):
        sio = StringIO()
        gz_file = gzip.GzipFile(mode='wb', fileobj=sio)
        gz_file.write(text)
        gz_file.close()
        return sio.getvalue()

    def test_valid_knit_data(self):
        sha1sum = sha.new('foo\nbar\n').hexdigest()
        gz_txt = self.create_gz_content('version rev-id-1 2 %s\n'
                                        'foo\n'
                                        'bar\n'
                                        'end rev-id-1\n'
                                        % (sha1sum,))
        transport = MockTransport([gz_txt])
        access = _KnitAccess(transport, 'filename', None, None, False, False)
        data = _KnitData(access=access)
        records = [('rev-id-1', (None, 0, len(gz_txt)))]

        contents = data.read_records(records)
        self.assertEqual({'rev-id-1':(['foo\n', 'bar\n'], sha1sum)}, contents)

        raw_contents = list(data.read_records_iter_raw(records))
        self.assertEqual([('rev-id-1', gz_txt, sha1sum)], raw_contents)

    def test_not_enough_lines(self):
        sha1sum = sha.new('foo\n').hexdigest()
        # record says 2 lines data says 1
        gz_txt = self.create_gz_content('version rev-id-1 2 %s\n'
                                        'foo\n'
                                        'end rev-id-1\n'
                                        % (sha1sum,))
        transport = MockTransport([gz_txt])
        access = _KnitAccess(transport, 'filename', None, None, False, False)
        data = _KnitData(access=access)
        records = [('rev-id-1', (None, 0, len(gz_txt)))]
        self.assertRaises(errors.KnitCorrupt, data.read_records, records)

        # read_records_iter_raw won't detect that sort of mismatch/corruption
        raw_contents = list(data.read_records_iter_raw(records))
        self.assertEqual([('rev-id-1', gz_txt, sha1sum)], raw_contents)

    def test_too_many_lines(self):
        sha1sum = sha.new('foo\nbar\n').hexdigest()
        # record says 1 lines data says 2
        gz_txt = self.create_gz_content('version rev-id-1 1 %s\n'
                                        'foo\n'
                                        'bar\n'
                                        'end rev-id-1\n'
                                        % (sha1sum,))
        transport = MockTransport([gz_txt])
        access = _KnitAccess(transport, 'filename', None, None, False, False)
        data = _KnitData(access=access)
        records = [('rev-id-1', (None, 0, len(gz_txt)))]
        self.assertRaises(errors.KnitCorrupt, data.read_records, records)

        # read_records_iter_raw won't detect that sort of mismatch/corruption
        raw_contents = list(data.read_records_iter_raw(records))
        self.assertEqual([('rev-id-1', gz_txt, sha1sum)], raw_contents)

    def test_mismatched_version_id(self):
        sha1sum = sha.new('foo\nbar\n').hexdigest()
        gz_txt = self.create_gz_content('version rev-id-1 2 %s\n'
                                        'foo\n'
                                        'bar\n'
                                        'end rev-id-1\n'
                                        % (sha1sum,))
        transport = MockTransport([gz_txt])
        access = _KnitAccess(transport, 'filename', None, None, False, False)
        data = _KnitData(access=access)
        # We are asking for rev-id-2, but the data is rev-id-1
        records = [('rev-id-2', (None, 0, len(gz_txt)))]
        self.assertRaises(errors.KnitCorrupt, data.read_records, records)

        # read_records_iter_raw will notice if we request the wrong version.
        self.assertRaises(errors.KnitCorrupt, list,
                          data.read_records_iter_raw(records))

    def test_uncompressed_data(self):
        sha1sum = sha.new('foo\nbar\n').hexdigest()
        txt = ('version rev-id-1 2 %s\n'
               'foo\n'
               'bar\n'
               'end rev-id-1\n'
               % (sha1sum,))
        transport = MockTransport([txt])
        access = _KnitAccess(transport, 'filename', None, None, False, False)
        data = _KnitData(access=access)
        records = [('rev-id-1', (None, 0, len(txt)))]

        # We don't have valid gzip data ==> corrupt
        self.assertRaises(errors.KnitCorrupt, data.read_records, records)

        # read_records_iter_raw will notice the bad data
        self.assertRaises(errors.KnitCorrupt, list,
                          data.read_records_iter_raw(records))

    def test_corrupted_data(self):
        sha1sum = sha.new('foo\nbar\n').hexdigest()
        gz_txt = self.create_gz_content('version rev-id-1 2 %s\n'
                                        'foo\n'
                                        'bar\n'
                                        'end rev-id-1\n'
                                        % (sha1sum,))
        # Change 2 bytes in the middle to \xff
        gz_txt = gz_txt[:10] + '\xff\xff' + gz_txt[12:]
        transport = MockTransport([gz_txt])
        access = _KnitAccess(transport, 'filename', None, None, False, False)
        data = _KnitData(access=access)
        records = [('rev-id-1', (None, 0, len(gz_txt)))]

        self.assertRaises(errors.KnitCorrupt, data.read_records, records)

        # read_records_iter_raw will notice if we request the wrong version.
        self.assertRaises(errors.KnitCorrupt, list,
                          data.read_records_iter_raw(records))


class LowLevelKnitIndexTests(TestCase):

    def get_knit_index(self, *args, **kwargs):
        orig = knit._load_data
        def reset():
            knit._load_data = orig
        self.addCleanup(reset)
        from bzrlib._knit_load_data_py import _load_data_py
        knit._load_data = _load_data_py
        return _KnitIndex(get_scope=lambda:None, *args, **kwargs)

    def test_no_such_file(self):
        transport = MockTransport()

        self.assertRaises(NoSuchFile, self.get_knit_index,
                          transport, "filename", "r")
        self.assertRaises(NoSuchFile, self.get_knit_index,
                          transport, "filename", "w", create=False)

    def test_create_file(self):
        transport = MockTransport()

        index = self.get_knit_index(transport, "filename", "w",
            file_mode="wb", create=True)
        self.assertEqual(
                ("put_bytes_non_atomic",
                    ("filename", index.HEADER), {"mode": "wb"}),
                transport.calls.pop(0))

    def test_delay_create_file(self):
        transport = MockTransport()

        index = self.get_knit_index(transport, "filename", "w",
            create=True, file_mode="wb", create_parent_dir=True,
            delay_create=True, dir_mode=0777)
        self.assertEqual([], transport.calls)

        index.add_versions([])
        name, (filename, f), kwargs = transport.calls.pop(0)
        self.assertEqual("put_file_non_atomic", name)
        self.assertEqual(
            {"dir_mode": 0777, "create_parent_dir": True, "mode": "wb"},
            kwargs)
        self.assertEqual("filename", filename)
        self.assertEqual(index.HEADER, f.read())

        index.add_versions([])
        self.assertEqual(("append_bytes", ("filename", ""), {}),
            transport.calls.pop(0))

    def test_read_utf8_version_id(self):
        unicode_revision_id = u"version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode('utf-8')
        transport = MockTransport([
            _KnitIndex.HEADER,
            '%s option 0 1 :' % (utf8_revision_id,)
            ])
        index = self.get_knit_index(transport, "filename", "r")
        # _KnitIndex is a private class, and deals in utf8 revision_ids, not
        # Unicode revision_ids.
        self.assertTrue(index.has_version(utf8_revision_id))
        self.assertFalse(index.has_version(unicode_revision_id))

    def test_read_utf8_parents(self):
        unicode_revision_id = u"version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode('utf-8')
        transport = MockTransport([
            _KnitIndex.HEADER,
            "version option 0 1 .%s :" % (utf8_revision_id,)
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual((utf8_revision_id,),
            index.get_parents_with_ghosts("version"))

    def test_read_ignore_corrupted_lines(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "corrupted",
            "corrupted options 0 1 .b .c ",
            "version options 0 1 :"
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(1, index.num_versions())
        self.assertTrue(index.has_version("version"))

    def test_read_corrupted_header(self):
        transport = MockTransport(['not a bzr knit index header\n'])
        self.assertRaises(KnitHeaderError,
            self.get_knit_index, transport, "filename", "r")

    def test_read_duplicate_entries(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "parent options 0 1 :",
            "version options1 0 1 0 :",
            "version options2 1 2 .other :",
            "version options3 3 4 0 .other :"
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(2, index.num_versions())
        # check that the index used is the first one written. (Specific
        # to KnitIndex style indices.
        self.assertEqual("1", index._version_list_to_index(["version"]))
        self.assertEqual((None, 3, 4), index.get_position("version"))
        self.assertEqual(["options3"], index.get_options("version"))
        self.assertEqual(("parent", "other"),
            index.get_parents_with_ghosts("version"))

    def test_read_compressed_parents(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 0 :",
            "c option 0 1 1 0 :",
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual({"b":("a",), "c":("b", "a")},
            index.get_parent_map(["b", "c"]))

    def test_write_utf8_version_id(self):
        unicode_revision_id = u"version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode('utf-8')
        transport = MockTransport([
            _KnitIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")
        index.add_version(utf8_revision_id, ["option"], (None, 0, 1), [])
        self.assertEqual(("append_bytes", ("filename",
            "\n%s option 0 1  :" % (utf8_revision_id,)),
            {}),
            transport.calls.pop(0))

    def test_write_utf8_parents(self):
        unicode_revision_id = u"version-\N{CYRILLIC CAPITAL LETTER A}"
        utf8_revision_id = unicode_revision_id.encode('utf-8')
        transport = MockTransport([
            _KnitIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")
        index.add_version("version", ["option"], (None, 0, 1), [utf8_revision_id])
        self.assertEqual(("append_bytes", ("filename",
            "\nversion option 0 1 .%s :" % (utf8_revision_id,)),
            {}),
            transport.calls.pop(0))

    def test_get_ancestry(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 0 .e :",
            "c option 0 1 1 0 :",
            "d option 0 1 2 .f :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual([], index.get_ancestry([]))
        self.assertEqual(["a"], index.get_ancestry(["a"]))
        self.assertEqual(["a", "b"], index.get_ancestry(["b"]))
        self.assertEqual(["a", "b", "c"], index.get_ancestry(["c"]))
        self.assertEqual(["a", "b", "c", "d"], index.get_ancestry(["d"]))
        self.assertEqual(["a", "b"], index.get_ancestry(["a", "b"]))
        self.assertEqual(["a", "b", "c"], index.get_ancestry(["a", "c"]))

        self.assertRaises(RevisionNotPresent, index.get_ancestry, ["e"])

    def test_get_ancestry_with_ghosts(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 0 .e :",
            "c option 0 1 0 .f .g :",
            "d option 0 1 2 .h .j .k :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual([], index.get_ancestry_with_ghosts([]))
        self.assertEqual(["a"], index.get_ancestry_with_ghosts(["a"]))
        self.assertEqual(["a", "e", "b"],
            index.get_ancestry_with_ghosts(["b"]))
        self.assertEqual(["a", "g", "f", "c"],
            index.get_ancestry_with_ghosts(["c"]))
        self.assertEqual(["a", "g", "f", "c", "k", "j", "h", "d"],
            index.get_ancestry_with_ghosts(["d"]))
        self.assertEqual(["a", "e", "b"],
            index.get_ancestry_with_ghosts(["a", "b"]))
        self.assertEqual(["a", "g", "f", "c"],
            index.get_ancestry_with_ghosts(["a", "c"]))
        self.assertEqual(
            ["a", "g", "f", "c", "e", "b", "k", "j", "h", "d"],
            index.get_ancestry_with_ghosts(["b", "d"]))

        self.assertRaises(RevisionNotPresent,
            index.get_ancestry_with_ghosts, ["e"])

    def test_num_versions(self):
        transport = MockTransport([
            _KnitIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual(0, index.num_versions())
        self.assertEqual(0, len(index))

        index.add_version("a", ["option"], (None, 0, 1), [])
        self.assertEqual(1, index.num_versions())
        self.assertEqual(1, len(index))

        index.add_version("a", ["option2"], (None, 1, 2), [])
        self.assertEqual(1, index.num_versions())
        self.assertEqual(1, len(index))

        index.add_version("b", ["option"], (None, 0, 1), [])
        self.assertEqual(2, index.num_versions())
        self.assertEqual(2, len(index))

    def test_get_versions(self):
        transport = MockTransport([
            _KnitIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual([], index.get_versions())

        index.add_version("a", ["option"], (None, 0, 1), [])
        self.assertEqual(["a"], index.get_versions())

        index.add_version("a", ["option"], (None, 0, 1), [])
        self.assertEqual(["a"], index.get_versions())

        index.add_version("b", ["option"], (None, 0, 1), [])
        self.assertEqual(["a", "b"], index.get_versions())

    def test_add_version(self):
        transport = MockTransport([
            _KnitIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")

        index.add_version("a", ["option"], (None, 0, 1), ["b"])
        self.assertEqual(("append_bytes",
            ("filename", "\na option 0 1 .b :"),
            {}), transport.calls.pop(0))
        self.assertTrue(index.has_version("a"))
        self.assertEqual(1, index.num_versions())
        self.assertEqual((None, 0, 1), index.get_position("a"))
        self.assertEqual(["option"], index.get_options("a"))
        self.assertEqual(("b",), index.get_parents_with_ghosts("a"))

        index.add_version("a", ["opt"], (None, 1, 2), ["c"])
        self.assertEqual(("append_bytes",
            ("filename", "\na opt 1 2 .c :"),
            {}), transport.calls.pop(0))
        self.assertTrue(index.has_version("a"))
        self.assertEqual(1, index.num_versions())
        self.assertEqual((None, 1, 2), index.get_position("a"))
        self.assertEqual(["opt"], index.get_options("a"))
        self.assertEqual(("c",), index.get_parents_with_ghosts("a"))

        index.add_version("b", ["option"], (None, 2, 3), ["a"])
        self.assertEqual(("append_bytes",
            ("filename", "\nb option 2 3 0 :"),
            {}), transport.calls.pop(0))
        self.assertTrue(index.has_version("b"))
        self.assertEqual(2, index.num_versions())
        self.assertEqual((None, 2, 3), index.get_position("b"))
        self.assertEqual(["option"], index.get_options("b"))
        self.assertEqual(("a",), index.get_parents_with_ghosts("b"))

    def test_add_versions(self):
        transport = MockTransport([
            _KnitIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")

        index.add_versions([
            ("a", ["option"], (None, 0, 1), ["b"]),
            ("a", ["opt"], (None, 1, 2), ["c"]),
            ("b", ["option"], (None, 2, 3), ["a"])
            ])
        self.assertEqual(("append_bytes", ("filename",
            "\na option 0 1 .b :"
            "\na opt 1 2 .c :"
            "\nb option 2 3 0 :"
            ), {}), transport.calls.pop(0))
        self.assertTrue(index.has_version("a"))
        self.assertTrue(index.has_version("b"))
        self.assertEqual(2, index.num_versions())
        self.assertEqual((None, 1, 2), index.get_position("a"))
        self.assertEqual((None, 2, 3), index.get_position("b"))
        self.assertEqual(["opt"], index.get_options("a"))
        self.assertEqual(["option"], index.get_options("b"))
        self.assertEqual(("c",), index.get_parents_with_ghosts("a"))
        self.assertEqual(("a",), index.get_parents_with_ghosts("b"))

    def test_add_versions_random_id_is_accepted(self):
        transport = MockTransport([
            _KnitIndex.HEADER
            ])
        index = self.get_knit_index(transport, "filename", "r")

        index.add_versions([
            ("a", ["option"], (None, 0, 1), ["b"]),
            ("a", ["opt"], (None, 1, 2), ["c"]),
            ("b", ["option"], (None, 2, 3), ["a"])
            ], random_id=True)

    def test_delay_create_and_add_versions(self):
        transport = MockTransport()

        index = self.get_knit_index(transport, "filename", "w",
            create=True, file_mode="wb", create_parent_dir=True,
            delay_create=True, dir_mode=0777)
        self.assertEqual([], transport.calls)

        index.add_versions([
            ("a", ["option"], (None, 0, 1), ["b"]),
            ("a", ["opt"], (None, 1, 2), ["c"]),
            ("b", ["option"], (None, 2, 3), ["a"])
            ])
        name, (filename, f), kwargs = transport.calls.pop(0)
        self.assertEqual("put_file_non_atomic", name)
        self.assertEqual(
            {"dir_mode": 0777, "create_parent_dir": True, "mode": "wb"},
            kwargs)
        self.assertEqual("filename", filename)
        self.assertEqual(
            index.HEADER +
            "\na option 0 1 .b :"
            "\na opt 1 2 .c :"
            "\nb option 2 3 0 :",
            f.read())

    def test_has_version(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertTrue(index.has_version("a"))
        self.assertFalse(index.has_version("b"))

    def test_get_position(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :",
            "b option 1 2 :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual((None, 0, 1), index.get_position("a"))
        self.assertEqual((None, 1, 2), index.get_position("b"))

    def test_get_method(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a fulltext,unknown 0 1 :",
            "b unknown,line-delta 1 2 :",
            "c bad 3 4 :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual("fulltext", index.get_method("a"))
        self.assertEqual("line-delta", index.get_method("b"))
        self.assertRaises(errors.KnitIndexUnknownMethod, index.get_method, "c")

    def test_get_options(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a opt1 0 1 :",
            "b opt2,opt3 1 2 :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual(["opt1"], index.get_options("a"))
        self.assertEqual(["opt2", "opt3"], index.get_options("b"))

    def test_get_parent_map(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :",
            "b option 1 2 0 .c :",
            "c option 1 2 1 0 .e :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual({
            "a":(),
            "b":("a", "c"),
            "c":("b", "a", "e"),
            }, index.get_parent_map(["a", "b", "c"]))

    def test_get_parents_with_ghosts(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :",
            "b option 1 2 0 .c :",
            "c option 1 2 1 0 .e :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        self.assertEqual((), index.get_parents_with_ghosts("a"))
        self.assertEqual(("a", "c"), index.get_parents_with_ghosts("b"))
        self.assertEqual(("b", "a", "e"),
            index.get_parents_with_ghosts("c"))

    def test_check_versions_present(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 :"
            ])
        index = self.get_knit_index(transport, "filename", "r")

        check = index.check_versions_present

        check([])
        check(["a"])
        check(["b"])
        check(["a", "b"])
        self.assertRaises(RevisionNotPresent, check, ["c"])
        self.assertRaises(RevisionNotPresent, check, ["a", "b", "c"])

    def test_impossible_parent(self):
        """Test we get KnitCorrupt if the parent couldn't possibly exist."""
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 4 :"  # We don't have a 4th record
            ])
        try:
            self.assertRaises(errors.KnitCorrupt,
                              self.get_knit_index, transport, 'filename', 'r')
        except TypeError, e:
            if (str(e) == ('exceptions must be strings, classes, or instances,'
                           ' not exceptions.IndexError')
                and sys.version_info[0:2] >= (2,5)):
                self.knownFailure('Pyrex <0.9.5 fails with TypeError when'
                                  ' raising new style exceptions with python'
                                  ' >=2.5')
            else:
                raise

    def test_corrupted_parent(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 :",
            "c option 0 1 1v :", # Can't have a parent of '1v'
            ])
        try:
            self.assertRaises(errors.KnitCorrupt,
                              self.get_knit_index, transport, 'filename', 'r')
        except TypeError, e:
            if (str(e) == ('exceptions must be strings, classes, or instances,'
                           ' not exceptions.ValueError')
                and sys.version_info[0:2] >= (2,5)):
                self.knownFailure('Pyrex <0.9.5 fails with TypeError when'
                                  ' raising new style exceptions with python'
                                  ' >=2.5')
            else:
                raise

    def test_corrupted_parent_in_list(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 1 :",
            "b option 0 1 :",
            "c option 0 1 1 v :", # Can't have a parent of 'v'
            ])
        try:
            self.assertRaises(errors.KnitCorrupt,
                              self.get_knit_index, transport, 'filename', 'r')
        except TypeError, e:
            if (str(e) == ('exceptions must be strings, classes, or instances,'
                           ' not exceptions.ValueError')
                and sys.version_info[0:2] >= (2,5)):
                self.knownFailure('Pyrex <0.9.5 fails with TypeError when'
                                  ' raising new style exceptions with python'
                                  ' >=2.5')
            else:
                raise

    def test_invalid_position(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 1v 1 :",
            ])
        try:
            self.assertRaises(errors.KnitCorrupt,
                              self.get_knit_index, transport, 'filename', 'r')
        except TypeError, e:
            if (str(e) == ('exceptions must be strings, classes, or instances,'
                           ' not exceptions.ValueError')
                and sys.version_info[0:2] >= (2,5)):
                self.knownFailure('Pyrex <0.9.5 fails with TypeError when'
                                  ' raising new style exceptions with python'
                                  ' >=2.5')
            else:
                raise

    def test_invalid_size(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 1 1v :",
            ])
        try:
            self.assertRaises(errors.KnitCorrupt,
                              self.get_knit_index, transport, 'filename', 'r')
        except TypeError, e:
            if (str(e) == ('exceptions must be strings, classes, or instances,'
                           ' not exceptions.ValueError')
                and sys.version_info[0:2] >= (2,5)):
                self.knownFailure('Pyrex <0.9.5 fails with TypeError when'
                                  ' raising new style exceptions with python'
                                  ' >=2.5')
            else:
                raise

    def test_short_line(self):
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 10  :",
            "b option 10 10 0", # This line isn't terminated, ignored
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(['a'], index.get_versions())

    def test_skip_incomplete_record(self):
        # A line with bogus data should just be skipped
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 10  :",
            "b option 10 10 0", # This line isn't terminated, ignored
            "c option 20 10 0 :", # Properly terminated, and starts with '\n'
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(['a', 'c'], index.get_versions())

    def test_trailing_characters(self):
        # A line with bogus data should just be skipped
        transport = MockTransport([
            _KnitIndex.HEADER,
            "a option 0 10  :",
            "b option 10 10 0 :a", # This line has extra trailing characters
            "c option 20 10 0 :", # Properly terminated, and starts with '\n'
            ])
        index = self.get_knit_index(transport, "filename", "r")
        self.assertEqual(['a', 'c'], index.get_versions())


class LowLevelKnitIndexTests_c(LowLevelKnitIndexTests):

    _test_needs_features = [CompiledKnitFeature]

    def get_knit_index(self, *args, **kwargs):
        orig = knit._load_data
        def reset():
            knit._load_data = orig
        self.addCleanup(reset)
        from bzrlib._knit_load_data_c import _load_data_c
        knit._load_data = _load_data_c
        return _KnitIndex(get_scope=lambda:None, *args, **kwargs)


class KnitTests(TestCaseWithTransport):
    """Class containing knit test helper routines."""

    def make_test_knit(self, annotate=False, delay_create=False, index=None,
                       name='test', delta=True, access_mode='w'):
        if not annotate:
            factory = KnitPlainFactory()
        else:
            factory = None
        if index is None:
            index = _KnitIndex(get_transport('.'), name + INDEX_SUFFIX,
                access_mode, create=True, file_mode=None,
                create_parent_dir=False, delay_create=delay_create,
                dir_mode=None, get_scope=lambda:None)
        access = _KnitAccess(get_transport('.'), name + DATA_SUFFIX, None,
            None, delay_create, False)
        return KnitVersionedFile(name, get_transport('.'), factory=factory,
            create=True, delay_create=delay_create, index=index,
            access_method=access, delta=delta)

    def assertRecordContentEqual(self, knit, version_id, candidate_content):
        """Assert that some raw record content matches the raw record content
        for a particular version_id in the given knit.
        """
        index_memo = knit._index.get_position(version_id)
        record = (version_id, index_memo)
        [(_, expected_content, _)] = list(knit._data.read_records_iter_raw([record]))
        self.assertEqual(expected_content, candidate_content)


class BasicKnitTests(KnitTests):

    def add_stock_one_and_one_a(self, k):
        k.add_lines('text-1', [], split_lines(TEXT_1))
        k.add_lines('text-1a', ['text-1'], split_lines(TEXT_1A))

    def test_knit_constructor(self):
        """Construct empty k"""
        self.make_test_knit()

    def test_make_explicit_index(self):
        """We can supply an index to use."""
        knit = KnitVersionedFile('test', get_transport('.'),
            index='strangelove', access_method="a")
        self.assertEqual(knit._index, 'strangelove')

    def test_knit_add(self):
        """Store one text in knit and retrieve"""
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        self.assertTrue(k.has_version('text-1'))
        self.assertEqualDiff(''.join(k.get_lines('text-1')), TEXT_1)

    def test_newline_empty_lines(self):
        # ensure that ["\n"] round trips ok.
        knit = self.make_test_knit()
        knit.add_lines('a', [], ["\n"])
        knit.add_lines_with_ghosts('b', [], ["\n"])
        self.assertEqual(["\n"], knit.get_lines('a'))
        self.assertEqual(["\n"], knit.get_lines('b'))
        self.assertEqual(['fulltext'], knit._index.get_options('a'))
        self.assertEqual(['fulltext'], knit._index.get_options('b'))
        knit.add_lines('c', ['a'], ["\n"])
        knit.add_lines_with_ghosts('d', ['b'], ["\n"])
        self.assertEqual(["\n"], knit.get_lines('c'))
        self.assertEqual(["\n"], knit.get_lines('d'))
        self.assertEqual(['line-delta'], knit._index.get_options('c'))
        self.assertEqual(['line-delta'], knit._index.get_options('d'))

    def test_empty_lines(self):
        # bizarrely, [] is not listed as having no-eol. 
        knit = self.make_test_knit()
        knit.add_lines('a', [], [])
        knit.add_lines_with_ghosts('b', [], [])
        self.assertEqual([], knit.get_lines('a'))
        self.assertEqual([], knit.get_lines('b'))
        self.assertEqual(['fulltext'], knit._index.get_options('a'))
        self.assertEqual(['fulltext'], knit._index.get_options('b'))
        knit.add_lines('c', ['a'], [])
        knit.add_lines_with_ghosts('d', ['b'], [])
        self.assertEqual([], knit.get_lines('c'))
        self.assertEqual([], knit.get_lines('d'))
        self.assertEqual(['line-delta'], knit._index.get_options('c'))
        self.assertEqual(['line-delta'], knit._index.get_options('d'))

    def test_knit_reload(self):
        # test that the content in a reloaded knit is correct
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        del k
        k2 = make_file_knit('test', get_transport('.'), access_mode='r',
            factory=KnitPlainFactory(), create=True)
        self.assertTrue(k2.has_version('text-1'))
        self.assertEqualDiff(''.join(k2.get_lines('text-1')), TEXT_1)

    def test_knit_several(self):
        """Store several texts in a knit"""
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        k.add_lines('text-2', [], split_lines(TEXT_2))
        self.assertEqualDiff(''.join(k.get_lines('text-1')), TEXT_1)
        self.assertEqualDiff(''.join(k.get_lines('text-2')), TEXT_2)
        
    def test_repeated_add(self):
        """Knit traps attempt to replace existing version"""
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        self.assertRaises(RevisionAlreadyPresent, 
                k.add_lines,
                'text-1', [], split_lines(TEXT_1))

    def test_empty(self):
        k = self.make_test_knit(True)
        k.add_lines('text-1', [], [])
        self.assertEquals(k.get_lines('text-1'), [])

    def test_incomplete(self):
        """Test if texts without a ending line-end can be inserted and
        extracted."""
        k = make_file_knit('test', get_transport('.'), delta=False, create=True)
        k.add_lines('text-1', [], ['a\n',    'b'  ])
        k.add_lines('text-2', ['text-1'], ['a\rb\n', 'b\n'])
        # reopening ensures maximum room for confusion
        k = make_file_knit('test', get_transport('.'), delta=False, create=True)
        self.assertEquals(k.get_lines('text-1'), ['a\n',    'b'  ])
        self.assertEquals(k.get_lines('text-2'), ['a\rb\n', 'b\n'])

    def test_delta(self):
        """Expression of knit delta as lines"""
        k = self.make_test_knit()
        td = list(line_delta(TEXT_1.splitlines(True),
                             TEXT_1A.splitlines(True)))
        self.assertEqualDiff(''.join(td), delta_1_1a)
        out = apply_line_delta(TEXT_1.splitlines(True), td)
        self.assertEqualDiff(''.join(out), TEXT_1A)

    def test_add_with_parents(self):
        """Store in knit with parents"""
        k = self.make_test_knit()
        self.add_stock_one_and_one_a(k)
        self.assertEqual({'text-1':(), 'text-1a':('text-1',)},
            k.get_parent_map(['text-1', 'text-1a']))

    def test_ancestry(self):
        """Store in knit with parents"""
        k = self.make_test_knit()
        self.add_stock_one_and_one_a(k)
        self.assertEquals(set(k.get_ancestry(['text-1a'])), set(['text-1a', 'text-1']))

    def test_add_delta(self):
        """Store in knit with parents"""
        k = self.make_test_knit(annotate=False)
        self.add_stock_one_and_one_a(k)
        self.assertEqualDiff(''.join(k.get_lines('text-1a')), TEXT_1A)

    def test_add_delta_knit_graph_index(self):
        """Does adding work with a KnitGraphIndex."""
        index = InMemoryGraphIndex(2)
        knit_index = KnitGraphIndex(index, add_callback=index.add_nodes,
            deltas=True)
        k = self.make_test_knit(annotate=True, index=knit_index)
        self.add_stock_one_and_one_a(k)
        self.assertEqualDiff(''.join(k.get_lines('text-1a')), TEXT_1A)
        # check the index had the right data added.
        self.assertEqual(set([
            (index, ('text-1', ), ' 0 127', ((), ())),
            (index, ('text-1a', ), ' 127 140', ((('text-1', ),), (('text-1', ),))),
            ]), set(index.iter_all_entries()))
        # we should not have a .kndx file
        self.assertFalse(get_transport('.').has('test.kndx'))

    def test_annotate(self):
        """Annotations"""
        k = self.make_test_knit(annotate=True, name='knit')
        self.insert_and_test_small_annotate(k)

    def insert_and_test_small_annotate(self, k):
        """test annotation with k works correctly."""
        k.add_lines('text-1', [], ['a\n', 'b\n'])
        k.add_lines('text-2', ['text-1'], ['a\n', 'c\n'])

        origins = k.annotate('text-2')
        self.assertEquals(origins[0], ('text-1', 'a\n'))
        self.assertEquals(origins[1], ('text-2', 'c\n'))

    def test_annotate_fulltext(self):
        """Annotations"""
        k = self.make_test_knit(annotate=True, name='knit', delta=False)
        self.insert_and_test_small_annotate(k)

    def test_annotate_merge_1(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n'])
        k.add_lines('text-a2', [], ['d\n', 'c\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['d\n', 'b\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a2', 'd\n'))
        self.assertEquals(origins[1], ('text-a1', 'b\n'))

    def test_annotate_merge_2(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['a\n', 'y\n', 'c\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a1', 'a\n'))
        self.assertEquals(origins[1], ('text-a2', 'y\n'))
        self.assertEquals(origins[2], ('text-a1', 'c\n'))

    def test_annotate_merge_9(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['k\n', 'y\n', 'c\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-am', 'k\n'))
        self.assertEquals(origins[1], ('text-a2', 'y\n'))
        self.assertEquals(origins[2], ('text-a1', 'c\n'))

    def test_annotate_merge_3(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [] ,['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['k\n', 'y\n', 'z\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-am', 'k\n'))
        self.assertEquals(origins[1], ('text-a2', 'y\n'))
        self.assertEquals(origins[2], ('text-a2', 'z\n'))

    def test_annotate_merge_4(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-a3', ['text-a1'], ['a\n', 'b\n', 'p\n'])
        k.add_lines('text-am', ['text-a2', 'text-a3'], ['a\n', 'b\n', 'z\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a1', 'a\n'))
        self.assertEquals(origins[1], ('text-a1', 'b\n'))
        self.assertEquals(origins[2], ('text-a2', 'z\n'))

    def test_annotate_merge_5(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['d\n', 'e\n', 'f\n'])
        k.add_lines('text-a3', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am',
                    ['text-a1', 'text-a2', 'text-a3'],
                    ['a\n', 'e\n', 'z\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a1', 'a\n'))
        self.assertEquals(origins[1], ('text-a2', 'e\n'))
        self.assertEquals(origins[2], ('text-a3', 'z\n'))

    def test_annotate_file_cherry_pick(self):
        k = self.make_test_knit(True)
        k.add_lines('text-1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-2', ['text-1'], ['d\n', 'e\n', 'f\n'])
        k.add_lines('text-3', ['text-2', 'text-1'], ['a\n', 'b\n', 'c\n'])
        origins = k.annotate('text-3')
        self.assertEquals(origins[0], ('text-1', 'a\n'))
        self.assertEquals(origins[1], ('text-1', 'b\n'))
        self.assertEquals(origins[2], ('text-1', 'c\n'))

    def test_reannotate(self):
        k1 = make_file_knit('knit1', get_transport('.'),
                               factory=KnitAnnotateFactory(), create=True)
        # 0
        k1.add_lines('text-a', [], ['a\n', 'b\n'])
        # 1
        k1.add_lines('text-b', ['text-a'], ['a\n', 'c\n'])

        k2 = make_file_knit('test2', get_transport('.'),
                               factory=KnitAnnotateFactory(), create=True)
        k2.insert_record_stream(k1.get_record_stream(k1.versions(),
            'unordered', False))

        # 2
        k1.add_lines('text-X', ['text-b'], ['a\n', 'b\n'])
        # 2
        k2.add_lines('text-c', ['text-b'], ['z\n', 'c\n'])
        # 3
        k2.add_lines('text-Y', ['text-b'], ['b\n', 'c\n'])

        # test-c will have index 3
        k1.insert_record_stream(k2.get_record_stream(['text-c'],
            'unordered', False))

        lines = k1.get_lines('text-c')
        self.assertEquals(lines, ['z\n', 'c\n'])

        origins = k1.annotate('text-c')
        self.assertEquals(origins[0], ('text-c', 'z\n'))
        self.assertEquals(origins[1], ('text-b', 'c\n'))

    def test_get_line_delta_texts(self):
        """Make sure we can call get_texts on text with reused line deltas"""
        k1 = make_file_knit('test1', get_transport('.'),
            factory=KnitPlainFactory(), create=True)
        for t in range(3):
            if t == 0:
                parents = []
            else:
                parents = ['%d' % (t-1)]
            k1.add_lines('%d' % t, parents, ['hello\n'] * t)
        k1.get_texts(('%d' % t) for t in range(3))
        
    def test_iter_lines_reads_in_order(self):
        instrumented_t = get_transport('trace+memory:///')
        k1 = make_file_knit('id', instrumented_t, create=True, delta=True)
        self.assertEqual([('get', 'id.kndx',)], instrumented_t._activity)
        # add texts with no required ordering
        k1.add_lines('base', [], ['text\n'])
        k1.add_lines('base2', [], ['text2\n'])
        # clear the logged activity, but preserve the list instance in case of
        # clones pointing at it.
        del instrumented_t._activity[:]
        # request a last-first iteration
        results = list(k1.iter_lines_added_or_present_in_versions(
            ['base2', 'base']))
        self.assertEqual(
            [('readv', 'id.knit', [(0, 87), (87, 89)], False, None)],
            instrumented_t._activity)
        self.assertEqual([('text\n', 'base'), ('text2\n', 'base2')], results)

    def test_knit_format(self):
        # this tests that a new knit index file has the expected content
        # and that is writes the data we expect as records are added.
        knit = self.make_test_knit(True)
        # Now knit files are not created until we first add data to them
        self.assertFileEqual("# bzr knit index 8\n", 'test.kndx')
        knit.add_lines_with_ghosts('revid', ['a_ghost'], ['a\n'])
        self.assertFileEqual(
            "# bzr knit index 8\n"
            "\n"
            "revid fulltext 0 84 .a_ghost :",
            'test.kndx')
        knit.add_lines_with_ghosts('revid2', ['revid'], ['a\n'])
        self.assertFileEqual(
            "# bzr knit index 8\n"
            "\nrevid fulltext 0 84 .a_ghost :"
            "\nrevid2 line-delta 84 82 0 :",
            'test.kndx')
        # we should be able to load this file again
        knit = make_file_knit('test', get_transport('.'), access_mode='r')
        self.assertEqual(['revid', 'revid2'], knit.versions())
        # write a short write to the file and ensure that its ignored
        indexfile = file('test.kndx', 'ab')
        indexfile.write('\nrevid3 line-delta 166 82 1 2 3 4 5 .phwoar:demo ')
        indexfile.close()
        # we should be able to load this file again
        knit = make_file_knit('test', get_transport('.'), access_mode='w')
        self.assertEqual(['revid', 'revid2'], knit.versions())
        # and add a revision with the same id the failed write had
        knit.add_lines('revid3', ['revid2'], ['a\n'])
        # and when reading it revid3 should now appear.
        knit = make_file_knit('test', get_transport('.'), access_mode='r')
        self.assertEqual(['revid', 'revid2', 'revid3'], knit.versions())
        self.assertEqual({'revid3':('revid2',)}, knit.get_parent_map(['revid3']))

    def test_delay_create(self):
        """Test that passing delay_create=True creates files late"""
        knit = self.make_test_knit(annotate=True, delay_create=True)
        self.failIfExists('test.knit')
        self.failIfExists('test.kndx')
        knit.add_lines_with_ghosts('revid', ['a_ghost'], ['a\n'])
        self.failUnlessExists('test.knit')
        self.assertFileEqual(
            "# bzr knit index 8\n"
            "\n"
            "revid fulltext 0 84 .a_ghost :",
            'test.kndx')

    def test_create_parent_dir(self):
        """create_parent_dir can create knits in nonexistant dirs"""
        # Has no effect if we don't set 'delay_create'
        trans = get_transport('.')
        self.assertRaises(NoSuchFile, make_file_knit, 'dir/test',
                          trans, access_mode='w', factory=None,
                          create=True, create_parent_dir=True)
        # Nothing should have changed yet
        knit = make_file_knit('dir/test', trans, access_mode='w',
                                 factory=None, create=True,
                                 create_parent_dir=True,
                                 delay_create=True)
        self.failIfExists('dir/test.knit')
        self.failIfExists('dir/test.kndx')
        self.failIfExists('dir')
        knit.add_lines('revid', [], ['a\n'])
        self.failUnlessExists('dir')
        self.failUnlessExists('dir/test.knit')
        self.assertFileEqual(
            "# bzr knit index 8\n"
            "\n"
            "revid fulltext 0 84  :",
            'dir/test.kndx')

    def test_create_mode_700(self):
        trans = get_transport('.')
        if not trans._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        knit = make_file_knit('dir/test', trans, access_mode='w', factory=None,
            create=True, create_parent_dir=True, delay_create=True,
            file_mode=0600, dir_mode=0700)
        knit.add_lines('revid', [], ['a\n'])
        self.assertTransportMode(trans, 'dir', 0700)
        self.assertTransportMode(trans, 'dir/test.knit', 0600)
        self.assertTransportMode(trans, 'dir/test.kndx', 0600)

    def test_create_mode_770(self):
        trans = get_transport('.')
        if not trans._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        knit = make_file_knit('dir/test', trans, access_mode='w', factory=None,
            create=True, create_parent_dir=True, delay_create=True,
            file_mode=0660, dir_mode=0770)
        knit.add_lines('revid', [], ['a\n'])
        self.assertTransportMode(trans, 'dir', 0770)
        self.assertTransportMode(trans, 'dir/test.knit', 0660)
        self.assertTransportMode(trans, 'dir/test.kndx', 0660)

    def test_create_mode_777(self):
        trans = get_transport('.')
        if not trans._can_roundtrip_unix_modebits():
            # Can't roundtrip, so no need to run this test
            return
        knit = make_file_knit('dir/test', trans, access_mode='w', factory=None,
            create=True, create_parent_dir=True, delay_create=True,
            file_mode=0666, dir_mode=0777)
        knit.add_lines('revid', [], ['a\n'])
        self.assertTransportMode(trans, 'dir', 0777)
        self.assertTransportMode(trans, 'dir/test.knit', 0666)
        self.assertTransportMode(trans, 'dir/test.kndx', 0666)

    def test_plan_merge(self):
        my_knit = self.make_test_knit(annotate=True)
        my_knit.add_lines('text1', [], split_lines(TEXT_1))
        my_knit.add_lines('text1a', ['text1'], split_lines(TEXT_1A))
        my_knit.add_lines('text1b', ['text1'], split_lines(TEXT_1B))
        plan = list(my_knit.plan_merge('text1a', 'text1b'))
        for plan_line, expected_line in zip(plan, AB_MERGE):
            self.assertEqual(plan_line, expected_line)


class GetDataStreamTests(KnitTests):
    """Tests for get_data_stream."""

    def test_get_stream_empty(self):
        """Get a data stream for an empty knit file."""
        k1 = self.make_test_knit()
        format, data_list, reader_callable = k1.get_data_stream([])
        self.assertEqual('knit-plain', format)
        self.assertEqual([], data_list)
        content = reader_callable(None)
        self.assertEqual('', content)
        self.assertIsInstance(content, str)

    def test_get_stream_one_version(self):
        """Get a data stream for a single record out of a knit containing just
        one record.
        """
        k1 = self.make_test_knit()
        test_data = [
            ('text-a', [], TEXT_1),
            ]
        expected_data_list = [
            # version, options, length, parents
            ('text-a', ['fulltext'], 122, ()),
           ]
        for version_id, parents, lines in test_data:
            k1.add_lines(version_id, parents, split_lines(lines))

        format, data_list, reader_callable = k1.get_data_stream(['text-a'])
        self.assertEqual('knit-plain', format)
        self.assertEqual(expected_data_list, data_list)
        # There's only one record in the knit, so the content should be the
        # entire knit data file's contents.
        self.assertEqual(k1.transport.get_bytes(k1._data._access._filename),
                         reader_callable(None))
        
    def test_get_stream_get_one_version_of_many(self):
        """Get a data stream for just one version out of a knit containing many
        versions.
        """
        k1 = self.make_test_knit()
        # Insert the same data as test_knit_join, as they seem to cover a range
        # of cases (no parents, one parent, multiple parents).
        test_data = [
            ('text-a', [], TEXT_1),
            ('text-b', ['text-a'], TEXT_1),
            ('text-c', [], TEXT_1),
            ('text-d', ['text-c'], TEXT_1),
            ('text-m', ['text-b', 'text-d'], TEXT_1),
            ]
        expected_data_list = [
            # version, options, length, parents
            ('text-m', ['line-delta'], 84, ('text-b', 'text-d')),
            ]
        for version_id, parents, lines in test_data:
            k1.add_lines(version_id, parents, split_lines(lines))

        format, data_list, reader_callable = k1.get_data_stream(['text-m'])
        self.assertEqual('knit-plain', format)
        self.assertEqual(expected_data_list, data_list)
        self.assertRecordContentEqual(k1, 'text-m', reader_callable(None))
        
    def test_get_data_stream_unordered_index(self):
        """Get a data stream when the knit index reports versions out of order.

        https://bugs.launchpad.net/bzr/+bug/164637
        """
        k1 = self.make_test_knit()
        test_data = [
            ('text-a', [], TEXT_1),
            ('text-b', ['text-a'], TEXT_1),
            ('text-c', [], TEXT_1),
            ('text-d', ['text-c'], TEXT_1),
            ('text-m', ['text-b', 'text-d'], TEXT_1),
            ]
        for version_id, parents, lines in test_data:
            k1.add_lines(version_id, parents, split_lines(lines))
        # monkey-patch versions method to return out of order, as if coming
        # from multiple independently indexed packs
        original_versions = k1.versions
        k1.versions = lambda: reversed(original_versions())
        expected_data_list = [
            ('text-a', ['fulltext'], 122, ()),
            ('text-b', ['line-delta'], 84, ('text-a',))]
        # now check the fulltext is first and the delta second
        format, data_list, _ = k1.get_data_stream(['text-a', 'text-b'])
        self.assertEqual('knit-plain', format)
        self.assertEqual(expected_data_list, data_list)
        # and that's true if we ask for them in the opposite order too
        format, data_list, _ = k1.get_data_stream(['text-b', 'text-a'])
        self.assertEqual(expected_data_list, data_list)
        # also try requesting more versions
        format, data_list, _ = k1.get_data_stream([
            'text-m', 'text-b', 'text-a'])
        self.assertEqual([
            ('text-a', ['fulltext'], 122, ()),
            ('text-b', ['line-delta'], 84, ('text-a',)),
            ('text-m', ['line-delta'], 84, ('text-b', 'text-d')),
            ], data_list)

    def test_get_stream_ghost_parent(self):
        """Get a data stream for a version with a ghost parent."""
        k1 = self.make_test_knit()
        # Test data
        k1.add_lines('text-a', [], split_lines(TEXT_1))
        k1.add_lines_with_ghosts('text-b', ['text-a', 'text-ghost'],
                                 split_lines(TEXT_1))
        # Expected data
        expected_data_list = [
            # version, options, length, parents
            ('text-b', ['line-delta'], 84, ('text-a', 'text-ghost')),
            ]
        
        format, data_list, reader_callable = k1.get_data_stream(['text-b'])
        self.assertEqual('knit-plain', format)
        self.assertEqual(expected_data_list, data_list)
        self.assertRecordContentEqual(k1, 'text-b', reader_callable(None))
    
    def test_get_stream_get_multiple_records(self):
        """Get a stream for multiple records of a knit."""
        k1 = self.make_test_knit()
        # Insert the same data as test_knit_join, as they seem to cover a range
        # of cases (no parents, one parent, multiple parents).
        test_data = [
            ('text-a', [], TEXT_1),
            ('text-b', ['text-a'], TEXT_1),
            ('text-c', [], TEXT_1),
            ('text-d', ['text-c'], TEXT_1),
            ('text-m', ['text-b', 'text-d'], TEXT_1),
            ]
        for version_id, parents, lines in test_data:
            k1.add_lines(version_id, parents, split_lines(lines))

        # This test is actually a bit strict as the order in which they're
        # returned is not defined.  This matches the current (deterministic)
        # behaviour.
        expected_data_list = [
            # version, options, length, parents
            ('text-d', ['line-delta'], 84, ('text-c',)),
            ('text-b', ['line-delta'], 84, ('text-a',)),
            ]
        # Note that even though we request the revision IDs in a particular
        # order, the data stream may return them in any order it likes.  In this
        # case, they'll be in the order they were inserted into the knit.
        format, data_list, reader_callable = k1.get_data_stream(
            ['text-d', 'text-b'])
        self.assertEqual('knit-plain', format)
        self.assertEqual(expected_data_list, data_list)
        # must match order they're returned
        self.assertRecordContentEqual(k1, 'text-d', reader_callable(84))
        self.assertRecordContentEqual(k1, 'text-b', reader_callable(84))
        self.assertEqual('', reader_callable(None),
                         "There should be no more bytes left to read.")

    def test_get_stream_all(self):
        """Get a data stream for all the records in a knit.

        This exercises fulltext records, line-delta records, records with
        various numbers of parents, and reading multiple records out of the
        callable.  These cases ought to all be exercised individually by the
        other test_get_stream_* tests; this test is basically just paranoia.
        """
        k1 = self.make_test_knit()
        # Insert the same data as test_knit_join, as they seem to cover a range
        # of cases (no parents, one parent, multiple parents).
        test_data = [
            ('text-a', [], TEXT_1),
            ('text-b', ['text-a'], TEXT_1),
            ('text-c', [], TEXT_1),
            ('text-d', ['text-c'], TEXT_1),
            ('text-m', ['text-b', 'text-d'], TEXT_1),
           ]
        for version_id, parents, lines in test_data:
            k1.add_lines(version_id, parents, split_lines(lines))

        # This test is actually a bit strict as the order in which they're
        # returned is not defined.  This matches the current (deterministic)
        # behaviour.
        expected_data_list = [
            # version, options, length, parents
            ('text-a', ['fulltext'], 122, ()),
            ('text-b', ['line-delta'], 84, ('text-a',)),
            ('text-m', ['line-delta'], 84, ('text-b', 'text-d')),
            ('text-c', ['fulltext'], 121, ()),
            ('text-d', ['line-delta'], 84, ('text-c',)),
            ]
        format, data_list, reader_callable = k1.get_data_stream(
            ['text-a', 'text-b', 'text-c', 'text-d', 'text-m'])
        self.assertEqual('knit-plain', format)
        self.assertEqual(expected_data_list, data_list)
        for version_id, options, length, parents in expected_data_list:
            bytes = reader_callable(length)
            self.assertRecordContentEqual(k1, version_id, bytes)


class InsertDataStreamTests(KnitTests):
    """Tests for insert_data_stream."""

    def assertKnitFilesEqual(self, knit1, knit2):
        """Assert that the contents of the index and data files of two knits are
        equal.
        """
        self.assertEqual(
            knit1.transport.get_bytes(knit1._data._access._filename),
            knit2.transport.get_bytes(knit2._data._access._filename))
        self.assertEqual(
            knit1.transport.get_bytes(knit1._index._filename),
            knit2.transport.get_bytes(knit2._index._filename))

    def assertKnitValuesEqual(self, left, right):
        """Assert that the texts, annotations and graph of left and right are
        the same.
        """
        self.assertEqual(set(left.versions()), set(right.versions()))
        for version in left.versions():
            self.assertEqual(left.get_parents_with_ghosts(version),
                right.get_parents_with_ghosts(version))
            self.assertEqual(left.get_lines(version),
                right.get_lines(version))
            self.assertEqual(left.annotate(version),
                right.annotate(version))

    def test_empty_stream(self):
        """Inserting a data stream with no records should not put any data into
        the knit.
        """
        k1 = self.make_test_knit()
        k1.insert_data_stream(
            (k1.get_format_signature(), [], lambda ignored: ''))
        self.assertEqual('', k1.transport.get_bytes(k1._data._access._filename),
                         "The .knit should be completely empty.")
        self.assertEqual(k1._index.HEADER,
                         k1.transport.get_bytes(k1._index._filename),
                         "The .kndx should have nothing apart from the header.")

    def test_one_record(self):
        """Inserting a data stream with one record from a knit with one record
        results in byte-identical files.
        """
        source = self.make_test_knit(name='source')
        source.add_lines('text-a', [], split_lines(TEXT_1))
        data_stream = source.get_data_stream(['text-a'])
        target = self.make_test_knit(name='target')
        target.insert_data_stream(data_stream)
        self.assertKnitFilesEqual(source, target)

    def test_annotated_stream_into_unannotated_knit(self):
        """Inserting an annotated datastream to an unannotated knit works."""
        # case one - full texts.
        source = self.make_test_knit(name='source', annotate=True)
        target = self.make_test_knit(name='target', annotate=False)
        source.add_lines('text-a', [], split_lines(TEXT_1))
        target.insert_data_stream(source.get_data_stream(['text-a']))
        self.assertKnitValuesEqual(source, target)
        # case two - deltas.
        source.add_lines('text-b', ['text-a'], split_lines(TEXT_2))
        target.insert_data_stream(source.get_data_stream(['text-b']))
        self.assertKnitValuesEqual(source, target)

    def test_unannotated_stream_into_annotated_knit(self):
        """Inserting an unannotated datastream to an annotated knit works."""
        # case one - full texts.
        source = self.make_test_knit(name='source', annotate=False)
        target = self.make_test_knit(name='target', annotate=True)
        source.add_lines('text-a', [], split_lines(TEXT_1))
        target.insert_data_stream(source.get_data_stream(['text-a']))
        self.assertKnitValuesEqual(source, target)
        # case two - deltas.
        source.add_lines('text-b', ['text-a'], split_lines(TEXT_2))
        target.insert_data_stream(source.get_data_stream(['text-b']))
        self.assertKnitValuesEqual(source, target)

    def test_records_already_present(self):
        """Insert a data stream where some records are alreday present in the
        target, and some not.  Only the new records are inserted.
        """
        source = self.make_test_knit(name='source')
        target = self.make_test_knit(name='target')
        # Insert 'text-a' into both source and target
        source.add_lines('text-a', [], split_lines(TEXT_1))
        target.insert_data_stream(source.get_data_stream(['text-a']))
        # Insert 'text-b' into just the source.
        source.add_lines('text-b', ['text-a'], split_lines(TEXT_1))
        # Get a data stream of both text-a and text-b, and insert it.
        data_stream = source.get_data_stream(['text-a', 'text-b'])
        target.insert_data_stream(data_stream)
        # The source and target will now be identical.  This means the text-a
        # record was not added a second time.
        self.assertKnitFilesEqual(source, target)

    def test_multiple_records(self):
        """Inserting a data stream of all records from a knit with multiple
        records results in byte-identical files.
        """
        source = self.make_test_knit(name='source')
        source.add_lines('text-a', [], split_lines(TEXT_1))
        source.add_lines('text-b', ['text-a'], split_lines(TEXT_1))
        source.add_lines('text-c', [], split_lines(TEXT_1))
        data_stream = source.get_data_stream(['text-a', 'text-b', 'text-c'])
        
        target = self.make_test_knit(name='target')
        target.insert_data_stream(data_stream)
        
        self.assertKnitFilesEqual(source, target)

    def test_ghost_parent(self):
        """Insert a data stream with a record that has a ghost parent."""
        # Make a knit with a record, text-a, that has a ghost parent.
        source = self.make_test_knit(name='source')
        source.add_lines_with_ghosts('text-a', ['text-ghost'],
                                     split_lines(TEXT_1))
        data_stream = source.get_data_stream(['text-a'])

        target = self.make_test_knit(name='target')
        target.insert_data_stream(data_stream)

        self.assertKnitFilesEqual(source, target)

        # The target knit object is in a consistent state, i.e. the record we
        # just added is immediately visible.
        self.assertTrue(target.has_version('text-a'))
        self.assertFalse(target.has_version('text-ghost'))
        self.assertEqual({'text-a':('text-ghost',)},
            target.get_parent_map(['text-a', 'text-ghost']))
        self.assertEqual(split_lines(TEXT_1), target.get_lines('text-a'))

    def test_inconsistent_version_lines(self):
        """Inserting a data stream which has different content for a version_id
        than already exists in the knit will raise KnitCorrupt.
        """
        source = self.make_test_knit(name='source')
        target = self.make_test_knit(name='target')
        # Insert a different 'text-a' into both source and target
        source.add_lines('text-a', [], split_lines(TEXT_1))
        target.add_lines('text-a', [], split_lines(TEXT_2))
        # Insert a data stream with conflicting content into the target
        data_stream = source.get_data_stream(['text-a'])
        self.assertRaises(
            errors.KnitCorrupt, target.insert_data_stream, data_stream)

    def test_inconsistent_version_parents(self):
        """Inserting a data stream which has different parents for a version_id
        than already exists in the knit will raise KnitCorrupt.
        """
        source = self.make_test_knit(name='source')
        target = self.make_test_knit(name='target')
        # Insert a different 'text-a' into both source and target.  They differ
        # only by the parents list, the content is the same.
        source.add_lines_with_ghosts('text-a', [], split_lines(TEXT_1))
        target.add_lines_with_ghosts('text-a', ['a-ghost'], split_lines(TEXT_1))
        # Insert a data stream with conflicting content into the target
        data_stream = source.get_data_stream(['text-a'])
        self.assertRaises(
            errors.KnitCorrupt, target.insert_data_stream, data_stream)

    def test_unknown_stream_format(self):
        """A data stream in a different format to the target knit cannot be
        inserted.

        It will raise KnitDataStreamUnknown because the fallback code will fail
        to make a knit. In future we may need KnitDataStreamIncompatible again,
        for more exotic cases.
        """
        data_stream = ('fake-format-signature', [], lambda _: '')
        target = self.make_test_knit(name='target')
        self.assertRaises(
            errors.KnitDataStreamUnknown,
            target.insert_data_stream, data_stream)

    def test_bug_208418(self):
        """You can insert a stream with an incompatible format, even when:
          * the stream has a line-delta record,
          * whose parent is in the target, also stored as a line-delta

        See <https://launchpad.net/bugs/208418>.
        """
        base_lines = split_lines(TEXT_1)
        # Make the target
        target = self.make_test_knit(name='target', annotate=True)
        target.add_lines('version-1', [], base_lines)
        target.add_lines('version-2', ['version-1'], base_lines + ['a\n'])
        # The second record should be a delta.
        self.assertEqual('line-delta', target._index.get_method('version-2'))
        
        # Make a source, with a different format, but the same data
        source = self.make_test_knit(name='source', annotate=False)
        source.add_lines('version-1', [], base_lines)
        source.add_lines('version-2', ['version-1'], base_lines + ['a\n'])
        # Now add another record, which should be stored as a delta against
        # version-2.
        source.add_lines('version-3', ['version-2'], base_lines + ['b\n'])
        self.assertEqual('line-delta', source._index.get_method('version-3'))

        # Make a stream of the new version
        data_stream = source.get_data_stream(['version-3'])
        # And insert into the target
        target.insert_data_stream(data_stream)
        # No errors should have been raised.

    def test_line_delta_record_into_non_delta_knit(self):
        # Make a data stream with a line-delta record
        source = self.make_test_knit(name='source', delta=True)
        base_lines = split_lines(TEXT_1)
        source.add_lines('version-1', [], base_lines)
        source.add_lines('version-2', ['version-1'], base_lines + ['a\n'])
        # The second record should be a delta.
        self.assertEqual('line-delta', source._index.get_method('version-2'))
        data_stream = source.get_data_stream(['version-1', 'version-2'])

        # Insert the stream into a non-delta knit.
        target = self.make_test_knit(name='target', delta=False)
        target.insert_data_stream(data_stream)
        
        # Both versions are fulltexts in the target
        self.assertEqual('fulltext', target._index.get_method('version-1'))
        self.assertEqual('fulltext', target._index.get_method('version-2'))


class DataStreamTests(KnitTests):

    def assertMadeStreamKnit(self, source_knit, versions, target_knit):
        """Assert that a knit made from a stream is as expected."""
        a_stream = source_knit.get_data_stream(versions)
        expected_data = a_stream[2](None)
        a_stream = source_knit.get_data_stream(versions)
        a_knit = target_knit._knit_from_datastream(a_stream)
        self.assertEqual(source_knit.factory.__class__,
            a_knit.factory.__class__)
        self.assertIsInstance(a_knit._data._access, _StreamAccess)
        self.assertIsInstance(a_knit._index, _StreamIndex)
        self.assertEqual(a_knit._index.data_list, a_stream[1])
        self.assertEqual(a_knit._data._access.data, expected_data)
        self.assertEqual(a_knit.filename, target_knit.filename)
        self.assertEqual(a_knit.transport, target_knit.transport)
        self.assertEqual(a_knit._index, a_knit._data._access.stream_index)
        self.assertEqual(target_knit, a_knit._data._access.backing_knit)
        self.assertIsInstance(a_knit._data._access.orig_factory,
            source_knit.factory.__class__)

    def test__knit_from_data_stream_empty(self):
        """Create a knit object from a datastream."""
        annotated = self.make_test_knit(name='source', annotate=True)
        plain = self.make_test_knit(name='target', annotate=False)
        # case 1: annotated source
        self.assertMadeStreamKnit(annotated, [], annotated)
        self.assertMadeStreamKnit(annotated, [], plain)
        # case 2: plain source
        self.assertMadeStreamKnit(plain, [], annotated)
        self.assertMadeStreamKnit(plain, [], plain)

    def test__knit_from_data_stream_unknown_format(self):
        annotated = self.make_test_knit(name='source', annotate=True)
        self.assertRaises(errors.KnitDataStreamUnknown,
            annotated._knit_from_datastream, ("unknown", None, None))


TEXT_1 = """\
Banana cup cakes:

- bananas
- eggs
- broken tea cups
"""

TEXT_1A = """\
Banana cup cake recipe
(serves 6)

- bananas
- eggs
- broken tea cups
- self-raising flour
"""

TEXT_1B = """\
Banana cup cake recipe

- bananas (do not use plantains!!!)
- broken tea cups
- flour
"""

delta_1_1a = """\
0,1,2
Banana cup cake recipe
(serves 6)
5,5,1
- self-raising flour
"""

TEXT_2 = """\
Boeuf bourguignon

- beef
- red wine
- small onions
- carrot
- mushrooms
"""

AB_MERGE_TEXT="""unchanged|Banana cup cake recipe
new-a|(serves 6)
unchanged|
killed-b|- bananas
killed-b|- eggs
new-b|- bananas (do not use plantains!!!)
unchanged|- broken tea cups
new-a|- self-raising flour
new-b|- flour
"""
AB_MERGE=[tuple(l.split('|')) for l in AB_MERGE_TEXT.splitlines(True)]


def line_delta(from_lines, to_lines):
    """Generate line-based delta from one text to another"""
    s = difflib.SequenceMatcher(None, from_lines, to_lines)
    for op in s.get_opcodes():
        if op[0] == 'equal':
            continue
        yield '%d,%d,%d\n' % (op[1], op[2], op[4]-op[3])
        for i in range(op[3], op[4]):
            yield to_lines[i]


def apply_line_delta(basis_lines, delta_lines):
    """Apply a line-based perfect diff
    
    basis_lines -- text to apply the patch to
    delta_lines -- diff instructions and content
    """
    out = basis_lines[:]
    i = 0
    offset = 0
    while i < len(delta_lines):
        l = delta_lines[i]
        a, b, c = map(long, l.split(','))
        i = i + 1
        out[offset+a:offset+b] = delta_lines[i:i+c]
        i = i + c
        offset = offset + (b - a) + c
    return out


class TestWeaveToKnit(KnitTests):

    def test_weave_to_knit_matches(self):
        # check that the WeaveToKnit is_compatible function
        # registers True for a Weave to a Knit.
        w = Weave(get_scope=lambda:None)
        k = self.make_test_knit()
        self.failUnless(WeaveToKnit.is_compatible(w, k))
        self.failIf(WeaveToKnit.is_compatible(k, w))
        self.failIf(WeaveToKnit.is_compatible(w, w))
        self.failIf(WeaveToKnit.is_compatible(k, k))


class TestKnitIndex(KnitTests):

    def test_add_versions_dictionary_compresses(self):
        """Adding versions to the index should update the lookup dict"""
        knit = self.make_test_knit()
        idx = knit._index
        idx.add_version('a-1', ['fulltext'], (None, 0, 0), [])
        self.check_file_contents('test.kndx',
            '# bzr knit index 8\n'
            '\n'
            'a-1 fulltext 0 0  :'
            )
        idx.add_versions([('a-2', ['fulltext'], (None, 0, 0), ['a-1']),
                          ('a-3', ['fulltext'], (None, 0, 0), ['a-2']),
                         ])
        self.check_file_contents('test.kndx',
            '# bzr knit index 8\n'
            '\n'
            'a-1 fulltext 0 0  :\n'
            'a-2 fulltext 0 0 0 :\n'
            'a-3 fulltext 0 0 1 :'
            )
        self.assertEqual(['a-1', 'a-2', 'a-3'], idx._history)
        self.assertEqual({'a-1':('a-1', ['fulltext'], 0, 0, (), 0),
                          'a-2':('a-2', ['fulltext'], 0, 0, ('a-1',), 1),
                          'a-3':('a-3', ['fulltext'], 0, 0, ('a-2',), 2),
                         }, idx._cache)

    def test_add_versions_fails_clean(self):
        """If add_versions fails in the middle, it restores a pristine state.

        Any modifications that are made to the index are reset if all versions
        cannot be added.
        """
        # This cheats a little bit by passing in a generator which will
        # raise an exception before the processing finishes
        # Other possibilities would be to have an version with the wrong number
        # of entries, or to make the backing transport unable to write any
        # files.

        knit = self.make_test_knit()
        idx = knit._index
        idx.add_version('a-1', ['fulltext'], (None, 0, 0), [])

        class StopEarly(Exception):
            pass

        def generate_failure():
            """Add some entries and then raise an exception"""
            yield ('a-2', ['fulltext'], (None, 0, 0), ('a-1',))
            yield ('a-3', ['fulltext'], (None, 0, 0), ('a-2',))
            raise StopEarly()

        # Assert the pre-condition
        self.assertEqual(['a-1'], idx._history)
        self.assertEqual({'a-1':('a-1', ['fulltext'], 0, 0, (), 0)}, idx._cache)

        self.assertRaises(StopEarly, idx.add_versions, generate_failure())

        # And it shouldn't be modified
        self.assertEqual(['a-1'], idx._history)
        self.assertEqual({'a-1':('a-1', ['fulltext'], 0, 0, (), 0)}, idx._cache)

    def test_knit_index_ignores_empty_files(self):
        # There was a race condition in older bzr, where a ^C at the right time
        # could leave an empty .kndx file, which bzr would later claim was a
        # corrupted file since the header was not present. In reality, the file
        # just wasn't created, so it should be ignored.
        t = get_transport('.')
        t.put_bytes('test.kndx', '')

        knit = self.make_test_knit()

    def test_knit_index_checks_header(self):
        t = get_transport('.')
        t.put_bytes('test.kndx', '# not really a knit header\n\n')

        self.assertRaises(KnitHeaderError, self.make_test_knit)


class TestGraphIndexKnit(KnitTests):
    """Tests for knits using a GraphIndex rather than a KnitIndex."""

    def make_g_index(self, name, ref_lists=0, nodes=[]):
        builder = GraphIndexBuilder(ref_lists)
        for node, references, value in nodes:
            builder.add_node(node, references, value)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file(name, stream)
        return GraphIndex(trans, name, size)

    def two_graph_index(self, deltas=False, catch_adds=False):
        """Build a two-graph index.

        :param deltas: If true, use underlying indices with two node-ref
            lists and 'parent' set to a delta-compressed against tail.
        """
        # build a complex graph across several indices.
        if deltas:
            # delta compression inn the index
            index1 = self.make_g_index('1', 2, [
                (('tip', ), 'N0 100', ([('parent', )], [], )),
                (('tail', ), '', ([], []))])
            index2 = self.make_g_index('2', 2, [
                (('parent', ), ' 100 78', ([('tail', ), ('ghost', )], [('tail', )])),
                (('separate', ), '', ([], []))])
        else:
            # just blob location and graph in the index.
            index1 = self.make_g_index('1', 1, [
                (('tip', ), 'N0 100', ([('parent', )], )),
                (('tail', ), '', ([], ))])
            index2 = self.make_g_index('2', 1, [
                (('parent', ), ' 100 78', ([('tail', ), ('ghost', )], )),
                (('separate', ), '', ([], ))])
        combined_index = CombinedGraphIndex([index1, index2])
        if catch_adds:
            self.combined_index = combined_index
            self.caught_entries = []
            add_callback = self.catch_add
        else:
            add_callback = None
        return KnitGraphIndex(combined_index, deltas=deltas,
            add_callback=add_callback)

    def test_get_ancestry(self):
        # get_ancestry is defined as eliding ghosts, not erroring.
        index = self.two_graph_index()
        self.assertEqual([], index.get_ancestry([]))
        self.assertEqual(['separate'], index.get_ancestry(['separate']))
        self.assertEqual(['tail'], index.get_ancestry(['tail']))
        self.assertEqual(['tail', 'parent'], index.get_ancestry(['parent']))
        self.assertEqual(['tail', 'parent', 'tip'], index.get_ancestry(['tip']))
        self.assertTrue(index.get_ancestry(['tip', 'separate']) in
            (['tail', 'parent', 'tip', 'separate'],
             ['separate', 'tail', 'parent', 'tip'],
            ))
        # and without topo_sort
        self.assertEqual(set(['separate']),
            set(index.get_ancestry(['separate'], topo_sorted=False)))
        self.assertEqual(set(['tail']),
            set(index.get_ancestry(['tail'], topo_sorted=False)))
        self.assertEqual(set(['tail', 'parent']),
            set(index.get_ancestry(['parent'], topo_sorted=False)))
        self.assertEqual(set(['tail', 'parent', 'tip']),
            set(index.get_ancestry(['tip'], topo_sorted=False)))
        self.assertEqual(set(['separate', 'tail', 'parent', 'tip']),
            set(index.get_ancestry(['tip', 'separate'])))
        # asking for a ghost makes it go boom.
        self.assertRaises(errors.RevisionNotPresent, index.get_ancestry, ['ghost'])

    def test_get_ancestry_with_ghosts(self):
        index = self.two_graph_index()
        self.assertEqual([], index.get_ancestry_with_ghosts([]))
        self.assertEqual(['separate'], index.get_ancestry_with_ghosts(['separate']))
        self.assertEqual(['tail'], index.get_ancestry_with_ghosts(['tail']))
        self.assertTrue(index.get_ancestry_with_ghosts(['parent']) in
            (['tail', 'ghost', 'parent'],
             ['ghost', 'tail', 'parent'],
            ))
        self.assertTrue(index.get_ancestry_with_ghosts(['tip']) in
            (['tail', 'ghost', 'parent', 'tip'],
             ['ghost', 'tail', 'parent', 'tip'],
            ))
        self.assertTrue(index.get_ancestry_with_ghosts(['tip', 'separate']) in
            (['tail', 'ghost', 'parent', 'tip', 'separate'],
             ['ghost', 'tail', 'parent', 'tip', 'separate'],
             ['separate', 'tail', 'ghost', 'parent', 'tip'],
             ['separate', 'ghost', 'tail', 'parent', 'tip'],
            ))
        # asking for a ghost makes it go boom.
        self.assertRaises(errors.RevisionNotPresent, index.get_ancestry_with_ghosts, ['ghost'])

    def test_num_versions(self):
        index = self.two_graph_index()
        self.assertEqual(4, index.num_versions())

    def test_get_versions(self):
        index = self.two_graph_index()
        self.assertEqual(set(['tail', 'tip', 'parent', 'separate']),
            set(index.get_versions()))

    def test_has_version(self):
        index = self.two_graph_index()
        self.assertTrue(index.has_version('tail'))
        self.assertFalse(index.has_version('ghost'))

    def test_get_position(self):
        index = self.two_graph_index()
        self.assertEqual((index._graph_index._indices[0], 0, 100), index.get_position('tip'))
        self.assertEqual((index._graph_index._indices[1], 100, 78), index.get_position('parent'))

    def test_get_method_deltas(self):
        index = self.two_graph_index(deltas=True)
        self.assertEqual('fulltext', index.get_method('tip'))
        self.assertEqual('line-delta', index.get_method('parent'))

    def test_get_method_no_deltas(self):
        # check that the parent-history lookup is ignored with deltas=False.
        index = self.two_graph_index(deltas=False)
        self.assertEqual('fulltext', index.get_method('tip'))
        self.assertEqual('fulltext', index.get_method('parent'))

    def test_get_options_deltas(self):
        index = self.two_graph_index(deltas=True)
        self.assertEqual(['fulltext', 'no-eol'], index.get_options('tip'))
        self.assertEqual(['line-delta'], index.get_options('parent'))

    def test_get_options_no_deltas(self):
        # check that the parent-history lookup is ignored with deltas=False.
        index = self.two_graph_index(deltas=False)
        self.assertEqual(['fulltext', 'no-eol'], index.get_options('tip'))
        self.assertEqual(['fulltext'], index.get_options('parent'))

    def test_get_parents_with_ghosts(self):
        index = self.two_graph_index()
        self.assertEqual(('tail', 'ghost'), index.get_parents_with_ghosts('parent'))
        # and errors on ghosts.
        self.assertRaises(errors.RevisionNotPresent,
            index.get_parents_with_ghosts, 'ghost')

    def test_check_versions_present(self):
        # ghosts should not be considered present
        index = self.two_graph_index()
        self.assertRaises(RevisionNotPresent, index.check_versions_present,
            ['ghost'])
        self.assertRaises(RevisionNotPresent, index.check_versions_present,
            ['tail', 'ghost'])
        index.check_versions_present(['tail', 'separate'])

    def catch_add(self, entries):
        self.caught_entries.append(entries)

    def test_add_no_callback_errors(self):
        index = self.two_graph_index()
        self.assertRaises(errors.ReadOnlyError, index.add_version,
            'new', 'fulltext,no-eol', (None, 50, 60), ['separate'])

    def test_add_version_smoke(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_version('new', 'fulltext,no-eol', (None, 50, 60), ['separate'])
        self.assertEqual([[(('new', ), 'N50 60', ((('separate',),),))]],
            self.caught_entries)

    def test_add_version_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'new', 'no-eol,line-delta', (None, 0, 100), ['parent'])
        self.assertEqual([], self.caught_entries)

    def test_add_version_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_version('tip', 'fulltext,no-eol', (None, 0, 100), ['parent'])
        index.add_version('tip', 'no-eol,fulltext', (None, 0, 100), ['parent'])
        # but neither should have added data.
        self.assertEqual([[], []], self.caught_entries)
        
    def test_add_version_different_dup(self):
        index = self.two_graph_index(deltas=True, catch_adds=True)
        # change options
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'no-eol,line-delta', (None, 0, 100), ['parent'])
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'line-delta,no-eol', (None, 0, 100), ['parent'])
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'fulltext', (None, 0, 100), ['parent'])
        # position/length
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'fulltext,no-eol', (None, 50, 100), ['parent'])
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'fulltext,no-eol', (None, 0, 1000), ['parent'])
        # parents
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'fulltext,no-eol', (None, 0, 100), [])
        self.assertEqual([], self.caught_entries)
        
    def test_add_versions_nodeltas(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_versions([
                ('new', 'fulltext,no-eol', (None, 50, 60), ['separate']),
                ('new2', 'fulltext', (None, 0, 6), ['new']),
                ])
        self.assertEqual([(('new', ), 'N50 60', ((('separate',),),)),
            (('new2', ), ' 0 6', ((('new',),),))],
            sorted(self.caught_entries[0]))
        self.assertEqual(1, len(self.caught_entries))

    def test_add_versions_deltas(self):
        index = self.two_graph_index(deltas=True, catch_adds=True)
        index.add_versions([
                ('new', 'fulltext,no-eol', (None, 50, 60), ['separate']),
                ('new2', 'line-delta', (None, 0, 6), ['new']),
                ])
        self.assertEqual([(('new', ), 'N50 60', ((('separate',),), ())),
            (('new2', ), ' 0 6', ((('new',),), (('new',),), ))],
            sorted(self.caught_entries[0]))
        self.assertEqual(1, len(self.caught_entries))

    def test_add_versions_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('new', 'no-eol,line-delta', (None, 0, 100), ['parent'])])
        self.assertEqual([], self.caught_entries)

    def test_add_versions_random_id_accepted(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_versions([], random_id=True)

    def test_add_versions_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_versions([('tip', 'fulltext,no-eol', (None, 0, 100), ['parent'])])
        index.add_versions([('tip', 'no-eol,fulltext', (None, 0, 100), ['parent'])])
        # but neither should have added data.
        self.assertEqual([[], []], self.caught_entries)
        
    def test_add_versions_different_dup(self):
        index = self.two_graph_index(deltas=True, catch_adds=True)
        # change options
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'no-eol,line-delta', (None, 0, 100), ['parent'])])
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'line-delta,no-eol', (None, 0, 100), ['parent'])])
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'fulltext', (None, 0, 100), ['parent'])])
        # position/length
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'fulltext,no-eol', (None, 50, 100), ['parent'])])
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'fulltext,no-eol', (None, 0, 1000), ['parent'])])
        # parents
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'fulltext,no-eol', (None, 0, 100), [])])
        # change options in the second record
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'fulltext,no-eol', (None, 0, 100), ['parent']),
             ('tip', 'no-eol,line-delta', (None, 0, 100), ['parent'])])
        self.assertEqual([], self.caught_entries)

class TestNoParentsGraphIndexKnit(KnitTests):
    """Tests for knits using KnitGraphIndex with no parents."""

    def make_g_index(self, name, ref_lists=0, nodes=[]):
        builder = GraphIndexBuilder(ref_lists)
        for node, references in nodes:
            builder.add_node(node, references)
        stream = builder.finish()
        trans = self.get_transport()
        size = trans.put_file(name, stream)
        return GraphIndex(trans, name, size)

    def test_parents_deltas_incompatible(self):
        index = CombinedGraphIndex([])
        self.assertRaises(errors.KnitError, KnitGraphIndex, index,
            deltas=True, parents=False)

    def two_graph_index(self, catch_adds=False):
        """Build a two-graph index.

        :param deltas: If true, use underlying indices with two node-ref
            lists and 'parent' set to a delta-compressed against tail.
        """
        # put several versions in the index.
        index1 = self.make_g_index('1', 0, [
            (('tip', ), 'N0 100'),
            (('tail', ), '')])
        index2 = self.make_g_index('2', 0, [
            (('parent', ), ' 100 78'),
            (('separate', ), '')])
        combined_index = CombinedGraphIndex([index1, index2])
        if catch_adds:
            self.combined_index = combined_index
            self.caught_entries = []
            add_callback = self.catch_add
        else:
            add_callback = None
        return KnitGraphIndex(combined_index, parents=False,
            add_callback=add_callback)

    def test_get_ancestry(self):
        # with no parents, ancestry is always just the key.
        index = self.two_graph_index()
        self.assertEqual([], index.get_ancestry([]))
        self.assertEqual(['separate'], index.get_ancestry(['separate']))
        self.assertEqual(['tail'], index.get_ancestry(['tail']))
        self.assertEqual(['parent'], index.get_ancestry(['parent']))
        self.assertEqual(['tip'], index.get_ancestry(['tip']))
        self.assertTrue(index.get_ancestry(['tip', 'separate']) in
            (['tip', 'separate'],
             ['separate', 'tip'],
            ))
        # asking for a ghost makes it go boom.
        self.assertRaises(errors.RevisionNotPresent, index.get_ancestry, ['ghost'])

    def test_get_ancestry_with_ghosts(self):
        index = self.two_graph_index()
        self.assertEqual([], index.get_ancestry_with_ghosts([]))
        self.assertEqual(['separate'], index.get_ancestry_with_ghosts(['separate']))
        self.assertEqual(['tail'], index.get_ancestry_with_ghosts(['tail']))
        self.assertEqual(['parent'], index.get_ancestry_with_ghosts(['parent']))
        self.assertEqual(['tip'], index.get_ancestry_with_ghosts(['tip']))
        self.assertTrue(index.get_ancestry_with_ghosts(['tip', 'separate']) in
            (['tip', 'separate'],
             ['separate', 'tip'],
            ))
        # asking for a ghost makes it go boom.
        self.assertRaises(errors.RevisionNotPresent, index.get_ancestry_with_ghosts, ['ghost'])

    def test_num_versions(self):
        index = self.two_graph_index()
        self.assertEqual(4, index.num_versions())

    def test_get_versions(self):
        index = self.two_graph_index()
        self.assertEqual(set(['tail', 'tip', 'parent', 'separate']),
            set(index.get_versions()))

    def test_has_version(self):
        index = self.two_graph_index()
        self.assertTrue(index.has_version('tail'))
        self.assertFalse(index.has_version('ghost'))

    def test_get_position(self):
        index = self.two_graph_index()
        self.assertEqual((index._graph_index._indices[0], 0, 100), index.get_position('tip'))
        self.assertEqual((index._graph_index._indices[1], 100, 78), index.get_position('parent'))

    def test_get_method(self):
        index = self.two_graph_index()
        self.assertEqual('fulltext', index.get_method('tip'))
        self.assertEqual(['fulltext'], index.get_options('parent'))

    def test_get_options(self):
        index = self.two_graph_index()
        self.assertEqual(['fulltext', 'no-eol'], index.get_options('tip'))
        self.assertEqual(['fulltext'], index.get_options('parent'))

    def test_get_parents_with_ghosts(self):
        index = self.two_graph_index()
        self.assertEqual((), index.get_parents_with_ghosts('parent'))
        # and errors on ghosts.
        self.assertRaises(errors.RevisionNotPresent,
            index.get_parents_with_ghosts, 'ghost')

    def test_check_versions_present(self):
        index = self.two_graph_index()
        self.assertRaises(RevisionNotPresent, index.check_versions_present,
            ['missing'])
        self.assertRaises(RevisionNotPresent, index.check_versions_present,
            ['tail', 'missing'])
        index.check_versions_present(['tail', 'separate'])

    def catch_add(self, entries):
        self.caught_entries.append(entries)

    def test_add_no_callback_errors(self):
        index = self.two_graph_index()
        self.assertRaises(errors.ReadOnlyError, index.add_version,
            'new', 'fulltext,no-eol', (None, 50, 60), ['separate'])

    def test_add_version_smoke(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_version('new', 'fulltext,no-eol', (None, 50, 60), [])
        self.assertEqual([[(('new', ), 'N50 60')]],
            self.caught_entries)

    def test_add_version_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'new', 'no-eol,line-delta', (None, 0, 100), [])
        self.assertEqual([], self.caught_entries)

    def test_add_version_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_version('tip', 'fulltext,no-eol', (None, 0, 100), [])
        index.add_version('tip', 'no-eol,fulltext', (None, 0, 100), [])
        # but neither should have added data.
        self.assertEqual([[], []], self.caught_entries)
        
    def test_add_version_different_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # change options
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'no-eol,line-delta', (None, 0, 100), [])
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'line-delta,no-eol', (None, 0, 100), [])
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'fulltext', (None, 0, 100), [])
        # position/length
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'fulltext,no-eol', (None, 50, 100), [])
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'fulltext,no-eol', (None, 0, 1000), [])
        # parents
        self.assertRaises(errors.KnitCorrupt, index.add_version,
            'tip', 'fulltext,no-eol', (None, 0, 100), ['parent'])
        self.assertEqual([], self.caught_entries)
        
    def test_add_versions(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_versions([
                ('new', 'fulltext,no-eol', (None, 50, 60), []),
                ('new2', 'fulltext', (None, 0, 6), []),
                ])
        self.assertEqual([(('new', ), 'N50 60'), (('new2', ), ' 0 6')],
            sorted(self.caught_entries[0]))
        self.assertEqual(1, len(self.caught_entries))

    def test_add_versions_delta_not_delta_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('new', 'no-eol,line-delta', (None, 0, 100), ['parent'])])
        self.assertEqual([], self.caught_entries)

    def test_add_versions_parents_not_parents_index(self):
        index = self.two_graph_index(catch_adds=True)
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('new', 'no-eol,fulltext', (None, 0, 100), ['parent'])])
        self.assertEqual([], self.caught_entries)

    def test_add_versions_random_id_accepted(self):
        index = self.two_graph_index(catch_adds=True)
        index.add_versions([], random_id=True)

    def test_add_versions_same_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # options can be spelt two different ways
        index.add_versions([('tip', 'fulltext,no-eol', (None, 0, 100), [])])
        index.add_versions([('tip', 'no-eol,fulltext', (None, 0, 100), [])])
        # but neither should have added data.
        self.assertEqual([[], []], self.caught_entries)
        
    def test_add_versions_different_dup(self):
        index = self.two_graph_index(catch_adds=True)
        # change options
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'no-eol,line-delta', (None, 0, 100), [])])
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'line-delta,no-eol', (None, 0, 100), [])])
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'fulltext', (None, 0, 100), [])])
        # position/length
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'fulltext,no-eol', (None, 50, 100), [])])
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'fulltext,no-eol', (None, 0, 1000), [])])
        # parents
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'fulltext,no-eol', (None, 0, 100), ['parent'])])
        # change options in the second record
        self.assertRaises(errors.KnitCorrupt, index.add_versions,
            [('tip', 'fulltext,no-eol', (None, 0, 100), []),
             ('tip', 'no-eol,line-delta', (None, 0, 100), [])])
        self.assertEqual([], self.caught_entries)

class TestPackKnits(KnitTests):
    """Tests that use a _PackAccess and KnitGraphIndex."""

    def test_get_data_stream_packs_ignores_pack_overhead(self):
        # Packs have an encoding overhead that should not be included in the
        # 'size' field of a data stream, because it is not returned by the
        # raw_reading functions - it is why index_memo's are opaque, and
        # get_data_stream was abusing this.
        packname = 'test.pack'
        transport = self.get_transport()
        def write_data(bytes):
            transport.append_bytes(packname, bytes)
        writer = pack.ContainerWriter(write_data)
        writer.begin()
        index = InMemoryGraphIndex(2)
        knit_index = KnitGraphIndex(index, add_callback=index.add_nodes,
            deltas=True)
        indices = {index:(transport, packname)}
        access = _PackAccess(indices, writer=(writer, index))
        k = KnitVersionedFile('test', get_transport('.'),
            delta=True, create=True, index=knit_index, access_method=access)
        # insert something into the knit
        k.add_lines('text-1', [], ["foo\n"])
        # get a data stream for it
        stream = k.get_data_stream(['text-1'])
        # if the stream has been incorrectly assembled, we will get a short read
        # reading from the stream (as streams have no trailer)
        expected_length = stream[1][0][2]
        # we use -1 to do the read, so that if a trailer is added this test
        # will fail and we'll adjust it to handle that case correctly, rather
        # than allowing an over-read that is bogus.
        self.assertEqual(expected_length, len(stream[2](-1)))


class Test_StreamIndex(KnitTests):

    def get_index(self, knit, stream):
        """Get a _StreamIndex from knit and stream."""
        return knit._knit_from_datastream(stream)._index

    def assertIndexVersions(self, knit, versions):
        """Check that the _StreamIndex versions are those of the stream."""
        index = self.get_index(knit, knit.get_data_stream(versions))
        self.assertEqual(set(index.get_versions()), set(versions))
        # check we didn't get duplicates
        self.assertEqual(len(index.get_versions()), len(versions))

    def assertIndexAncestry(self, knit, ancestry_versions, versions, result):
        """Check the result of a get_ancestry call on knit."""
        index = self.get_index(knit, knit.get_data_stream(versions))
        self.assertEqual(
            set(result),
            set(index.get_ancestry(ancestry_versions, False)))

    def assertGetMethod(self, knit, versions, version, result):
        index = self.get_index(knit, knit.get_data_stream(versions))
        self.assertEqual(result, index.get_method(version))

    def assertGetOptions(self, knit, version, options):
        index = self.get_index(knit, knit.get_data_stream(version))
        self.assertEqual(options, index.get_options(version))

    def assertGetPosition(self, knit, versions, version, result):
        index = self.get_index(knit, knit.get_data_stream(versions))
        if result[1] is None:
            result = (result[0], index, result[2], result[3])
        self.assertEqual(result, index.get_position(version))

    def assertGetParentsWithGhosts(self, knit, versions, version, parents):
        index = self.get_index(knit, knit.get_data_stream(versions))
        self.assertEqual(parents, index.get_parents_with_ghosts(version))

    def make_knit_with_4_versions_2_dags(self):
        knit = self.make_test_knit()
        knit.add_lines('a', [], ["foo"])
        knit.add_lines('b', [], [])
        knit.add_lines('c', ['b', 'a'], [])
        knit.add_lines_with_ghosts('d', ['e', 'f'], [])
        return knit

    def test_versions(self):
        """The versions of a StreamIndex are those of the datastream."""
        knit = self.make_knit_with_4_versions_2_dags()
        # ask for most permutations, which catches bugs like falling back to the
        # target knit, or showing ghosts, etc.
        self.assertIndexVersions(knit, [])
        self.assertIndexVersions(knit, ['a'])
        self.assertIndexVersions(knit, ['b'])
        self.assertIndexVersions(knit, ['c'])
        self.assertIndexVersions(knit, ['d'])
        self.assertIndexVersions(knit, ['a', 'b'])
        self.assertIndexVersions(knit, ['b', 'c'])
        self.assertIndexVersions(knit, ['a', 'c'])
        self.assertIndexVersions(knit, ['a', 'b', 'c'])
        self.assertIndexVersions(knit, ['a', 'b', 'c', 'd'])

    def test_construct(self):
        """Constructing a StreamIndex generates index data."""
        data_list = [('text-a', ['fulltext'], 127, []),
            ('text-b', ['option'], 128, ['text-c'])]
        index = _StreamIndex(data_list, None)
        self.assertEqual({'text-a':(['fulltext'], (0, 127), []),
            'text-b':(['option'], (127, 127 + 128), ['text-c'])},
            index._by_version)

    def test_get_ancestry(self):
        knit = self.make_knit_with_4_versions_2_dags()
        self.assertIndexAncestry(knit, ['a'], ['a'], ['a'])
        self.assertIndexAncestry(knit, ['b'], ['b'], ['b'])
        self.assertIndexAncestry(knit, ['c'], ['c'], ['c'])
        self.assertIndexAncestry(knit, ['c'], ['a', 'b', 'c'],
            set(['a', 'b', 'c']))
        self.assertIndexAncestry(knit, ['c', 'd'], ['a', 'b', 'c', 'd'],
            set(['a', 'b', 'c', 'd']))

    def test_get_method(self):
        knit = self.make_knit_with_4_versions_2_dags()
        self.assertGetMethod(knit, ['a'], 'a', 'fulltext')
        self.assertGetMethod(knit, ['c'], 'c', 'line-delta')
        # get_method on a basis that is not in the datastream (but in the
        # backing knit) returns 'fulltext', because thats what we'll create as
        # we thunk across.
        self.assertGetMethod(knit, ['c'], 'b', 'fulltext')

    def test_get_options(self):
        knit = self.make_knit_with_4_versions_2_dags()
        self.assertGetOptions(knit, 'a', ['no-eol', 'fulltext'])
        self.assertGetOptions(knit, 'c', ['line-delta'])

    def test_get_parents_with_ghosts(self):
        knit = self.make_knit_with_4_versions_2_dags()
        self.assertGetParentsWithGhosts(knit, ['a'], 'a', ())
        self.assertGetParentsWithGhosts(knit, ['c'], 'c', ('b', 'a'))
        self.assertGetParentsWithGhosts(knit, ['d'], 'd', ('e', 'f'))

    def test_get_position(self):
        knit = self.make_knit_with_4_versions_2_dags()
        # get_position returns (thunk_flag, index(can be None), start, end) for
        # _StreamAccess to use.
        self.assertGetPosition(knit, ['a'], 'a', (False, None, 0, 78))
        self.assertGetPosition(knit, ['a', 'c'], 'c', (False, None, 78, 156))
        # get_position on a text that is not in the datastream (but in the
        # backing knit) returns (True, 'versionid', None, None) - and then the
        # access object can construct the relevant data as needed.
        self.assertGetPosition(knit, ['a', 'c'], 'b', (True, 'b', None, None))


class Test_StreamAccess(KnitTests):

    def get_index_access(self, knit, stream):
        """Get a _StreamAccess from knit and stream."""
        knit =  knit._knit_from_datastream(stream)
        return knit._index, knit._data._access

    def assertGetRawRecords(self, knit, versions):
        index, access = self.get_index_access(knit,
            knit.get_data_stream(versions))
        # check that every version asked for can be obtained from the resulting
        # access object.
        # batch
        memos = []
        for version in versions:
            memos.append(knit._index.get_position(version))
        original = {}
        for version, data in zip(
            versions, knit._data._access.get_raw_records(memos)):
            original[version] = data
        memos = []
        for version in versions:
            memos.append(index.get_position(version))
        streamed = {}
        for version, data in zip(versions, access.get_raw_records(memos)):
            streamed[version] = data
        self.assertEqual(original, streamed)
        # individually
        for version in versions:
            data = list(access.get_raw_records(
                [index.get_position(version)]))[0]
            self.assertEqual(original[version], data)

    def make_knit_with_two_versions(self):
        knit = self.make_test_knit()
        knit.add_lines('a', [], ["foo"])
        knit.add_lines('b', [], ["bar"])
        return knit

    def test_get_raw_records(self):
        knit = self.make_knit_with_two_versions()
        self.assertGetRawRecords(knit, ['a', 'b'])
        self.assertGetRawRecords(knit, ['a'])
        self.assertGetRawRecords(knit, ['b'])
    
    def test_get_raw_record_from_backing_knit(self):
        # the thunk layer should create an artificial A on-demand when needed.
        source_knit = self.make_test_knit(name='plain', annotate=False)
        target_knit = self.make_test_knit(name='annotated', annotate=True)
        source_knit.add_lines("A", [], ["Foo\n"])
        # Give the target A, so we can try to thunk across to it.
        target_knit.insert_record_stream(source_knit.get_record_stream(['A'],
            'unordered', False))
        index, access = self.get_index_access(target_knit,
            source_knit.get_data_stream([]))
        raw_data = list(access.get_raw_records([(True, "A", None, None)]))[0]
        df = GzipFile(mode='rb', fileobj=StringIO(raw_data))
        self.assertEqual(
            'version A 1 5d36b88bb697a2d778f024048bafabd443d74503\n'
            'Foo\nend A\n',
            df.read())

    def test_asking_for_thunk_stream_is_not_plain_errors(self):
        knit = self.make_test_knit(name='annotated', annotate=True)
        knit.add_lines("A", [], ["Foo\n"])
        index, access = self.get_index_access(knit,
            knit.get_data_stream([]))
        self.assertRaises(errors.KnitCorrupt,
            list, access.get_raw_records([(True, "A", None, None)]))


class TestFormatSignatures(KnitTests):

    def test_knit_format_signatures(self):
        """Different formats of knit have different signature strings."""
        knit = self.make_test_knit(name='a', annotate=True)
        self.assertEqual('knit-annotated', knit.get_format_signature())
        knit = self.make_test_knit(name='p', annotate=False)
        self.assertEqual('knit-plain', knit.get_format_signature())
