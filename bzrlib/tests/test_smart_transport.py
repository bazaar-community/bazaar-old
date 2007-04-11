# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Tests for smart transport"""

# all of this deals with byte strings so this is safe
from cStringIO import StringIO
import os
import socket
import threading
import urllib2

from bzrlib import (
        bzrdir,
        errors,
        osutils,
        smart,
        tests,
        urlutils,
        )
from bzrlib.smart import (
        client,
        medium,
        protocol,
        request,
        server,
        vfs,
)
from bzrlib.tests.HTTPTestUtil import (
        HTTPServerWithSmarts,
        SmartRequestHandler,
        )
from bzrlib.tests.test_smart import TestCaseWithSmartMedium
from bzrlib.transport import (
        get_transport,
        local,
        memory,
        remote,
        )
from bzrlib.transport.http import SmartClientHTTPMediumRequest


class StringIOSSHVendor(object):
    """A SSH vendor that uses StringIO to buffer writes and answer reads."""

    def __init__(self, read_from, write_to):
        self.read_from = read_from
        self.write_to = write_to
        self.calls = []

    def connect_ssh(self, username, password, host, port, command):
        self.calls.append(('connect_ssh', username, password, host, port,
            command))
        return StringIOSSHConnection(self)


class StringIOSSHConnection(object):
    """A SSH connection that uses StringIO to buffer writes and answer reads."""

    def __init__(self, vendor):
        self.vendor = vendor
    
    def close(self):
        self.vendor.calls.append(('close', ))
        
    def get_filelike_channels(self):
        return self.vendor.read_from, self.vendor.write_to



