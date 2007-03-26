# Copyright (C) 2005, 2006 Canonical Ltd
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

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    errors,
    urlutils,
    )
from bzrlib.bundle import serializer as _serializer
from bzrlib.transport import (
    do_catching_redirections,
    get_transport,
    )
""")
from bzrlib.trace import note


def read_bundle_from_url(url):
    """Read a bundle from a given URL.

    :return: A BundleReader, may raise NotABundle if the target 
            is not a proper bundle.
    """
    url = urlutils.normalize_url(url)
    url, filename = urlutils.split(url, exclude_trailing_slash=False)
    if not filename:
        # A path to a directory was passed in
        # definitely not a bundle
        raise errors.NotABundle('A directory cannot be a bundle')

    # All of this must be in the try/except
    # Some transports cannot detect that we are trying to read a
    # directory until we actually issue read() on the handle.
    try:
        transport = get_transport(url)

        def get_bundle(transport):
            return transport.get(filename)

        def redirected_transport(transport, exception, redirection_notice):
            note(redirection_notice)
            url, filename = urlutils.split(exception.target,
                                           exclude_trailing_slash=False)
            if not filename:
                raise errors.NotABundle('A directory cannot be a bundle')
            return get_transport(url)

        try:
            f = do_catching_redirections(get_bundle, transport,
                                         redirected_transport)
        except errors.TooManyRedirections:
            raise errors.NotABundle(str(url))

        return _serializer.read_bundle(f)
    except (errors.TransportError, errors.PathError), e:
        raise errors.NotABundle(str(e))
    except (IOError,), e:
        # jam 20060707
        # Abstraction leakage, SFTPTransport.get('directory')
        # doesn't always fail at get() time. Sometimes it fails
        # during read. And that raises a generic IOError with
        # just the string 'Failure'
        # StubSFTPServer does fail during get() (because of prefetch) 
        # so it has an opportunity to translate the error.
        raise errors.NotABundle(str(e))

