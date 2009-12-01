# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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

import cStringIO
import re

from bzrlib import (
    cache_utf8,
    errors,
    inventory,
    revision as _mod_revision,
    trace,
    )
from bzrlib.xml_serializer import (
    Element,
    SubElement,
    XMLSerializer,
    escape_invalid_chars,
    )
from bzrlib.inventory import ROOT_ID, Inventory, InventoryEntry
from bzrlib.revision import Revision
from bzrlib.errors import BzrError


_utf8_re = None
_unicode_re = None
_xml_escape_map = {
    "&":'&amp;',
    "'":"&apos;", # FIXME: overkill
    "\"":"&quot;",
    "<":"&lt;",
    ">":"&gt;",
    }


def _ensure_utf8_re():
    """Make sure the _utf8_re and _unicode_re regexes have been compiled."""
    global _utf8_re, _unicode_re
    if _utf8_re is None:
        _utf8_re = re.compile('[&<>\'\"]|[\x80-\xff]+')
    if _unicode_re is None:
        _unicode_re = re.compile(u'[&<>\'\"\u0080-\uffff]')


def _unicode_escape_replace(match, _map=_xml_escape_map):
    """Replace a string of non-ascii, non XML safe characters with their escape

    This will escape both Standard XML escapes, like <>"', etc.
    As well as escaping non ascii characters, because ElementTree did.
    This helps us remain compatible to older versions of bzr. We may change
    our policy in the future, though.
    """
    # jam 20060816 Benchmarks show that try/KeyError is faster if you
    # expect the entity to rarely miss. There is about a 10% difference
    # in overall time. But if you miss frequently, then if None is much
    # faster. For our use case, we *rarely* have a revision id, file id
    # or path name that is unicode. So use try/KeyError.
    try:
        return _map[match.group()]
    except KeyError:
        return "&#%d;" % ord(match.group())


def _utf8_escape_replace(match, _map=_xml_escape_map):
    """Escape utf8 characters into XML safe ones.

    This uses 2 tricks. It is either escaping "standard" characters, like "&<>,
    or it is handling characters with the high-bit set. For ascii characters,
    we just lookup the replacement in the dictionary. For everything else, we
    decode back into Unicode, and then use the XML escape code.
    """
    try:
        return _map[match.group()]
    except KeyError:
        return ''.join('&#%d;' % ord(uni_chr)
                       for uni_chr in match.group().decode('utf8'))


_to_escaped_map = {}

def _encode_and_escape(unicode_or_utf8_str, _map=_to_escaped_map):
    """Encode the string into utf8, and escape invalid XML characters"""
    # We frequently get entities we have not seen before, so it is better
    # to check if None, rather than try/KeyError
    text = _map.get(unicode_or_utf8_str)
    if text is None:
        if unicode_or_utf8_str.__class__ is unicode:
            # The alternative policy is to do a regular UTF8 encoding
            # and then escape only XML meta characters.
            # Performance is equivalent once you use cache_utf8. *However*
            # this makes the serialized texts incompatible with old versions
            # of bzr. So no net gain. (Perhaps the read code would handle utf8
            # better than entity escapes, but cElementTree seems to do just fine
            # either way)
            text = str(_unicode_re.sub(_unicode_escape_replace,
                                       unicode_or_utf8_str)) + '"'
        else:
            # Plain strings are considered to already be in utf-8 so we do a
            # slightly different method for escaping.
            text = _utf8_re.sub(_utf8_escape_replace,
                                unicode_or_utf8_str) + '"'
        _map[unicode_or_utf8_str] = text
    return text


def _get_utf8_or_ascii(a_str,
                       _encode_utf8=cache_utf8.encode,
                       _get_cached_ascii=cache_utf8.get_cached_ascii):
    """Return a cached version of the string.

    cElementTree will return a plain string if the XML is plain ascii. It only
    returns Unicode when it needs to. We want to work in utf-8 strings. So if
    cElementTree returns a plain string, we can just return the cached version.
    If it is Unicode, then we need to encode it.

    :param a_str: An 8-bit string or Unicode as returned by
                  cElementTree.Element.get()
    :return: A utf-8 encoded 8-bit string.
    """
    # This is fairly optimized because we know what cElementTree does, this is
    # not meant as a generic function for all cases. Because it is possible for
    # an 8-bit string to not be ascii or valid utf8.
    if a_str.__class__ is unicode:
        return _encode_utf8(a_str)
    else:
        return intern(a_str)


def _clear_cache():
    """Clean out the unicode => escaped map"""
    _to_escaped_map.clear()