class SmartClientMediumTests(tests.TestCase):
    """Tests for SmartClientMedium.

    We should create a test scenario for this: we need a server module that
    construct the test-servers (like make_loopsocket_and_medium), and the list
    of SmartClientMedium classes to test.
    """

    def make_loopsocket_and_medium(self):
        """Create a loopback socket for testing, and a medium aimed at it."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        client_medium = medium.SmartTCPClientMedium('127.0.0.1', port)
        return sock, client_medium

    def receive_bytes_on_server(self, sock, bytes):
        """Accept a connection on sock and read 3 bytes.

        The bytes are appended to the list bytes.

        :return: a Thread which is running to do the accept and recv.
        """
        def _receive_bytes_on_server():
            connection, address = sock.accept()
            bytes.append(osutils.recv_all(connection, 3))
            connection.close()
        t = threading.Thread(target=_receive_bytes_on_server)
        t.start()
        return t
    
    def test_construct_smart_stream_medium_client(self):
        # make a new instance of the common base for Stream-like Mediums.
        # this just ensures that the constructor stays parameter-free which
        # is important for reuse : some subclasses will dynamically connect,
        # others are always on, etc.
        client_medium = medium.SmartClientStreamMedium()

    def test_construct_smart_client_medium(self):
        # the base client medium takes no parameters
        client_medium = medium.SmartClientMedium()
    
    def test_construct_smart_simple_pipes_client_medium(self):
        # the SimplePipes client medium takes two pipes:
        # readable pipe, writeable pipe.
        # Constructing one should just save these and do nothing.
        # We test this by passing in None.
        client_medium = medium.SmartSimplePipesClientMedium(None, None)
        
    def test_simple_pipes_client_request_type(self):
        # SimplePipesClient should use SmartClientStreamMediumRequest's.
        client_medium = medium.SmartSimplePipesClientMedium(None, None)
        request = client_medium.get_request()
        self.assertIsInstance(request, medium.SmartClientStreamMediumRequest)

    def test_simple_pipes_client_get_concurrent_requests(self):
        # the simple_pipes client does not support pipelined requests:
        # but it does support serial requests: we construct one after 
        # another is finished. This is a smoke test testing the integration
        # of the SmartClientStreamMediumRequest and the SmartClientStreamMedium
        # classes - as the sibling classes share this logic, they do not have
        # explicit tests for this.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = client_medium.get_request()
        request.finished_writing()
        request.finished_reading()
        request2 = client_medium.get_request()
        request2.finished_writing()
        request2.finished_reading()

    def test_simple_pipes_client__accept_bytes_writes_to_writable(self):
        # accept_bytes writes to the writeable pipe.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        client_medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
    
    def test_simple_pipes_client_disconnect_does_nothing(self):
        # calling disconnect does nothing.
        input = StringIO()
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        # send some bytes to ensure disconnecting after activity still does not
        # close.
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        self.assertFalse(input.closed)
        self.assertFalse(output.closed)

    def test_simple_pipes_client_accept_bytes_after_disconnect(self):
        # calling disconnect on the client does not alter the pipe that
        # accept_bytes writes to.
        input = StringIO()
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        client_medium._accept_bytes('abc')
        self.assertFalse(input.closed)
        self.assertFalse(output.closed)
        self.assertEqual('abcabc', output.getvalue())
    
    def test_simple_pipes_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) SimplePipes medium
        # does nothing.
        client_medium = medium.SmartSimplePipesClientMedium(None, None)
        client_medium.disconnect()

    def test_simple_pipes_client_can_always_read(self):
        # SmartSimplePipesClientMedium is never disconnected, so read_bytes
        # always tries to read from the underlying pipe.
        input = StringIO('abcdef')
        client_medium = medium.SmartSimplePipesClientMedium(input, None)
        self.assertEqual('abc', client_medium.read_bytes(3))
        client_medium.disconnect()
        self.assertEqual('def', client_medium.read_bytes(3))
        
    def test_simple_pipes_client_supports__flush(self):
        # invoking _flush on a SimplePipesClient should flush the output 
        # pipe. We test this by creating an output pipe that records
        # flush calls made to it.
        from StringIO import StringIO # get regular StringIO
        input = StringIO()
        output = StringIO()
        flush_calls = []
        def logging_flush(): flush_calls.append('flush')
        output.flush = logging_flush
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        # this call is here to ensure we only flush once, not on every
        # _accept_bytes call.
        client_medium._accept_bytes('abc')
        client_medium._flush()
        client_medium.disconnect()
        self.assertEqual(['flush'], flush_calls)

    def test_construct_smart_ssh_client_medium(self):
        # the SSH client medium takes:
        # host, port, username, password, vendor
        # Constructing one should just save these and do nothing.
        # we test this by creating a empty bound socket and constructing
        # a medium.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        unopened_port = sock.getsockname()[1]
        # having vendor be invalid means that if it tries to connect via the
        # vendor it will blow up.
        client_medium = medium.SmartSSHClientMedium('127.0.0.1', unopened_port,
            username=None, password=None, vendor="not a vendor")
        sock.close()

    def test_ssh_client_connects_on_first_use(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = StringIO()
        vendor = StringIOSSHVendor(StringIO(), output)
        client_medium = medium.SmartSSHClientMedium(
            'a hostname', 'a port', 'a username', 'a password', vendor)
        client_medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
        self.assertEqual([('connect_ssh', 'a username', 'a password',
            'a hostname', 'a port',
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes'])],
            vendor.calls)
    
    def test_ssh_client_changes_command_when_BZR_REMOTE_PATH_is_set(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = StringIO()
        vendor = StringIOSSHVendor(StringIO(), output)
        orig_bzr_remote_path = os.environ.get('BZR_REMOTE_PATH')
        def cleanup_environ():
            osutils.set_or_unset_env('BZR_REMOTE_PATH', orig_bzr_remote_path)
        self.addCleanup(cleanup_environ)
        os.environ['BZR_REMOTE_PATH'] = 'fugly'
        client_medium = medium.SmartSSHClientMedium('a hostname', 'a port', 'a username',
            'a password', vendor)
        client_medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
        self.assertEqual([('connect_ssh', 'a username', 'a password',
            'a hostname', 'a port',
            ['fugly', 'serve', '--inet', '--directory=/', '--allow-writes'])],
            vendor.calls)
    
    def test_ssh_client_disconnect_does_so(self):
        # calling disconnect should disconnect both the read_from and write_to
        # file-like object it from the ssh connection.
        input = StringIO()
        output = StringIO()
        vendor = StringIOSSHVendor(input, output)
        client_medium = medium.SmartSSHClientMedium('a hostname', vendor=vendor)
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        self.assertTrue(input.closed)
        self.assertTrue(output.closed)
        self.assertEqual([
            ('connect_ssh', None, None, 'a hostname', None,
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes']),
            ('close', ),
            ],
            vendor.calls)

    def test_ssh_client_disconnect_allows_reconnection(self):
        # calling disconnect on the client terminates the connection, but should
        # not prevent additional connections occuring.
        # we test this by initiating a second connection after doing a
        # disconnect.
        input = StringIO()
        output = StringIO()
        vendor = StringIOSSHVendor(input, output)
        client_medium = medium.SmartSSHClientMedium('a hostname', vendor=vendor)
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        # the disconnect has closed output, so we need a new output for the
        # new connection to write to.
        input2 = StringIO()
        output2 = StringIO()
        vendor.read_from = input2
        vendor.write_to = output2
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        self.assertTrue(input.closed)
        self.assertTrue(output.closed)
        self.assertTrue(input2.closed)
        self.assertTrue(output2.closed)
        self.assertEqual([
            ('connect_ssh', None, None, 'a hostname', None,
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes']),
            ('close', ),
            ('connect_ssh', None, None, 'a hostname', None,
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes']),
            ('close', ),
            ],
            vendor.calls)
    
    def test_ssh_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) SSH medium
        # does not fail.  It's ok to disconnect an unconnected medium.
        client_medium = medium.SmartSSHClientMedium(None)
        client_medium.disconnect()

    def test_ssh_client_raises_on_read_when_not_connected(self):
        # Doing a read on a new (and thus unconnected) SSH medium raises
        # MediumNotConnected.
        client_medium = medium.SmartSSHClientMedium(None)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes, 0)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes, 1)

    def test_ssh_client_supports__flush(self):
        # invoking _flush on a SSHClientMedium should flush the output 
        # pipe. We test this by creating an output pipe that records
        # flush calls made to it.
        from StringIO import StringIO # get regular StringIO
        input = StringIO()
        output = StringIO()
        flush_calls = []
        def logging_flush(): flush_calls.append('flush')
        output.flush = logging_flush
        vendor = StringIOSSHVendor(input, output)
        client_medium = medium.SmartSSHClientMedium('a hostname', vendor=vendor)
        # this call is here to ensure we only flush once, not on every
        # _accept_bytes call.
        client_medium._accept_bytes('abc')
        client_medium._flush()
        client_medium.disconnect()
        self.assertEqual(['flush'], flush_calls)
        
    def test_construct_smart_tcp_client_medium(self):
        # the TCP client medium takes a host and a port.  Constructing it won't
        # connect to anything.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        unopened_port = sock.getsockname()[1]
        client_medium = medium.SmartTCPClientMedium('127.0.0.1', unopened_port)
        sock.close()

    def test_tcp_client_connects_on_first_use(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        medium.accept_bytes('abc')
        t.join()
        sock.close()
        self.assertEqual(['abc'], bytes)
    
    def test_tcp_client_disconnect_does_so(self):
        # calling disconnect on the client terminates the connection.
        # we test this by forcing a short read during a socket.MSG_WAITALL
        # call: write 2 bytes, try to read 3, and then the client disconnects.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        medium.accept_bytes('ab')
        medium.disconnect()
        t.join()
        sock.close()
        self.assertEqual(['ab'], bytes)
        # now disconnect again: this should not do anything, if disconnection
        # really did disconnect.
        medium.disconnect()
    
    def test_tcp_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) TCP medium
        # does not fail.  It's ok to disconnect an unconnected medium.
        client_medium = medium.SmartTCPClientMedium(None, None)
        client_medium.disconnect()

    def test_tcp_client_raises_on_read_when_not_connected(self):
        # Doing a read on a new (and thus unconnected) TCP medium raises
        # MediumNotConnected.
        client_medium = medium.SmartTCPClientMedium(None, None)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes, 0)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes, 1)

    def test_tcp_client_supports__flush(self):
        # invoking _flush on a TCPClientMedium should do something useful.
        # RBC 20060922 not sure how to test/tell in this case.
        sock, medium = self.make_loopsocket_and_medium()
        bytes = []
        t = self.receive_bytes_on_server(sock, bytes)
        # try with nothing buffered
        medium._flush()
        medium._accept_bytes('ab')
        # and with something sent.
        medium._flush()
        medium.disconnect()
        t.join()
        sock.close()
        self.assertEqual(['ab'], bytes)
        # now disconnect again : this should not do anything, if disconnection
        # really did disconnect.
        medium.disconnect()


class TestSmartClientStreamMediumRequest(tests.TestCase):
    """Tests the for SmartClientStreamMediumRequest.
    
    SmartClientStreamMediumRequest is a helper for the three stream based 
    mediums: TCP, SSH, SimplePipes, so we only test it once, and then test that
    those three mediums implement the interface it expects.
    """

    def test_accept_bytes_after_finished_writing_errors(self):
        # calling accept_bytes after calling finished_writing raises 
        # WritingCompleted to prevent bad assumptions on stream environments
        # breaking the needs of message-based environments.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        self.assertRaises(errors.WritingCompleted, request.accept_bytes, None)

    def test_accept_bytes(self):
        # accept bytes should invoke _accept_bytes on the stream medium.
        # we test this by using the SimplePipes medium - the most trivial one
        # and checking that the pipes get the data.
        input = StringIO()
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.accept_bytes('123')
        request.finished_writing()
        request.finished_reading()
        self.assertEqual('', input.getvalue())
        self.assertEqual('123', output.getvalue())

    def test_construct_sets_stream_request(self):
        # constructing a SmartClientStreamMediumRequest on a StreamMedium sets
        # the current request to the new SmartClientStreamMediumRequest
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertIs(client_medium._current_request, request)

    def test_construct_while_another_request_active_throws(self):
        # constructing a SmartClientStreamMediumRequest on a StreamMedium with
        # a non-None _current_request raises TooManyConcurrentRequests.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        client_medium._current_request = "a"
        self.assertRaises(errors.TooManyConcurrentRequests,
            medium.SmartClientStreamMediumRequest, client_medium)

    def test_finished_read_clears_current_request(self):
        # calling finished_reading clears the current request from the requests
        # medium
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        request.finished_reading()
        self.assertEqual(None, client_medium._current_request)

    def test_finished_read_before_finished_write_errors(self):
        # calling finished_reading before calling finished_writing triggers a
        # WritingNotComplete error.
        client_medium = medium.SmartSimplePipesClientMedium(None, None)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertRaises(errors.WritingNotComplete, request.finished_reading)
        
    def test_read_bytes(self):
        # read bytes should invoke _read_bytes on the stream medium.
        # we test this by using the SimplePipes medium - the most trivial one
        # and checking that the data is supplied. Its possible that a 
        # faulty implementation could poke at the pipe variables them selves,
        # but we trust that this will be caught as it will break the integration
        # smoke tests.
        input = StringIO('321')
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        self.assertEqual('321', request.read_bytes(3))
        request.finished_reading()
        self.assertEqual('', input.read())
        self.assertEqual('', output.getvalue())

    def test_read_bytes_before_finished_write_errors(self):
        # calling read_bytes before calling finished_writing triggers a
        # WritingNotComplete error because the Smart protocol is designed to be
        # compatible with strict message based protocols like HTTP where the
        # request cannot be submitted until the writing has completed.
        client_medium = medium.SmartSimplePipesClientMedium(None, None)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertRaises(errors.WritingNotComplete, request.read_bytes, None)

    def test_read_bytes_after_finished_reading_errors(self):
        # calling read_bytes after calling finished_reading raises 
        # ReadingCompleted to prevent bad assumptions on stream environments
        # breaking the needs of message-based environments.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        request.finished_reading()
        self.assertRaises(errors.ReadingCompleted, request.read_bytes, None)


class RemoteTransportTests(TestCaseWithSmartMedium):

    def test_plausible_url(self):
        self.assert_(self.get_url().startswith('bzr://'))

    def test_probe_transport(self):
        t = self.get_transport()
        self.assertIsInstance(t, remote.RemoteTransport)

    def test_get_medium_from_transport(self):
        """Remote transport has a medium always, which it can return."""
        t = self.get_transport()
        client_medium = t.get_smart_medium()
        self.assertIsInstance(client_medium, medium.SmartClientMedium)


class ErrorRaisingProtocol(object):

    def __init__(self, exception):
        self.exception = exception

    def next_read_size(self):
        raise self.exception


class SampleRequest(object):
    
    def __init__(self, expected_bytes):
        self.accepted_bytes = ''
        self._finished_reading = False
        self.expected_bytes = expected_bytes
        self.excess_buffer = ''

    def accept_bytes(self, bytes):
        self.accepted_bytes += bytes
        if self.accepted_bytes.startswith(self.expected_bytes):
            self._finished_reading = True
            self.excess_buffer = self.accepted_bytes[len(self.expected_bytes):]

    def next_read_size(self):
        if self._finished_reading:
            return 0
        else:
            return 1


class TestSmartServerStreamMedium(tests.TestCase):

    def setUp(self):
        super(TestSmartServerStreamMedium, self).setUp()
        self._captureVar('BZR_NO_SMART_VFS', None)

    def portable_socket_pair(self):
        """Return a pair of TCP sockets connected to each other.
        
        Unlike socket.socketpair, this should work on Windows.
        """
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen_sock.bind(('127.0.0.1', 0))
        listen_sock.listen(1)
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(listen_sock.getsockname())
        server_sock, addr = listen_sock.accept()
        listen_sock.close()
        return server_sock, client_sock
    
    def test_smart_query_version(self):
        """Feed a canned query version to a server"""
        # wire-to-wire, using the whole stack
        to_server = StringIO('hello\n')
        from_server = StringIO()
        transport = local.LocalTransport(urlutils.local_path_to_url('/'))
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, transport)
        smart_protocol = protocol.SmartServerRequestProtocolOne(transport,
                from_server.write)
        server._serve_one_request(smart_protocol)
        self.assertEqual('ok\0011\n',
                         from_server.getvalue())

    def test_response_to_canned_get(self):
        transport = memory.MemoryTransport('memory:///')
        transport.put_bytes('testfile', 'contents\nof\nfile\n')
        to_server = StringIO('get\001./testfile\n')
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, transport)
        smart_protocol = protocol.SmartServerRequestProtocolOne(transport,
                from_server.write)
        server._serve_one_request(smart_protocol)
        self.assertEqual('ok\n'
                         '17\n'
                         'contents\nof\nfile\n'
                         'done\n',
                         from_server.getvalue())

    def test_response_to_canned_get_of_utf8(self):
        # wire-to-wire, using the whole stack, with a UTF-8 filename.
        transport = memory.MemoryTransport('memory:///')
        utf8_filename = u'testfile\N{INTERROBANG}'.encode('utf-8')
        transport.put_bytes(utf8_filename, 'contents\nof\nfile\n')
        to_server = StringIO('get\001' + utf8_filename + '\n')
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, transport)
        smart_protocol = protocol.SmartServerRequestProtocolOne(transport,
                from_server.write)
        server._serve_one_request(smart_protocol)
        self.assertEqual('ok\n'
                         '17\n'
                         'contents\nof\nfile\n'
                         'done\n',
                         from_server.getvalue())

    def test_pipe_like_stream_with_bulk_data(self):
        sample_request_bytes = 'command\n9\nbulk datadone\n'
        to_server = StringIO(sample_request_bytes)
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        sample_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(sample_protocol)
        self.assertEqual('', from_server.getvalue())
        self.assertEqual(sample_request_bytes, sample_protocol.accepted_bytes)
        self.assertFalse(server.finished)

    def test_socket_stream_with_bulk_data(self):
        sample_request_bytes = 'command\n9\nbulk datadone\n'
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        sample_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        client_sock.sendall(sample_request_bytes)
        server._serve_one_request(sample_protocol)
        server_sock.close()
        self.assertEqual('', client_sock.recv(1))
        self.assertEqual(sample_request_bytes, sample_protocol.accepted_bytes)
        self.assertFalse(server.finished)

    def test_pipe_like_stream_shutdown_detection(self):
        to_server = StringIO('')
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(to_server, from_server, None)
        server._serve_one_request(SampleRequest('x'))
        self.assertTrue(server.finished)
        
    def test_socket_stream_shutdown_detection(self):
        server_sock, client_sock = self.portable_socket_pair()
        client_sock.close()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        server._serve_one_request(SampleRequest('x'))
        self.assertTrue(server.finished)
        
    def test_pipe_like_stream_with_two_requests(self):
        # If two requests are read in one go, then two calls to
        # _serve_one_request should still process both of them as if they had
        # been received seperately.
        sample_request_bytes = 'command\n'
        to_server = StringIO(sample_request_bytes * 2)
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        first_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(first_protocol)
        self.assertEqual(0, first_protocol.next_read_size())
        self.assertEqual('', from_server.getvalue())
        self.assertFalse(server.finished)
        # Make a new protocol, call _serve_one_request with it to collect the
        # second request.
        second_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        server._serve_one_request(second_protocol)
        self.assertEqual('', from_server.getvalue())
        self.assertEqual(sample_request_bytes, second_protocol.accepted_bytes)
        self.assertFalse(server.finished)
        
    def test_socket_stream_with_two_requests(self):
        # If two requests are read in one go, then two calls to
        # _serve_one_request should still process both of them as if they had
        # been received seperately.
        sample_request_bytes = 'command\n'
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        first_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        # Put two whole requests on the wire.
        client_sock.sendall(sample_request_bytes * 2)
        server._serve_one_request(first_protocol)
        self.assertEqual(0, first_protocol.next_read_size())
        self.assertFalse(server.finished)
        # Make a new protocol, call _serve_one_request with it to collect the
        # second request.
        second_protocol = SampleRequest(expected_bytes=sample_request_bytes)
        stream_still_open = server._serve_one_request(second_protocol)
        self.assertEqual(sample_request_bytes, second_protocol.accepted_bytes)
        self.assertFalse(server.finished)
        server_sock.close()
        self.assertEqual('', client_sock.recv(1))

    def test_pipe_like_stream_error_handling(self):
        # Use plain python StringIO so we can monkey-patch the close method to
        # not discard the contents.
        from StringIO import StringIO
        to_server = StringIO('')
        from_server = StringIO()
        self.closed = False
        def close():
            self.closed = True
        from_server.close = close
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        fake_protocol = ErrorRaisingProtocol(Exception('boom'))
        server._serve_one_request(fake_protocol)
        self.assertEqual('', from_server.getvalue())
        self.assertTrue(self.closed)
        self.assertTrue(server.finished)
        
    def test_socket_stream_error_handling(self):
        # Use plain python StringIO so we can monkey-patch the close method to
        # not discard the contents.
        from StringIO import StringIO
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        fake_protocol = ErrorRaisingProtocol(Exception('boom'))
        server._serve_one_request(fake_protocol)
        # recv should not block, because the other end of the socket has been
        # closed.
        self.assertEqual('', client_sock.recv(1))
        self.assertTrue(server.finished)
        
    def test_pipe_like_stream_keyboard_interrupt_handling(self):
        # Use plain python StringIO so we can monkey-patch the close method to
        # not discard the contents.
        to_server = StringIO('')
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        fake_protocol = ErrorRaisingProtocol(KeyboardInterrupt('boom'))
        self.assertRaises(
            KeyboardInterrupt, server._serve_one_request, fake_protocol)
        self.assertEqual('', from_server.getvalue())

    def test_socket_stream_keyboard_interrupt_handling(self):
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        fake_protocol = ErrorRaisingProtocol(KeyboardInterrupt('boom'))
        self.assertRaises(
            KeyboardInterrupt, server._serve_one_request, fake_protocol)
        server_sock.close()
        self.assertEqual('', client_sock.recv(1))
        

class TestSmartTCPServer(tests.TestCase):

    def test_get_error_unexpected(self):
        """Error reported by server with no specific representation"""
        self._captureVar('BZR_NO_SMART_VFS', None)
        class FlakyTransport(object):
            base = 'a_url'
            def get_bytes(self, path):
                raise Exception("some random exception from inside server")
        smart_server = server.SmartTCPServer(backing_transport=FlakyTransport())
        smart_server.start_background_thread()
        try:
            transport = remote.SmartTCPTransport(smart_server.get_url())
            try:
                transport.get('something')
            except errors.TransportError, e:
                self.assertContainsRe(str(e), 'some random exception')
            else:
                self.fail("get did not raise expected error")
        finally:
            smart_server.stop_background_thread()


class SmartTCPTests(tests.TestCase):
    """Tests for connection/end to end behaviour using the TCP server.

    All of these tests are run with a server running on another thread serving
    a MemoryTransport, and a connection to it already open.

    the server is obtained by calling self.setUpServer(readonly=False).
    """

    def setUpServer(self, readonly=False):
        """Setup the server.

        :param readonly: Create a readonly server.
        """
        self.backing_transport = memory.MemoryTransport()
        if readonly:
            self.real_backing_transport = self.backing_transport
            self.backing_transport = get_transport("readonly+" + self.backing_transport.abspath('.'))
        self.server = server.SmartTCPServer(self.backing_transport)
        self.server.start_background_thread()
        self.transport = remote.SmartTCPTransport(self.server.get_url())
        self.addCleanup(self.tearDownServer)

    def tearDownServer(self):
        if getattr(self, 'transport', None):
            self.transport.disconnect()
            del self.transport
        if getattr(self, 'server', None):
            self.server.stop_background_thread()
            del self.server


class TestServerSocketUsage(SmartTCPTests):

    def test_server_setup_teardown(self):
        """It should be safe to teardown the server with no requests."""
        self.setUpServer()
        server = self.server
        transport = remote.SmartTCPTransport(self.server.get_url())
        self.tearDownServer()
        self.assertRaises(errors.ConnectionError, transport.has, '.')

    def test_server_closes_listening_sock_on_shutdown_after_request(self):
        """The server should close its listening socket when it's stopped."""
        self.setUpServer()
        server = self.server
        self.transport.has('.')
        self.tearDownServer()
        # if the listening socket has closed, we should get a BADFD error
        # when connecting, rather than a hang.
        transport = remote.SmartTCPTransport(server.get_url())
        self.assertRaises(errors.ConnectionError, transport.has, '.')


