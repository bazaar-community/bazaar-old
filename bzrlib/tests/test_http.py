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

# FIXME: This test should be repeated for each available http client
# implementation; at the moment we have urllib and pycurl.

# TODO: Should be renamed to bzrlib.transport.http.tests?
# TODO: What about renaming to bzrlib.tests.transport.http ?

from cStringIO import StringIO
import os
import select
import socket
import sys
import threading

import bzrlib
from bzrlib import (
    config,
    errors,
    osutils,
    tests,
    ui,
    urlutils,
    )
from bzrlib.tests.HttpServer import (
    HttpServer,
    HttpServer_PyCurl,
    HttpServer_urllib,
    )
from bzrlib.tests.HTTPTestUtil import (
    BadProtocolRequestHandler,
    BadStatusRequestHandler,
    ForbiddenRequestHandler,
    HTTPBasicAuthServer,
    HTTPDigestAuthServer,
    HTTPServerRedirecting,
    InvalidStatusRequestHandler,
    LimitedRangeHTTPServer,
    NoRangeRequestHandler,
    ProxyBasicAuthServer,
    ProxyDigestAuthServer,
    ProxyServer,
    SingleRangeRequestHandler,
    SingleOnlyRangeRequestHandler,
    TestCaseWithRedirectedWebserver,
    TestCaseWithTwoWebservers,
    TestCaseWithWebserver,
    WallRequestHandler,
    )
from bzrlib.transport import (
    _CoalescedOffset,
    do_catching_redirections,
    get_transport,
    Transport,
    )
from bzrlib.transport.http import (
    extract_auth,
    HttpTransportBase,
    _urllib2_wrappers,
    )
from bzrlib.transport.http._urllib import HttpTransport_urllib
from bzrlib.transport.http._urllib2_wrappers import (
    ProxyHandler,
    Request,
    )


class FakeManager(object):

    def __init__(self):
        self.credentials = []

    def add_password(self, realm, host, username, password):
        self.credentials.append([realm, host, username, password])


class RecordingServer(object):
    """A fake HTTP server.
    
    It records the bytes sent to it, and replies with a 200.
    """

    def __init__(self, expect_body_tail=None):
        """Constructor.

        :type expect_body_tail: str
        :param expect_body_tail: a reply won't be sent until this string is
            received.
        """
        self._expect_body_tail = expect_body_tail
        self.host = None
        self.port = None
        self.received_bytes = ''

    def setUp(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(('127.0.0.1', 0))
        self.host, self.port = self._sock.getsockname()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._accept_read_and_reply)
        self._thread.setDaemon(True)
        self._thread.start()
        self._ready.wait(5)

    def _accept_read_and_reply(self):
        self._sock.listen(1)
        self._ready.set()
        self._sock.settimeout(5)
        try:
            conn, address = self._sock.accept()
            # On win32, the accepted connection will be non-blocking to start
            # with because we're using settimeout.
            conn.setblocking(True)
            while not self.received_bytes.endswith(self._expect_body_tail):
                self.received_bytes += conn.recv(4096)
            conn.sendall('HTTP/1.1 200 OK\r\n')
        except socket.timeout:
            # Make sure the client isn't stuck waiting for us to e.g. accept.
            self._sock.close()
        except socket.error:
            # The client may have already closed the socket.
            pass

    def tearDown(self):
        try:
            self._sock.close()
        except socket.error:
            # We might have already closed it.  We don't care.
            pass
        self.host = None
        self.port = None


class TestWithTransport_pycurl(object):
    """Test case to inherit from if pycurl is present"""

    def _get_pycurl_maybe(self):
        try:
            from bzrlib.transport.http._pycurl import PyCurlTransport
            return PyCurlTransport
        except errors.DependencyNotPresent:
            raise tests.TestSkipped('pycurl not present')

    _transport = property(_get_pycurl_maybe)


class TestHttpUrls(tests.TestCase):

    # TODO: This should be moved to authorization tests once they
    # are written.

    def test_url_parsing(self):
        f = FakeManager()
        url = extract_auth('http://example.com', f)
        self.assertEquals('http://example.com', url)
        self.assertEquals(0, len(f.credentials))
        url = extract_auth('http://user:pass@www.bazaar-vcs.org/bzr/bzr.dev', f)
        self.assertEquals('http://www.bazaar-vcs.org/bzr/bzr.dev', url)
        self.assertEquals(1, len(f.credentials))
        self.assertEquals([None, 'www.bazaar-vcs.org', 'user', 'pass'],
                          f.credentials[0])


class TestHttpTransportUrls(object):
    """Test the http urls.

    This MUST be used by daughter classes that also inherit from
    TestCase.

    We can't inherit directly from TestCase or the
    test framework will try to create an instance which cannot
    run, its implementation being incomplete.
    """

    def test_abs_url(self):
        """Construction of absolute http URLs"""
        t = self._transport('http://bazaar-vcs.org/bzr/bzr.dev/')
        eq = self.assertEqualDiff
        eq(t.abspath('.'), 'http://bazaar-vcs.org/bzr/bzr.dev')
        eq(t.abspath('foo/bar'), 'http://bazaar-vcs.org/bzr/bzr.dev/foo/bar')
        eq(t.abspath('.bzr'), 'http://bazaar-vcs.org/bzr/bzr.dev/.bzr')
        eq(t.abspath('.bzr/1//2/./3'),
           'http://bazaar-vcs.org/bzr/bzr.dev/.bzr/1/2/3')

    def test_invalid_http_urls(self):
        """Trap invalid construction of urls"""
        t = self._transport('http://bazaar-vcs.org/bzr/bzr.dev/')
        self.assertRaises(errors.InvalidURL,
                          self._transport,
                          'http://http://bazaar-vcs.org/bzr/bzr.dev/')

    def test_http_root_urls(self):
        """Construction of URLs from server root"""
        t = self._transport('http://bzr.ozlabs.org/')
        eq = self.assertEqualDiff
        eq(t.abspath('.bzr/tree-version'),
           'http://bzr.ozlabs.org/.bzr/tree-version')

    def test_http_impl_urls(self):
        """There are servers which ask for particular clients to connect"""
        server = self._server()
        try:
            server.setUp()
            url = server.get_url()
            self.assertTrue(url.startswith('%s://' % self._qualified_prefix))
        finally:
            server.tearDown()


