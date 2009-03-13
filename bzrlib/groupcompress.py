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
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Core compression logic for compressing streams of related files."""

from itertools import izip
from cStringIO import StringIO
import struct
import zlib
try:
    import pylzma
except ImportError:
    pylzma = None

from bzrlib import (
    annotate,
    debug,
    diff,
    errors,
    graph as _mod_graph,
    osutils,
    pack,
    patiencediff,
    )
from bzrlib.graph import Graph
from bzrlib.knit import _DirectPackAccess
from bzrlib.osutils import (
    contains_whitespace,
    sha_string,
    split_lines,
    )
from bzrlib.btree_index import BTreeBuilder
from bzrlib.lru_cache import LRUSizeCache
from bzrlib.tsort import topo_sort
from bzrlib.versionedfile import (
    adapter_registry,
    AbsentContentFactory,
    ChunkedContentFactory,
    FulltextContentFactory,
    VersionedFiles,
    )

_USE_LZMA = False and (pylzma is not None)
_NO_LABELS = False
_FAST = False

def encode_base128_int(val):
    """Convert an integer into a 7-bit lsb encoding."""
    bytes = []
    count = 0
    while val >= 0x80:
        bytes.append(chr((val | 0x80) & 0xFF))
        val >>= 7
    bytes.append(chr(val))
    return ''.join(bytes)


def decode_base128_int(bytes):
    """Decode an integer from a 7-bit lsb encoding."""
    offset = 0
    val = 0
    shift = 0
    bval = ord(bytes[offset])
    while bval >= 0x80:
        val |= (bval & 0x7F) << shift
        shift += 7
        offset += 1
        bval = ord(bytes[offset])
    val |= bval << shift
    offset += 1
    return val, offset


def sort_gc_optimal(parent_map):
    """Sort and group the keys in parent_map into groupcompress order.

    groupcompress is defined (currently) as reverse-topological order, grouped by
    the key prefix.

    :return: A sorted-list of keys
    """
    # groupcompress ordering is approximately reverse topological,
    # properly grouped by file-id.
    per_prefix_map = {}
    for item in parent_map.iteritems():
        key = item[0]
        if isinstance(key, str) or len(key) == 1:
            prefix = ''
        else:
            prefix = key[0]
        try:
            per_prefix_map[prefix].append(item)
        except KeyError:
            per_prefix_map[prefix] = [item]

    present_keys = []
    for prefix in sorted(per_prefix_map):
        present_keys.extend(reversed(topo_sort(per_prefix_map[prefix])))
    return present_keys


class GroupCompressBlockEntry(object):
    """Track the information about a single object inside a GC group.

    This is generally just the dumb data structure.
    """

    def __init__(self, key, type, sha1, start, length):
        self.key = key
        self.type = type # delta, fulltext, external?
        self.sha1 = sha1 # Sha1 of content
        self.start = start # Byte offset to start of data
        self.length = length # Length of content

    def __repr__(self):
        return '%s(%s, %s, %s, %s, %s)' % (
            self.__class__.__name__,
            self.key, self.type, self.sha1, self.start, self.length
            )


class GroupCompressBlock(object):
    """An object which maintains the internal structure of the compressed data.

    This tracks the meta info (start of text, length, type, etc.)
    """

    # Group Compress Block v1 Zlib
    GCB_HEADER = 'gcb1z\n'
    GCB_LZ_HEADER = 'gcb1l\n'

    def __init__(self):
        # map by key? or just order in file?
        self._entries = {}
        self._content = None
        self._size = 0

    def _parse_header(self):
        """Parse the meta-info from the stream."""

    def __len__(self):
        return self._size

    def _parse_header_bytes(self, header_bytes):
        """Parse the header part of the block."""
        if _NO_LABELS:
            # Don't parse the label structure if we aren't going to use it
            return
        lines = header_bytes.split('\n')
        info_dict = {}
        for line in lines:
            if not line: #End of record
                if not info_dict:
                    break
                self.add_entry(**info_dict)
                info_dict = {}
                continue
            key, value = line.split(':', 1)
            if key == 'key':
                value = tuple(map(intern, value.split('\x00')))
            elif key in ('start', 'length'):
                value = int(value)
            elif key == 'type':
                value = intern(value)
            info_dict[key] = value

    @classmethod
    def from_bytes(cls, bytes):
        out = cls()
        if bytes[:6] not in (cls.GCB_HEADER, cls.GCB_LZ_HEADER):
            raise ValueError('bytes did not start with %r' % (cls.GCB_HEADER,))
        if bytes[4] == 'z':
            decomp = zlib.decompress
        elif bytes[4] == 'l':
            decomp = pylzma.decompress
        else:
            raise ValueError('unknown compressor: %r' % (bytes,))
        pos = bytes.index('\n', 6)
        z_header_length = int(bytes[6:pos])
        pos += 1
        pos2 = bytes.index('\n', pos)
        header_length = int(bytes[pos:pos2])
        if z_header_length == 0:
            if header_length != 0:
                raise ValueError('z_header_length 0, but header length != 0')
            zcontent = bytes[pos2+1:]
            if zcontent:
                out._content = decomp(zcontent)
                out._size = len(out._content)
            return out
        pos = pos2 + 1
        pos2 = pos + z_header_length
        z_header_bytes = bytes[pos:pos2]
        if len(z_header_bytes) != z_header_length:
            raise ValueError('Wrong length of compressed header. %s != %s'
                             % (len(z_header_bytes), z_header_length))
        header_bytes = decomp(z_header_bytes)
        if len(header_bytes) != header_length:
            raise ValueError('Wrong length of header. %s != %s'
                             % (len(header_bytes), header_length))
        del z_header_bytes
        out._parse_header_bytes(header_bytes)
        del header_bytes
        zcontent = bytes[pos2:]
        if zcontent:
            out._content = decomp(zcontent)
            out._size = header_length + len(out._content)
        return out

    def extract(self, key, index_memo, sha1=None):
        """Extract the text for a specific key.

        :param key: The label used for this content
        :param sha1: TODO (should we validate only when sha1 is supplied?)
        :return: The bytes for the content
        """
        if _NO_LABELS or not self._entries:
            start, end = index_memo[3:5]
            # The bytes are 'f' or 'd' for the type, then a variable-length
            # base128 integer for the content size, then the actual content
            # We know that the variable-length integer won't be longer than 10
            # bytes (it only takes 5 bytes to encode 2^32)
            c = self._content[start]
            if c == 'f':
                type = 'fulltext'
            else:
                if c != 'd':
                    raise ValueError('Unknown content control code: %s'
                                     % (c,))
                type = 'delta'
            entry = GroupCompressBlockEntry(key, type, sha1=None,
                                            start=start, length=end-start)
        else:
            entry = self._entries[key]
            c = self._content[entry.start]
            if entry.type == 'fulltext':
                if c != 'f':
                    raise ValueError('Label claimed fulltext, byte claims: %s'
                                     % (c,))
            elif entry.type == 'delta':
                if c != 'd':
                    raise ValueError('Label claimed delta, byte claims: %s'
                                     % (c,))
            start = entry.start
        content_len, len_len = decode_base128_int(
                            self._content[entry.start + 1:entry.start + 11])
        content_start = entry.start + 1 + len_len
        end = entry.start + entry.length
        content = self._content[content_start:end]
        if c == 'f':
            bytes = content
        elif c == 'd':
            bytes = _groupcompress_pyx.apply_delta(self._content, content)
        if entry.sha1 is None:
            entry.sha1 = sha_string(bytes)
        return entry, bytes

    def add_entry(self, key, type, sha1, start, length):
        """Add new meta info about an entry.

        :param key: The key for the new content
        :param type: Whether this is a delta or fulltext entry (external?)
        :param sha1: sha1sum of the fulltext of this entry
        :param start: where the encoded bytes start
        :param length: total number of bytes in the encoded form
        :return: The entry?
        """
        entry = GroupCompressBlockEntry(key, type, sha1, start, length)
        if key in self._entries:
            raise ValueError('Duplicate key found: %s' % (key,))
        self._entries[key] = entry
        return entry

    def to_bytes(self, content=''):
        """Encode the information into a byte stream."""
        compress = zlib.compress
        if _USE_LZMA:
            compress = pylzma.compress
        chunks = []
        for key in sorted(self._entries):
            entry = self._entries[key]
            chunk = ('key:%s\n'
                     'sha1:%s\n'
                     'type:%s\n'
                     'start:%s\n'
                     'length:%s\n'
                     '\n'
                     ) % ('\x00'.join(entry.key),
                          entry.sha1,
                          entry.type,
                          entry.start,
                          entry.length,
                          )
            chunks.append(chunk)
        bytes = ''.join(chunks)
        info_len = len(bytes)
        z_bytes = []
        z_bytes.append(compress(bytes))
        del bytes
        # TODO: we may want to have the header compressed in the same chain
        #       as the data, or we may not, evaulate it
        #       having them compressed together is probably a win for
        #       revisions and the 'inv' portion of chk inventories. As the
        #       label in the header is duplicated in the text.
        #       For chk pages and real bytes, I would guess this is not
        #       true.
        z_len = sum(map(len, z_bytes))
        c_len = len(content)
        if _NO_LABELS:
            z_bytes = []
            z_len = 0
            info_len = 0
        z_bytes.append(compress(content))
        if _USE_LZMA:
            header = self.GCB_LZ_HEADER
        else:
            header = self.GCB_HEADER
        chunks = [header,
                  '%d\n' % (z_len,),
                  '%d\n' % (info_len,),
                  #'%d\n' % (c_len,),
                 ]
        chunks.extend(z_bytes)
        return ''.join(chunks)


class GroupCompressor(object):
    """Produce a serialised group of compressed texts.

    It contains code very similar to SequenceMatcher because of having a similar
    task. However some key differences apply:
     - there is no junk, we want a minimal edit not a human readable diff.
     - we don't filter very common lines (because we don't know where a good
       range will start, and after the first text we want to be emitting minmal
       edits only.
     - we chain the left side, not the right side
     - we incrementally update the adjacency matrix as new lines are provided.
     - we look for matches in all of the left side, so the routine which does
       the analagous task of find_longest_match does not need to filter on the
       left side.
    """

    def __init__(self, delta=True):
        """Create a GroupCompressor.

        :param delta: If False, do not compress records.
        """
        # Consider seeding the lines with some sort of GC Start flag, or
        # putting it as part of the output stream, rather than in the
        # compressed bytes.
        self.lines = []
        self.endpoint = 0
        self.input_bytes = 0
        self.num_keys = 0
        self.labels_deltas = {}
        self._last = None
        self._delta_index = _groupcompress_pyx.DeltaIndex()
        self._block = GroupCompressBlock()

    def compress(self, key, bytes, expected_sha, nostore_sha=None, soft=False):
        """Compress lines with label key.

        :param key: A key tuple. It is stored in the output
            for identification of the text during decompression. If the last
            element is 'None' it is replaced with the sha1 of the text -
            e.g. sha1:xxxxxxx.
        :param bytes: The bytes to be compressed
        :param expected_sha: If non-None, the sha the lines are believed to
            have. During compression the sha is calculated; a mismatch will
            cause an error.
        :param nostore_sha: If the computed sha1 sum matches, we will raise
            ExistingContent rather than adding the text.
        :param soft: Do a 'soft' compression. This means that we require larger
            ranges to match to be considered for a copy command.
        :return: The sha1 of lines, and the number of bytes accumulated in
            the group output so far.
        :seealso VersionedFiles.add_lines:
        """
        if not _FAST or expected_sha is None:
            sha1 = sha_string(bytes)
        else:
            sha1 = expected_sha
        if sha1 == nostore_sha:
            raise errors.ExistingContent()
        if key[-1] is None:
            key = key[:-1] + ('sha1:' + sha1,)
        input_len = len(bytes)
        # By having action/label/sha1/len, we can parse the group if the index
        # was ever destroyed, we have the key in 'label', we know the final
        # bytes are valid from sha1, and we know where to find the end of this
        # record because of 'len'. (the delta record itself will store the
        # total length for the expanded record)
        # 'len: %d\n' costs approximately 1% increase in total data
        # Having the labels at all costs us 9-10% increase, 38% increase for
        # inventory pages, and 5.8% increase for text pages
        # new_chunks = ['label:%s\nsha1:%s\n' % (label, sha1)]
        if self._delta_index._source_offset != self.endpoint:
            raise AssertionError('_source_offset != endpoint'
                ' somehow the DeltaIndex got out of sync with'
                ' the output lines')
        max_delta_size = len(bytes) / 2
        delta = self._delta_index.make_delta(bytes, max_delta_size)
        if (delta is None):
            type = 'fulltext'
            enc_length = encode_base128_int(len(bytes))
            len_mini_header = 1 + len(enc_length)
            length = len(bytes) + len_mini_header
            self._delta_index.add_source(bytes, len_mini_header)
            new_chunks = ['f', enc_length, bytes]
        else:
            type = 'delta'
            enc_length = encode_base128_int(len(delta))
            len_mini_header = 1 + len(enc_length)
            length = len(delta) + len_mini_header
            new_chunks = ['d', enc_length, delta]
            if _FAST:
                self._delta_index._source_offset += length
            else:
                self._delta_index.add_delta_source(delta, len_mini_header)
        self._block.add_entry(key, type=type, sha1=sha1,
                              start=self.endpoint, length=length)
        delta_start = (self.endpoint, len(self.lines))
        self.num_keys += 1
        self.output_chunks(new_chunks)
        self.input_bytes += input_len
        delta_end = (self.endpoint, len(self.lines))
        self.labels_deltas[key] = (delta_start, delta_end)
        if not self._delta_index._source_offset == self.endpoint:
            raise AssertionError('the delta index is out of sync'
                'with the output lines %s != %s'
                % (self._delta_index._source_offset, self.endpoint))
        return sha1, self.endpoint, type, length

    def extract(self, key):
        """Extract a key previously added to the compressor.

        :param key: The key to extract.
        :return: An iterable over bytes and the sha1.
        """
        delta_details = self.labels_deltas[key]
        delta_chunks = self.lines[delta_details[0][1]:delta_details[1][1]]
        stored_bytes = ''.join(delta_chunks)
        # TODO: Fix this, we shouldn't really be peeking here
        entry = self._block._entries[key]
        if entry.type == 'fulltext':
            if stored_bytes[0] != 'f':
                raise ValueError('Index claimed fulltext, but stored bytes'
                                 ' indicate %s' % (stored_bytes[0],))
            fulltext_len, offset = decode_base128_int(stored_bytes[1:10])
            if fulltext_len + 1 + offset != len(stored_bytes):
                raise ValueError('Index claimed fulltext len, but stored bytes'
                                 ' claim %s != %s'
                                 % (len(stored_bytes),
                                    fulltext_len + 1 + offset))
            bytes = stored_bytes[offset + 1:]
        else:
            if entry.type != 'delta':
                raise ValueError('Unknown entry type: %s' % (entry.type,))
            # XXX: This is inefficient at best
            source = ''.join(self.lines)
            if stored_bytes[0] != 'd':
                raise ValueError('Entry type claims delta, bytes claim %s'
                                 % (stored_bytes[0],))
            delta_len, offset = decode_base128_int(stored_bytes[1:10])
            if delta_len + 1 + offset != len(stored_bytes):
                raise ValueError('Index claimed delta len, but stored bytes'
                                 ' claim %s != %s'
                                 % (len(stored_bytes),
                                    delta_len + 1 + offset))
            bytes = _groupcompress_pyx.apply_delta(source,
                                                   stored_bytes[offset + 1:])
        bytes_sha1 = sha_string(bytes)
        if entry.sha1 != bytes_sha1:
            raise ValueError('Recorded sha1 != measured %s != %s'
                             % (entry.sha1, bytes_sha1))
        return bytes, entry.sha1

    def output_chunks(self, new_chunks):
        """Output some chunks.

        :param new_chunks: The chunks to output.
        """
        self._last = (len(self.lines), self.endpoint)
        endpoint = self.endpoint
        self.lines.extend(new_chunks)
        endpoint += sum(map(len, new_chunks))
        self.endpoint = endpoint

    def pop_last(self):
        """Call this if you want to 'revoke' the last compression.

        After this, the data structures will be rolled back, but you cannot do
        more compression.
        """
        self._delta_index = None
        del self.lines[self._last[0]:]
        self.endpoint = self._last[1]
        self._last = None

    def ratio(self):
        """Return the overall compression ratio."""
        return float(self.input_bytes) / float(self.endpoint)


def make_pack_factory(graph, delta, keylength):
    """Create a factory for creating a pack based groupcompress.

    This is only functional enough to run interface tests, it doesn't try to
    provide a full pack environment.

    :param graph: Store a graph.
    :param delta: Delta compress contents.
    :param keylength: How long should keys be.
    """
    def factory(transport):
        parents = graph or delta
        ref_length = 0
        if graph:
            ref_length = 1
        graph_index = BTreeBuilder(reference_lists=ref_length,
            key_elements=keylength)
        stream = transport.open_write_stream('newpack')
        writer = pack.ContainerWriter(stream.write)
        writer.begin()
        index = _GCGraphIndex(graph_index, lambda:True, parents=parents,
            add_callback=graph_index.add_nodes)
        access = _DirectPackAccess({})
        access.set_writer(writer, graph_index, (transport, 'newpack'))
        result = GroupCompressVersionedFiles(index, access, delta)
        result.stream = stream
        result.writer = writer
        return result
    return factory


def cleanup_pack_group(versioned_files):
    versioned_files.writer.end()
    versioned_files.stream.close()


class GroupCompressVersionedFiles(VersionedFiles):
    """A group-compress based VersionedFiles implementation."""

    def __init__(self, index, access, delta=True):
        """Create a GroupCompressVersionedFiles object.

        :param index: The index object storing access and graph data.
        :param access: The access object storing raw data.
        :param delta: Whether to delta compress or just entropy compress.
        """
        self._index = index
        self._access = access
        self._delta = delta
        self._unadded_refs = {}
        self._group_cache = LRUSizeCache(max_size=50*1024*1024)
        self._fallback_vfs = []

    def add_lines(self, key, parents, lines, parent_texts=None,
        left_matching_blocks=None, nostore_sha=None, random_id=False,
        check_content=True):
        """Add a text to the store.

        :param key: The key tuple of the text to add.
        :param parents: The parents key tuples of the text to add.
        :param lines: A list of lines. Each line must be a bytestring. And all
            of them except the last must be terminated with \n and contain no
            other \n's. The last line may either contain no \n's or a single
            terminating \n. If the lines list does meet this constraint the add
            routine may error or may succeed - but you will be unable to read
            the data back accurately. (Checking the lines have been split
            correctly is expensive and extremely unlikely to catch bugs so it
            is not done at runtime unless check_content is True.)
        :param parent_texts: An optional dictionary containing the opaque
            representations of some or all of the parents of version_id to
            allow delta optimisations.  VERY IMPORTANT: the texts must be those
            returned by add_lines or data corruption can be caused.
        :param left_matching_blocks: a hint about which areas are common
            between the text and its left-hand-parent.  The format is
            the SequenceMatcher.get_matching_blocks format.
        :param nostore_sha: Raise ExistingContent and do not add the lines to
            the versioned file if the digest of the lines matches this.
        :param random_id: If True a random id has been selected rather than
            an id determined by some deterministic process such as a converter
            from a foreign VCS. When True the backend may choose not to check
            for uniqueness of the resulting key within the versioned file, so
            this should only be done when the result is expected to be unique
            anyway.
        :param check_content: If True, the lines supplied are verified to be
            bytestrings that are correctly formed lines.
        :return: The text sha1, the number of bytes in the text, and an opaque
                 representation of the inserted version which can be provided
                 back to future add_lines calls in the parent_texts dictionary.
        """
        self._index._check_write_ok()
        self._check_add(key, lines, random_id, check_content)
        if parents is None:
            # The caller might pass None if there is no graph data, but kndx
            # indexes can't directly store that, so we give them
            # an empty tuple instead.
            parents = ()
        # double handling for now. Make it work until then.
        length = sum(map(len, lines))
        record = ChunkedContentFactory(key, parents, None, lines)
        sha1 = list(self._insert_record_stream([record], random_id=random_id,
                                               nostore_sha=nostore_sha))[0]
        return sha1, length, None

    def add_fallback_versioned_files(self, a_versioned_files):
        """Add a source of texts for texts not present in this knit.

        :param a_versioned_files: A VersionedFiles object.
        """
        self._fallback_vfs.append(a_versioned_files)

    def annotate(self, key):
        """See VersionedFiles.annotate."""
        graph = Graph(self)
        parent_map = self.get_parent_map([key])
        if not parent_map:
            raise errors.RevisionNotPresent(key, self)
        if parent_map[key] is not None:
            search = graph._make_breadth_first_searcher([key])
            keys = set()
            while True:
                try:
                    present, ghosts = search.next_with_ghosts()
                except StopIteration:
                    break
                keys.update(present)
            parent_map = self.get_parent_map(keys)
        else:
            keys = [key]
            parent_map = {key:()}
        head_cache = _mod_graph.FrozenHeadsCache(graph)
        parent_cache = {}
        reannotate = annotate.reannotate
        for record in self.get_record_stream(keys, 'topological', True):
            key = record.key
            chunks = osutils.chunks_to_lines(record.get_bytes_as('chunked'))
            parent_lines = [parent_cache[parent] for parent in parent_map[key]]
            parent_cache[key] = list(
                reannotate(parent_lines, chunks, key, None, head_cache))
        return parent_cache[key]

    def check(self, progress_bar=None):
        """See VersionedFiles.check()."""
        keys = self.keys()
        for record in self.get_record_stream(keys, 'unordered', True):
            record.get_bytes_as('fulltext')

    def _check_add(self, key, lines, random_id, check_content):
        """check that version_id and lines are safe to add."""
        version_id = key[-1]
        if version_id is not None:
            if contains_whitespace(version_id):
                raise errors.InvalidRevisionId(version_id, self)
        self.check_not_reserved_id(version_id)
        # TODO: If random_id==False and the key is already present, we should
        # probably check that the existing content is identical to what is
        # being inserted, and otherwise raise an exception.  This would make
        # the bundle code simpler.
        if check_content:
            self._check_lines_not_unicode(lines)
            self._check_lines_are_lines(lines)

    def get_parent_map(self, keys):
        """Get a map of the graph parents of keys.

        :param keys: The keys to look up parents for.
        :return: A mapping from keys to parents. Absent keys are absent from
            the mapping.
        """
        return self._get_parent_map_with_sources(keys)[0]

    def _get_parent_map_with_sources(self, keys):
        """Get a map of the parents of keys.

        :param keys: The keys to look up parents for.
        :return: A tuple. The first element is a mapping from keys to parents.
            Absent keys are absent from the mapping. The second element is a
            list with the locations each key was found in. The first element
            is the in-this-knit parents, the second the first fallback source,
            and so on.
        """
        result = {}
        sources = [self._index] + self._fallback_vfs
        source_results = []
        missing = set(keys)
        for source in sources:
            if not missing:
                break
            new_result = source.get_parent_map(missing)
            source_results.append(new_result)
            result.update(new_result)
            missing.difference_update(set(new_result))
        return result, source_results

    def _get_block(self, index_memo):
        read_memo = index_memo[0:3]
        # get the group:
        try:
            block = self._group_cache[read_memo]
        except KeyError:
            # read the group
            zdata = self._access.get_raw_records([read_memo]).next()
            # decompress - whole thing - this is not a bug, as it
            # permits caching. We might want to store the partially
            # decompresed group and decompress object, so that recent
            # texts are not penalised by big groups.
            block = GroupCompressBlock.from_bytes(zdata)
            self._group_cache[read_memo] = block
        # cheapo debugging:
        # print len(zdata), len(plain)
        # parse - requires split_lines, better to have byte offsets
        # here (but not by much - we only split the region for the
        # recipe, and we often want to end up with lines anyway.
        return block

    def get_missing_compression_parent_keys(self):
        """Return the keys of missing compression parents.

        Missing compression parents occur when a record stream was missing
        basis texts, or a index was scanned that had missing basis texts.
        """
        # GroupCompress cannot currently reference texts that are not in the
        # group, so this is valid for now
        return frozenset()

    def get_record_stream(self, keys, ordering, include_delta_closure):
        """Get a stream of records for keys.

        :param keys: The keys to include.
        :param ordering: Either 'unordered' or 'topological'. A topologically
            sorted stream has compression parents strictly before their
            children.
        :param include_delta_closure: If True then the closure across any
            compression parents will be included (in the opaque data).
        :return: An iterator of ContentFactory objects, each of which is only
            valid until the iterator is advanced.
        """
        # keys might be a generator
        orig_keys = list(keys)
        keys = set(keys)
        if not keys:
            return
        if (not self._index.has_graph
            and ordering in ('topological', 'groupcompress')):
            # Cannot topological order when no graph has been stored.
            # but we allow 'as-requested' or 'unordered'
            ordering = 'unordered'

        remaining_keys = keys
        while True:
            try:
                keys = set(remaining_keys)
                for content_factory in self._get_remaining_record_stream(keys,
                        orig_keys, ordering, include_delta_closure):
                    remaining_keys.discard(content_factory.key)
                    yield content_factory
                return
            except errors.RetryWithNewPacks, e:
                self._access.reload_or_raise(e)

    def _find_from_fallback(self, missing):
        """Find whatever keys you can from the fallbacks.

        :param missing: A set of missing keys. This set will be mutated as keys
            are found from a fallback_vfs
        :return: (parent_map, key_to_source_map, source_results)
            parent_map  the overall key => parent_keys
            key_to_source_map   a dict from {key: source}
            source_results      a list of (source: keys)
        """
        parent_map = {}
        key_to_source_map = {}
        source_results = []
        for source in self._fallback_vfs:
            if not missing:
                break
            source_parents = source.get_parent_map(missing)
            parent_map.update(source_parents)
            source_parents = list(source_parents)
            source_results.append((source, source_parents))
            key_to_source_map.update((key, source) for key in source_parents)
            missing.difference_update(source_parents)
        return parent_map, key_to_source_map, source_results

    def _get_ordered_source_keys(self, ordering, parent_map, key_to_source_map):
        """Get the (source, [keys]) list.

        The returned objects should be in the order defined by 'ordering',
        which can weave between different sources.
        :param ordering: Must be one of 'topological' or 'groupcompress'
        :return: List of [(source, [keys])] tuples, such that all keys are in
            the defined order, regardless of source.
        """
        if ordering == 'topological':
            present_keys = topo_sort(parent_map)
        else:
            # ordering == 'groupcompress'
            # XXX: This only optimizes for the target ordering. We may need
            #      to balance that with the time it takes to extract
            #      ordering, by somehow grouping based on
            #      locations[key][0:3]
            present_keys = sort_gc_optimal(parent_map)
        # Now group by source:
        source_keys = []
        current_source = None
        for key in present_keys:
            source = key_to_source_map.get(key, self)
            if source is not current_source:
                source_keys.append((source, []))
            source_keys[-1][1].append(key)
        return source_keys

    def _get_as_requested_source_keys(self, orig_keys, locations, unadded_keys,
                                      key_to_source_map):
        source_keys = []
        current_source = None
        for key in orig_keys:
            if key in locations or key in unadded_keys:
                source = self
            elif key in key_to_source_map:
                source = key_to_source_map[key]
            else: # absent
                continue
            if source is not current_source:
                source_keys.append((source, []))
            source_keys[-1][1].append(key)
        return source_keys

    def _get_io_ordered_source_keys(self, locations, unadded_keys,
                                    source_result):
        def get_group(key):
            # This is the group the bytes are stored in, followed by the
            # location in the group
            return locations[key][0]
        present_keys = sorted(locations.iterkeys(), key=get_group)
        # We don't have an ordering for keys in the in-memory object, but
        # lets process the in-memory ones first.
        present_keys = list(unadded_keys) + present_keys
        # Now grab all of the ones from other sources
        source_keys = [(self, present_keys)]
        source_keys.extend(source_result)
        return source_keys

    def _get_remaining_record_stream(self, keys, orig_keys, ordering,
                                     include_delta_closure):
        """Get a stream of records for keys.

        :param keys: The keys to include.
        :param ordering: one of 'unordered', 'topological', 'groupcompress' or
            'as-requested'
        :param include_delta_closure: If True then the closure across any
            compression parents will be included (in the opaque data).
        :return: An iterator of ContentFactory objects, each of which is only
            valid until the iterator is advanced.
        """
        # Cheap: iterate
        locations = self._index.get_build_details(keys)
        unadded_keys = set(self._unadded_refs).intersection(keys)
        missing = keys.difference(locations)
        missing.difference_update(unadded_keys)
        (fallback_parent_map, key_to_source_map,
         source_result) = self._find_from_fallback(missing)
        if ordering in ('topological', 'groupcompress'):
            # would be better to not globally sort initially but instead
            # start with one key, recurse to its oldest parent, then grab
            # everything in the same group, etc.
            parent_map = dict((key, details[2]) for key, details in
                locations.iteritems())
            for key in unadded_keys:
                parent_map[key] = self._unadded_refs[key]
            parent_map.update(fallback_parent_map)
            source_keys = self._get_ordered_source_keys(ordering, parent_map,
                                                        key_to_source_map)
        elif ordering == 'as-requested':
            source_keys = self._get_as_requested_source_keys(orig_keys,
                locations, unadded_keys, key_to_source_map)
        else:
            # We want to yield the keys in a semi-optimal (read-wise) ordering.
            # Otherwise we thrash the _group_cache and destroy performance
            source_keys = self._get_io_ordered_source_keys(locations,
                unadded_keys, source_result)
        for key in missing:
            yield AbsentContentFactory(key)
        for source, keys in source_keys:
            if source is self:
                for key in keys:
                    if key in self._unadded_refs:
                        bytes, sha1 = self._compressor.extract(key)
                        parents = self._unadded_refs[key]
                    else:
                        index_memo, _, parents, (method, _) = locations[key]
                        block = self._get_block(index_memo)
                        entry, bytes = block.extract(key, index_memo)
                        sha1 = entry.sha1
                        # TODO: If we don't have labels, then the sha1 here is computed
                        #       from the data, so we don't want to re-sha the string.
                        if not _FAST and sha_string(bytes) != sha1:
                            raise AssertionError('sha1 sum did not match')
                    yield FulltextContentFactory(key, parents, sha1, bytes)
            else:
                for record in source.get_record_stream(keys, ordering,
                                                       include_delta_closure):
                    yield record

    def get_sha1s(self, keys):
        """See VersionedFiles.get_sha1s()."""
        result = {}
        for record in self.get_record_stream(keys, 'unordered', True):
            if record.sha1 != None:
                result[record.key] = record.sha1
            else:
                if record.storage_kind != 'absent':
                    result[record.key] == sha_string(record.get_bytes_as(
                        'fulltext'))
        return result

    def insert_record_stream(self, stream):
        """Insert a record stream into this container.

        :param stream: A stream of records to insert.
        :return: None
        :seealso VersionedFiles.get_record_stream:
        """
        for _ in self._insert_record_stream(stream):
            pass

    def _insert_record_stream(self, stream, random_id=False, nostore_sha=None):
        """Internal core to insert a record stream into this container.

        This helper function has a different interface than insert_record_stream
        to allow add_lines to be minimal, but still return the needed data.

        :param stream: A stream of records to insert.
        :param nostore_sha: If the sha1 of a given text matches nostore_sha,
            raise ExistingContent, rather than committing the new text.
        :return: An iterator over the sha1 of the inserted records.
        :seealso insert_record_stream:
        :seealso add_lines:
        """
        adapters = {}
        def get_adapter(adapter_key):
            try:
                return adapters[adapter_key]
            except KeyError:
                adapter_factory = adapter_registry.get(adapter_key)
                adapter = adapter_factory(self)
                adapters[adapter_key] = adapter
                return adapter
        # This will go up to fulltexts for gc to gc fetching, which isn't
        # ideal.
        self._compressor = GroupCompressor(self._delta)
        self._unadded_refs = {}
        keys_to_add = []
        basis_end = 0
        def flush():
            bytes = self._compressor._block.to_bytes(
                ''.join(self._compressor.lines))
            index, start, length = self._access.add_raw_records(
                [(None, len(bytes))], bytes)[0]
            nodes = []
            for key, reads, refs in keys_to_add:
                nodes.append((key, "%d %d %s" % (start, length, reads), refs))
            self._index.add_records(nodes, random_id=random_id)
            self._unadded_refs = {}
            del keys_to_add[:]
            self._compressor = GroupCompressor(self._delta)

        last_prefix = None
        last_fulltext_len = None
        max_fulltext_len = 0
        max_fulltext_prefix = None
        for record in stream:
            # Raise an error when a record is missing.
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent(record.key, self)
            try:
                bytes = record.get_bytes_as('fulltext')
            except errors.UnavailableRepresentation:
                adapter_key = record.storage_kind, 'fulltext'
                adapter = get_adapter(adapter_key)
                bytes = adapter.get_bytes(record)
            if len(record.key) > 1:
                prefix = record.key[0]
                soft = (prefix == last_prefix)
            else:
                prefix = None
                soft = False
            if max_fulltext_len < len(bytes):
                max_fulltext_len = len(bytes)
                max_fulltext_prefix = prefix
            (found_sha1, end_point, type,
             length) = self._compressor.compress(record.key,
                bytes, record.sha1, soft=soft,
                nostore_sha=nostore_sha)
            # delta_ratio = float(len(bytes)) / length
            # Check if we want to continue to include that text
            if (prefix == max_fulltext_prefix
                and end_point < 2 * max_fulltext_len):
                # As long as we are on the same file_id, we will fill at least
                # 2 * max_fulltext_len
                start_new_block = False
            elif end_point > 4*1024*1024:
                start_new_block = True
            elif (prefix is not None and prefix != last_prefix
                  and end_point > 2*1024*1024):
                start_new_block = True
            else:
                start_new_block = False
            # if type == 'fulltext':
            #     # If this is the first text, we don't do anything
            #     if self._compressor.num_keys > 1:
            #         if prefix is not None and prefix != last_prefix:
            #             # We just inserted a fulltext for a different prefix
            #             # (aka file-id).
            #             if end_point > 512 * 1024:
            #                 start_new_block = True
            #             # TODO: Consider packing several small texts together
            #             #       maybe only flush if end_point > some threshold
            #             # if end_point > 512 * 1024 or len(bytes) <
            #             #     start_new_block = true
            #         else:
            #             # We just added a fulltext, part of the same file-id
            #             if (end_point > 2*1024*1024
            #                 and end_point > 5*max_fulltext_len):
            #                 start_new_block = True
            #     last_fulltext_len = len(bytes)
            # else:
            #     delta_ratio = float(len(bytes)) / length
            #     if delta_ratio < 3: # Not much compression
            #         if end_point > 1*1024*1024:
            #             start_new_block = True
            #     elif delta_ratio < 10: # 10:1 compression
            #         if end_point > 4*1024*1024:
            #             start_new_block = True
            last_prefix = prefix
            if start_new_block:
                self._compressor.pop_last()
                flush()
                basis_end = 0
                max_fulltext_len = len(bytes)
                (found_sha1, end_point, type,
                 length) = self._compressor.compress(record.key,
                    bytes, record.sha1)
                last_fulltext_len = length
            if record.key[-1] is None:
                key = record.key[:-1] + ('sha1:' + found_sha1,)
            else:
                key = record.key
            self._unadded_refs[key] = record.parents
            yield found_sha1
            keys_to_add.append((key, '%d %d' % (basis_end, end_point),
                (record.parents,)))
            basis_end = end_point
        if len(keys_to_add):
            flush()
        self._compressor = None

    def iter_lines_added_or_present_in_keys(self, keys, pb=None):
        """Iterate over the lines in the versioned files from keys.

        This may return lines from other keys. Each item the returned
        iterator yields is a tuple of a line and a text version that that line
        is present in (not introduced in).

        Ordering of results is in whatever order is most suitable for the
        underlying storage format.

        If a progress bar is supplied, it may be used to indicate progress.
        The caller is responsible for cleaning up progress bars (because this
        is an iterator).

        NOTES:
         * Lines are normalised by the underlying store: they will all have \n
           terminators.
         * Lines are returned in arbitrary order.

        :return: An iterator over (line, key).
        """
        if pb is None:
            pb = progress.DummyProgress()
        keys = set(keys)
        total = len(keys)
        # we don't care about inclusions, the caller cares.
        # but we need to setup a list of records to visit.
        # we need key, position, length
        for key_idx, record in enumerate(self.get_record_stream(keys,
            'unordered', True)):
            # XXX: todo - optimise to use less than full texts.
            key = record.key
            pb.update('Walking content.', key_idx, total)
            if record.storage_kind == 'absent':
                raise errors.RevisionNotPresent(key, self)
            lines = split_lines(record.get_bytes_as('fulltext'))
            for line in lines:
                yield line, key
        pb.update('Walking content.', total, total)

    def keys(self):
        """See VersionedFiles.keys."""
        if 'evil' in debug.debug_flags:
            trace.mutter_callsite(2, "keys scales with size of history")
        sources = [self._index] + self._fallback_vfs
        result = set()
        for source in sources:
            result.update(source.keys())
        return result


class _GCGraphIndex(object):
    """Mapper from GroupCompressVersionedFiles needs into GraphIndex storage."""

    def __init__(self, graph_index, is_locked, parents=True,
        add_callback=None):
        """Construct a _GCGraphIndex on a graph_index.

        :param graph_index: An implementation of bzrlib.index.GraphIndex.
        :param is_locked: A callback, returns True if the index is locked and
            thus usable.
        :param parents: If True, record knits parents, if not do not record
            parents.
        :param add_callback: If not None, allow additions to the index and call
            this callback with a list of added GraphIndex nodes:
            [(node, value, node_refs), ...]
        """
        self._add_callback = add_callback
        self._graph_index = graph_index
        self._parents = parents
        self.has_graph = parents
        self._is_locked = is_locked

    def add_records(self, records, random_id=False):
        """Add multiple records to the index.

        This function does not insert data into the Immutable GraphIndex
        backing the KnitGraphIndex, instead it prepares data for insertion by
        the caller and checks that it is safe to insert then calls
        self._add_callback with the prepared GraphIndex nodes.

        :param records: a list of tuples:
                         (key, options, access_memo, parents).
        :param random_id: If True the ids being added were randomly generated
            and no check for existence will be performed.
        """
        if not self._add_callback:
            raise errors.ReadOnlyError(self)
        # we hope there are no repositories with inconsistent parentage
        # anymore.

        changed = False
        keys = {}
        for (key, value, refs) in records:
            if not self._parents:
                if refs:
                    for ref in refs:
                        if ref:
                            raise KnitCorrupt(self,
                                "attempt to add node with parents "
                                "in parentless index.")
                    refs = ()
                    changed = True
            keys[key] = (value, refs)
        # check for dups
        if not random_id:
            present_nodes = self._get_entries(keys)
            for (index, key, value, node_refs) in present_nodes:
                if node_refs != keys[key][1]:
                    raise errors.KnitCorrupt(self, "inconsistent details in add_records"
                        ": %s %s" % ((value, node_refs), keys[key]))
                del keys[key]
                changed = True
        if changed:
            result = []
            if self._parents:
                for key, (value, node_refs) in keys.iteritems():
                    result.append((key, value, node_refs))
            else:
                for key, (value, node_refs) in keys.iteritems():
                    result.append((key, value))
            records = result
        self._add_callback(records)

    def _check_read(self):
        """Raise an exception if reads are not permitted."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)

    def _check_write_ok(self):
        """Raise an exception if writes are not permitted."""
        if not self._is_locked():
            raise errors.ObjectNotLocked(self)

    def _get_entries(self, keys, check_present=False):
        """Get the entries for keys.

        Note: Callers are responsible for checking that the index is locked
        before calling this method.

        :param keys: An iterable of index key tuples.
        """
        keys = set(keys)
        found_keys = set()
        if self._parents:
            for node in self._graph_index.iter_entries(keys):
                yield node
                found_keys.add(node[1])
        else:
            # adapt parentless index to the rest of the code.
            for node in self._graph_index.iter_entries(keys):
                yield node[0], node[1], node[2], ()
                found_keys.add(node[1])
        if check_present:
            missing_keys = keys.difference(found_keys)
            if missing_keys:
                raise RevisionNotPresent(missing_keys.pop(), self)

    def get_parent_map(self, keys):
        """Get a map of the parents of keys.

        :param keys: The keys to look up parents for.
        :return: A mapping from keys to parents. Absent keys are absent from
            the mapping.
        """
        self._check_read()
        nodes = self._get_entries(keys)
        result = {}
        if self._parents:
            for node in nodes:
                result[node[1]] = node[3][0]
        else:
            for node in nodes:
                result[node[1]] = None
        return result

    def get_build_details(self, keys):
        """Get the various build details for keys.

        Ghosts are omitted from the result.

        :param keys: An iterable of keys.
        :return: A dict of key:
            (index_memo, compression_parent, parents, record_details).
            index_memo
                opaque structure to pass to read_records to extract the raw
                data
            compression_parent
                Content that this record is built upon, may be None
            parents
                Logical parents of this node
            record_details
                extra information about the content which needs to be passed to
                Factory.parse_record
        """
        self._check_read()
        result = {}
        entries = self._get_entries(keys)
        for entry in entries:
            key = entry[1]
            if not self._parents:
                parents = None
            else:
                parents = entry[3][0]
            method = 'group'
            result[key] = (self._node_to_position(entry),
                                  None, parents, (method, None))
        return result

    def keys(self):
        """Get all the keys in the collection.

        The keys are not ordered.
        """
        self._check_read()
        return [node[1] for node in self._graph_index.iter_all_entries()]

    def _node_to_position(self, node):
        """Convert an index value to position details."""
        bits = node[2].split(' ')
        # It would be nice not to read the entire gzip.
        start = int(bits[0])
        stop = int(bits[1])
        basis_end = int(bits[2])
        delta_end = int(bits[3])
        return node[0], start, stop, basis_end, delta_end


try:
    from bzrlib import _groupcompress_pyx
except ImportError:
    pass
