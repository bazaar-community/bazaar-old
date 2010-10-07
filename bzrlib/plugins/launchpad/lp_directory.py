# Copyright (C) 2007-2010 Canonical Ltd
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


"""Directory lookup that uses Launchpad."""

from urlparse import urlsplit
import xmlrpclib

from bzrlib import (
    debug,
    errors,
    trace,
    )
from bzrlib.transport import (
    get_transport,
    register_urlparse_netloc_protocol,
    )

from bzrlib.plugins.launchpad.lp_registration import (
    LaunchpadService, ResolveLaunchpadPathRequest)
from bzrlib.plugins.launchpad.account import get_lp_login


# As bzrlib.transport.remote may not be loaded yet, make sure bzr+ssh
# is counted as a netloc protocol.
register_urlparse_netloc_protocol('bzr+ssh')
register_urlparse_netloc_protocol('lp')


class LaunchpadDirectory(object):

    def _requires_launchpad_login(self, scheme, netloc, path, query,
                                  fragment):
        """Does the URL require a Launchpad login in order to be reached?

        The URL is specified by its parsed components, as returned from
        urlsplit.
        """
        return (scheme in ('bzr+ssh', 'sftp')
                and (netloc.endswith('launchpad.net')
                     or netloc.endswith('launchpad.dev')))

    def look_up(self, name, url):
        """See DirectoryService.look_up"""
        return self._resolve(url)

    def _resolve(self, url,
                 _request_factory=ResolveLaunchpadPathRequest,
                 _lp_login=None):
        """Resolve the base URL for this transport."""
        service = LaunchpadService.for_url(url)
        result = urlsplit(url)
        if _lp_login is None:
            _lp_login = get_lp_login()
        path = result[2].strip('/')
        if path.startswith('~/'):
            if _lp_login is None:
                raise errors.InvalidURL(path=url,
                    extra='Cannot resolve "~" to your username.'
                          ' See "bzr help launchpad-login"')
            path = '~' + _lp_login + path[1:]
        resolve = _request_factory(path)
        try:
            result = resolve.submit(service)
        except xmlrpclib.Fault, fault:
            raise errors.InvalidURL(
                path=url, extra=fault.faultString)

        if 'launchpad' in debug.debug_flags:
            trace.mutter("resolve_lp_path(%r) == %r", url, result)

        _warned_login = False
        for url in result['urls']:
            scheme, netloc, path, query, fragment = urlsplit(url)
            if self._requires_launchpad_login(scheme, netloc, path, query,
                                              fragment):
                # Only accept launchpad.net bzr+ssh URLs if we know
                # the user's Launchpad login:
                if _lp_login is not None:
                    break
                if _lp_login is None:
                    if not _warned_login:
                        trace.warning(
'You have not informed bzr of your Launchpad ID, and you must do this to\n'
'write to Launchpad or access private data.  See "bzr help launchpad-login".')
                        _warned_login = True
            else:
                # Use the URL if we can create a transport for it.
                try:
                    get_transport(url)
                except (errors.PathError, errors.TransportError):
                    pass
                else:
                    break
        else:
            raise errors.InvalidURL(path=url, extra='no supported schemes')
        return url


def get_test_permutations():
    # Since this transport doesn't do anything once opened, it's not subjected
    # to the usual transport tests.
    return []