class TestHttpUrls_urllib(TestHttpTransportUrls, tests.TestCase):
    """Test http urls with urllib"""

    _transport = HttpTransport_urllib
    _server = HttpServer_urllib
    _qualified_prefix = 'http+urllib'


class TestHttpUrls_pycurl(TestWithTransport_pycurl, TestHttpTransportUrls,
                          tests.TestCase):
    """Test http urls with pycurl"""

    _server = HttpServer_PyCurl
    _qualified_prefix = 'http+pycurl'

    # TODO: This should really be moved into another pycurl
    # specific test. When https tests will be implemented, take
    # this one into account.
    def test_pycurl_without_https_support(self):
        """Test that pycurl without SSL do not fail with a traceback.

        For the purpose of the test, we force pycurl to ignore
        https by supplying a fake version_info that do not
        support it.
        """
        try:
            import pycurl
        except ImportError:
            raise tests.TestSkipped('pycurl not present')
        # Now that we have pycurl imported, we can fake its version_info
        # This was taken from a windows pycurl without SSL
        # (thanks to bialix)
        pycurl.version_info = lambda : (2,
                                        '7.13.2',
                                        462082,
                                        'i386-pc-win32',
                                        2576,
                                        None,
                                        0,
                                        None,
                                        ('ftp', 'gopher', 'telnet',
                                         'dict', 'ldap', 'http', 'file'),
                                        None,
                                        0,
                                        None)
        self.assertRaises(errors.DependencyNotPresent, self._transport,
                          'https://launchpad.net')

