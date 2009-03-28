# Copyright (C) 2009 Canonical Ltd
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

"""End of Line Conversion filters.

See bzr help eol for details.
"""


import re, sys

from bzrlib import filters


# Real Linux/Unix/OSX newline - \n without \r before it
_LINUX_NL_RE = re.compile(r'(?<!\r)\n')


def _to_lf_converter(chunks, context=None):
    """A content file that converts crlf to lf."""
    content = ''.join(chunks)
    if '\x00' in content:
        return [content]
    else:
        return [content.replace('\r\n', '\n')]


def _to_crlf_converter(chunks, context=None):
    """A content file that converts lf to crlf."""
    content = ''.join(chunks)
    if '\x00' in content:
        return [content]
    else:
        return [_LINUX_NL_RE.sub('\r\n', content)]


# Define and register the EOL filter stacks
if sys.platform == 'win32':
    _native_output = _to_crlf_converter
else:
    _native_output = _to_lf_converter
_eol_filter_stack_map = {
    'exact': [],
    'lf':    [filters.ContentFilter(_to_lf_converter, _native_output)],
    'crlf':  [filters.ContentFilter(_to_crlf_converter, _native_output)],
    }
filters.register_filter_stack_map('eol', _eol_filter_stack_map)
