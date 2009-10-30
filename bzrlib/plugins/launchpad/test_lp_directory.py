# Copyright (C) 2007, 2008 Canonical Ltd
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

"""Tests for directory lookup through Launchpad.net"""

import os
import xmlrpclib

from bzrlib import (
    errors,
    tests,
    )
from bzrlib.branch import Branch
from bzrlib.directory_service import directories
from bzrlib.tests import (
    TestCaseInTempDir,
    TestCaseWithMemoryTransport
)
from bzrlib.transport import get_transport
from bzrlib.plugins.launchpad import (
    _register_directory,
    lp_registration,
    )
from bzrlib.plugins.launchpad.lp_directory import (
    LaunchpadDirectory)
from bzrlib.plugins.launchpad.account import get_lp_login
from bzrlib.tests import (
    http_server,
    http_utils,
    )


def load_tests(standard_tests, module, loader):
    result = loader.suiteClass()
    t_tests, remaining_tests = tests.split_suite_by_condition(
        standard_tests, tests.condition_isinstance((
                TestTransport,
                )))
    transport_scenarios = [
        ('http', dict(server_class=PreCannedHTTPServer,)),
        ]
    if tests.HTTPSServerFeature.available():
        transport_scenarios.append(
            ('https', dict(server_class=PreCannedHTTPSServer,)),
            )
    tests.multiply_tests(t_tests, transport_scenarios, result)

    # No parametrization for the remaining tests
    result.addTests(remaining_tests)

    return result


class FakeResolveFactory(object):
    def __init__(self, test, expected_path, result):
        self._test = test
        self._expected_path = expected_path
        self._result = result

    def __call__(self, path):
        self._test.assertEqual(self._expected_path, path)
        return self

    def submit(self, service):
        self._service_url = service.service_url
        return self._result


class DirectoryUrlTests(TestCaseInTempDir):
    """Tests for branch urls through Launchpad.net directory"""

    def test_short_form(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          directory._resolve('lp:apt', factory))
        # Make sure that resolve went to the production server.
        self.assertEquals('https://xmlrpc.edge.launchpad.net/bazaar/',
                          factory._service_url)

    def test_staging(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'http://bazaar.staging.launchpad.net/~apt/apt/devel']))
        url = 'lp://staging/apt'
        directory = LaunchpadDirectory()
        self.assertEquals('http://bazaar.staging.launchpad.net/~apt/apt/devel',
                          directory._resolve(url, factory))
        # Make sure that resolve went to the staging server.
        self.assertEquals('https://xmlrpc.staging.launchpad.net/bazaar/',
                          factory._service_url)

    def test_url_from_directory(self):
        """A launchpad url should map to a http url"""
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          directory._resolve('lp:///apt', factory))

    def test_directory_skip_bad_schemes(self):
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'bad-scheme://bazaar.launchpad.net/~apt/apt/devel',
                    'http://bazaar.launchpad.net/~apt/apt/devel',
                    'http://another/location']))
        directory = LaunchpadDirectory()
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          directory._resolve('lp:///apt', factory))

    def test_directory_no_matching_schemes(self):
        # If the XMLRPC call does not return any protocols we support,
        # invalidURL is raised.
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'bad-scheme://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertRaises(errors.InvalidURL,
                          directory._resolve, 'lp:///apt', factory)

    def test_directory_fault(self):
        # Test that XMLRPC faults get converted to InvalidURL errors.
        factory = FakeResolveFactory(self, 'apt', None)
        def submit(service):
            raise xmlrpclib.Fault(42, 'something went wrong')
        factory.submit = submit
        directory = LaunchpadDirectory()
        self.assertRaises(errors.InvalidURL,
                          directory._resolve, 'lp:///apt', factory)

    def test_skip_bzr_ssh_launchpad_net_when_anonymous(self):
        # Test that bzr+ssh://bazaar.launchpad.net gets skipped if
        # Bazaar does not know the user's Launchpad ID:
        self.assertEqual(None, get_lp_login())
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'bzr+ssh://bazaar.launchpad.net/~apt/apt/devel',
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          directory._resolve('lp:///apt', factory))

    def test_skip_sftp_launchpad_net_when_anonymous(self):
        # Test that sftp://bazaar.launchpad.net gets skipped if
        # Bazaar does not know the user's Launchpad ID:
        self.assertEqual(None, get_lp_login())
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'sftp://bazaar.launchpad.net/~apt/apt/devel',
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEquals('http://bazaar.launchpad.net/~apt/apt/devel',
                          directory._resolve('lp:///apt', factory))

    def test_rewrite_bzr_ssh_launchpad_net(self):
        # Test that bzr+ssh URLs get rewritten to include the user's
        # Launchpad ID (assuming we know the Launchpad ID).
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'bzr+ssh://bazaar.launchpad.net/~apt/apt/devel',
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEquals(
            'bzr+ssh://bazaar.launchpad.net/~apt/apt/devel',
            directory._resolve('lp:///apt', factory, _lp_login='username'))

    def test_no_rewrite_of_other_bzr_ssh(self):
        # Test that we don't rewrite bzr+ssh URLs for other
        self.assertEqual(None, get_lp_login())
        factory = FakeResolveFactory(
            self, 'apt', dict(urls=[
                    'bzr+ssh://example.com/~apt/apt/devel',
                    'http://bazaar.launchpad.net/~apt/apt/devel']))
        directory = LaunchpadDirectory()
        self.assertEquals('bzr+ssh://example.com/~apt/apt/devel',
                          directory._resolve('lp:///apt', factory))

    # TODO: check we get an error if the url is unreasonable
    def test_error_for_bad_url(self):
        directory = LaunchpadDirectory()
        self.assertRaises(errors.InvalidURL,
            directory._resolve, 'lp://ratotehunoahu')