class WritableEndToEndTests(SmartTCPTests):
    """Client to server tests that require a writable transport."""

    def setUp(self):
        super(WritableEndToEndTests, self).setUp()
        self.setUpServer()

    def test_start_tcp_server(self):
        url = self.server.get_url()
        self.assertContainsRe(url, r'^bzr://127\.0\.0\.1:[0-9]{2,}/')

    def test_smart_transport_has(self):
        """Checking for file existence over smart."""
        self._captureVar('BZR_NO_SMART_VFS', None)
        self.backing_transport.put_bytes("foo", "contents of foo\n")
        self.assertTrue(self.transport.has("foo"))
        self.assertFalse(self.transport.has("non-foo"))

    def test_smart_transport_get(self):
        """Read back a file over smart."""
        self._captureVar('BZR_NO_SMART_VFS', None)
        self.backing_transport.put_bytes("foo", "contents\nof\nfoo\n")
        fp = self.transport.get("foo")
        self.assertEqual('contents\nof\nfoo\n', fp.read())

    def test_get_error_enoent(self):
        """Error reported from server getting nonexistent file."""
        # The path in a raised NoSuchFile exception should be the precise path
        # asked for by the client. This gives meaningful and unsurprising errors
        # for users.
        self._captureVar('BZR_NO_SMART_VFS', None)
        try:
            self.transport.get('not%20a%20file')
        except errors.NoSuchFile, e:
            self.assertEqual('not%20a%20file', e.path)
        else:
            self.fail("get did not raise expected error")

    def test_simple_clone_conn(self):
        """Test that cloning reuses the same connection."""
        # we create a real connection not a loopback one, but it will use the
        # same server and pipes
        conn2 = self.transport.clone('.')
        self.assertIs(self.transport._medium, conn2._medium)

    def test__remote_path(self):
        self.assertEquals('/foo/bar',
                          self.transport._remote_path('foo/bar'))

    def test_clone_changes_base(self):
        """Cloning transport produces one with a new base location"""
        conn2 = self.transport.clone('subdir')
        self.assertEquals(self.transport.base + 'subdir/',
                          conn2.base)

    def test_open_dir(self):
        """Test changing directory"""
        self._captureVar('BZR_NO_SMART_VFS', None)
        transport = self.transport
        self.backing_transport.mkdir('toffee')
        self.backing_transport.mkdir('toffee/apple')
        self.assertEquals('/toffee', transport._remote_path('toffee'))
        toffee_trans = transport.clone('toffee')
        # Check that each transport has only the contents of its directory
        # directly visible. If state was being held in the wrong object, it's
        # conceivable that cloning a transport would alter the state of the
        # cloned-from transport.
        self.assertTrue(transport.has('toffee'))
        self.assertFalse(toffee_trans.has('toffee'))
        self.assertFalse(transport.has('apple'))
        self.assertTrue(toffee_trans.has('apple'))

    def test_open_bzrdir(self):
        """Open an existing bzrdir over smart transport"""
        transport = self.transport
        t = self.backing_transport
        bzrdir.BzrDirFormat.get_default_format().initialize_on_transport(t)
        result_dir = bzrdir.BzrDir.open_containing_from_transport(transport)