class TestHttpConnections(object):
    """Test the http connections.

    This MUST be used by daughter classes that also inherit from
    TestCaseWithWebserver.

    We can't inherit directly from TestCaseWithWebserver or the
    test framework will try to create an instance which cannot
    run, its implementation being incomplete.
    """

    def setUp(self):
        TestCaseWithWebserver.setUp(self)
        self.build_tree(['xxx', 'foo/', 'foo/bar'], line_endings='binary',
                        transport=self.get_transport())

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertEqual(t.has('foo/bar'), True)
        self.assertEqual(len(server.logs), 1)
        self.assertContainsRe(server.logs[0],
            r'"HEAD /foo/bar HTTP/1.." (200|302) - "-" "bzr/')

    def test_http_has_not_found(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertEqual(t.has('not-found'), False)
        self.assertContainsRe(server.logs[1],
            r'"HEAD /not-found HTTP/1.." 404 - "-" "bzr/')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        fp = t.get('foo/bar')
        self.assertEqualDiff(
            fp.read(),
            'contents of foo/bar\n')
        self.assertEqual(len(server.logs), 1)
        self.assertTrue(server.logs[0].find(
            '"GET /foo/bar HTTP/1.1" 200 - "-" "bzr/%s'
            % bzrlib.__version__) > -1)

    def test_get_smart_medium(self):
        # For HTTP, get_smart_medium should return the transport object.
        server = self.get_readonly_server()
        http_transport = self._transport(server.get_url())
        medium = http_transport.get_smart_medium()
        self.assertIs(medium, http_transport)

    def test_has_on_bogus_host(self):
        # Get a free address and don't 'accept' on it, so that we
        # can be sure there is no http handler there, but set a
        # reasonable timeout to not slow down tests too much.
        default_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(2)
            s = socket.socket()
            s.bind(('localhost', 0))
            t = self._transport('http://%s:%s/' % s.getsockname())
            self.assertRaises(errors.ConnectionError, t.has, 'foo/bar')
        finally:
            socket.setdefaulttimeout(default_timeout)


class TestHttpConnections_urllib(TestHttpConnections, TestCaseWithWebserver):
    """Test http connections with urllib"""

    _transport = HttpTransport_urllib



class TestHttpConnections_pycurl(TestWithTransport_pycurl,
                                 TestHttpConnections,
                                 TestCaseWithWebserver):
    """Test http connections with pycurl"""


class TestHttpTransportRegistration(tests.TestCase):
    """Test registrations of various http implementations"""

    def test_http_registered(self):
        # urlllib should always be present
        t = get_transport('http+urllib://bzr.google.com/')
        self.assertIsInstance(t, Transport)
        self.assertIsInstance(t, HttpTransport_urllib)


class TestPost(object):

    def _test_post_body_is_received(self, scheme):
        server = RecordingServer(expect_body_tail='end-of-body')
        server.setUp()
        self.addCleanup(server.tearDown)
        url = '%s://%s:%s/' % (scheme, server.host, server.port)
        try:
            http_transport = get_transport(url)
        except errors.UnsupportedProtocol:
            raise tests.TestSkipped('%s not available' % scheme)
        code, response = http_transport._post('abc def end-of-body')
        self.assertTrue(
            server.received_bytes.startswith('POST /.bzr/smart HTTP/1.'))
        self.assertTrue('content-length: 19\r' in server.received_bytes.lower())
        # The transport should not be assuming that the server can accept
        # chunked encoding the first time it connects, because HTTP/1.1, so we
        # check for the literal string.
        self.assertTrue(
            server.received_bytes.endswith('\r\n\r\nabc def end-of-body'))


class TestPost_urllib(tests.TestCase, TestPost):
    """TestPost for urllib implementation"""

    _transport = HttpTransport_urllib

    def test_post_body_is_received_urllib(self):
        self._test_post_body_is_received('http+urllib')


class TestPost_pycurl(TestWithTransport_pycurl, tests.TestCase, TestPost):
    """TestPost for pycurl implementation"""

    def test_post_body_is_received_pycurl(self):
        self._test_post_body_is_received('http+pycurl')


class TestRangeHeader(tests.TestCase):
    """Test range_header method"""

    def check_header(self, value, ranges=[], tail=0):
        offsets = [ (start, end - start + 1) for start, end in ranges]
        coalesce = Transport._coalesce_offsets
        coalesced = list(coalesce(offsets, limit=0, fudge_factor=0))
        range_header = HttpTransportBase._range_header
        self.assertEqual(value, range_header(coalesced, tail))

    def test_range_header_single(self):
        self.check_header('0-9', ranges=[(0,9)])
        self.check_header('100-109', ranges=[(100,109)])

    def test_range_header_tail(self):
        self.check_header('-10', tail=10)
        self.check_header('-50', tail=50)

    def test_range_header_multi(self):
        self.check_header('0-9,100-200,300-5000',
                          ranges=[(0,9), (100, 200), (300,5000)])

    def test_range_header_mixed(self):
        self.check_header('0-9,300-5000,-50',
                          ranges=[(0,9), (300,5000)],
                          tail=50)


class TestWallServer(object):
    """Tests exceptions during the connection phase"""

    def create_transport_readonly_server(self):
        return HttpServer(WallRequestHandler)

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        # Unfortunately httplib (see HTTPResponse._read_status
        # for details) make no distinction between a closed
        # socket and badly formatted status line, so we can't
        # just test for ConnectionError, we have to test
        # InvalidHttpResponse too.
        self.assertRaises((errors.ConnectionError, errors.InvalidHttpResponse),
                          t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises((errors.ConnectionError, errors.InvalidHttpResponse),
                          t.get, 'foo/bar')


class TestWallServer_urllib(TestWallServer, TestCaseWithWebserver):
    """Tests "wall" server for urllib implementation"""

    _transport = HttpTransport_urllib


class TestWallServer_pycurl(TestWithTransport_pycurl,
                            TestWallServer,
                            TestCaseWithWebserver):
    """Tests "wall" server for pycurl implementation"""


class TestBadStatusServer(object):
    """Tests bad status from server."""

    def create_transport_readonly_server(self):
        return HttpServer(BadStatusRequestHandler)

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.InvalidHttpResponse, t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'foo/bar')


class TestBadStatusServer_urllib(TestBadStatusServer, TestCaseWithWebserver):
    """Tests bad status server for urllib implementation"""

    _transport = HttpTransport_urllib


class TestBadStatusServer_pycurl(TestWithTransport_pycurl,
                                 TestBadStatusServer,
                                 TestCaseWithWebserver):
    """Tests bad status server for pycurl implementation"""


class TestInvalidStatusServer(TestBadStatusServer):
    """Tests invalid status from server.

    Both implementations raises the same error as for a bad status.
    """

    def create_transport_readonly_server(self):
        return HttpServer(InvalidStatusRequestHandler)


class TestInvalidStatusServer_urllib(TestInvalidStatusServer,
                                     TestCaseWithWebserver):
    """Tests invalid status server for urllib implementation"""

    _transport = HttpTransport_urllib


class TestInvalidStatusServer_pycurl(TestWithTransport_pycurl,
                                     TestInvalidStatusServer,
                                     TestCaseWithWebserver):
    """Tests invalid status server for pycurl implementation"""


class TestBadProtocolServer(object):
    """Tests bad protocol from server."""

    def create_transport_readonly_server(self):
        return HttpServer(BadProtocolRequestHandler)

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.InvalidHttpResponse, t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'foo/bar')


class TestBadProtocolServer_urllib(TestBadProtocolServer,
                                   TestCaseWithWebserver):
    """Tests bad protocol server for urllib implementation"""

    _transport = HttpTransport_urllib

# curl don't check the protocol version
#class TestBadProtocolServer_pycurl(TestWithTransport_pycurl,
#                                   TestBadProtocolServer,
#                                   TestCaseWithWebserver):
#    """Tests bad protocol server for pycurl implementation"""


