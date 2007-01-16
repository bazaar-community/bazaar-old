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

"""bzr library"""

from bzrlib.osutils import get_user_encoding


IGNORE_FILENAME = ".bzrignore"


# XXX: Compatibility. This should probably be deprecated
user_encoding = get_user_encoding()


__copyright__ = "Copyright 2005, 2006, 2007 Canonical Ltd."

# same format as sys.version_info: "A tuple containing the five components of
# the version number: major, minor, micro, releaselevel, and serial. All
# values except releaselevel are integers; the release level is 'alpha',
# 'beta', 'candidate', or 'final'. The version_info value corresponding to the
# Python version 2.0 is (2, 0, 0, 'final', 0)."  Additionally we use a
# releaselevel of 'dev' for unreleased under-development code.

version_info = (0, 14, 0, 'candidate', 1)

if version_info[3] == 'final':
    version_string = '%d.%d.%d' % version_info[:3]
else:
    version_string = '%d.%d.%d%s%d' % version_info
__version__ = version_string

from bzrlib.symbol_versioning import (deprecated_function,
                                      zero_seven,
                                      zero_nine,
                                      deprecated_list,
                                     )

# Kept for compatibility with 0.8, it is considered deprecated to modify it
DEFAULT_IGNORE = deprecated_list(zero_nine, 'DEFAULT_IGNORE', [],
                    'Consider using bzrlib.ignores.add_unique_user_ignores'
                    ' or bzrlib.ignores.add_runtime_ignores')

def test_suite():
    import tests
    return tests.test_suite()
