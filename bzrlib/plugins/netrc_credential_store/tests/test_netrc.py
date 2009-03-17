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

from cStringIO import StringIO

from bzrlib import (
    config,
    errors,
    osutils,
    tests,
    )

from bzrlib.plugins import netrc_credential_store


class TestNetrcCSNoNetrc(tests.TestCaseInTempDir):

    def test_home_netrc_does_not_exist(self):
        self.assertRaises(errors.NoSuchFile,
                          config.credential_store_registry.get_credential_store,
                          'netrc')


class TestNetrcCS(tests.TestCaseInTempDir):

    def setUp(self):
        super(TestNetrcCS, self).setUp()
        # Create a .netrc file
        netrc_content = """
machine host login joe password secret
default login anonymous password joe@home
"""
        f = open(osutils.pathjoin(self.test_home_dir, '.netrc'), 'wb')
        try:
            f.write(netrc_content)
        finally:
            f.close()

    def _get_netrc_cs(self):
        return  config.credential_store_registry.get_credential_store('netrc')

    def test_not_matching_user(self):
        cs = self._get_netrc_cs()
        password = cs.decode_password(dict(host='host', user='jim'))
        self.assertIs(None, password)

    def test_matching_user(self):
        cs = self._get_netrc_cs()
        password = cs.decode_password(dict(host='host', user='joe'))
        self.assertEquals('secret', password)

    def test_default_password(self):
        cs = self._get_netrc_cs()
        password = cs.decode_password(dict(host='other', user='anonymous'))
        self.assertEquals('joe@home', password)

    def test_default_password_without_user(self):
        cs = self._get_netrc_cs()
        password = cs.decode_password(dict(host='other'))
        self.assertIs(None, password)

    def test_get_netrc_credentials_via_auth_config(self):
        # Create a test AuthenticationConfig object
        ac_content = """
[host1]
host = host
user = joe
password_encoding = netrc
"""
        conf = config.AuthenticationConfig(_file=StringIO(ac_content))
        credentials = conf.get_credentials('scheme', 'host', user='joe')
        self.assertIsNot(None, credentials)
        self.assertEquals('secret', credentials.get('password', None))