class ReadOnlyEndToEndTests(SmartTCPTests):
    """Tests from the client to the server using a readonly backing transport."""

    def test_mkdir_error_readonly(self):
        """TransportNotPossible should be preserved from the backing transport."""
        self._captureVar('BZR_NO_SMART_VFS', None)
        self.setUpServer(readonly=True)
        self.assertRaises(errors.TransportNotPossible, self.transport.mkdir,
            'foo')


class TestServerHooks(SmartTCPTests):

    def capture_server_call(self, backing_url, public_url):
        """Record a server_started|stopped hook firing."""
        self.hook_calls.append((backing_url, public_url))

    def test_server_started_hook(self):
        """The server_started hook fires when the server is started."""
        self.hook_calls = []
        server.SmartTCPServer.hooks.install_hook('server_started',
            self.capture_server_call)
        self.setUpServer()
        # at this point, the server will be starting a thread up.
        # there is no indicator at the moment, so bodge it by doing a request.
        self.transport.has('.')
        self.assertEqual([(self.backing_transport.base, self.transport.base)],
            self.hook_calls)

    def test_server_stopped_hook_simple(self):
        """The server_stopped hook fires when the server is stopped."""
        self.hook_calls = []
        server.SmartTCPServer.hooks.install_hook('server_stopped',
            self.capture_server_call)
        self.setUpServer()
        result = [(self.backing_transport.base, self.transport.base)]
        # check the stopping message isn't emitted up front.
        self.assertEqual([], self.hook_calls)
        # nor after a single message
        self.transport.has('.')
        self.assertEqual([], self.hook_calls)
        # clean up the server
        self.tearDownServer()
        # now it should have fired.
        self.assertEqual(result, self.hook_calls)

