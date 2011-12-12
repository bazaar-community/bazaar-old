# Copyright (C) 2005-2010 Canonical Ltd
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

"""XML externalization support."""

# "XML is like violence: if it doesn't solve your problem, you aren't
# using enough of it." -- various

# importing this module is fairly slow because it has to load several
# ElementTree bits

import re

from bzrlib.serializer import Serializer
from bzrlib.trace import mutter

try:
    try:
        # it's in this package in python2.5
        from xml.etree.cElementTree import (ElementTree, SubElement, Element,
            XMLTreeBuilder, fromstring, tostring)
        import xml.etree as elementtree
        # Also import ElementTree module so monkey-patching below always works
        import xml.etree.ElementTree
    except ImportError:
        from cElementTree import (ElementTree, SubElement, Element,
                                  XMLTreeBuilder, fromstring, tostring)
        import elementtree.ElementTree
    ParseError = SyntaxError
except ImportError:
    mutter('WARNING: using slower ElementTree; consider installing cElementTree'
           " and make sure it's on your PYTHONPATH")
    # this copy is shipped with bzr
    from util.elementtree.ElementTree import (ElementTree, SubElement,
                                              Element, XMLTreeBuilder,
                                              fromstring, tostring)
    import util.elementtree as elementtree
    from xml.parsers.expat import ExpatError as ParseError

from bzrlib import (
    cache_utf8,
    lazy_regex,
    errors,
    )


class XMLSerializer(Serializer):
    """Abstract XML object serialize/deserialize"""

    squashes_xml_invalid_characters = True

    def read_inventory_from_string(self, xml_string, revision_id=None,
                                   entry_cache=None, return_from_cache=False):
        """Read xml_string into an inventory object.

        :param xml_string: The xml to read.
        :param revision_id: If not-None, the expected revision id of the
            inventory. Some serialisers use this to set the results' root
            revision. This should be supplied for deserialising all
            from-repository inventories so that xml5 inventories that were
            serialised without a revision identifier can be given the right
            revision id (but not for working tree inventories where users can
            edit the data without triggering checksum errors or anything).
        :param entry_cache: An optional cache of InventoryEntry objects. If
            supplied we will look up entries via (file_id, revision_id) which
            should map to a valid InventoryEntry (File/Directory/etc) object.
        :param return_from_cache: Return entries directly from the cache,
            rather than copying them first. This is only safe if the caller
            promises not to mutate the returned inventory entries, but it can
            make some operations significantly faster.
        """
        try:
            return self._unpack_inventory(fromstring(xml_string), revision_id,
                                          entry_cache=entry_cache,
                                          return_from_cache=return_from_cache)
        except ParseError, e:
            raise errors.UnexpectedInventoryFormat(e)

    def read_inventory(self, f, revision_id=None):
        try:
            try:
                return self._unpack_inventory(self._read_element(f),
                    revision_id=None)
            finally:
                f.close()
        except ParseError, e:
            raise errors.UnexpectedInventoryFormat(e)

    def write_revision(self, rev, f):
        self._write_element(self._pack_revision(rev), f)

    def write_revision_to_string(self, rev):
        return tostring(self._pack_revision(rev)) + '\n'

    def read_revision(self, f):
        return self._unpack_revision(self._read_element(f))

    def read_revision_from_string(self, xml_string):
        return self._unpack_revision(fromstring(xml_string))

    def _write_element(self, elt, f):
        ElementTree(elt).write(f, 'utf-8')
        f.write('\n')

    def _read_element(self, f):
        return ElementTree().parse(f)


def escape_invalid_chars(message):
    """Escape the XML-invalid characters in a commit message.

    :param message: Commit message to escape
    :return: tuple with escaped message and number of characters escaped
    """
    if message is None:
        return None, 0
    # Python strings can include characters that can't be
    # represented in well-formed XML; escape characters that
    # aren't listed in the XML specification
    # (http://www.w3.org/TR/REC-xml/#NT-Char).
    return re.subn(u'[^\x09\x0A\x0D\u0020-\uD7FF\uE000-\uFFFD]+',
            lambda match: match.group(0).encode('unicode_escape'),
            message)


def get_utf8_or_ascii(a_str,
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


_utf8_re = lazy_regex.lazy_compile('[&<>\'\"]|[\x80-\xff]+')
_unicode_re = lazy_regex.lazy_compile(u'[&<>\'\"\u0080-\uffff]')


_xml_escape_map = {
    "&":'&amp;',
    "'":"&apos;", # FIXME: overkill
    "\"":"&quot;",
    "<":"&lt;",
    ">":"&gt;",
    }


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

def encode_and_escape(unicode_or_utf8_str, _map=_to_escaped_map):
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


def _clear_cache():
    """Clean out the unicode => escaped map"""
    _to_escaped_map.clear()
