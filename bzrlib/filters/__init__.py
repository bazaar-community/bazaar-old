# Copyright (C) 2008 Canonical Ltd
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


"""Working tree content filtering support.

Filters have the following signatures::

    read_filter(chunks) -> chunks
    write_filter(chunks, context) -> chunks

where:

 * chunks is an iterator over a sequence of 8-bit utf-8 strings

 * context is an optional object (possibly None) providing filters access
   to interesting information, e.g. the relative path of the file.

Note that context is currently only supported for write filters.
"""


import cStringIO
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
        osutils,
        )
""")


class ContentFilter(object):

    def __init__(self, reader, writer):
        """Create a filter that converts content while reading and writing.
 
        :param reader: function for converting external to internal content
        :param writer: function for converting internal to external content
        """
        self.reader = reader
        self.writer = writer


class ContentFilterContext(object):
    """Object providing information that filters can use.
    
    In the future, this is likely to be expanded to include
    details like the Revision when this file was last updated.
    """

    def __init__(self, relpath=None):
        """Create a context.

        :param relpath: the relative path or None if this context doesn't
           support that information.
        """
        self._relpath = relpath

    def relpath(self):
        """Relative path of file to tree-root."""
        if self._relpath is None:
            raise NotImplementedError(self.relpath)
        else:
            return self._relpath


def filtered_input_file(f, filters):
    """Get an input file that converts external to internal content.
    
    :param f: the original input file
    :param filters: the stack of filters to apply
    :return: a file-like object
    """
    if filters:
        chunks = [f.read()]
        for filter in filters:
            if filter.reader is not None:
                chunks = filter.reader(chunks)
        return cStringIO.StringIO(''.join(chunks))
    else:
        return f


def filtered_output_lines(chunks, filters, context=None):
    """Convert output lines from internal to external format.
    
    :param chunks: an iterator containing the original content
    :param filters: the stack of filters to apply
    :param context: a ContentFilterContext object passed to
        each filter
    :return: an iterator containing the content to output
    """
    if filters:
        for filter in reversed(filters):
            if filter.writer is not None:
                chunks = filter.writer(chunks, context)
    return chunks


def sha_file_by_name(name, filters):
    """Get sha of internal content given external content.
    
    :param name: path to file
    :param filters: the stack of filters to apply
    """
    if filters:
        f = open(name, 'rb', 65000)
        return osutils.sha_strings(filtered_input_file(f, filters))
    else:
        return osutils.sha_file_by_name(name)
