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

import errno
import select
import socket
import threading

import bzrlib
from bzrlib.errors import DependencyNotPresent, UnsupportedProtocol
from bzrlib.tests import TestCase, TestSkipped
from bzrlib.transport import get_transport, Transport
from bzrlib.transport.http import extract_auth, HttpTransportBase
from bzrlib.transport.http._urllib import HttpTransport_urllib
from bzrlib.tests.HTTPTestUtil import TestCaseWithWebserver


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

    def tearDown(self):
        try:
            self._sock.close()
        except socket.error:
            # We might have already closed it.  We don't care.
            pass
        self.host = None
        self.port = None


class TestHttpUrls(TestCase):

    def test_url_parsing(self):
        f = FakeManager()
        url = extract_auth('http://example.com', f)
        self.assertEquals('http://example.com', url)
        self.assertEquals(0, len(f.credentials))
        url = extract_auth('http://user:pass@www.bazaar-vcs.org/bzr/bzr.dev', f)
        self.assertEquals('http://www.bazaar-vcs.org/bzr/bzr.dev', url)
        self.assertEquals(1, len(f.credentials))
        self.assertEquals([None, 'www.bazaar-vcs.org', 'user', 'pass'], f.credentials[0])
        
    def test_abs_url(self):
        """Construction of absolute http URLs"""
        t = HttpTransport_urllib('http://bazaar-vcs.org/bzr/bzr.dev/')
        eq = self.assertEqualDiff
        eq(t.abspath('.'),
           'http://bazaar-vcs.org/bzr/bzr.dev')
        eq(t.abspath('foo/bar'), 
           'http://bazaar-vcs.org/bzr/bzr.dev/foo/bar')
        eq(t.abspath('.bzr'),
           'http://bazaar-vcs.org/bzr/bzr.dev/.bzr')
        eq(t.abspath('.bzr/1//2/./3'),
           'http://bazaar-vcs.org/bzr/bzr.dev/.bzr/1/2/3')

    def test_invalid_http_urls(self):
        """Trap invalid construction of urls"""
        t = HttpTransport_urllib('http://bazaar-vcs.org/bzr/bzr.dev/')
        self.assertRaises(ValueError,
            t.abspath,
            '.bzr/')

    def test_http_root_urls(self):
        """Construction of URLs from server root"""
        t = HttpTransport_urllib('http://bzr.ozlabs.org/')
        eq = self.assertEqualDiff
        eq(t.abspath('.bzr/tree-version'),
           'http://bzr.ozlabs.org/.bzr/tree-version')

    def test_http_impl_urls(self):
        """There are servers which ask for particular clients to connect"""
        try:
            from bzrlib.transport.http._pycurl import HttpServer_PyCurl
            server = HttpServer_PyCurl()
            try:
                server.setUp()
                url = server.get_url()
                self.assertTrue(url.startswith('http+pycurl://'))
            finally:
                server.tearDown()
        except DependencyNotPresent:
            raise TestSkipped('pycurl not present')


class TestHttpMixins(object):

    def _prep_tree(self):
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
            '"GET /foo/bar HTTP/1.1" 200 - "-" "bzr/%s' % bzrlib.__version__) > -1)

    def test_get_smart_medium(self):
        # For HTTP, get_smart_medium should return the transport object.
        server = self.get_readonly_server()
        http_transport = self._transport(server.get_url())
        medium = http_transport.get_smart_medium()
        self.assertIs(medium, http_transport)
        

class TestHttpConnections_urllib(TestCaseWithWebserver, TestHttpMixins):

    _transport = HttpTransport_urllib

    def setUp(self):
        TestCaseWithWebserver.setUp(self)
        self._prep_tree()

    def test_has_on_bogus_host(self):
        import urllib2
        # Get a random address, so that we can be sure there is no
        # http handler there.
        s = socket.socket()
        s.bind(('localhost', 0))
        t = self._transport('http://%s:%s/' % s.getsockname())
        self.assertRaises(urllib2.URLError, t.has, 'foo/bar')


class TestHttpConnections_pycurl(TestCaseWithWebserver, TestHttpMixins):

    def _get_pycurl_maybe(self):
        try:
            from bzrlib.transport.http._pycurl import PyCurlTransport
            return PyCurlTransport
        except DependencyNotPresent:
            raise TestSkipped('pycurl not present')

    _transport = property(_get_pycurl_maybe)

    def setUp(self):
        TestCaseWithWebserver.setUp(self)
        self._prep_tree()


class TestHttpTransportRegistration(TestCase):
    """Test registrations of various http implementations"""

    def test_http_registered(self):
        import bzrlib.transport.http._urllib
        from bzrlib.transport import get_transport
        # urlllib should always be present
        t = get_transport('http+urllib://bzr.google.com/')
        self.assertIsInstance(t, Transport)
        self.assertIsInstance(t, bzrlib.transport.http._urllib.HttpTransport_urllib)


class TestOffsets(TestCase):
    """Test offsets_to_ranges method"""

    def test_offsets_to_ranges_simple(self):
        to_range = HttpTransportBase.offsets_to_ranges
        ranges = to_range([(10, 1)])
        self.assertEqual([[10, 10]], ranges)

        ranges = to_range([(0, 1), (1, 1)])
        self.assertEqual([[0, 1]], ranges)

        ranges = to_range([(1, 1), (0, 1)])
        self.assertEqual([[0, 1]], ranges)

    def test_offset_to_ranges_overlapped(self):
        to_range = HttpTransportBase.offsets_to_ranges

        ranges = to_range([(10, 1), (20, 2), (22, 5)])
        self.assertEqual([[10, 10], [20, 26]], ranges)

        ranges = to_range([(10, 1), (11, 2), (22, 5)])
        self.assertEqual([[10, 12], [22, 26]], ranges)


class TestPost(TestCase):

    def _test_post_body_is_received(self, scheme):
        server = RecordingServer(expect_body_tail='end-of-body')
        server.setUp()
        self.addCleanup(server.tearDown)
        url = '%s://%s:%s/' % (scheme, server.host, server.port)
        try:
            http_transport = get_transport(url)
        except UnsupportedProtocol:
            raise TestSkipped('%s not available' % scheme)
        code, response = http_transport._post('abc def end-of-body')
        self.assertTrue(
            server.received_bytes.startswith('POST /.bzr/smart HTTP/1.'))
        self.assertTrue('content-length: 19\r' in server.received_bytes.lower())
        # The transport should not be assuming that the server can accept
        # chunked encoding the first time it connects, because HTTP/1.1, so we
        # check for the literal string.
        self.assertTrue(
            server.received_bytes.endswith('\r\n\r\nabc def end-of-body'))

    def test_post_body_is_received_urllib(self):
        self._test_post_body_is_received('http+urllib')

    def test_post_body_is_received_pycurl(self):
        self._test_post_body_is_received('http+pycurl')


class TestRangeHeader(TestCase):
    """Test range_header method"""

    def check_header(self, value, ranges=[], tail=0):
        range_header = HttpTransportBase.range_header
        self.assertEqual(value, range_header(ranges, tail))

    def test_range_header_single(self):
        self.check_header('0-9', ranges=[[0,9]])
        self.check_header('100-109', ranges=[[100,109]])

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

        
class TestRecordingServer(TestCase):

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
                         sock.recv(4096, socket.MSG_WAITALL))
        self.assertEqual('abc', server.received_bytes)
