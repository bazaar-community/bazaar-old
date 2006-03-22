# Copyright (C) 2006 by Canonical Ltd
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


from getpass import getpass
from urlparse import urlsplit, urlunsplit
from urllib import unquote, quote
import xmlrpclib

import bzrlib.config

# TODO: use last component of the branch's url as the default id?

# TODO: Allow server url to be overridden by an environment variable for
# testing; similarly for user email and password.

class BranchRegistrationRequest(object):
    """Request to tell Launchpad about a bzr branch."""

    _methodname = 'register_branch'

    # NB: this should always end in a slash to avoid xmlrpclib appending
    # '/RPC2'
    DEFAULT_SERVICE_URL = 'http://xmlrpc.launchpad.net/bazaar/'

    # None means to use the xmlrpc default, which is almost always what you
    # want.  But it might be useful for testing.

    def __init__(self, branch_url, branch_id):
        assert branch_url
        self.branch_url = branch_url
        if branch_id:
            self.branch_id = branch_id
        else:
            self.branch_id = self._find_default_branch_id(self.branch_url)
        self.branch_title = ''
        self.branch_description = ''
        self.author_email = ''
        self.product_name = ''
        self.service_url = self.DEFAULT_SERVICE_URL
        self.registrant_email = 'testuser@launchpad.net'
        self.registrant_password = 'testpassword'

    def _request_params(self):
        """Return xmlrpc request parameters"""
        # This must match the parameter tuple expected by Launchpad for this
        # method
        return (self.branch_url,
                self.branch_id,
                self.branch_title,
                self.branch_description,
                self.author_email,
                self.product_name,
               )

    def submit(self, transport=None):
        """Submit registration request to the server.
        
        The particular server to use is set in self.service_url; this 
        should only need to be changed for testing.

        :param transport: If non-null, use a special xmlrpclib.Transport
            to send the request.  This has no connection to bzrlib
            Transports.
        """
        # auth info must be in url
        scheme, hostinfo, path = urlsplit(self.service_url)[:3]
        assert '@' not in hostinfo
        hostinfo = '%s:%s@%s' % (quote(self.registrant_email),
                                 quote(self.registrant_password),
                                 hostinfo)
        url = urlunsplit((scheme, hostinfo, path, '', ''))
        proxy = xmlrpclib.ServerProxy(url, transport=transport)
        proxy.register_branch(*self._request_params())

    def _find_default_branch_id(self, branch_url):
        i = branch_url.rfind('/')
        return branch_url[i+1:]

def register_interactive(branch_url):
    """Register a branch, prompting for a password if needed."""
    rego = BranchRegistrationRequest(branch_url, '')
    config = bzrlib.config.GlobalConfig()
    rego.registrant_email = config.user_email()
    prompt = 'launchpad.net password for %s: ' % \
            rego.registrant_email
    rego.registrant_password = getpass(prompt)
    rego.submit()