class Serializer_v8(XMLSerializer):
    """This serialiser adds rich roots.

    Its revision format number matches its inventory number.
    """

    __slots__ = []

    root_id = None
    support_altered_by_hack = True
    # This format supports the altered-by hack that reads file ids directly out
    # of the versionedfile, without doing XML parsing.

    supported_kinds = set(['file', 'directory', 'symlink'])
    format_num = '8'
    revision_format_num = None

    def _check_revisions(self, inv):
        """Extension point for subclasses to check during serialisation.

        :param inv: An inventory about to be serialised, to be checked.
        :raises: AssertionError if an error has occurred.
        """
        if inv.revision_id is None:
            raise AssertionError("inv.revision_id is None")
        if inv.root.revision is None:
            raise AssertionError("inv.root.revision is None")

    def _check_cache_size(self, inv_size, entry_cache):
        """Check that the entry_cache is large enough.

        We want the cache to be ~2x the size of an inventory. The reason is
        because we use a FIFO cache, and how Inventory records are likely to
        change. In general, you have a small number of records which change
        often, and a lot of records which do not change at all. So when the
        cache gets full, you actually flush out a lot of the records you are
        interested in, which means you need to recreate all of those records.
        An LRU Cache would be better, but the overhead negates the cache
        coherency benefit.

        One way to look at it, only the size of the cache > len(inv) is your
        'working' set. And in general, it shouldn't be a problem to hold 2
        inventories in memory anyway.

        :param inv_size: The number of entries in an inventory.
        """
        if entry_cache is None:
            return
        # 1.5 times might also be reasonable.
        recommended_min_cache_size = inv_size * 1.5
        if entry_cache.cache_size() < recommended_min_cache_size:
            recommended_cache_size = inv_size * 2
            trace.mutter('Resizing the inventory entry cache from %d to %d',
                         entry_cache.cache_size(), recommended_cache_size)
            entry_cache.resize(recommended_cache_size)

    def write_inventory_to_lines(self, inv):
        """Return a list of lines with the encoded inventory."""
        return self.write_inventory(inv, None)

    def write_inventory_to_string(self, inv, working=False):
        """Just call write_inventory with a StringIO and return the value.

        :param working: If True skip history data - text_sha1, text_size,
            reference_revision, symlink_target.
        """
        sio = cStringIO.StringIO()
        self.write_inventory(inv, sio, working)
        return sio.getvalue()

    def write_inventory(self, inv, f, working=False):
        """Write inventory to a file.

        :param inv: the inventory to write.
        :param f: the file to write. (May be None if the lines are the desired
            output).
        :param working: If True skip history data - text_sha1, text_size,
            reference_revision, symlink_target.
        :return: The inventory as a list of lines.
        """
        _ensure_utf8_re()
        self._check_revisions(inv)
        output = []
        append = output.append
        self._append_inventory_root(append, inv)
        entries = inv.iter_entries()
        # Skip the root
        root_path, root_ie = entries.next()
        for path, ie in entries:
            if ie.parent_id != self.root_id:
                parent_str = ' parent_id="'
                parent_id  = _encode_and_escape(ie.parent_id)
            else:
                parent_str = ''
                parent_id  = ''
            if ie.kind == 'file':
                if ie.executable:
                    executable = ' executable="yes"'
                else:
                    executable = ''
                if not working:
                    append('<file%s file_id="%s name="%s%s%s revision="%s '
                        'text_sha1="%s" text_size="%d" />\n' % (
                        executable, _encode_and_escape(ie.file_id),
                        _encode_and_escape(ie.name), parent_str, parent_id,
                        _encode_and_escape(ie.revision), ie.text_sha1,
                        ie.text_size))
                else:
                    append('<file%s file_id="%s name="%s%s%s />\n' % (
                        executable, _encode_and_escape(ie.file_id),
                        _encode_and_escape(ie.name), parent_str, parent_id))
            elif ie.kind == 'directory':
                if not working:
                    append('<directory file_id="%s name="%s%s%s revision="%s '
                        '/>\n' % (
                        _encode_and_escape(ie.file_id),
                        _encode_and_escape(ie.name),
                        parent_str, parent_id,
                        _encode_and_escape(ie.revision)))
                else:
                    append('<directory file_id="%s name="%s%s%s />\n' % (
                        _encode_and_escape(ie.file_id),
                        _encode_and_escape(ie.name),
                        parent_str, parent_id))
            elif ie.kind == 'symlink':
                if not working:
                    append('<symlink file_id="%s name="%s%s%s revision="%s '
                        'symlink_target="%s />\n' % (
                        _encode_and_escape(ie.file_id),
                        _encode_and_escape(ie.name),
                        parent_str, parent_id,
                        _encode_and_escape(ie.revision),
                        _encode_and_escape(ie.symlink_target)))
                else:
                    append('<symlink file_id="%s name="%s%s%s />\n' % (
                        _encode_and_escape(ie.file_id),
                        _encode_and_escape(ie.name),
                        parent_str, parent_id))
            elif ie.kind == 'tree-reference':
                if ie.kind not in self.supported_kinds:
                    raise errors.UnsupportedInventoryKind(ie.kind)
                if not working:
                    append('<tree-reference file_id="%s name="%s%s%s '
                        'revision="%s reference_revision="%s />\n' % (
                        _encode_and_escape(ie.file_id),
                        _encode_and_escape(ie.name),
                        parent_str, parent_id,
                        _encode_and_escape(ie.revision),
                        _encode_and_escape(ie.reference_revision)))
                else:
                    append('<tree-reference file_id="%s name="%s%s%s />\n' % (
                        _encode_and_escape(ie.file_id),
                        _encode_and_escape(ie.name),
                        parent_str, parent_id))
            else:
                raise errors.UnsupportedInventoryKind(ie.kind)
        append('</inventory>\n')
        if f is not None:
            f.writelines(output)
        # Just to keep the cache from growing without bounds
        # but we may actually not want to do clear the cache
        #_clear_cache()
        return output

    def _append_inventory_root(self, append, inv):
        """Append the inventory root to output."""
        if inv.revision_id is not None:
            revid1 = ' revision_id="'
            revid2 = _encode_and_escape(inv.revision_id)
        else:
            revid1 = ""
            revid2 = ""
        append('<inventory format="%s"%s%s>\n' % (
            self.format_num, revid1, revid2))
        append('<directory file_id="%s name="%s revision="%s />\n' % (
            _encode_and_escape(inv.root.file_id),
            _encode_and_escape(inv.root.name),
            _encode_and_escape(inv.root.revision)))

    def _pack_revision(self, rev):
        """Revision object -> xml tree"""
        # For the XML format, we need to write them as Unicode rather than as
        # utf-8 strings. So that cElementTree can handle properly escaping
        # them.
        decode_utf8 = cache_utf8.decode
        revision_id = rev.revision_id
        if isinstance(revision_id, str):
            revision_id = decode_utf8(revision_id)
        format_num = self.format_num
        if self.revision_format_num is not None:
            format_num = self.revision_format_num
        root = Element('revision',
                       committer = rev.committer,
                       timestamp = '%.3f' % rev.timestamp,
                       revision_id = revision_id,
                       inventory_sha1 = rev.inventory_sha1,
                       format=format_num,
                       )
        if rev.timezone is not None:
            root.set('timezone', str(rev.timezone))
        root.text = '\n'
        msg = SubElement(root, 'message')
        msg.text = escape_invalid_chars(rev.message)[0]
        msg.tail = '\n'
        if rev.parent_ids:
            pelts = SubElement(root, 'parents')
            pelts.tail = pelts.text = '\n'
            for parent_id in rev.parent_ids:
                _mod_revision.check_not_reserved_id(parent_id)
                p = SubElement(pelts, 'revision_ref')
                p.tail = '\n'
                if isinstance(parent_id, str):
                    parent_id = decode_utf8(parent_id)
                p.set('revision_id', parent_id)
        if rev.properties:
            self._pack_revision_properties(rev, root)
        return root

    def _pack_revision_properties(self, rev, under_element):
        top_elt = SubElement(under_element, 'properties')
        for prop_name, prop_value in sorted(rev.properties.items()):
            prop_elt = SubElement(top_elt, 'property')
            prop_elt.set('name', prop_name)
            prop_elt.text = prop_value
            prop_elt.tail = '\n'
        top_elt.tail = '\n'

    def _unpack_inventory(self, elt, revision_id=None, entry_cache=None):
        """Construct from XML Element"""
        if elt.tag != 'inventory':
            raise errors.UnexpectedInventoryFormat('Root tag is %r' % elt.tag)
        format = elt.get('format')
        if format != self.format_num:
            raise errors.UnexpectedInventoryFormat('Invalid format version %r'
                                                   % format)
        revision_id = elt.get('revision_id')
        if revision_id is not None:
            revision_id = cache_utf8.encode(revision_id)
        inv = inventory.Inventory(root_id=None, revision_id=revision_id)
        for e in elt:
            ie = self._unpack_entry(e, entry_cache=entry_cache)
            inv.add(ie)
        self._check_cache_size(len(inv), entry_cache)
        return inv

    def _unpack_entry(self, elt, entry_cache=None):
        elt_get = elt.get
        file_id = elt_get('file_id')
        revision = elt_get('revision')
        # Check and see if we have already unpacked this exact entry
        # Some timings for "repo.revision_trees(last_100_revs)"
        #               bzr     mysql
        #   unmodified  4.1s    40.8s
        #   using lru   3.5s
        #   using fifo  2.83s   29.1s
        #   lru._cache  2.8s
        #   dict        2.75s   26.8s
        #   inv.add     2.5s    26.0s
        #   no_copy     2.00s   20.5s
        #   no_c,dict   1.95s   18.0s
        # Note that a cache of 10k nodes is more than sufficient to hold all of
        # the inventory for the last 100 revs for bzr, but not for mysql (20k
        # is enough for mysql, which saves the same 2s as using a dict)

        # Breakdown of mysql using time.clock()
        #   4.1s    2 calls to element.get for file_id, revision_id
        #   4.5s    cache_hit lookup
        #   7.1s    InventoryFile.copy()
        #   2.4s    InventoryDirectory.copy()
        #   0.4s    decoding unique entries
        #   1.6s    decoding entries after FIFO fills up
        #   0.8s    Adding nodes to FIFO (including flushes)
        #   0.1s    cache miss lookups
        # Using an LRU cache
        #   4.1s    2 calls to element.get for file_id, revision_id
        #   9.9s    cache_hit lookup
        #   10.8s   InventoryEntry.copy()
        #   0.3s    cache miss lookus
        #   1.2s    decoding entries
        #   1.0s    adding nodes to LRU
        if entry_cache is not None and revision is not None:
            key = (file_id, revision)
            try:
                # We copy it, because some operations may mutate it
                cached_ie = entry_cache[key]
            except KeyError:
                pass
            else:
                # Only copying directory entries drops us 2.85s => 2.35s
                if self.safe_to_use_cache_items:
                    if cached_ie.kind == 'directory':
                        return cached_ie.copy()
                    return cached_ie
                return cached_ie.copy()

        kind = elt.tag
        if not InventoryEntry.versionable_kind(kind):
            raise AssertionError('unsupported entry kind %s' % kind)

        get_cached = _get_utf8_or_ascii

        file_id = get_cached(file_id)
        if revision is not None:
            revision = get_cached(revision)
        parent_id = elt_get('parent_id')
        if parent_id is not None:
            parent_id = get_cached(parent_id)

        if kind == 'directory':
            ie = inventory.InventoryDirectory(file_id,
                                              elt_get('name'),
                                              parent_id)
        elif kind == 'file':
            ie = inventory.InventoryFile(file_id,
                                         elt_get('name'),
                                         parent_id)
            ie.text_sha1 = elt_get('text_sha1')
            if elt_get('executable') == 'yes':
                ie.executable = True
            v = elt_get('text_size')
            ie.text_size = v and int(v)
        elif kind == 'symlink':
            ie = inventory.InventoryLink(file_id,
                                         elt_get('name'),
                                         parent_id)
            ie.symlink_target = elt_get('symlink_target')
        else:
            raise errors.UnsupportedInventoryKind(kind)
        ie.revision = revision
        if revision is not None and entry_cache is not None:
            # We cache a copy() because callers like to mutate objects, and
            # that would cause the item in cache to mutate as well.
            # This has a small effect on many-inventory performance, because
            # the majority fraction is spent in cache hits, not misses.
            entry_cache[key] = ie.copy()

        return ie

    def _unpack_revision(self, elt):
        """XML Element -> Revision object"""
        format = elt.get('format')
        format_num = self.format_num
        if self.revision_format_num is not None:
            format_num = self.revision_format_num
        if format is not None:
            if format != format_num:
                raise BzrError("invalid format version %r on revision"
                                % format)
        get_cached = _get_utf8_or_ascii
        rev = Revision(committer = elt.get('committer'),
                       timestamp = float(elt.get('timestamp')),
                       revision_id = get_cached(elt.get('revision_id')),
                       inventory_sha1 = elt.get('inventory_sha1')
                       )
        parents = elt.find('parents') or []
        for p in parents:
            rev.parent_ids.append(get_cached(p.get('revision_id')))
        self._unpack_revision_properties(elt, rev)
        v = elt.get('timezone')
        if v is None:
            rev.timezone = 0
        else:
            rev.timezone = int(v)
        rev.message = elt.findtext('message') # text of <message>
        return rev

    def _unpack_revision_properties(self, elt, rev):
        """Unpack properties onto a revision."""
        props_elt = elt.find('properties')
        if not props_elt:
            return
        for prop_elt in props_elt:
            if prop_elt.tag != 'property':
                raise AssertionError(
                    "bad tag under properties list: %r" % prop_elt.tag)
            name = prop_elt.get('name')
            value = prop_elt.text
            # If a property had an empty value ('') cElementTree reads
            # that back as None, convert it back to '', so that all
            # properties have string values
            if value is None:
                value = ''
            if name in rev.properties:
                raise AssertionError("repeated property %r" % name)
            rev.properties[name] = value


serializer_v8 = Serializer_v8()
