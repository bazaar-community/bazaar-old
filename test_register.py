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

import base64
import os
from StringIO import StringIO
import xmlrpclib

from bzrlib.tests import TestCase, TestSkipped

# local import
from lp_registration import (
        BranchRegistrationRequest, LaunchpadService,
        BaseRequest)


# TODO: Test that the command-line client, making sure that it'll pass the
# request through to a dummy transport, and that the transport will validate
# the results passed in.  Not sure how to get the transport object back out to
# validate that its OK - may not be necessary.

# TODO: Add test for (and implement) other command-line options to set
# project, author_email, description.

# TODO: project_id is not properly handled -- must be passed in rpc or path.

class InstrumentedXMLRPCConnection(object):
    """Stands in place of an http connection for the purposes of testing"""

    def __init__(self, testcase):
        self.testcase = testcase

    def getreply(self):
        """Fake the http reply.

        :returns: (errcode, errmsg, headers)
        """
        return (200, 'OK', [])

    def getfile(self):
        """Return a fake file containing the response content."""
        return StringIO('''\
<?xml version="1.0" ?>
<methodResponse>
    <params>
        <param>
            <value>
                <string>victoria dock</string>
            </value>
        </param>
    </params>
</methodResponse>''')



class InstrumentedXMLRPCTransport(xmlrpclib.Transport):

    def __init__(self, testcase):
        self.testcase = testcase

    def make_connection(self, host):
        host, http_headers, x509 = self.get_host_info(host)
        test = self.testcase
        self.connected_host = host
        auth_hdrs = [v for k,v in http_headers if k == 'Authorization']
        assert len(auth_hdrs) == 1
        authinfo = auth_hdrs[0]
        expected_auth = 'testuser@launchpad.net:testpassword'
        test.assertEquals(authinfo,
                'Basic ' + base64.encodestring(expected_auth).strip())
        return InstrumentedXMLRPCConnection(test)

    def send_request(self, connection, handler_path, request_body):
        test = self.testcase
        self.got_request = True

    def send_host(self, conn, host):
        pass

    def send_user_agent(self, conn):
        # TODO: send special user agent string, including bzrlib version
        # number
        pass

    def send_content(self, conn, request_body):
        unpacked, method = xmlrpclib.loads(request_body)
        assert None not in unpacked, \
                "xmlrpc result %r shouldn't contain None" % (unpacked,)
        self.sent_params = unpacked


class MockLaunchpadService(LaunchpadService):

    def send_request(self, method_name, method_params):
        """Stash away the method details rather than sending them to a real server"""
        self.called_method_name = method_name
        self.called_method_params = method_params


class TestBranchRegistration(TestCase):
    SAMPLE_URL = 'http://bazaar-vcs.org/bzr/bzr.dev/'
    SAMPLE_OWNER = 'jhacker@foo.com'
    SAMPLE_BRANCH_ID = 'bzr.dev'

    def setUp(self):
        super(TestBranchRegistration, self).setUp()
        # make sure we have a reproducible standard environment
        if 'BZR_LP_XMLRPC_URL' in os.environ:
            del os.environ['BZR_LP_XMLRPC_URL']

    def test_register_help(self):
        """register-branch accepts --help"""
        out, err = self.run_bzr('register-branch', '--help')
        self.assertContainsRe(out, r'Register a branch')

    def test_register_no_url(self):
        """register-branch command requires parameters"""
        self.run_bzr('register-branch', retcode=3)

    def test_21_register_cmd_simple_branch(self):
        """Register a well-known branch to fake server"""
        # disabled until we can set a different transport within the command
        # command
        ## self.run_bzr('register-branch', self.SAMPLE_URL)

    def test_onto_transport(self):
        """Test how the request is sent by transmitting across a mock Transport"""
        # use a real transport, but intercept at the http/xml layer
        service = LaunchpadService()
        service.registrant_email = 'testuser@launchpad.net'
        service.registrant_password = 'testpassword'
        transport = InstrumentedXMLRPCTransport(self)
        service.transport = transport
        rego = BranchRegistrationRequest('http://test-server.com/bzr/branch',
                'branch-id',
                'my test branch',
                'description',
                'author@launchpad.net',
                'product')
        rego.submit(service)
        self.assertEquals(transport.connected_host, 'xmlrpc.launchpad.net')
        self.assertEquals(len(transport.sent_params), 6)
        # string branch_url,
        # string branch_id,
        # string branch_title
        # unicode branch_description,
        # string owner_email,
        self.assertEquals(transport.sent_params,
                ('http://test-server.com/bzr/branch',  # branch_url
                 'branch-id',                          # branch_name
                 'my test branch',                     # branch_title
                 'description',
                 'author@launchpad.net',
                 'product'))
        self.assertTrue(transport.got_request)

    def test_against_mock_server(self):
        """Send registration to mock server"""
        return ############################ broken
        service = MockLaunchpadService()
        rego = BranchRegistrationRequest('http://test-server.com/bzr/branch',
                'branch-id')
        rego.branch_title = 'short description'
        rego.submit(service)

    def test_subclass_request(self):
        """Define a new type of xmlrpc request"""
        class DummyRequest(BaseRequest):
            _methodname = 'dummy_request'
            def _request_params(self):
                return (42,)

        service = MockLaunchpadService()
        service.registrant_email = 'test@launchpad.net'
        service.registrant_password = ''
        request = DummyRequest()
        request.submit(service)
        self.assertEquals(service.called_method_name, 'dummy_request')
        self.assertEquals(service.called_method_params, (42,))

