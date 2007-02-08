# Copyright (C) 2007 Canonical Ltd
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


"""Transport indirection that uses Launchpad as a directory lookup.

When the transport is opened, it immediately redirects to a url
on Launchpad, which can then either serve the branch itself or redirect
again.
"""

from bzrlib import (
    errors,
    )
from bzrlib.transport import (
    get_transport,
    Transport,
    )


def launchpad_transport_indirect(base_url):
    """Uses Launchpad.net as a directory of open source software"""
    if base_url.startswith('lp:///'):
        real_url = 'http://code.launchpad.net/' + base_url[6:]
    elif base_url.startswith('lp:') and base_url[3] != '/':
        real_url = 'http://code.launchpad.net/' + base_url[3:]
    else:
        raise errors.InvalidURL(path=base_url)
    return get_transport(real_url)


def get_test_permutations():
    # Since this transport doesn't do anything once opened, it's not subjected
    # to the usual transport tests.
    return []