class TestForbiddenServer(object):
    """Tests forbidden server"""

    def create_transport_readonly_server(self):
        return HttpServer(ForbiddenRequestHandler)

    def test_http_has(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.TransportError, t.has, 'foo/bar')

    def test_http_get(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        self.assertRaises(errors.TransportError, t.get, 'foo/bar')


class TestForbiddenServer_urllib(TestForbiddenServer, TestCaseWithWebserver):
    """Tests forbidden server for urllib implementation"""

    _transport = HttpTransport_urllib


class TestForbiddenServer_pycurl(TestWithTransport_pycurl,
                                 TestForbiddenServer,
                                 TestCaseWithWebserver):
    """Tests forbidden server for pycurl implementation"""


class TestRecordingServer(tests.TestCase):

    def test_create(self):
        server = RecordingServer(expect_body_tail=None)
        self.assertEqual('', server.received_bytes)
        self.assertEqual(None, server.host)
        self.assertEqual(None, server.port)

    def test_setUp_and_tearDown(self):
        server = RecordingServer(expect_body_tail=None)
        server.setUp()
        try:
            self.assertNotEqual(None, server.host)
            self.assertNotEqual(None, server.port)
        finally:
            server.tearDown()
        self.assertEqual(None, server.host)
        self.assertEqual(None, server.port)

    def test_send_receive_bytes(self):
        server = RecordingServer(expect_body_tail='c')
        server.setUp()
        self.addCleanup(server.tearDown)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((server.host, server.port))
        sock.sendall('abc')
        self.assertEqual('HTTP/1.1 200 OK\r\n',
                         osutils.recv_all(sock, 4096))
        self.assertEqual('abc', server.received_bytes)


class TestRangeRequestServer(object):
    """Tests readv requests against server.

    This MUST be used by daughter classes that also inherit from
    TestCaseWithWebserver.

    We can't inherit directly from TestCaseWithWebserver or the
    test framework will try to create an instance which cannot
    run, its implementation being incomplete.
    """

    def setUp(self):
        TestCaseWithWebserver.setUp(self)
        self.build_tree_contents([('a', '0123456789')],)

    def test_readv(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        l = list(t.readv('a', ((0, 1), (1, 1), (3, 2), (9, 1))))
        self.assertEqual(l[0], (0, '0'))
        self.assertEqual(l[1], (1, '1'))
        self.assertEqual(l[2], (3, '34'))
        self.assertEqual(l[3], (9, '9'))

    def test_readv_out_of_order(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        l = list(t.readv('a', ((1, 1), (9, 1), (0, 1), (3, 2))))
        self.assertEqual(l[0], (1, '1'))
        self.assertEqual(l[1], (9, '9'))
        self.assertEqual(l[2], (0, '0'))
        self.assertEqual(l[3], (3, '34'))

    def test_readv_invalid_ranges(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())

        # This is intentionally reading off the end of the file
        # since we are sure that it cannot get there
        self.assertListRaises((errors.InvalidRange, errors.ShortReadvError,),
                              t.readv, 'a', [(1,1), (8,10)])

        # This is trying to seek past the end of the file, it should
        # also raise a special error
        self.assertListRaises((errors.InvalidRange, errors.ShortReadvError,),
                              t.readv, 'a', [(12,2)])

    def test_readv_multiple_get_requests(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        # force transport to issue multiple requests
        t._max_readv_combine = 1
        t._max_get_ranges = 1
        l = list(t.readv('a', ((0, 1), (1, 1), (3, 2), (9, 1))))
        self.assertEqual(l[0], (0, '0'))
        self.assertEqual(l[1], (1, '1'))
        self.assertEqual(l[2], (3, '34'))
        self.assertEqual(l[3], (9, '9'))
        # The server should have issued 4 requests
        self.assertEqual(4, server.GET_request_nb)

    def test_readv_get_max_size(self):
        server = self.get_readonly_server()
        t = self._transport(server.get_url())
        # force transport to issue multiple requests by limiting the number of
        # bytes by request. Note that this apply to coalesced offsets only, a
        # single range ill keep its size even if bigger than the limit.
        t._get_max_size = 2
        l = list(t.readv('a', ((0, 1), (1, 1), (2, 4), (6, 4))))
        self.assertEqual(l[0], (0, '0'))
        self.assertEqual(l[1], (1, '1'))
        self.assertEqual(l[2], (2, '2345'))
        self.assertEqual(l[3], (6, '6789'))
        # The server should have issued 3 requests
        self.assertEqual(3, server.GET_request_nb)


class TestSingleRangeRequestServer(TestRangeRequestServer):
    """Test readv against a server which accept only single range requests"""

    def create_transport_readonly_server(self):
        return HttpServer(SingleRangeRequestHandler)


class TestSingleRangeRequestServer_urllib(TestSingleRangeRequestServer,
                                          TestCaseWithWebserver):
    """Tests single range requests accepting server for urllib implementation"""

    _transport = HttpTransport_urllib


class TestSingleRangeRequestServer_pycurl(TestWithTransport_pycurl,
                                          TestSingleRangeRequestServer,
                                          TestCaseWithWebserver):
    """Tests single range requests accepting server for pycurl implementation"""


class TestSingleOnlyRangeRequestServer(TestRangeRequestServer):
    """Test readv against a server which only accept single range requests"""

    def create_transport_readonly_server(self):
        return HttpServer(SingleOnlyRangeRequestHandler)


class TestSingleOnlyRangeRequestServer_urllib(TestSingleOnlyRangeRequestServer,
                                              TestCaseWithWebserver):
    """Tests single range requests accepting server for urllib implementation"""

    _transport = HttpTransport_urllib


class TestSingleOnlyRangeRequestServer_pycurl(TestWithTransport_pycurl,
                                              TestSingleOnlyRangeRequestServer,
                                              TestCaseWithWebserver):
    """Tests single range requests accepting server for pycurl implementation"""


class TestNoRangeRequestServer(TestRangeRequestServer):
    """Test readv against a server which do not accept range requests"""

    def create_transport_readonly_server(self):
        return HttpServer(NoRangeRequestHandler)


class TestNoRangeRequestServer_urllib(TestNoRangeRequestServer,
                                      TestCaseWithWebserver):
    """Tests range requests refusing server for urllib implementation"""

    _transport = HttpTransport_urllib


class TestNoRangeRequestServer_pycurl(TestWithTransport_pycurl,
                                      TestNoRangeRequestServer,
                                      TestCaseWithWebserver):
    """Tests range requests refusing server for pycurl implementation"""


class TestLimitedRangeRequestServer(object):
    """Tests readv requests against server that errors out on too much ranges.

    This MUST be used by daughter classes that also inherit from
    TestCaseWithWebserver.

    We can't inherit directly from TestCaseWithWebserver or the
    test framework will try to create an instance which cannot
    run, its implementation being incomplete.
    """

    range_limit = 3

    def create_transport_readonly_server(self):
        # Requests with more range specifiers will error out
        return LimitedRangeHTTPServer(range_limit=self.range_limit)

    def get_transport(self):
        return self._transport(self.get_readonly_server().get_url())

    def setUp(self):
        TestCaseWithWebserver.setUp(self)
        # We need to manipulate ranges that correspond to real chunks in the
        # response, so we build a content appropriately.
        filler = ''.join(['abcdefghij' for x in range(102)])
        content = ''.join(['%04d' % v + filler for v in range(16)])
        self.build_tree_contents([('a', content)],)

    def test_few_ranges(self):
        t = self.get_transport()
        l = list(t.readv('a', ((0, 4), (1024, 4), )))
        self.assertEqual(l[0], (0, '0000'))
        self.assertEqual(l[1], (1024, '0001'))
        self.assertEqual(1, self.get_readonly_server().GET_request_nb)

    def test_more_ranges(self):
        t = self.get_transport()
        l = list(t.readv('a', ((0, 4), (1024, 4), (4096, 4), (8192, 4))))
        self.assertEqual(l[0], (0, '0000'))
        self.assertEqual(l[1], (1024, '0001'))
        self.assertEqual(l[2], (4096, '0004'))
        self.assertEqual(l[3], (8192, '0008'))
        # The server will refuse to serve the first request (too much ranges),
        # a second request will succeeds.
        self.assertEqual(2, self.get_readonly_server().GET_request_nb)


class TestLimitedRangeRequestServer_urllib(TestLimitedRangeRequestServer,
                                          TestCaseWithWebserver):
    """Tests limited range requests server for urllib implementation"""

    _transport = HttpTransport_urllib


class TestLimitedRangeRequestServer_pycurl(TestWithTransport_pycurl,
                                          TestLimitedRangeRequestServer,
                                          TestCaseWithWebserver):
    """Tests limited range requests server for pycurl implementation"""



class TestHttpProxyWhiteBox(tests.TestCase):
    """Whitebox test proxy http authorization.

    Only the urllib implementation is tested here.
    """

    def setUp(self):
        tests.TestCase.setUp(self)
        self._old_env = {}

    def tearDown(self):
        self._restore_env()

    def _install_env(self, env):
        for name, value in env.iteritems():
            self._old_env[name] = osutils.set_or_unset_env(name, value)

    def _restore_env(self):
        for name, value in self._old_env.iteritems():
            osutils.set_or_unset_env(name, value)

    def _proxied_request(self):
        handler = ProxyHandler()
        request = Request('GET','http://baz/buzzle')
        handler.set_proxy(request, 'http')
        return request

    def test_empty_user(self):
        self._install_env({'http_proxy': 'http://bar.com'})
        request = self._proxied_request()
        self.assertFalse(request.headers.has_key('Proxy-authorization'))

    def test_invalid_proxy(self):
        """A proxy env variable without scheme"""
        self._install_env({'http_proxy': 'host:1234'})
        self.assertRaises(errors.InvalidURL, self._proxied_request)


class TestProxyHttpServer(object):
    """Tests proxy server.

    This MUST be used by daughter classes that also inherit from
    TestCaseWithTwoWebservers.

    We can't inherit directly from TestCaseWithTwoWebservers or
    the test framework will try to create an instance which
    cannot run, its implementation being incomplete.

    Be aware that we do not setup a real proxy here. Instead, we
    check that the *connection* goes through the proxy by serving
    different content (the faked proxy server append '-proxied'
    to the file names).
    """

    # FIXME: We don't have an https server available, so we don't
    # test https connections.

    def setUp(self):
        TestCaseWithTwoWebservers.setUp(self)
        self.build_tree_contents([('foo', 'contents of foo\n'),
                                  ('foo-proxied', 'proxied contents of foo\n')])
        # Let's setup some attributes for tests
        self.server = self.get_readonly_server()
        self.proxy_address = '%s:%d' % (self.server.host, self.server.port)
        self.no_proxy_host = self.proxy_address
        # The secondary server is the proxy
        self.proxy = self.get_secondary_server()
        self.proxy_url = self.proxy.get_url()
        self._old_env = {}

    def create_transport_secondary_server(self):
        """Creates an http server that will serve files with
        '-proxied' appended to their names.
        """
        return ProxyServer()

    def _install_env(self, env):
        for name, value in env.iteritems():
            self._old_env[name] = osutils.set_or_unset_env(name, value)

    def _restore_env(self):
        for name, value in self._old_env.iteritems():
            osutils.set_or_unset_env(name, value)

    def proxied_in_env(self, env):
        self._install_env(env)
        url = self.server.get_url()
        t = self._transport(url)
        try:
            self.assertEqual(t.get('foo').read(), 'proxied contents of foo\n')
        finally:
            self._restore_env()

    def not_proxied_in_env(self, env):
        self._install_env(env)
        url = self.server.get_url()
        t = self._transport(url)
        try:
            self.assertEqual(t.get('foo').read(), 'contents of foo\n')
        finally:
            self._restore_env()

    def test_http_proxy(self):
        self.proxied_in_env({'http_proxy': self.proxy_url})

    def test_HTTP_PROXY(self):
        self.proxied_in_env({'HTTP_PROXY': self.proxy_url})

    def test_all_proxy(self):
        self.proxied_in_env({'all_proxy': self.proxy_url})

    def test_ALL_PROXY(self):
        self.proxied_in_env({'ALL_PROXY': self.proxy_url})

    def test_http_proxy_with_no_proxy(self):
        self.not_proxied_in_env({'http_proxy': self.proxy_url,
                                 'no_proxy': self.no_proxy_host})

    def test_HTTP_PROXY_with_NO_PROXY(self):
        self.not_proxied_in_env({'HTTP_PROXY': self.proxy_url,
                                 'NO_PROXY': self.no_proxy_host})

    def test_all_proxy_with_no_proxy(self):
        self.not_proxied_in_env({'all_proxy': self.proxy_url,
                                 'no_proxy': self.no_proxy_host})

    def test_ALL_PROXY_with_NO_PROXY(self):
        self.not_proxied_in_env({'ALL_PROXY': self.proxy_url,
                                 'NO_PROXY': self.no_proxy_host})

    def test_http_proxy_without_scheme(self):
        self.assertRaises(errors.InvalidURL,
                          self.proxied_in_env,
                          {'http_proxy': self.proxy_address})


class TestProxyHttpServer_urllib(TestProxyHttpServer,
                                 TestCaseWithTwoWebservers):
    """Tests proxy server for urllib implementation"""

    _transport = HttpTransport_urllib


class TestProxyHttpServer_pycurl(TestWithTransport_pycurl,
                                 TestProxyHttpServer,
                                 TestCaseWithTwoWebservers):
    """Tests proxy server for pycurl implementation"""

    def setUp(self):
        TestProxyHttpServer.setUp(self)
        # Oh my ! pycurl does not check for the port as part of
        # no_proxy :-( So we just test the host part
        self.no_proxy_host = 'localhost'

    def test_HTTP_PROXY(self):
        # pycurl does not check HTTP_PROXY for security reasons
        # (for use in a CGI context that we do not care
        # about. Should we ?)
        raise tests.TestNotApplicable(
            'pycurl does not check HTTP_PROXY for security reasons')

    def test_HTTP_PROXY_with_NO_PROXY(self):
        raise tests.TestNotApplicable(
            'pycurl does not check HTTP_PROXY for security reasons')

    def test_http_proxy_without_scheme(self):
        # pycurl *ignores* invalid proxy env variables. If that
        # ever change in the future, this test will fail
        # indicating that pycurl do not ignore anymore such
        # variables.
        self.not_proxied_in_env({'http_proxy': self.proxy_address})


class TestRanges(object):
    """Test the Range header in GET methods..

    This MUST be used by daughter classes that also inherit from
    TestCaseWithWebserver.

    We can't inherit directly from TestCaseWithWebserver or the
    test framework will try to create an instance which cannot
    run, its implementation being incomplete.
    """

    def setUp(self):
        TestCaseWithWebserver.setUp(self)
        self.build_tree_contents([('a', '0123456789')],)
        server = self.get_readonly_server()
        self.transport = self._transport(server.get_url())

    def _file_contents(self, relpath, ranges):
        offsets = [ (start, end - start + 1) for start, end in ranges]
        coalesce = self.transport._coalesce_offsets
        coalesced = list(coalesce(offsets, limit=0, fudge_factor=0))
        code, data = self.transport._get(relpath, coalesced)
        self.assertTrue(code in (200, 206),'_get returns: %d' % code)
        for start, end in ranges:
            data.seek(start)
            yield data.read(end - start + 1)

    def _file_tail(self, relpath, tail_amount):
        code, data = self.transport._get(relpath, [], tail_amount)
        self.assertTrue(code in (200, 206),'_get returns: %d' % code)
        data.seek(-tail_amount, 2)
        return data.read(tail_amount)

    def test_range_header(self):
        # Valid ranges
        map(self.assertEqual,['0', '234'],
            list(self._file_contents('a', [(0,0), (2,4)])),)
        # Tail
        self.assertEqual('789', self._file_tail('a', 3))
        # Syntactically invalid range
        self.assertListRaises(errors.InvalidHttpRange,
                          self._file_contents, 'a', [(4, 3)])
        # Semantically invalid range
        self.assertListRaises(errors.InvalidHttpRange,
                          self._file_contents, 'a', [(42, 128)])


class TestRanges_urllib(TestRanges, TestCaseWithWebserver):
    """Test the Range header in GET methods for urllib implementation"""

    _transport = HttpTransport_urllib


class TestRanges_pycurl(TestWithTransport_pycurl,
                        TestRanges,
                        TestCaseWithWebserver):
    """Test the Range header in GET methods for pycurl implementation"""


class TestHTTPRedirections(object):
    """Test redirection between http servers.

    This MUST be used by daughter classes that also inherit from
    TestCaseWithRedirectedWebserver.

    We can't inherit directly from TestCaseWithTwoWebservers or the
    test framework will try to create an instance which cannot
    run, its implementation being incomplete. 
    """

    def create_transport_secondary_server(self):
        """Create the secondary server redirecting to the primary server"""
        new = self.get_readonly_server()

        redirecting = HTTPServerRedirecting()
        redirecting.redirect_to(new.host, new.port)
        return redirecting

    def setUp(self):
        super(TestHTTPRedirections, self).setUp()
        self.build_tree_contents([('a', '0123456789'),
                                  ('bundle',
                                  '# Bazaar revision bundle v0.9\n#\n')
                                  ],)

        self.old_transport = self._transport(self.old_server.get_url())

    def test_redirected(self):
        self.assertRaises(errors.RedirectRequested, self.old_transport.get, 'a')
        t = self._transport(self.new_server.get_url())
        self.assertEqual('0123456789', t.get('a').read())

    def test_read_redirected_bundle_from_url(self):
        from bzrlib.bundle import read_bundle_from_url
        url = self.old_transport.abspath('bundle')
        bundle = read_bundle_from_url(url)
        # If read_bundle_from_url was successful we get an empty bundle
        self.assertEqual([], bundle.revisions)


class TestHTTPRedirections_urllib(TestHTTPRedirections,
                                  TestCaseWithRedirectedWebserver):
    """Tests redirections for urllib implementation"""

    _transport = HttpTransport_urllib



class TestHTTPRedirections_pycurl(TestWithTransport_pycurl,
                                  TestHTTPRedirections,
                                  TestCaseWithRedirectedWebserver):
    """Tests redirections for pycurl implementation"""


class RedirectedRequest(Request):
    """Request following redirections"""

    init_orig = Request.__init__

    def __init__(self, method, url, *args, **kwargs):
        RedirectedRequest.init_orig(self, method, url, args, kwargs)
        self.follow_redirections = True


class TestHTTPSilentRedirections_urllib(TestCaseWithRedirectedWebserver):
    """Test redirections provided by urllib.

    http implementations do not redirect silently anymore (they
    do not redirect at all in fact). The mechanism is still in
    place at the _urllib2_wrappers.Request level and these tests
    exercise it.

    For the pycurl implementation
    the redirection have been deleted as we may deprecate pycurl
    and I have no place to keep a working implementation.
    -- vila 20070212
    """

    _transport = HttpTransport_urllib

    def setUp(self):
        super(TestHTTPSilentRedirections_urllib, self).setUp()
        self.setup_redirected_request()
        self.addCleanup(self.cleanup_redirected_request)
        self.build_tree_contents([('a','a'),
                                  ('1/',),
                                  ('1/a', 'redirected once'),
                                  ('2/',),
                                  ('2/a', 'redirected twice'),
                                  ('3/',),
                                  ('3/a', 'redirected thrice'),
                                  ('4/',),
                                  ('4/a', 'redirected 4 times'),
                                  ('5/',),
                                  ('5/a', 'redirected 5 times'),
                                  ],)

        self.old_transport = self._transport(self.old_server.get_url())

    def setup_redirected_request(self):
        self.original_class = _urllib2_wrappers.Request
        _urllib2_wrappers.Request = RedirectedRequest

    def cleanup_redirected_request(self):
        _urllib2_wrappers.Request = self.original_class

    def create_transport_secondary_server(self):
        """Create the secondary server, redirections are defined in the tests"""
        return HTTPServerRedirecting()

    def test_one_redirection(self):
        t = self.old_transport

        req = RedirectedRequest('GET', t.abspath('a'))
        req.follow_redirections = True
        new_prefix = 'http://%s:%s' % (self.new_server.host,
                                       self.new_server.port)
        self.old_server.redirections = \
            [('(.*)', r'%s/1\1' % (new_prefix), 301),]
        self.assertEquals('redirected once',t._perform(req).read())

    def test_five_redirections(self):
        t = self.old_transport

        req = RedirectedRequest('GET', t.abspath('a'))
        req.follow_redirections = True
        old_prefix = 'http://%s:%s' % (self.old_server.host,
                                       self.old_server.port)
        new_prefix = 'http://%s:%s' % (self.new_server.host,
                                       self.new_server.port)
        self.old_server.redirections = \
            [('/1(.*)', r'%s/2\1' % (old_prefix), 302),
             ('/2(.*)', r'%s/3\1' % (old_prefix), 303),
             ('/3(.*)', r'%s/4\1' % (old_prefix), 307),
             ('/4(.*)', r'%s/5\1' % (new_prefix), 301),
             ('(/[^/]+)', r'%s/1\1' % (old_prefix), 301),
             ]
        self.assertEquals('redirected 5 times',t._perform(req).read())


class TestDoCatchRedirections(TestCaseWithRedirectedWebserver):
    """Test transport.do_catching_redirections.

    We arbitrarily choose to use urllib transports
    """

    _transport = HttpTransport_urllib

    def setUp(self):
        super(TestDoCatchRedirections, self).setUp()
        self.build_tree_contents([('a', '0123456789'),],)

        self.old_transport = self._transport(self.old_server.get_url())

    def get_a(self, transport):
        return transport.get('a')

    def test_no_redirection(self):
        t = self._transport(self.new_server.get_url())

        # We use None for redirected so that we fail if redirected
        self.assertEquals('0123456789',
                          do_catching_redirections(self.get_a, t, None).read())

    def test_one_redirection(self):
        self.redirections = 0

        def redirected(transport, exception, redirection_notice):
            self.redirections += 1
            dir, file = urlutils.split(exception.target)
            return self._transport(dir)

        self.assertEquals('0123456789',
                          do_catching_redirections(self.get_a,
                                                   self.old_transport,
                                                   redirected
                                                   ).read())
        self.assertEquals(1, self.redirections)

    def test_redirection_loop(self):

        def redirected(transport, exception, redirection_notice):
            # By using the redirected url as a base dir for the
            # *old* transport, we create a loop: a => a/a =>
            # a/a/a
            return self.old_transport.clone(exception.target)

        self.assertRaises(errors.TooManyRedirections, do_catching_redirections,
                          self.get_a, self.old_transport, redirected)


class TestAuth(object):
    """Test some authentication scheme specified by daughter class.

    This MUST be used by daughter classes that also inherit from
    either TestCaseWithWebserver or TestCaseWithTwoWebservers.
    """

    _password_prompt_prefix = ''

    def setUp(self):
        """Set up the test environment

        Daughter classes should set up their own environment
        (including self.server) and explicitely call this
        method. This is needed because we want to reuse the same
        tests for proxy and no-proxy accesses which have
        different ways of setting self.server.
        """
        self.build_tree_contents([('a', 'contents of a\n'),
                                  ('b', 'contents of b\n'),])

    def get_user_url(self, user=None, password=None):
        """Build an url embedding user and password"""
        url = '%s://' % self.server._url_protocol
        if user is not None:
            url += user
            if password is not None:
                url += ':' + password
            url += '@'
        url += '%s:%s/' % (self.server.host, self.server.port)
        return url

    def test_no_user(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport()
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'a')
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_empty_pass(self):
        self.server.add_user('joe', '')
        t = self.get_user_transport('joe', '')
        self.assertEqual('contents of a\n', t.get('a').read())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_user_pass(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', 'foo')
        self.assertEqual('contents of a\n', t.get('a').read())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def test_unknown_user(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('bill', 'foo')
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'a')
        # Two 'Authentication Required' errors should occur (the
        # initial 'who are you' and 'I don't know you, who are
        # you').
        self.assertEqual(2, self.server.auth_required_errors)

    def test_wrong_pass(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', 'bar')
        self.assertRaises(errors.InvalidHttpResponse, t.get, 'a')
        # Two 'Authentication Required' errors should occur (the
        # initial 'who are you' and 'this is not you, who are you')
        self.assertEqual(2, self.server.auth_required_errors)

    def test_prompt_for_password(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', None)
        stdout = tests.StringIOWrapper()
        ui.ui_factory = tests.TestUIFactory(stdin='foo\n', stdout=stdout)
        self.assertEqual('contents of a\n',t.get('a').read())
        # stdin should be empty
        self.assertEqual('', ui.ui_factory.stdin.readline())
        self._check_password_prompt(t._unqualified_scheme, 'joe',
                                    stdout.getvalue())
        # And we shouldn't prompt again for a different request
        # against the same transport.
        self.assertEqual('contents of b\n',t.get('b').read())
        t2 = t.clone()
        # And neither against a clone
        self.assertEqual('contents of b\n',t2.get('b').read())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)

    def _check_password_prompt(self, scheme, user, actual_prompt):
        expected_prompt = (self._password_prompt_prefix
                           + ("%s %s@%s:%d, Realm: '%s' password: "
                              % (scheme.upper(),
                                 user, self.server.host, self.server.port,
                                 self.server.auth_realm)))
        self.assertEquals(expected_prompt, actual_prompt)

    def test_no_prompt_for_password_when_using_auth_config(self):
        user =' joe'
        password = 'foo'
        stdin_content = 'bar\n'  # Not the right password
        self.server.add_user(user, password)
        t = self.get_user_transport(user, None)
        ui.ui_factory = tests.TestUIFactory(stdin=stdin_content,
                                            stdout=tests.StringIOWrapper())
        # Create a minimal config file with the right password
        conf = config.AuthenticationConfig()
        conf._get_config().update(
            {'httptest': {'scheme': 'http', 'port': self.server.port,
                          'user': user, 'password': password}})
        conf._save()
        # Issue a request to the server to connect
        self.assertEqual('contents of a\n',t.get('a').read())
        # stdin should have  been left untouched
        self.assertEqual(stdin_content, ui.ui_factory.stdin.readline())
        # Only one 'Authentication Required' error should occur
        self.assertEqual(1, self.server.auth_required_errors)



class TestHTTPAuth(TestAuth):
    """Test HTTP authentication schemes.

    Daughter classes MUST inherit from TestCaseWithWebserver too.
    """

    _auth_header = 'Authorization'

    def setUp(self):
        TestCaseWithWebserver.setUp(self)
        self.server = self.get_readonly_server()
        TestAuth.setUp(self)

    def get_user_transport(self, user=None, password=None):
        return self._transport(self.get_user_url(user, password))


class TestProxyAuth(TestAuth):
    """Test proxy authentication schemes.

    Daughter classes MUST also inherit from TestCaseWithWebserver.
    """
    _auth_header = 'Proxy-authorization'
    _password_prompt_prefix = 'Proxy '


    def setUp(self):
        TestCaseWithWebserver.setUp(self)
        self.server = self.get_readonly_server()
        self._old_env = {}
        self.addCleanup(self._restore_env)
        TestAuth.setUp(self)
        # Override the contents to avoid false positives
        self.build_tree_contents([('a', 'not proxied contents of a\n'),
                                  ('b', 'not proxied contents of b\n'),
                                  ('a-proxied', 'contents of a\n'),
                                  ('b-proxied', 'contents of b\n'),
                                  ])

    def get_user_transport(self, user=None, password=None):
        self._install_env({'all_proxy': self.get_user_url(user, password)})
        return self._transport(self.server.get_url())

    def _install_env(self, env):
        for name, value in env.iteritems():
            self._old_env[name] = osutils.set_or_unset_env(name, value)

    def _restore_env(self):
        for name, value in self._old_env.iteritems():
            osutils.set_or_unset_env(name, value)


class TestHTTPBasicAuth(TestWithTransport_pycurl, TestHTTPAuth,
                        TestCaseWithWebserver):
    """Test http basic authentication scheme"""

    def create_transport_readonly_server(self):
        return HTTPBasicAuthServer()


class TestHTTPProxyBasicAuth(TestWithTransport_pycurl, 
                             TestProxyAuth, TestCaseWithWebserver):
    """Test proxy basic authentication scheme"""

    def create_transport_readonly_server(self):
        return ProxyBasicAuthServer()


class TestDigestAuth(object):
    """Digest Authentication specific tests"""

    def test_changing_nonce(self):
        self.server.add_user('joe', 'foo')
        t = self.get_user_transport('joe', 'foo')
        self.assertEqual('contents of a\n', t.get('a').read())
        self.assertEqual('contents of b\n', t.get('b').read())
        # Only one 'Authentication Required' error should have
        # occured so far
        self.assertEqual(1, self.server.auth_required_errors)
        # The server invalidates the current nonce
        self.server.auth_nonce = self.server.auth_nonce + '. No, now!'
        self.assertEqual('contents of a\n', t.get('a').read())
        # Two 'Authentication Required' errors should occur (the
        # initial 'who are you' and a second 'who are you' with the new nonce)
        self.assertEqual(2, self.server.auth_required_errors)


class TestHTTPDigestAuth(TestWithTransport_pycurl,
                         TestHTTPAuth, TestDigestAuth, TestCaseWithWebserver):
    """Test http digest authentication scheme"""

    def create_transport_readonly_server(self):
        return HTTPDigestAuthServer()


class TestHTTPProxyDigestAuth(TestWithTransport_pycurl, TestProxyAuth,
                              TestDigestAuth, TestCaseWithWebserver):
    """Test proxy digest authentication scheme"""

    def create_transport_readonly_server(self):
        return ProxyDigestAuthServer()