# TODO: test that when the server suffers an exception that it calls the
# server-stopped hook.


class SmartServerCommandTests(tests.TestCaseWithTransport):
    """Tests that call directly into the command objects, bypassing the network
    and the request dispatching.
    """
        
    def test_hello(self):
        cmd = request.HelloRequest(None)
        response = cmd.execute()
        self.assertEqual(('ok', '1'), response.args)
        self.assertEqual(None, response.body)
        
    def test_get_bundle(self):
        from bzrlib.bundle import serializer
        wt = self.make_branch_and_tree('.')
        self.build_tree_contents([('hello', 'hello world')])
        wt.add('hello')
        rev_id = wt.commit('add hello')
        
        cmd = request.GetBundleRequest(self.get_transport())
        response = cmd.execute('.', rev_id)
        bundle = serializer.read_bundle(StringIO(response.body))
        self.assertEqual((), response.args)


class SmartServerRequestHandlerTests(tests.TestCaseWithTransport):
    """Test that call directly into the handler logic, bypassing the network."""

    def setUp(self):
        super(SmartServerRequestHandlerTests, self).setUp()
        self._captureVar('BZR_NO_SMART_VFS', None)

    def build_handler(self, transport):
        """Returns a handler for the commands in protocol version one."""
        return smart.SmartServerRequestHandler(transport, request.request_handlers)

    def test_construct_request_handler(self):
        """Constructing a request handler should be easy and set defaults."""
        handler = smart.SmartServerRequestHandler(None, None)
        self.assertFalse(handler.finished_reading)

    def test_hello(self):
        handler = self.build_handler(None)
        handler.dispatch_command('hello', ())
        self.assertEqual(('ok', '1'), handler.response.args)
        self.assertEqual(None, handler.response.body)
        
    def test_disable_vfs_handler_classes_via_environment(self):
        # VFS handler classes will raise an error from "execute" if
        # BZR_NO_SMART_VFS is set.
        handler = vfs.HasRequest(None)
        # set environment variable after construction to make sure it's
        # examined.
        # Note that we can safely clobber BZR_NO_SMART_VFS here, because setUp
        # has called _captureVar, so it will be restored to the right state
        # afterwards.
        os.environ['BZR_NO_SMART_VFS'] = ''
        self.assertRaises(errors.DisabledMethod, handler.execute)

    def test_readonly_exception_becomes_transport_not_possible(self):
        """The response for a read-only error is ('ReadOnlyError')."""
        handler = self.build_handler(self.get_readonly_transport())
        # send a mkdir for foo, with no explicit mode - should fail.
        handler.dispatch_command('mkdir', ('foo', ''))
        # and the failure should be an explicit ReadOnlyError
        self.assertEqual(("ReadOnlyError", ), handler.response.args)
        # XXX: TODO: test that other TransportNotPossible errors are
        # presented as TransportNotPossible - not possible to do that
        # until I figure out how to trigger that relatively cleanly via
        # the api. RBC 20060918

    def test_hello_has_finished_body_on_dispatch(self):
        """The 'hello' command should set finished_reading."""
        handler = self.build_handler(None)
        handler.dispatch_command('hello', ())
        self.assertTrue(handler.finished_reading)
        self.assertNotEqual(None, handler.response)

    def test_put_bytes_non_atomic(self):
        """'put_...' should set finished_reading after reading the bytes."""
        handler = self.build_handler(self.get_transport())
        handler.dispatch_command('put_non_atomic', ('a-file', '', 'F', ''))
        self.assertFalse(handler.finished_reading)
        handler.accept_body('1234')
        self.assertFalse(handler.finished_reading)
        handler.accept_body('5678')
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(('ok', ), handler.response.args)
        self.assertEqual(None, handler.response.body)
        
    def test_readv_accept_body(self):
        """'readv' should set finished_reading after reading offsets."""
        self.build_tree(['a-file'])
        handler = self.build_handler(self.get_readonly_transport())
        handler.dispatch_command('readv', ('a-file', ))
        self.assertFalse(handler.finished_reading)
        handler.accept_body('2,')
        self.assertFalse(handler.finished_reading)
        handler.accept_body('3')
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(('readv', ), handler.response.args)
        # co - nte - nt of a-file is the file contents we are extracting from.
        self.assertEqual('nte', handler.response.body)

    def test_readv_short_read_response_contents(self):
        """'readv' when a short read occurs sets the response appropriately."""
        self.build_tree(['a-file'])
        handler = self.build_handler(self.get_readonly_transport())
        handler.dispatch_command('readv', ('a-file', ))
        # read beyond the end of the file.
        handler.accept_body('100,1')
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(('ShortReadvError', 'a-file', '100', '1', '0'),
            handler.response.args)
        self.assertEqual(None, handler.response.body)


