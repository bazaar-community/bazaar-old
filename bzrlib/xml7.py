# Copyright (C) 2006, 2007 Canonical Ltd
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

from bzrlib import (
    inventory,
    xml6,
    )


class Serializer_v7(xml6.Serializer_v6):
    """A Serializer that supports tree references"""

    # this format is used by BzrBranch6

    supported_kinds = set(['file', 'directory', 'symlink', 'tree-reference'])
    format_num = '7'

    def _unpack_entry(self, elt, entry_cache=None, return_from_cache=False):
        kind = elt.tag
        if not kind in self.supported_kinds:
            raise AssertionError('unsupported entry kind %s' % kind)
        if kind == 'tree-reference':
            file_id = elt.attrib['file_id']
            name = elt.attrib['name']
            parent_id = elt.attrib['parent_id']
            revision = elt.get('revision')
            reference_revision = elt.get('reference_revision')
            return inventory.TreeReference(file_id, name, parent_id, revision,
                                           reference_revision)
        else:
            return xml6.Serializer_v6._unpack_entry(self, elt,
                entry_cache=entry_cache, return_from_cache=return_from_cache)

serializer_v7 = Serializer_v7()