class DirectoryOpenBranchTests(TestCaseWithMemoryTransport):

    def test_directory_open_branch(self):
        # Test that opening an lp: branch redirects to the real location.
        target_branch = self.make_branch('target')
        class FooService(object):
            """A directory service that maps the name to a FILE url"""

            def look_up(self, name, url):
                if 'lp:///apt' == url:
                    return target_branch.base.rstrip('/')
                return '!unexpected look_up value!'

        directories.remove('lp:')
        directories.register('lp:', FooService, 'Map lp URLs to local urls')
        self.addCleanup(_register_directory)
        self.addCleanup(lambda: directories.remove('lp:'))
        transport = get_transport('lp:///apt')
        branch = Branch.open_from_transport(transport)
        self.assertEqual(target_branch.base, branch.base)


class PredefinedRequestHandler(http_server.TestingHTTPRequestHandler):
    """Request handler for a unique and pre-defined request.

    The only thing we care about here is that we receive a connection. But
    since we want to dialog with a real http client, we have to send it correct
    responses.

    We expect to receive a *single* request nothing more (and we won't even
    check what request it is), the tests will recognize us from our response.
    """

    def handle_one_request(self):
        tcs = self.server.test_case_server
        requestline = self.rfile.readline()
        headers = self.MessageClass(self.rfile, 0)
        if requestline.startswith('POST'):
            # The body should be a single line (or we don't know where it ends
            # and we don't want to issue a blocking read)
            body = self.rfile.readline()

        self.wfile.write(tcs.canned_response)

class PreCannedServerMixin(object):

    def __init__(self):
        super(PreCannedServerMixin, self).__init__(
            request_handler=PredefinedRequestHandler)
        # Bytes read and written by the server
        self.bytes_read = 0
        self.bytes_written = 0
        self.canned_response = None


class PreCannedHTTPServer(PreCannedServerMixin, http_server.HttpServer):
    pass


if tests.HTTPSServerFeature.available():
    from bzrlib.tests import https_server
    class PreCannedHTTPSServer(PreCannedServerMixin, https_server.HTTPSServer):
        pass


class TestTransport(tests.TestCase):

    # set by load_tests
    server_class = None

    def setUp(self):
        tests.TestCase.setUp(self)
        self.server = self.server_class()
        self.server.setUp()
        # Ensure we don't clobber env
        self._captureVar('BZR_LP_XMLRPC_URL', None)

    def tearDown(self):
        self.server.tearDown()
        tests.TestCase.tearDown(self)

    def set_canned_response(self, server, path):
        response_format = '''HTTP/1.1 200 OK\r
Date: Tue, 11 Jul 2006 04:32:56 GMT\r
Server: Apache/2.0.54 (Fedora)\r
Last-Modified: Sun, 23 Apr 2006 19:35:20 GMT\r
ETag: "56691-23-38e9ae00"\r
Accept-Ranges: bytes\r
Content-Length: %(length)d\r
Connection: close\r
Content-Type: text/plain; charset=UTF-8\r
\r
<?xml version='1.0'?>
<methodResponse>
<params>
<param>
<value><struct>
<member>
<name>urls</name>
<value><array><data>
<value><string>bzr+ssh://bazaar.launchpad.net/%(path)s</string></value>
<value><string>http://bazaar.launchpad.net/%(path)s</string></value>
</data></array></value>
</member>
</struct></value>
</param>
</params>
</methodResponse>
'''
        length = 334 + 2 * len(path)
        server.canned_response = response_format % dict(length=length,
                                                        path=path)

    def do_request(self, server_url):
        os.environ['BZR_LP_XMLRPC_URL'] = self.server.get_url()
        service = lp_registration.LaunchpadService()
        resolve = lp_registration.ResolveLaunchpadPathRequest('bzr')
        result = resolve.submit(service)
        return result

    def test_direct_request(self):
        self.set_canned_response(self.server, '~bzr-pqm/bzr/bzr.dev')
        result = self.do_request(self.server.get_url())
        urls = result.get('urls', None)
        self.assertIsNot(None, urls)
        self.assertEquals(
            ['bzr+ssh://bazaar.launchpad.net/~bzr-pqm/bzr/bzr.dev',
             'http://bazaar.launchpad.net/~bzr-pqm/bzr/bzr.dev'],
            urls)
    # FIXME: we need to test with a real proxy, I can't find a way so simulate
    # CONNECT without leaving one server hanging the test :-/ Since that maybe
    # related to the leaking tests problems, I'll punt for now -- vila 20091030