class RemoteTransportRegistration(tests.TestCase):

    def test_registration(self):
        t = get_transport('bzr+ssh://example.com/path')
        self.assertIsInstance(t, remote.SmartSSHTransport)
        self.assertEqual('example.com', t._host)


class TestRemoteTransport(tests.TestCase):
        
    def test_use_connection_factory(self):
        # We want to be able to pass a client as a parameter to RemoteTransport.
        input = StringIO("ok\n3\nbardone\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        transport = remote.RemoteTransport(
            'bzr://localhost/', medium=client_medium)

        # We want to make sure the client is used when the first remote
        # method is called.  No data should have been sent, or read.
        self.assertEqual(0, input.tell())
        self.assertEqual('', output.getvalue())

        # Now call a method that should result in a single request : as the
        # transport makes its own protocol instances, we check on the wire.
        # XXX: TODO: give the transport a protocol factory, which can make
        # an instrumented protocol for us.
        self.assertEqual('bar', transport.get_bytes('foo'))
        # only the needed data should have been sent/received.
        self.assertEqual(13, input.tell())
        self.assertEqual('get\x01/foo\n', output.getvalue())

    def test__translate_error_readonly(self):
        """Sending a ReadOnlyError to _translate_error raises TransportNotPossible."""
        client_medium = medium.SmartClientMedium()
        transport = remote.RemoteTransport(
            'bzr://localhost/', medium=client_medium)
        self.assertRaises(errors.TransportNotPossible,
            transport._translate_error, ("ReadOnlyError", ))


class InstrumentedServerProtocol(medium.SmartServerStreamMedium):
    """A smart server which is backed by memory and saves its write requests."""

    def __init__(self, write_output_list):
        medium.SmartServerStreamMedium.__init__(self, memory.MemoryTransport())
        self._write_output_list = write_output_list


