# Copyright (C) 2010 Canonical Ltd
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

from __future__ import absolute_import

"""A sphinx builder producing texinfo output."""

from sphinx import builders
from sphinx.builders import text as _text_builder

from bzrlib.doc_generate.writers import texinfo as texinfo_writer

class TexinfoBuilder(_text_builder.TextBuilder):

    name = 'texinfo'
    format = 'texinfo'
    out_suffix = '.texi'

    def prepare_writing(self, docnames):
        self.writer = texinfo_writer.TexinfoWriter(self)

    def get_target_uri(self, docname, typ=None):
        # FIXME: Revisit when info file generation is defined (the suffix is
        # left here for clarity but the final version may just get rid of
        # it). And we probalby will join several files into bigger info files
        # anyway. -- vila 20100506
        return docname + '.info'


def setup(app):
    app.add_builder(TexinfoBuilder)