class TestSmartProtocol(tests.TestCase):
    """Tests for the smart protocol.

    Each test case gets a smart_server and smart_client created during setUp().

    It is planned that the client can be called with self.call_client() giving
    it an expected server response, which will be fed into it when it tries to
    read. Likewise, self.call_server will call a servers method with a canned
    serialised client request. Output done by the client or server for these
    calls will be captured to self.to_server and self.to_client. Each element
    in the list is a write call from the client or server respectively.
    """

    def setUp(self):
        super(TestSmartProtocol, self).setUp()
        # XXX: self.server_to_client doesn't seem to be used.  If so,
        # InstrumentedServerProtocol is redundant too.
        self.server_to_client = []
        self.to_server = StringIO()
        self.to_client = StringIO()
        self.client_medium = medium.SmartSimplePipesClientMedium(self.to_client,
            self.to_server)
        self.client_protocol = protocol.SmartClientRequestProtocolOne(
            self.client_medium)
        self.smart_server = InstrumentedServerProtocol(self.server_to_client)
        self.smart_server_request = request.SmartServerRequestHandler(
            None, request.request_handlers)

    def assertOffsetSerialisation(self, expected_offsets, expected_serialised,
        client):
        """Check that smart (de)serialises offsets as expected.
        
        We check both serialisation and deserialisation at the same time
        to ensure that the round tripping cannot skew: both directions should
        be as expected.
        
        :param expected_offsets: a readv offset list.
        :param expected_seralised: an expected serial form of the offsets.
        """
        # XXX: '_deserialise_offsets' should be a method of the
        # SmartServerRequestProtocol in future.
        readv_cmd = vfs.ReadvRequest(None)
        offsets = readv_cmd._deserialise_offsets(expected_serialised)
        self.assertEqual(expected_offsets, offsets)
        serialised = client._serialise_offsets(offsets)
        self.assertEqual(expected_serialised, serialised)

    def build_protocol_waiting_for_body(self):
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(None,
                out_stream.write)
        smart_protocol.has_dispatched = True
        smart_protocol.request = self.smart_server_request
        class FakeCommand(object):
            def do_body(cmd, body_bytes):
                self.end_received = True
                self.assertEqual('abcdefg', body_bytes)
                return request.SmartServerResponse(('ok', ))
        smart_protocol.request._command = FakeCommand()
        # Call accept_bytes to make sure that internal state like _body_decoder
        # is initialised.  This test should probably be given a clearer
        # interface to work with that will not cause this inconsistency.
        #   -- Andrew Bennetts, 2006-09-28
        smart_protocol.accept_bytes('')
        return smart_protocol

    def test_construct_version_one_server_protocol(self):
        smart_protocol = protocol.SmartServerRequestProtocolOne(None, None)
        self.assertEqual('', smart_protocol.excess_buffer)
        self.assertEqual('', smart_protocol.in_buffer)
        self.assertFalse(smart_protocol.has_dispatched)
        self.assertEqual(1, smart_protocol.next_read_size())

    def test_construct_version_one_client_protocol(self):
        # we can construct a client protocol from a client medium request
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(None, output)
        request = client_medium.get_request()
        client_protocol = protocol.SmartClientRequestProtocolOne(request)

    def test_server_offset_serialisation(self):
        """The Smart protocol serialises offsets as a comma and \n string.

        We check a number of boundary cases are as expected: empty, one offset,
        one with the order of reads not increasing (an out of order read), and
        one that should coalesce.
        """
        self.assertOffsetSerialisation([], '', self.client_protocol)
        self.assertOffsetSerialisation([(1,2)], '1,2', self.client_protocol)
        self.assertOffsetSerialisation([(10,40), (0,5)], '10,40\n0,5',
            self.client_protocol)
        self.assertOffsetSerialisation([(1,2), (3,4), (100, 200)],
            '1,2\n3,4\n100,200', self.client_protocol)

    def test_accept_bytes_of_bad_request_to_protocol(self):
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, out_stream.write)
        smart_protocol.accept_bytes('abc')
        self.assertEqual('abc', smart_protocol.in_buffer)
        smart_protocol.accept_bytes('\n')
        self.assertEqual(
            "error\x01Generic bzr smart protocol error: bad request 'abc'\n",
            out_stream.getvalue())
        self.assertTrue(smart_protocol.has_dispatched)
        self.assertEqual(0, smart_protocol.next_read_size())

    def test_accept_body_bytes_to_protocol(self):
        protocol = self.build_protocol_waiting_for_body()
        self.assertEqual(6, protocol.next_read_size())
        protocol.accept_bytes('7\nabc')
        self.assertEqual(9, protocol.next_read_size())
        protocol.accept_bytes('defgd')
        protocol.accept_bytes('one\n')
        self.assertEqual(0, protocol.next_read_size())
        self.assertTrue(self.end_received)

    def test_accept_request_and_body_all_at_once(self):
        self._captureVar('BZR_NO_SMART_VFS', None)
        mem_transport = memory.MemoryTransport()
        mem_transport.put_bytes('foo', 'abcdefghij')
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(mem_transport,
                out_stream.write)
        smart_protocol.accept_bytes('readv\x01foo\n3\n3,3done\n')
        self.assertEqual(0, smart_protocol.next_read_size())
        self.assertEqual('readv\n3\ndefdone\n', out_stream.getvalue())
        self.assertEqual('', smart_protocol.excess_buffer)
        self.assertEqual('', smart_protocol.in_buffer)

    def test_accept_excess_bytes_are_preserved(self):
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, out_stream.write)
        smart_protocol.accept_bytes('hello\nhello\n')
        self.assertEqual("ok\x011\n", out_stream.getvalue())
        self.assertEqual("hello\n", smart_protocol.excess_buffer)
        self.assertEqual("", smart_protocol.in_buffer)

    def test_accept_excess_bytes_after_body(self):
        protocol = self.build_protocol_waiting_for_body()
        protocol.accept_bytes('7\nabcdefgdone\nX')
        self.assertTrue(self.end_received)
        self.assertEqual("X", protocol.excess_buffer)
        self.assertEqual("", protocol.in_buffer)
        protocol.accept_bytes('Y')
        self.assertEqual("XY", protocol.excess_buffer)
        self.assertEqual("", protocol.in_buffer)

    def test_accept_excess_bytes_after_dispatch(self):
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, out_stream.write)
        smart_protocol.accept_bytes('hello\n')
        self.assertEqual("ok\x011\n", out_stream.getvalue())
        smart_protocol.accept_bytes('hel')
        self.assertEqual("hel", smart_protocol.excess_buffer)
        smart_protocol.accept_bytes('lo\n')
        self.assertEqual("hello\n", smart_protocol.excess_buffer)
        self.assertEqual("", smart_protocol.in_buffer)

    def test__send_response_sets_finished_reading(self):
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, lambda x: None)
        self.assertEqual(1, smart_protocol.next_read_size())
        smart_protocol._send_response(('x',))
        self.assertEqual(0, smart_protocol.next_read_size())

    def test_query_version(self):
        """query_version on a SmartClientProtocolOne should return a number.
        
        The protocol provides the query_version because the domain level clients
        may all need to be able to probe for capabilities.
        """
        # What we really want to test here is that SmartClientProtocolOne calls
        # accept_bytes(tuple_based_encoding_of_hello) and reads and parses the
        # response of tuple-encoded (ok, 1).  Also, seperately we should test
        # the error if the response is a non-understood version.
        input = StringIO('ok\x011\n')
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        self.assertEqual(1, smart_protocol.query_version())

    def assertServerToClientEncoding(self, expected_bytes, expected_tuple,
            input_tuples):
        """Assert that each input_tuple serialises as expected_bytes, and the
        bytes deserialise as expected_tuple.
        """
        # check the encoding of the server for all input_tuples matches
        # expected bytes
        for input_tuple in input_tuples:
            server_output = StringIO()
            server_protocol = protocol.SmartServerRequestProtocolOne(
                None, server_output.write)
            server_protocol._send_response(input_tuple)
            self.assertEqual(expected_bytes, server_output.getvalue())
        # check the decoding of the client smart_protocol from expected_bytes:
        input = StringIO(expected_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call('foo')
        self.assertEqual(expected_tuple, smart_protocol.read_response_tuple())

    def test_client_call_empty_response(self):
        # protocol.call() can get back an empty tuple as a response. This occurs
        # when the parsed line is an empty line, and results in a tuple with
        # one element - an empty string.
        self.assertServerToClientEncoding('\n', ('', ), [(), ('', )])

    def test_client_call_three_element_response(self):
        # protocol.call() can get back tuples of other lengths. A three element
        # tuple should be unpacked as three strings.
        self.assertServerToClientEncoding('a\x01b\x0134\n', ('a', 'b', '34'),
            [('a', 'b', '34')])

    def test_client_call_with_body_bytes_uploads(self):
        # protocol.call_with_body_bytes should length-prefix the bytes onto the
        # wire.
        expected_bytes = "foo\n7\nabcdefgdone\n"
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call_with_body_bytes(('foo', ), "abcdefg")
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_call_with_body_readv_array(self):
        # protocol.call_with_upload should encode the readv array and then
        # length-prefix the bytes onto the wire.
        expected_bytes = "foo\n7\n1,2\n5,6done\n"
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call_with_body_readv_array(('foo', ), [(1,2),(5,6)])
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_read_body_bytes_all(self):
        # read_body_bytes should decode the body bytes from the wire into
        # a response.
        expected_bytes = "1234567"
        server_bytes = "ok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes, smart_protocol.read_body_bytes())

    def test_client_read_body_bytes_incremental(self):
        # test reading a few bytes at a time from the body
        # XXX: possibly we should test dribbling the bytes into the stringio
        # to make the state machine work harder: however, as we use the
        # LengthPrefixedBodyDecoder that is already well tested - we can skip
        # that.
        expected_bytes = "1234567"
        server_bytes = "ok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes[0:2], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[2:4], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[4:6], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[6], smart_protocol.read_body_bytes())

    def test_client_cancel_read_body_does_not_eat_body_bytes(self):
        # cancelling the expected body needs to finish the request, but not
        # read any more bytes.
        expected_bytes = "1234567"
        server_bytes = "ok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        smart_protocol.cancel_read_body()
        self.assertEqual(3, input.tell())
        self.assertRaises(
            errors.ReadingCompleted, smart_protocol.read_body_bytes)


class TestSmartClientUnicode(tests.TestCase):
    """SmartClient tests for unicode arguments.

    Unicode arguments to call_with_body_bytes are not correct (remote method
    names, arguments, and bodies must all be expressed as byte strings), but
    SmartClient should gracefully reject them, rather than getting into a broken
    state that prevents future correct calls from working.  That is, it should
    be possible to issue more requests on the medium afterwards, rather than
    allowing one bad call to call_with_body_bytes to cause later calls to
    mysteriously fail with TooManyConcurrentRequests.
    """

    def assertCallDoesNotBreakMedium(self, method, args, body):
        """Call a medium with the given method, args and body, then assert that
        the medium is left in a sane state, i.e. is capable of allowing further
        requests.
        """
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(input, output)
        smart_client = client.SmartClient(client_medium)
        self.assertRaises(TypeError,
            smart_client.call_with_body_bytes, method, args, body)
        self.assertEqual("", output.getvalue())
        self.assertEqual(None, client_medium._current_request)

    def test_call_with_body_bytes_unicode_method(self):
        self.assertCallDoesNotBreakMedium(u'method', ('args',), 'body')

    def test_call_with_body_bytes_unicode_args(self):
        self.assertCallDoesNotBreakMedium('method', (u'args',), 'body')

    def test_call_with_body_bytes_unicode_body(self):
        self.assertCallDoesNotBreakMedium('method', ('args',), u'body')


class LengthPrefixedBodyDecoder(tests.TestCase):

    # XXX: TODO: make accept_reading_trailer invoke translate_response or 
    # something similar to the ProtocolBase method.

    def test_construct(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)

    def test_accept_bytes(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        decoder.accept_bytes('')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('7')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(6, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('\na')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(11, decoder.next_read_size())
        self.assertEqual('a', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('bcdefgd')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(4, decoder.next_read_size())
        self.assertEqual('bcdefg', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('one')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('\nblarg')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('blarg', decoder.unused_data)
        
    def test_accept_bytes_all_at_once_with_excess(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        decoder.accept_bytes('1\nadone\nunused')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('a', decoder.read_pending_data())
        self.assertEqual('unused', decoder.unused_data)

    def test_accept_bytes_exact_end_of_body(self):
        decoder = protocol.LengthPrefixedBodyDecoder()
        decoder.accept_bytes('1\na')
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(5, decoder.next_read_size())
        self.assertEqual('a', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)
        decoder.accept_bytes('done\n')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(1, decoder.next_read_size())
        self.assertEqual('', decoder.read_pending_data())
        self.assertEqual('', decoder.unused_data)


class FakeHTTPMedium(object):
    def __init__(self):
        self.written_request = None
        self._current_request = None
    def send_http_smart_request(self, bytes):
        self.written_request = bytes
        return None


class HTTPTunnellingSmokeTest(tests.TestCaseWithTransport):
    
    def setUp(self):
        super(HTTPTunnellingSmokeTest, self).setUp()
        # We use the VFS layer as part of HTTP tunnelling tests.
        self._captureVar('BZR_NO_SMART_VFS', None)

    def _test_bulk_data(self, url_protocol):
        # We should be able to send and receive bulk data in a single message.
        # The 'readv' command in the smart protocol both sends and receives bulk
        # data, so we use that.
        self.build_tree(['data-file'])
        self.transport_readonly_server = HTTPServerWithSmarts

        http_transport = self.get_readonly_transport()
        medium = http_transport.get_smart_medium()
        #remote_transport = RemoteTransport('fake_url', medium)
        remote_transport = remote.RemoteTransport('/', medium=medium)
        self.assertEqual(
            [(0, "c")], list(remote_transport.readv("data-file", [(0,1)])))

    def test_bulk_data_pycurl(self):
        try:
            self._test_bulk_data('http+pycurl')
        except errors.UnsupportedProtocol, e:
            raise tests.TestSkipped(str(e))
    
    def test_bulk_data_urllib(self):
        self._test_bulk_data('http+urllib')

    def test_smart_http_medium_request_accept_bytes(self):
        medium = FakeHTTPMedium()
        request = SmartClientHTTPMediumRequest(medium)
        request.accept_bytes('abc')
        request.accept_bytes('def')
        self.assertEqual(None, medium.written_request)
        request.finished_writing()
        self.assertEqual('abcdef', medium.written_request)

    def _test_http_send_smart_request(self, url_protocol):
        http_server = HTTPServerWithSmarts()
        http_server._url_protocol = url_protocol
        http_server.setUp(self.get_vfs_only_server())
        self.addCleanup(http_server.tearDown)

        post_body = 'hello\n'
        expected_reply_body = 'ok\x011\n'

        http_transport = get_transport(http_server.get_url())
        medium = http_transport.get_smart_medium()
        response = medium.send_http_smart_request(post_body)
        reply_body = response.read()
        self.assertEqual(expected_reply_body, reply_body)

    def test_http_send_smart_request_pycurl(self):
        try:
            self._test_http_send_smart_request('http+pycurl')
        except errors.UnsupportedProtocol, e:
            raise tests.TestSkipped(str(e))

    def test_http_send_smart_request_urllib(self):
        self._test_http_send_smart_request('http+urllib')

    def test_http_server_with_smarts(self):
        self.transport_readonly_server = HTTPServerWithSmarts

        post_body = 'hello\n'
        expected_reply_body = 'ok\x011\n'

        smart_server_url = self.get_readonly_url('.bzr/smart')
        reply = urllib2.urlopen(smart_server_url, post_body).read()

        self.assertEqual(expected_reply_body, reply)

    def test_smart_http_server_post_request_handler(self):
        self.transport_readonly_server = HTTPServerWithSmarts
        httpd = self.get_readonly_server()._get_httpd()

        socket = SampleSocket(
            'POST /.bzr/smart HTTP/1.0\r\n'
            # HTTP/1.0 posts must have a Content-Length.
            'Content-Length: 6\r\n'
            '\r\n'
            'hello\n')
        # Beware: the ('localhost', 80) below is the
        # client_address parameter, but we don't have one because
        # we have defined a socket which is not bound to an
        # address. The test framework never uses this client
        # address, so far...
        request_handler = SmartRequestHandler(socket, ('localhost', 80), httpd)
        response = socket.writefile.getvalue()
        self.assertStartsWith(response, 'HTTP/1.0 200 ')
        # This includes the end of the HTTP headers, and all the body.
        expected_end_of_response = '\r\n\r\nok\x011\n'
        self.assertEndsWith(response, expected_end_of_response)


class SampleSocket(object):
    """A socket-like object for use in testing the HTTP request handler."""
    
    def __init__(self, socket_read_content):
        """Constructs a sample socket.

        :param socket_read_content: a byte sequence
        """
        # Use plain python StringIO so we can monkey-patch the close method to
        # not discard the contents.
        from StringIO import StringIO
        self.readfile = StringIO(socket_read_content)
        self.writefile = StringIO()
        self.writefile.close = lambda: None
        
    def makefile(self, mode='r', bufsize=None):
        if 'r' in mode:
            return self.readfile
        else:
            return self.writefile


# TODO: Client feature that does get_bundle and then installs that into a
# branch; this can be used in place of the regular pull/fetch operation when
# coming from a smart server.
#
# TODO: Eventually, want to do a 'branch' command by fetching the whole
# history as one big bundle.  How?  
#
# The branch command does 'br_from.sprout', which tries to preserve the same
# format.  We don't necessarily even want that.  
#
# It might be simpler to handle cmd_pull first, which does a simpler fetch()
# operation from one branch into another.  It already has some code for
# pulling from a bundle, which it does by trying to see if the destination is
# a bundle file.  So it seems the logic for pull ought to be:
# 
#  - if it's a smart server, get a bundle from there and install that
#  - if it's a bundle, install that
#  - if it's a branch, pull from there
#
# Getting a bundle from a smart server is a bit different from reading a
# bundle from a URL:
#
#  - we can reasonably remember the URL we last read from 
#  - you can specify a revision number to pull, and we need to pass it across
#    to the server as a limit on what will be requested
#
# TODO: Given a URL, determine whether it is a smart server or not (or perhaps
# otherwise whether it's a bundle?)  Should this be a property or method of
# the transport?  For the ssh protocol, we always know it's a smart server.
# For http, we potentially need to probe.  But if we're explicitly given
# bzr+http:// then we can skip that for now. 
