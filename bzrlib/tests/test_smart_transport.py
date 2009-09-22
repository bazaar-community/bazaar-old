# Copyright (C) 2006, 2007, 2008, 2009 Canonical Ltd
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

"""Tests for smart transport"""

# all of this deals with byte strings so this is safe
from cStringIO import StringIO
import os
import socket
import threading

import bzrlib
from bzrlib import (
        bzrdir,
        errors,
        osutils,
        tests,
        urlutils,
        )
from bzrlib.smart import (
        client,
        medium,
        message,
        protocol,
        request as _mod_request,
        server,
        vfs,
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


class _InvalidHostnameFeature(tests.Feature):
    """Does 'non_existent.invalid' fail to resolve?

    RFC 2606 states that .invalid is reserved for invalid domain names, and
    also underscores are not a valid character in domain names.  Despite this,
    it's possible a badly misconfigured name server might decide to always
    return an address for any name, so this feature allows us to distinguish a
    broken system from a broken test.
    """

    def _probe(self):
        try:
            socket.gethostbyname('non_existent.invalid')
        except socket.gaierror:
            # The host name failed to resolve.  Good.
            return True
        else:
            return False

    def feature_name(self):
        return 'invalid hostname'

InvalidHostnameFeature = _InvalidHostnameFeature()


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
        client_medium = medium.SmartTCPClientMedium('127.0.0.1', port, 'base')
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

    def test_construct_smart_simple_pipes_client_medium(self):
        # the SimplePipes client medium takes two pipes:
        # readable pipe, writeable pipe.
        # Constructing one should just save these and do nothing.
        # We test this by passing in None.
        client_medium = medium.SmartSimplePipesClientMedium(None, None, None)

    def test_simple_pipes_client_request_type(self):
        # SimplePipesClient should use SmartClientStreamMediumRequest's.
        client_medium = medium.SmartSimplePipesClientMedium(None, None, None)
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
        client_medium = medium.SmartSimplePipesClientMedium(
            None, output, 'base')
        request = client_medium.get_request()
        request.finished_writing()
        request.finished_reading()
        request2 = client_medium.get_request()
        request2.finished_writing()
        request2.finished_reading()

    def test_simple_pipes_client__accept_bytes_writes_to_writable(self):
        # accept_bytes writes to the writeable pipe.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            None, output, 'base')
        client_medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())

    def test_simple_pipes_client_disconnect_does_nothing(self):
        # calling disconnect does nothing.
        input = StringIO()
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
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
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        client_medium._accept_bytes('abc')
        client_medium.disconnect()
        client_medium._accept_bytes('abc')
        self.assertFalse(input.closed)
        self.assertFalse(output.closed)
        self.assertEqual('abcabc', output.getvalue())

    def test_simple_pipes_client_ignores_disconnect_when_not_connected(self):
        # Doing a disconnect on a new (and thus unconnected) SimplePipes medium
        # does nothing.
        client_medium = medium.SmartSimplePipesClientMedium(None, None, 'base')
        client_medium.disconnect()

    def test_simple_pipes_client_can_always_read(self):
        # SmartSimplePipesClientMedium is never disconnected, so read_bytes
        # always tries to read from the underlying pipe.
        input = StringIO('abcdef')
        client_medium = medium.SmartSimplePipesClientMedium(input, None, 'base')
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
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
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
            username=None, password=None, base='base', vendor="not a vendor",
            bzr_remote_path='bzr')
        sock.close()

    def test_ssh_client_connects_on_first_use(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = StringIO()
        vendor = StringIOSSHVendor(StringIO(), output)
        client_medium = medium.SmartSSHClientMedium(
            'a hostname', 'a port', 'a username', 'a password', 'base', vendor,
            'bzr')
        client_medium._accept_bytes('abc')
        self.assertEqual('abc', output.getvalue())
        self.assertEqual([('connect_ssh', 'a username', 'a password',
            'a hostname', 'a port',
            ['bzr', 'serve', '--inet', '--directory=/', '--allow-writes'])],
            vendor.calls)

    def test_ssh_client_changes_command_when_bzr_remote_path_passed(self):
        # The only thing that initiates a connection from the medium is giving
        # it bytes.
        output = StringIO()
        vendor = StringIOSSHVendor(StringIO(), output)
        client_medium = medium.SmartSSHClientMedium('a hostname', 'a port',
            'a username', 'a password', 'base', vendor, bzr_remote_path='fugly')
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
        client_medium = medium.SmartSSHClientMedium(
            'a hostname', base='base', vendor=vendor, bzr_remote_path='bzr')
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
        client_medium = medium.SmartSSHClientMedium(
            'a hostname', base='base', vendor=vendor, bzr_remote_path='bzr')
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
        client_medium = medium.SmartSSHClientMedium(
            None, base='base', bzr_remote_path='bzr')
        client_medium.disconnect()

    def test_ssh_client_raises_on_read_when_not_connected(self):
        # Doing a read on a new (and thus unconnected) SSH medium raises
        # MediumNotConnected.
        client_medium = medium.SmartSSHClientMedium(
            None, base='base', bzr_remote_path='bzr')
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes,
                          0)
        self.assertRaises(errors.MediumNotConnected, client_medium.read_bytes,
                          1)

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
        client_medium = medium.SmartSSHClientMedium(
            'a hostname', base='base', vendor=vendor, bzr_remote_path='bzr')
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
        client_medium = medium.SmartTCPClientMedium(
            '127.0.0.1', unopened_port, 'base')
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
        client_medium = medium.SmartTCPClientMedium(None, None, None)
        client_medium.disconnect()

    def test_tcp_client_raises_on_read_when_not_connected(self):
        # Doing a read on a new (and thus unconnected) TCP medium raises
        # MediumNotConnected.
        client_medium = medium.SmartTCPClientMedium(None, None, None)
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

    def test_tcp_client_host_unknown_connection_error(self):
        self.requireFeature(InvalidHostnameFeature)
        client_medium = medium.SmartTCPClientMedium(
            'non_existent.invalid', 4155, 'base')
        self.assertRaises(
            errors.ConnectionError, client_medium._ensure_connection)


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
        client_medium = medium.SmartSimplePipesClientMedium(
            None, output, 'base')
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        self.assertRaises(errors.WritingCompleted, request.accept_bytes, None)

    def test_accept_bytes(self):
        # accept bytes should invoke _accept_bytes on the stream medium.
        # we test this by using the SimplePipes medium - the most trivial one
        # and checking that the pipes get the data.
        input = StringIO()
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
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
        client_medium = medium.SmartSimplePipesClientMedium(
            None, output, 'base')
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertIs(client_medium._current_request, request)

    def test_construct_while_another_request_active_throws(self):
        # constructing a SmartClientStreamMediumRequest on a StreamMedium with
        # a non-None _current_request raises TooManyConcurrentRequests.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            None, output, 'base')
        client_medium._current_request = "a"
        self.assertRaises(errors.TooManyConcurrentRequests,
            medium.SmartClientStreamMediumRequest, client_medium)

    def test_finished_read_clears_current_request(self):
        # calling finished_reading clears the current request from the requests
        # medium
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            None, output, 'base')
        request = medium.SmartClientStreamMediumRequest(client_medium)
        request.finished_writing()
        request.finished_reading()
        self.assertEqual(None, client_medium._current_request)

    def test_finished_read_before_finished_write_errors(self):
        # calling finished_reading before calling finished_writing triggers a
        # WritingNotComplete error.
        client_medium = medium.SmartSimplePipesClientMedium(
            None, None, 'base')
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
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
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
        client_medium = medium.SmartSimplePipesClientMedium(None, None, 'base')
        request = medium.SmartClientStreamMediumRequest(client_medium)
        self.assertRaises(errors.WritingNotComplete, request.read_bytes, None)

    def test_read_bytes_after_finished_reading_errors(self):
        # calling read_bytes after calling finished_reading raises
        # ReadingCompleted to prevent bad assumptions on stream environments
        # breaking the needs of message-based environments.
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            None, output, 'base')
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
        self.unused_data = ''

    def accept_bytes(self, bytes):
        self.accepted_bytes += bytes
        if self.accepted_bytes.startswith(self.expected_bytes):
            self._finished_reading = True
            self.unused_data = self.accepted_bytes[len(self.expected_bytes):]

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
        self.assertEqual('ok\0012\n',
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

    def test_socket_stream_incomplete_request(self):
        """The medium should still construct the right protocol version even if
        the initial read only reads part of the request.

        Specifically, it should correctly read the protocol version line even
        if the partial read doesn't end in a newline.  An older, naive
        implementation of _get_line in the server used to have a bug in that
        case.
        """
        incomplete_request_bytes = protocol.REQUEST_VERSION_TWO + 'hel'
        rest_of_request_bytes = 'lo\n'
        expected_response = (
            protocol.RESPONSE_VERSION_TWO + 'success\nok\x012\n')
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        client_sock.sendall(incomplete_request_bytes)
        server_protocol = server._build_protocol()
        client_sock.sendall(rest_of_request_bytes)
        server._serve_one_request(server_protocol)
        server_sock.close()
        self.assertEqual(expected_response, osutils.recv_all(client_sock, 50),
                         "Not a version 2 response to 'hello' request.")
        self.assertEqual('', client_sock.recv(1))

    def test_pipe_stream_incomplete_request(self):
        """The medium should still construct the right protocol version even if
        the initial read only reads part of the request.

        Specifically, it should correctly read the protocol version line even
        if the partial read doesn't end in a newline.  An older, naive
        implementation of _get_line in the server used to have a bug in that
        case.
        """
        incomplete_request_bytes = protocol.REQUEST_VERSION_TWO + 'hel'
        rest_of_request_bytes = 'lo\n'
        expected_response = (
            protocol.RESPONSE_VERSION_TWO + 'success\nok\x012\n')
        # Make a pair of pipes, to and from the server
        to_server, to_server_w = os.pipe()
        from_server_r, from_server = os.pipe()
        to_server = os.fdopen(to_server, 'r', 0)
        to_server_w = os.fdopen(to_server_w, 'w', 0)
        from_server_r = os.fdopen(from_server_r, 'r', 0)
        from_server = os.fdopen(from_server, 'w', 0)
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        # Like test_socket_stream_incomplete_request, write an incomplete
        # request (that does not end in '\n') and build a protocol from it.
        to_server_w.write(incomplete_request_bytes)
        server_protocol = server._build_protocol()
        # Send the rest of the request, and finish serving it.
        to_server_w.write(rest_of_request_bytes)
        server._serve_one_request(server_protocol)
        to_server_w.close()
        from_server.close()
        self.assertEqual(expected_response, from_server_r.read(),
                         "Not a version 2 response to 'hello' request.")
        self.assertEqual('', from_server_r.read(1))
        from_server_r.close()
        to_server.close()

    def test_pipe_like_stream_with_two_requests(self):
        # If two requests are read in one go, then two calls to
        # _serve_one_request should still process both of them as if they had
        # been received separately.
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
        # been received separately.
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

    def build_protocol_pipe_like(self, bytes):
        to_server = StringIO(bytes)
        from_server = StringIO()
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, None)
        return server._build_protocol()

    def build_protocol_socket(self, bytes):
        server_sock, client_sock = self.portable_socket_pair()
        server = medium.SmartServerSocketStreamMedium(
            server_sock, None)
        client_sock.sendall(bytes)
        client_sock.close()
        return server._build_protocol()

    def assertProtocolOne(self, server_protocol):
        # Use assertIs because assertIsInstance will wrongly pass
        # SmartServerRequestProtocolTwo (because it subclasses
        # SmartServerRequestProtocolOne).
        self.assertIs(
            type(server_protocol), protocol.SmartServerRequestProtocolOne)

    def assertProtocolTwo(self, server_protocol):
        self.assertIsInstance(
            server_protocol, protocol.SmartServerRequestProtocolTwo)

    def test_pipe_like_build_protocol_empty_bytes(self):
        # Any empty request (i.e. no bytes) is detected as protocol version one.
        server_protocol = self.build_protocol_pipe_like('')
        self.assertProtocolOne(server_protocol)

    def test_socket_like_build_protocol_empty_bytes(self):
        # Any empty request (i.e. no bytes) is detected as protocol version one.
        server_protocol = self.build_protocol_socket('')
        self.assertProtocolOne(server_protocol)

    def test_pipe_like_build_protocol_non_two(self):
        # A request that doesn't start with "bzr request 2\n" is version one.
        server_protocol = self.build_protocol_pipe_like('abc\n')
        self.assertProtocolOne(server_protocol)

    def test_socket_build_protocol_non_two(self):
        # A request that doesn't start with "bzr request 2\n" is version one.
        server_protocol = self.build_protocol_socket('abc\n')
        self.assertProtocolOne(server_protocol)

    def test_pipe_like_build_protocol_two(self):
        # A request that starts with "bzr request 2\n" is version two.
        server_protocol = self.build_protocol_pipe_like('bzr request 2\n')
        self.assertProtocolTwo(server_protocol)

    def test_socket_build_protocol_two(self):
        # A request that starts with "bzr request 2\n" is version two.
        server_protocol = self.build_protocol_socket('bzr request 2\n')
        self.assertProtocolTwo(server_protocol)


class TestGetProtocolFactoryForBytes(tests.TestCase):
    """_get_protocol_factory_for_bytes identifies the protocol factory a server
    should use to decode a given request.  Any bytes not part of the version
    marker string (and thus part of the actual request) are returned alongside
    the protocol factory.
    """

    def test_version_three(self):
        result = medium._get_protocol_factory_for_bytes(
            'bzr message 3 (bzr 1.6)\nextra bytes')
        protocol_factory, remainder = result
        self.assertEqual(
            protocol.build_server_protocol_three, protocol_factory)
        self.assertEqual('extra bytes', remainder)

    def test_version_two(self):
        result = medium._get_protocol_factory_for_bytes(
            'bzr request 2\nextra bytes')
        protocol_factory, remainder = result
        self.assertEqual(
            protocol.SmartServerRequestProtocolTwo, protocol_factory)
        self.assertEqual('extra bytes', remainder)

    def test_version_one(self):
        """Version one requests have no version markers."""
        result = medium._get_protocol_factory_for_bytes('anything\n')
        protocol_factory, remainder = result
        self.assertEqual(
            protocol.SmartServerRequestProtocolOne, protocol_factory)
        self.assertEqual('anything\n', remainder)


class TestSmartTCPServer(tests.TestCase):

    def test_get_error_unexpected(self):
        """Error reported by server with no specific representation"""
        self._captureVar('BZR_NO_SMART_VFS', None)
        class FlakyTransport(object):
            base = 'a_url'
            def external_url(self):
                return self.base
            def get_bytes(self, path):
                raise Exception("some random exception from inside server")
        smart_server = server.SmartTCPServer(backing_transport=FlakyTransport())
        smart_server.start_background_thread('-' + self.id())
        try:
            transport = remote.RemoteTCPTransport(smart_server.get_url())
            err = self.assertRaises(errors.UnknownErrorFromSmartServer,
                transport.get, 'something')
            self.assertContainsRe(str(err), 'some random exception')
            transport.disconnect()
        finally:
            smart_server.stop_background_thread()


class SmartTCPTests(tests.TestCase):
    """Tests for connection/end to end behaviour using the TCP server.

    All of these tests are run with a server running on another thread serving
    a MemoryTransport, and a connection to it already open.

    the server is obtained by calling self.setUpServer(readonly=False).
    """

    def setUpServer(self, readonly=False, backing_transport=None):
        """Setup the server.

        :param readonly: Create a readonly server.
        """
        # NB: Tests using this fall into two categories: tests of the server,
        # tests wanting a server. The latter should be updated to use
        # self.vfs_transport_factory etc.
        if not backing_transport:
            self.backing_transport = memory.MemoryTransport()
        else:
            self.backing_transport = backing_transport
        if readonly:
            self.real_backing_transport = self.backing_transport
            self.backing_transport = get_transport("readonly+" + self.backing_transport.abspath('.'))
        self.server = server.SmartTCPServer(self.backing_transport)
        self.server.start_background_thread('-' + self.id())
        self.transport = remote.RemoteTCPTransport(self.server.get_url())
        self.addCleanup(self.tearDownServer)
        self.permit_url(self.server.get_url())

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
        transport = remote.RemoteTCPTransport(self.server.get_url())
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
        transport = remote.RemoteTCPTransport(server.get_url())
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
        err = self.assertRaises(
            errors.NoSuchFile, self.transport.get, 'not%20a%20file')
        self.assertSubset([err.path], ['not%20a%20file', './not%20a%20file'])

    def test_simple_clone_conn(self):
        """Test that cloning reuses the same connection."""
        # we create a real connection not a loopback one, but it will use the
        # same server and pipes
        conn2 = self.transport.clone('.')
        self.assertIs(self.transport.get_smart_medium(),
                      conn2.get_smart_medium())

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

    def capture_server_call(self, backing_urls, public_url):
        """Record a server_started|stopped hook firing."""
        self.hook_calls.append((backing_urls, public_url))

    def test_server_started_hook_memory(self):
        """The server_started hook fires when the server is started."""
        self.hook_calls = []
        server.SmartTCPServer.hooks.install_named_hook('server_started',
            self.capture_server_call, None)
        self.setUpServer()
        # at this point, the server will be starting a thread up.
        # there is no indicator at the moment, so bodge it by doing a request.
        self.transport.has('.')
        # The default test server uses MemoryTransport and that has no external
        # url:
        self.assertEqual([([self.backing_transport.base], self.transport.base)],
            self.hook_calls)

    def test_server_started_hook_file(self):
        """The server_started hook fires when the server is started."""
        self.hook_calls = []
        server.SmartTCPServer.hooks.install_named_hook('server_started',
            self.capture_server_call, None)
        self.setUpServer(backing_transport=get_transport("."))
        # at this point, the server will be starting a thread up.
        # there is no indicator at the moment, so bodge it by doing a request.
        self.transport.has('.')
        # The default test server uses MemoryTransport and that has no external
        # url:
        self.assertEqual([([
            self.backing_transport.base, self.backing_transport.external_url()],
             self.transport.base)],
            self.hook_calls)

    def test_server_stopped_hook_simple_memory(self):
        """The server_stopped hook fires when the server is stopped."""
        self.hook_calls = []
        server.SmartTCPServer.hooks.install_named_hook('server_stopped',
            self.capture_server_call, None)
        self.setUpServer()
        result = [([self.backing_transport.base], self.transport.base)]
        # check the stopping message isn't emitted up front.
        self.assertEqual([], self.hook_calls)
        # nor after a single message
        self.transport.has('.')
        self.assertEqual([], self.hook_calls)
        # clean up the server
        self.tearDownServer()
        # now it should have fired.
        self.assertEqual(result, self.hook_calls)

    def test_server_stopped_hook_simple_file(self):
        """The server_stopped hook fires when the server is stopped."""
        self.hook_calls = []
        server.SmartTCPServer.hooks.install_named_hook('server_stopped',
            self.capture_server_call, None)
        self.setUpServer(backing_transport=get_transport("."))
        result = [(
            [self.backing_transport.base, self.backing_transport.external_url()]
            , self.transport.base)]
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

    Note: these tests are rudimentary versions of the command object tests in
    test_smart.py.
    """

    def test_hello(self):
        cmd = _mod_request.HelloRequest(None, '/')
        response = cmd.execute()
        self.assertEqual(('ok', '2'), response.args)
        self.assertEqual(None, response.body)

    def test_get_bundle(self):
        from bzrlib.bundle import serializer
        wt = self.make_branch_and_tree('.')
        self.build_tree_contents([('hello', 'hello world')])
        wt.add('hello')
        rev_id = wt.commit('add hello')

        cmd = _mod_request.GetBundleRequest(self.get_transport(), '/')
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
        return _mod_request.SmartServerRequestHandler(
            transport, _mod_request.request_handlers, '/')

    def test_construct_request_handler(self):
        """Constructing a request handler should be easy and set defaults."""
        handler = _mod_request.SmartServerRequestHandler(None, commands=None,
                root_client_path='/')
        self.assertFalse(handler.finished_reading)

    def test_hello(self):
        handler = self.build_handler(None)
        handler.args_received(('hello',))
        self.assertEqual(('ok', '2'), handler.response.args)
        self.assertEqual(None, handler.response.body)

    def test_disable_vfs_handler_classes_via_environment(self):
        # VFS handler classes will raise an error from "execute" if
        # BZR_NO_SMART_VFS is set.
        handler = vfs.HasRequest(None, '/')
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
        handler.args_received(('mkdir', 'foo', ''))
        # and the failure should be an explicit ReadOnlyError
        self.assertEqual(("ReadOnlyError", ), handler.response.args)
        # XXX: TODO: test that other TransportNotPossible errors are
        # presented as TransportNotPossible - not possible to do that
        # until I figure out how to trigger that relatively cleanly via
        # the api. RBC 20060918

    def test_hello_has_finished_body_on_dispatch(self):
        """The 'hello' command should set finished_reading."""
        handler = self.build_handler(None)
        handler.args_received(('hello',))
        self.assertTrue(handler.finished_reading)
        self.assertNotEqual(None, handler.response)

    def test_put_bytes_non_atomic(self):
        """'put_...' should set finished_reading after reading the bytes."""
        handler = self.build_handler(self.get_transport())
        handler.args_received(('put_non_atomic', 'a-file', '', 'F', ''))
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
        handler.args_received(('readv', 'a-file'))
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
        handler.args_received(('readv', 'a-file'))
        # read beyond the end of the file.
        handler.accept_body('100,1')
        handler.end_of_body()
        self.assertTrue(handler.finished_reading)
        self.assertEqual(('ShortReadvError', './a-file', '100', '1', '0'),
            handler.response.args)
        self.assertEqual(None, handler.response.body)


class RemoteTransportRegistration(tests.TestCase):

    def test_registration(self):
        t = get_transport('bzr+ssh://example.com/path')
        self.assertIsInstance(t, remote.RemoteSSHTransport)
        self.assertEqual('example.com', t._host)

    def test_bzr_https(self):
        # https://bugs.launchpad.net/bzr/+bug/128456
        t = get_transport('bzr+https://example.com/path')
        self.assertIsInstance(t, remote.RemoteHTTPTransport)
        self.assertStartsWith(
            t._http_transport.base,
            'https://')


class TestRemoteTransport(tests.TestCase):

    def test_use_connection_factory(self):
        # We want to be able to pass a client as a parameter to RemoteTransport.
        input = StringIO('ok\n3\nbardone\n')
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        transport = remote.RemoteTransport(
            'bzr://localhost/', medium=client_medium)
        # Disable version detection.
        client_medium._protocol_version = 1

        # We want to make sure the client is used when the first remote
        # method is called.  No data should have been sent, or read.
        self.assertEqual(0, input.tell())
        self.assertEqual('', output.getvalue())

        # Now call a method that should result in one request: as the
        # transport makes its own protocol instances, we check on the wire.
        # XXX: TODO: give the transport a protocol factory, which can make
        # an instrumented protocol for us.
        self.assertEqual('bar', transport.get_bytes('foo'))
        # only the needed data should have been sent/received.
        self.assertEqual(13, input.tell())
        self.assertEqual('get\x01/foo\n', output.getvalue())

    def test__translate_error_readonly(self):
        """Sending a ReadOnlyError to _translate_error raises TransportNotPossible."""
        client_medium = medium.SmartSimplePipesClientMedium(None, None, 'base')
        transport = remote.RemoteTransport(
            'bzr://localhost/', medium=client_medium)
        err = errors.ErrorFromSmartServer(("ReadOnlyError", ))
        self.assertRaises(errors.TransportNotPossible,
            transport._translate_error, err)


class TestSmartProtocol(tests.TestCase):
    """Base class for smart protocol tests.

    Each test case gets a smart_server and smart_client created during setUp().

    It is planned that the client can be called with self.call_client() giving
    it an expected server response, which will be fed into it when it tries to
    read. Likewise, self.call_server will call a servers method with a canned
    serialised client request. Output done by the client or server for these
    calls will be captured to self.to_server and self.to_client. Each element
    in the list is a write call from the client or server respectively.

    Subclasses can override client_protocol_class and server_protocol_class.
    """

    request_encoder = None
    response_decoder = None
    server_protocol_class = None
    client_protocol_class = None

    def make_client_protocol_and_output(self, input_bytes=None):
        """
        :returns: a Request
        """
        # This is very similar to
        # bzrlib.smart.client._SmartClient._build_client_protocol
        # XXX: make this use _SmartClient!
        if input_bytes is None:
            input = StringIO()
        else:
            input = StringIO(input_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        if self.client_protocol_class is not None:
            client_protocol = self.client_protocol_class(request)
            return client_protocol, client_protocol, output
        else:
            self.assertNotEqual(None, self.request_encoder)
            self.assertNotEqual(None, self.response_decoder)
            requester = self.request_encoder(request)
            response_handler = message.ConventionalResponseHandler()
            response_protocol = self.response_decoder(
                response_handler, expect_version_marker=True)
            response_handler.setProtoAndMediumRequest(
                response_protocol, request)
            return requester, response_handler, output

    def make_client_protocol(self, input_bytes=None):
        result = self.make_client_protocol_and_output(input_bytes=input_bytes)
        requester, response_handler, output = result
        return requester, response_handler

    def make_server_protocol(self):
        out_stream = StringIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        return smart_protocol, out_stream

    def setUp(self):
        super(TestSmartProtocol, self).setUp()
        self.response_marker = getattr(
            self.client_protocol_class, 'response_marker', None)
        self.request_marker = getattr(
            self.client_protocol_class, 'request_marker', None)

    def assertOffsetSerialisation(self, expected_offsets, expected_serialised,
        requester):
        """Check that smart (de)serialises offsets as expected.

        We check both serialisation and deserialisation at the same time
        to ensure that the round tripping cannot skew: both directions should
        be as expected.

        :param expected_offsets: a readv offset list.
        :param expected_seralised: an expected serial form of the offsets.
        """
        # XXX: '_deserialise_offsets' should be a method of the
        # SmartServerRequestProtocol in future.
        readv_cmd = vfs.ReadvRequest(None, '/')
        offsets = readv_cmd._deserialise_offsets(expected_serialised)
        self.assertEqual(expected_offsets, offsets)
        serialised = requester._serialise_offsets(offsets)
        self.assertEqual(expected_serialised, serialised)

    def build_protocol_waiting_for_body(self):
        smart_protocol, out_stream = self.make_server_protocol()
        smart_protocol._has_dispatched = True
        smart_protocol.request = _mod_request.SmartServerRequestHandler(
            None, _mod_request.request_handlers, '/')
        class FakeCommand(_mod_request.SmartServerRequest):
            def do_body(self_cmd, body_bytes):
                self.end_received = True
                self.assertEqual('abcdefg', body_bytes)
                return _mod_request.SuccessfulSmartServerResponse(('ok', ))
        smart_protocol.request._command = FakeCommand(None)
        # Call accept_bytes to make sure that internal state like _body_decoder
        # is initialised.  This test should probably be given a clearer
        # interface to work with that will not cause this inconsistency.
        #   -- Andrew Bennetts, 2006-09-28
        smart_protocol.accept_bytes('')
        return smart_protocol

    def assertServerToClientEncoding(self, expected_bytes, expected_tuple,
            input_tuples):
        """Assert that each input_tuple serialises as expected_bytes, and the
        bytes deserialise as expected_tuple.
        """
        # check the encoding of the server for all input_tuples matches
        # expected bytes
        for input_tuple in input_tuples:
            server_protocol, server_output = self.make_server_protocol()
            server_protocol._send_response(
                _mod_request.SuccessfulSmartServerResponse(input_tuple))
            self.assertEqual(expected_bytes, server_output.getvalue())
        # check the decoding of the client smart_protocol from expected_bytes:
        requester, response_handler = self.make_client_protocol(expected_bytes)
        requester.call('foo')
        self.assertEqual(expected_tuple, response_handler.read_response_tuple())


class CommonSmartProtocolTestMixin(object):

    def test_connection_closed_reporting(self):
        requester, response_handler = self.make_client_protocol()
        requester.call('hello')
        ex = self.assertRaises(errors.ConnectionReset,
            response_handler.read_response_tuple)
        self.assertEqual("Connection closed: "
            "Unexpected end of message. Please check connectivity "
            "and permissions, and report a bug if problems persist. ",
            str(ex))

    def test_server_offset_serialisation(self):
        """The Smart protocol serialises offsets as a comma and \n string.

        We check a number of boundary cases are as expected: empty, one offset,
        one with the order of reads not increasing (an out of order read), and
        one that should coalesce.
        """
        requester, response_handler = self.make_client_protocol()
        self.assertOffsetSerialisation([], '', requester)
        self.assertOffsetSerialisation([(1,2)], '1,2', requester)
        self.assertOffsetSerialisation([(10,40), (0,5)], '10,40\n0,5',
            requester)
        self.assertOffsetSerialisation([(1,2), (3,4), (100, 200)],
            '1,2\n3,4\n100,200', requester)


class TestVersionOneFeaturesInProtocolOne(
    TestSmartProtocol, CommonSmartProtocolTestMixin):
    """Tests for version one smart protocol features as implemeted by version
    one."""

    client_protocol_class = protocol.SmartClientRequestProtocolOne
    server_protocol_class = protocol.SmartServerRequestProtocolOne

    def test_construct_version_one_server_protocol(self):
        smart_protocol = protocol.SmartServerRequestProtocolOne(None, None)
        self.assertEqual('', smart_protocol.unused_data)
        self.assertEqual('', smart_protocol.in_buffer)
        self.assertFalse(smart_protocol._has_dispatched)
        self.assertEqual(1, smart_protocol.next_read_size())

    def test_construct_version_one_client_protocol(self):
        # we can construct a client protocol from a client medium request
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            None, output, 'base')
        request = client_medium.get_request()
        client_protocol = protocol.SmartClientRequestProtocolOne(request)

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
        self.assertTrue(smart_protocol._has_dispatched)
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
        self.assertEqual('', smart_protocol.unused_data)
        self.assertEqual('', smart_protocol.in_buffer)

    def test_accept_excess_bytes_are_preserved(self):
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, out_stream.write)
        smart_protocol.accept_bytes('hello\nhello\n')
        self.assertEqual("ok\x012\n", out_stream.getvalue())
        self.assertEqual("hello\n", smart_protocol.unused_data)
        self.assertEqual("", smart_protocol.in_buffer)

    def test_accept_excess_bytes_after_body(self):
        protocol = self.build_protocol_waiting_for_body()
        protocol.accept_bytes('7\nabcdefgdone\nX')
        self.assertTrue(self.end_received)
        self.assertEqual("X", protocol.unused_data)
        self.assertEqual("", protocol.in_buffer)
        protocol.accept_bytes('Y')
        self.assertEqual("XY", protocol.unused_data)
        self.assertEqual("", protocol.in_buffer)

    def test_accept_excess_bytes_after_dispatch(self):
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, out_stream.write)
        smart_protocol.accept_bytes('hello\n')
        self.assertEqual("ok\x012\n", out_stream.getvalue())
        smart_protocol.accept_bytes('hel')
        self.assertEqual("hel", smart_protocol.unused_data)
        smart_protocol.accept_bytes('lo\n')
        self.assertEqual("hello\n", smart_protocol.unused_data)
        self.assertEqual("", smart_protocol.in_buffer)

    def test__send_response_sets_finished_reading(self):
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, lambda x: None)
        self.assertEqual(1, smart_protocol.next_read_size())
        smart_protocol._send_response(
            _mod_request.SuccessfulSmartServerResponse(('x',)))
        self.assertEqual(0, smart_protocol.next_read_size())

    def test__send_response_errors_with_base_response(self):
        """Ensure that only the Successful/Failed subclasses are used."""
        smart_protocol = protocol.SmartServerRequestProtocolOne(
            None, lambda x: None)
        self.assertRaises(AttributeError, smart_protocol._send_response,
            _mod_request.SmartServerResponse(('x',)))

    def test_query_version(self):
        """query_version on a SmartClientProtocolOne should return a number.

        The protocol provides the query_version because the domain level clients
        may all need to be able to probe for capabilities.
        """
        # What we really want to test here is that SmartClientProtocolOne calls
        # accept_bytes(tuple_based_encoding_of_hello) and reads and parses the
        # response of tuple-encoded (ok, 1).  Also, separately we should test
        # the error if the response is a non-understood version.
        input = StringIO('ok\x012\n')
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        self.assertEqual(2, smart_protocol.query_version())

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
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
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
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call_with_body_readv_array(('foo', ), [(1,2),(5,6)])
        self.assertEqual(expected_bytes, output.getvalue())

    def _test_client_read_response_tuple_raises_UnknownSmartMethod(self,
            server_bytes):
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call('foo')
        self.assertRaises(
            errors.UnknownSmartMethod, smart_protocol.read_response_tuple)
        # The request has been finished.  There is no body to read, and
        # attempts to read one will fail.
        self.assertRaises(
            errors.ReadingCompleted, smart_protocol.read_body_bytes)

    def test_client_read_response_tuple_raises_UnknownSmartMethod(self):
        """read_response_tuple raises UnknownSmartMethod if the response says
        the server did not recognise the request.
        """
        server_bytes = (
            "error\x01Generic bzr smart protocol error: bad request 'foo'\n")
        self._test_client_read_response_tuple_raises_UnknownSmartMethod(
            server_bytes)

    def test_client_read_response_tuple_raises_UnknownSmartMethod_0_11(self):
        """read_response_tuple also raises UnknownSmartMethod if the response
        from a bzr 0.11 says the server did not recognise the request.

        (bzr 0.11 sends a slightly different error message to later versions.)
        """
        server_bytes = (
            "error\x01Generic bzr smart protocol error: bad request u'foo'\n")
        self._test_client_read_response_tuple_raises_UnknownSmartMethod(
            server_bytes)

    def test_client_read_body_bytes_all(self):
        # read_body_bytes should decode the body bytes from the wire into
        # a response.
        expected_bytes = "1234567"
        server_bytes = "ok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
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
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
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
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolOne(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        smart_protocol.cancel_read_body()
        self.assertEqual(3, input.tell())
        self.assertRaises(
            errors.ReadingCompleted, smart_protocol.read_body_bytes)

    def test_client_read_body_bytes_interrupted_connection(self):
        server_bytes = "ok\n999\nincomplete body"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        self.assertRaises(
            errors.ConnectionReset, smart_protocol.read_body_bytes)


class TestVersionOneFeaturesInProtocolTwo(
    TestSmartProtocol, CommonSmartProtocolTestMixin):
    """Tests for version one smart protocol features as implemeted by version
    two.
    """

    client_protocol_class = protocol.SmartClientRequestProtocolTwo
    server_protocol_class = protocol.SmartServerRequestProtocolTwo

    def test_construct_version_two_server_protocol(self):
        smart_protocol = protocol.SmartServerRequestProtocolTwo(None, None)
        self.assertEqual('', smart_protocol.unused_data)
        self.assertEqual('', smart_protocol.in_buffer)
        self.assertFalse(smart_protocol._has_dispatched)
        self.assertEqual(1, smart_protocol.next_read_size())

    def test_construct_version_two_client_protocol(self):
        # we can construct a client protocol from a client medium request
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            None, output, 'base')
        request = client_medium.get_request()
        client_protocol = protocol.SmartClientRequestProtocolTwo(request)

    def test_accept_bytes_of_bad_request_to_protocol(self):
        out_stream = StringIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        smart_protocol.accept_bytes('abc')
        self.assertEqual('abc', smart_protocol.in_buffer)
        smart_protocol.accept_bytes('\n')
        self.assertEqual(
            self.response_marker +
            "failed\nerror\x01Generic bzr smart protocol error: bad request 'abc'\n",
            out_stream.getvalue())
        self.assertTrue(smart_protocol._has_dispatched)
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
        smart_protocol = self.server_protocol_class(
            mem_transport, out_stream.write)
        smart_protocol.accept_bytes('readv\x01foo\n3\n3,3done\n')
        self.assertEqual(0, smart_protocol.next_read_size())
        self.assertEqual(self.response_marker +
                         'success\nreadv\n3\ndefdone\n',
                         out_stream.getvalue())
        self.assertEqual('', smart_protocol.unused_data)
        self.assertEqual('', smart_protocol.in_buffer)

    def test_accept_excess_bytes_are_preserved(self):
        out_stream = StringIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        smart_protocol.accept_bytes('hello\nhello\n')
        self.assertEqual(self.response_marker + "success\nok\x012\n",
                         out_stream.getvalue())
        self.assertEqual("hello\n", smart_protocol.unused_data)
        self.assertEqual("", smart_protocol.in_buffer)

    def test_accept_excess_bytes_after_body(self):
        # The excess bytes look like the start of another request.
        server_protocol = self.build_protocol_waiting_for_body()
        server_protocol.accept_bytes('7\nabcdefgdone\n' + self.response_marker)
        self.assertTrue(self.end_received)
        self.assertEqual(self.response_marker,
                         server_protocol.unused_data)
        self.assertEqual("", server_protocol.in_buffer)
        server_protocol.accept_bytes('Y')
        self.assertEqual(self.response_marker + "Y",
                         server_protocol.unused_data)
        self.assertEqual("", server_protocol.in_buffer)

    def test_accept_excess_bytes_after_dispatch(self):
        out_stream = StringIO()
        smart_protocol = self.server_protocol_class(None, out_stream.write)
        smart_protocol.accept_bytes('hello\n')
        self.assertEqual(self.response_marker + "success\nok\x012\n",
                         out_stream.getvalue())
        smart_protocol.accept_bytes(self.request_marker + 'hel')
        self.assertEqual(self.request_marker + "hel",
                         smart_protocol.unused_data)
        smart_protocol.accept_bytes('lo\n')
        self.assertEqual(self.request_marker + "hello\n",
                         smart_protocol.unused_data)
        self.assertEqual("", smart_protocol.in_buffer)

    def test__send_response_sets_finished_reading(self):
        smart_protocol = self.server_protocol_class(None, lambda x: None)
        self.assertEqual(1, smart_protocol.next_read_size())
        smart_protocol._send_response(
            _mod_request.SuccessfulSmartServerResponse(('x',)))
        self.assertEqual(0, smart_protocol.next_read_size())

    def test__send_response_errors_with_base_response(self):
        """Ensure that only the Successful/Failed subclasses are used."""
        smart_protocol = self.server_protocol_class(None, lambda x: None)
        self.assertRaises(AttributeError, smart_protocol._send_response,
            _mod_request.SmartServerResponse(('x',)))

    def test_query_version(self):
        """query_version on a SmartClientProtocolTwo should return a number.

        The protocol provides the query_version because the domain level clients
        may all need to be able to probe for capabilities.
        """
        # What we really want to test here is that SmartClientProtocolTwo calls
        # accept_bytes(tuple_based_encoding_of_hello) and reads and parses the
        # response of tuple-encoded (ok, 1).  Also, separately we should test
        # the error if the response is a non-understood version.
        input = StringIO(self.response_marker + 'success\nok\x012\n')
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        self.assertEqual(2, smart_protocol.query_version())

    def test_client_call_empty_response(self):
        # protocol.call() can get back an empty tuple as a response. This occurs
        # when the parsed line is an empty line, and results in a tuple with
        # one element - an empty string.
        self.assertServerToClientEncoding(
            self.response_marker + 'success\n\n', ('', ), [(), ('', )])

    def test_client_call_three_element_response(self):
        # protocol.call() can get back tuples of other lengths. A three element
        # tuple should be unpacked as three strings.
        self.assertServerToClientEncoding(
            self.response_marker + 'success\na\x01b\x0134\n',
            ('a', 'b', '34'),
            [('a', 'b', '34')])

    def test_client_call_with_body_bytes_uploads(self):
        # protocol.call_with_body_bytes should length-prefix the bytes onto the
        # wire.
        expected_bytes = self.request_marker + "foo\n7\nabcdefgdone\n"
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call_with_body_bytes(('foo', ), "abcdefg")
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_call_with_body_readv_array(self):
        # protocol.call_with_upload should encode the readv array and then
        # length-prefix the bytes onto the wire.
        expected_bytes = self.request_marker + "foo\n7\n1,2\n5,6done\n"
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call_with_body_readv_array(('foo', ), [(1,2),(5,6)])
        self.assertEqual(expected_bytes, output.getvalue())

    def test_client_read_body_bytes_all(self):
        # read_body_bytes should decode the body bytes from the wire into
        # a response.
        expected_bytes = "1234567"
        server_bytes = (self.response_marker +
                        "success\nok\n7\n1234567done\n")
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
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
        server_bytes = self.response_marker + "success\nok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        self.assertEqual(expected_bytes[0:2], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[2:4], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[4:6], smart_protocol.read_body_bytes(2))
        self.assertEqual(expected_bytes[6], smart_protocol.read_body_bytes())

    def test_client_cancel_read_body_does_not_eat_body_bytes(self):
        # cancelling the expected body needs to finish the request, but not
        # read any more bytes.
        server_bytes = self.response_marker + "success\nok\n7\n1234567done\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        smart_protocol.cancel_read_body()
        self.assertEqual(len(self.response_marker + 'success\nok\n'),
                         input.tell())
        self.assertRaises(
            errors.ReadingCompleted, smart_protocol.read_body_bytes)

    def test_client_read_body_bytes_interrupted_connection(self):
        server_bytes = (self.response_marker +
                        "success\nok\n999\nincomplete body")
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = self.client_protocol_class(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        self.assertRaises(
            errors.ConnectionReset, smart_protocol.read_body_bytes)


class TestSmartProtocolTwoSpecificsMixin(object):

    def assertBodyStreamSerialisation(self, expected_serialisation,
                                      body_stream):
        """Assert that body_stream is serialised as expected_serialisation."""
        out_stream = StringIO()
        protocol._send_stream(body_stream, out_stream.write)
        self.assertEqual(expected_serialisation, out_stream.getvalue())

    def assertBodyStreamRoundTrips(self, body_stream):
        """Assert that body_stream is the same after being serialised and
        deserialised.
        """
        out_stream = StringIO()
        protocol._send_stream(body_stream, out_stream.write)
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes(out_stream.getvalue())
        decoded_stream = list(iter(decoder.read_next_chunk, None))
        self.assertEqual(body_stream, decoded_stream)

    def test_body_stream_serialisation_empty(self):
        """A body_stream with no bytes can be serialised."""
        self.assertBodyStreamSerialisation('chunked\nEND\n', [])
        self.assertBodyStreamRoundTrips([])

    def test_body_stream_serialisation(self):
        stream = ['chunk one', 'chunk two', 'chunk three']
        self.assertBodyStreamSerialisation(
            'chunked\n' + '9\nchunk one' + '9\nchunk two' + 'b\nchunk three' +
            'END\n',
            stream)
        self.assertBodyStreamRoundTrips(stream)

    def test_body_stream_with_empty_element_serialisation(self):
        """A body stream can include ''.

        The empty string can be transmitted like any other string.
        """
        stream = ['', 'chunk']
        self.assertBodyStreamSerialisation(
            'chunked\n' + '0\n' + '5\nchunk' + 'END\n', stream)
        self.assertBodyStreamRoundTrips(stream)

    def test_body_stream_error_serialistion(self):
        stream = ['first chunk',
                  _mod_request.FailedSmartServerResponse(
                      ('FailureName', 'failure arg'))]
        expected_bytes = (
            'chunked\n' + 'b\nfirst chunk' +
            'ERR\n' + 'b\nFailureName' + 'b\nfailure arg' +
            'END\n')
        self.assertBodyStreamSerialisation(expected_bytes, stream)
        self.assertBodyStreamRoundTrips(stream)

    def test__send_response_includes_failure_marker(self):
        """FailedSmartServerResponse have 'failed\n' after the version."""
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolTwo(
            None, out_stream.write)
        smart_protocol._send_response(
            _mod_request.FailedSmartServerResponse(('x',)))
        self.assertEqual(protocol.RESPONSE_VERSION_TWO + 'failed\nx\n',
                         out_stream.getvalue())

    def test__send_response_includes_success_marker(self):
        """SuccessfulSmartServerResponse have 'success\n' after the version."""
        out_stream = StringIO()
        smart_protocol = protocol.SmartServerRequestProtocolTwo(
            None, out_stream.write)
        smart_protocol._send_response(
            _mod_request.SuccessfulSmartServerResponse(('x',)))
        self.assertEqual(protocol.RESPONSE_VERSION_TWO + 'success\nx\n',
                         out_stream.getvalue())

    def test__send_response_with_body_stream_sets_finished_reading(self):
        smart_protocol = protocol.SmartServerRequestProtocolTwo(
            None, lambda x: None)
        self.assertEqual(1, smart_protocol.next_read_size())
        smart_protocol._send_response(
            _mod_request.SuccessfulSmartServerResponse(('x',), body_stream=[]))
        self.assertEqual(0, smart_protocol.next_read_size())

    def test_streamed_body_bytes(self):
        body_header = 'chunked\n'
        two_body_chunks = "4\n1234" + "3\n567"
        body_terminator = "END\n"
        server_bytes = (protocol.RESPONSE_VERSION_TWO +
                        "success\nok\n" + body_header + two_body_chunks +
                        body_terminator)
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        stream = smart_protocol.read_streamed_body()
        self.assertEqual(['1234', '567'], list(stream))

    def test_read_streamed_body_error(self):
        """When a stream is interrupted by an error..."""
        body_header = 'chunked\n'
        a_body_chunk = '4\naaaa'
        err_signal = 'ERR\n'
        err_chunks = 'a\nerror arg1' + '4\narg2'
        finish = 'END\n'
        body = body_header + a_body_chunk + err_signal + err_chunks + finish
        server_bytes = (protocol.RESPONSE_VERSION_TWO +
                        "success\nok\n" + body)
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        smart_request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(smart_request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        expected_chunks = [
            'aaaa',
            _mod_request.FailedSmartServerResponse(('error arg1', 'arg2'))]
        stream = smart_protocol.read_streamed_body()
        self.assertEqual(expected_chunks, list(stream))

    def test_streamed_body_bytes_interrupted_connection(self):
        body_header = 'chunked\n'
        incomplete_body_chunk = "9999\nincomplete chunk"
        server_bytes = (protocol.RESPONSE_VERSION_TWO +
                        "success\nok\n" + body_header + incomplete_body_chunk)
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(True)
        stream = smart_protocol.read_streamed_body()
        self.assertRaises(errors.ConnectionReset, stream.next)

    def test_client_read_response_tuple_sets_response_status(self):
        server_bytes = protocol.RESPONSE_VERSION_TWO + "success\nok\n"
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call('foo')
        smart_protocol.read_response_tuple(False)
        self.assertEqual(True, smart_protocol.response_status)

    def test_client_read_response_tuple_raises_UnknownSmartMethod(self):
        """read_response_tuple raises UnknownSmartMethod if the response says
        the server did not recognise the request.
        """
        server_bytes = (
            protocol.RESPONSE_VERSION_TWO +
            "failed\n" +
            "error\x01Generic bzr smart protocol error: bad request 'foo'\n")
        input = StringIO(server_bytes)
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'base')
        request = client_medium.get_request()
        smart_protocol = protocol.SmartClientRequestProtocolTwo(request)
        smart_protocol.call('foo')
        self.assertRaises(
            errors.UnknownSmartMethod, smart_protocol.read_response_tuple)
        # The request has been finished.  There is no body to read, and
        # attempts to read one will fail.
        self.assertRaises(
            errors.ReadingCompleted, smart_protocol.read_body_bytes)


class TestSmartProtocolTwoSpecifics(
        TestSmartProtocol, TestSmartProtocolTwoSpecificsMixin):
    """Tests for aspects of smart protocol version two that are unique to
    version two.

    Thus tests involving body streams and success/failure markers belong here.
    """

    client_protocol_class = protocol.SmartClientRequestProtocolTwo
    server_protocol_class = protocol.SmartServerRequestProtocolTwo


class TestVersionOneFeaturesInProtocolThree(
    TestSmartProtocol, CommonSmartProtocolTestMixin):
    """Tests for version one smart protocol features as implemented by version
    three.
    """

    request_encoder = protocol.ProtocolThreeRequester
    response_decoder = protocol.ProtocolThreeDecoder
    # build_server_protocol_three is a function, so we can't set it as a class
    # attribute directly, because then Python will assume it is actually a
    # method.  So we make server_protocol_class be a static method, rather than
    # simply doing:
    # "server_protocol_class = protocol.build_server_protocol_three".
    server_protocol_class = staticmethod(protocol.build_server_protocol_three)

    def setUp(self):
        super(TestVersionOneFeaturesInProtocolThree, self).setUp()
        self.response_marker = protocol.MESSAGE_VERSION_THREE
        self.request_marker = protocol.MESSAGE_VERSION_THREE

    def test_construct_version_three_server_protocol(self):
        smart_protocol = protocol.ProtocolThreeDecoder(None)
        self.assertEqual('', smart_protocol.unused_data)
        self.assertEqual([], smart_protocol._in_buffer_list)
        self.assertEqual(0, smart_protocol._in_buffer_len)
        self.assertFalse(smart_protocol._has_dispatched)
        # The protocol starts by expecting four bytes, a length prefix for the
        # headers.
        self.assertEqual(4, smart_protocol.next_read_size())


class LoggingMessageHandler(object):

    def __init__(self):
        self.event_log = []

    def _log(self, *args):
        self.event_log.append(args)

    def headers_received(self, headers):
        self._log('headers', headers)

    def protocol_error(self, exception):
        self._log('protocol_error', exception)

    def byte_part_received(self, byte):
        self._log('byte', byte)

    def bytes_part_received(self, bytes):
        self._log('bytes', bytes)

    def structure_part_received(self, structure):
        self._log('structure', structure)

    def end_received(self):
        self._log('end')


class TestProtocolThree(TestSmartProtocol):
    """Tests for v3 of the server-side protocol."""

    request_encoder = protocol.ProtocolThreeRequester
    response_decoder = protocol.ProtocolThreeDecoder
    server_protocol_class = protocol.ProtocolThreeDecoder

    def test_trivial_request(self):
        """Smoke test for the simplest possible v3 request: empty headers, no
        message parts.
        """
        output = StringIO()
        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
        end = 'e'
        request_bytes = headers + end
        smart_protocol = self.server_protocol_class(LoggingMessageHandler())
        smart_protocol.accept_bytes(request_bytes)
        self.assertEqual(0, smart_protocol.next_read_size())
        self.assertEqual('', smart_protocol.unused_data)

    def test_repeated_excess(self):
        """Repeated calls to accept_bytes after the message end has been parsed
        accumlates the bytes in the unused_data attribute.
        """
        output = StringIO()
        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
        end = 'e'
        request_bytes = headers + end
        smart_protocol = self.server_protocol_class(LoggingMessageHandler())
        smart_protocol.accept_bytes(request_bytes)
        self.assertEqual('', smart_protocol.unused_data)
        smart_protocol.accept_bytes('aaa')
        self.assertEqual('aaa', smart_protocol.unused_data)
        smart_protocol.accept_bytes('bbb')
        self.assertEqual('aaabbb', smart_protocol.unused_data)
        self.assertEqual(0, smart_protocol.next_read_size())

    def make_protocol_expecting_message_part(self):
        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
        message_handler = LoggingMessageHandler()
        smart_protocol = self.server_protocol_class(message_handler)
        smart_protocol.accept_bytes(headers)
        # Clear the event log
        del message_handler.event_log[:]
        return smart_protocol, message_handler.event_log

    def test_decode_one_byte(self):
        """The protocol can decode a 'one byte' message part."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes('ox')
        self.assertEqual([('byte', 'x')], event_log)

    def test_decode_bytes(self):
        """The protocol can decode a 'bytes' message part."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes(
            'b' # message part kind
            '\0\0\0\x07' # length prefix
            'payload' # payload
            )
        self.assertEqual([('bytes', 'payload')], event_log)

    def test_decode_structure(self):
        """The protocol can decode a 'structure' message part."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes(
            's' # message part kind
            '\0\0\0\x07' # length prefix
            'l3:ARGe' # ['ARG']
            )
        self.assertEqual([('structure', ('ARG',))], event_log)

    def test_decode_multiple_bytes(self):
        """The protocol can decode a multiple 'bytes' message parts."""
        smart_protocol, event_log = self.make_protocol_expecting_message_part()
        smart_protocol.accept_bytes(
            'b' # message part kind
            '\0\0\0\x05' # length prefix
            'first' # payload
            'b' # message part kind
            '\0\0\0\x06'
            'second'
            )
        self.assertEqual(
            [('bytes', 'first'), ('bytes', 'second')], event_log)


class TestConventionalResponseHandlerBodyStream(tests.TestCase):

    def make_response_handler(self, response_bytes):
        from bzrlib.smart.message import ConventionalResponseHandler
        response_handler = ConventionalResponseHandler()
        protocol_decoder = protocol.ProtocolThreeDecoder(response_handler)
        # put decoder in desired state (waiting for message parts)
        protocol_decoder.state_accept = protocol_decoder._state_accept_expecting_message_part
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            StringIO(response_bytes), output, 'base')
        medium_request = client_medium.get_request()
        medium_request.finished_writing()
        response_handler.setProtoAndMediumRequest(
            protocol_decoder, medium_request)
        return response_handler

    def test_interrupted_by_error(self):
        response_handler = self.make_response_handler(interrupted_body_stream)
        stream = response_handler.read_streamed_body()
        self.assertEqual('aaa', stream.next())
        self.assertEqual('bbb', stream.next())
        exc = self.assertRaises(errors.ErrorFromSmartServer, stream.next)
        self.assertEqual(('error', 'Boom!'), exc.error_tuple)

    def test_interrupted_by_connection_lost(self):
        interrupted_body_stream = (
            'oS' # successful response
            's\0\0\0\x02le' # empty args
            'b\0\0\xff\xffincomplete chunk')
        response_handler = self.make_response_handler(interrupted_body_stream)
        stream = response_handler.read_streamed_body()
        self.assertRaises(errors.ConnectionReset, stream.next)

    def test_read_body_bytes_interrupted_by_connection_lost(self):
        interrupted_body_stream = (
            'oS' # successful response
            's\0\0\0\x02le' # empty args
            'b\0\0\xff\xffincomplete chunk')
        response_handler = self.make_response_handler(interrupted_body_stream)
        self.assertRaises(
            errors.ConnectionReset, response_handler.read_body_bytes)

    def test_multiple_bytes_parts(self):
        multiple_bytes_parts = (
            'oS' # successful response
            's\0\0\0\x02le' # empty args
            'b\0\0\0\x0bSome bytes\n' # some bytes
            'b\0\0\0\x0aMore bytes' # more bytes
            'e' # message end
            )
        response_handler = self.make_response_handler(multiple_bytes_parts)
        self.assertEqual(
            'Some bytes\nMore bytes', response_handler.read_body_bytes())
        response_handler = self.make_response_handler(multiple_bytes_parts)
        self.assertEqual(
            ['Some bytes\n', 'More bytes'],
            list(response_handler.read_streamed_body()))


class FakeResponder(object):

    response_sent = False

    def send_error(self, exc):
        raise exc

    def send_response(self, response):
        pass


class TestConventionalRequestHandlerBodyStream(tests.TestCase):
    """Tests for ConventionalRequestHandler's handling of request bodies."""

    def make_request_handler(self, request_bytes):
        """Make a ConventionalRequestHandler for the given bytes using test
        doubles for the request_handler and the responder.
        """
        from bzrlib.smart.message import ConventionalRequestHandler
        request_handler = InstrumentedRequestHandler()
        request_handler.response = _mod_request.SuccessfulSmartServerResponse(('arg', 'arg'))
        responder = FakeResponder()
        message_handler = ConventionalRequestHandler(request_handler, responder)
        protocol_decoder = protocol.ProtocolThreeDecoder(message_handler)
        # put decoder in desired state (waiting for message parts)
        protocol_decoder.state_accept = protocol_decoder._state_accept_expecting_message_part
        protocol_decoder.accept_bytes(request_bytes)
        return request_handler

    def test_multiple_bytes_parts(self):
        """Each bytes part triggers a call to the request_handler's
        accept_body method.
        """
        multiple_bytes_parts = (
            's\0\0\0\x07l3:fooe' # args
            'b\0\0\0\x0bSome bytes\n' # some bytes
            'b\0\0\0\x0aMore bytes' # more bytes
            'e' # message end
            )
        request_handler = self.make_request_handler(multiple_bytes_parts)
        accept_body_calls = [
            call_info[1] for call_info in request_handler.calls
            if call_info[0] == 'accept_body']
        self.assertEqual(
            ['Some bytes\n', 'More bytes'], accept_body_calls)

    def test_error_flag_after_body(self):
        body_then_error = (
            's\0\0\0\x07l3:fooe' # request args
            'b\0\0\0\x0bSome bytes\n' # some bytes
            'b\0\0\0\x0aMore bytes' # more bytes
            'oE' # error flag
            's\0\0\0\x07l3:bare' # error args
            'e' # message end
            )
        request_handler = self.make_request_handler(body_then_error)
        self.assertEqual(
            [('post_body_error_received', ('bar',)), ('end_received',)],
            request_handler.calls[-2:])


class TestMessageHandlerErrors(tests.TestCase):
    """Tests for v3 that unrecognised (but well-formed) requests/responses are
    still fully read off the wire, so that subsequent requests/responses on the
    same medium can be decoded.
    """

    def test_non_conventional_request(self):
        """ConventionalRequestHandler (the default message handler on the
        server side) will reject an unconventional message, but still consume
        all the bytes of that message and signal when it has done so.

        This is what allows a server to continue to accept requests after the
        client sends a completely unrecognised request.
        """
        # Define an invalid request (but one that is a well-formed message).
        # This particular invalid request not only lacks the mandatory
        # verb+args tuple, it has a single-byte part, which is forbidden.  In
        # fact it has that part twice, to trigger multiple errors.
        invalid_request = (
            protocol.MESSAGE_VERSION_THREE +  # protocol version marker
            '\0\0\0\x02de' + # empty headers
            'oX' + # a single byte part: 'X'.  ConventionalRequestHandler will
                   # error at this part.
            'oX' + # and again.
            'e' # end of message
            )

        to_server = StringIO(invalid_request)
        from_server = StringIO()
        transport = memory.MemoryTransport('memory:///')
        server = medium.SmartServerPipeStreamMedium(
            to_server, from_server, transport)
        proto = server._build_protocol()
        message_handler = proto.message_handler
        server._serve_one_request(proto)
        # All the bytes have been read from the medium...
        self.assertEqual('', to_server.read())
        # ...and the protocol decoder has consumed all the bytes, and has
        # finished reading.
        self.assertEqual('', proto.unused_data)
        self.assertEqual(0, proto.next_read_size())


class InstrumentedRequestHandler(object):
    """Test Double of SmartServerRequestHandler."""

    def __init__(self):
        self.calls = []
        self.finished_reading = False

    def no_body_received(self):
        self.calls.append(('no_body_received',))

    def end_received(self):
        self.calls.append(('end_received',))
        self.finished_reading = True

    def args_received(self, args):
        self.calls.append(('args_received', args))

    def accept_body(self, bytes):
        self.calls.append(('accept_body', bytes))

    def end_of_body(self):
        self.calls.append(('end_of_body',))
        self.finished_reading = True

    def post_body_error_received(self, error_args):
        self.calls.append(('post_body_error_received', error_args))


class StubRequest(object):

    def finished_reading(self):
        pass


class TestClientDecodingProtocolThree(TestSmartProtocol):
    """Tests for v3 of the client-side protocol decoding."""

    def make_logging_response_decoder(self):
        """Make v3 response decoder using a test response handler."""
        response_handler = LoggingMessageHandler()
        decoder = protocol.ProtocolThreeDecoder(response_handler)
        return decoder, response_handler

    def make_conventional_response_decoder(self):
        """Make v3 response decoder using a conventional response handler."""
        response_handler = message.ConventionalResponseHandler()
        decoder = protocol.ProtocolThreeDecoder(response_handler)
        response_handler.setProtoAndMediumRequest(decoder, StubRequest())
        return decoder, response_handler

    def test_trivial_response_decoding(self):
        """Smoke test for the simplest possible v3 response: empty headers,
        status byte, empty args, no body.
        """
        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
        response_status = 'oS' # success
        args = 's\0\0\0\x02le' # length-prefixed, bencoded empty list
        end = 'e' # end marker
        message_bytes = headers + response_status + args + end
        decoder, response_handler = self.make_logging_response_decoder()
        decoder.accept_bytes(message_bytes)
        # The protocol decoder has finished, and consumed all bytes
        self.assertEqual(0, decoder.next_read_size())
        self.assertEqual('', decoder.unused_data)
        # The message handler has been invoked with all the parts of the
        # trivial response: empty headers, status byte, no args, end.
        self.assertEqual(
            [('headers', {}), ('byte', 'S'), ('structure', ()), ('end',)],
            response_handler.event_log)

    def test_incomplete_message(self):
        """A decoder will keep signalling that it needs more bytes via
        next_read_size() != 0 until it has seen a complete message, regardless
        which state it is in.
        """
        # Define a simple response that uses all possible message parts.
        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
        response_status = 'oS' # success
        args = 's\0\0\0\x02le' # length-prefixed, bencoded empty list
        body = 'b\0\0\0\x04BODY' # a body: 'BODY'
        end = 'e' # end marker
        simple_response = headers + response_status + args + body + end
        # Feed the request to the decoder one byte at a time.
        decoder, response_handler = self.make_logging_response_decoder()
        for byte in simple_response:
            self.assertNotEqual(0, decoder.next_read_size())
            decoder.accept_bytes(byte)
        # Now the response is complete
        self.assertEqual(0, decoder.next_read_size())

    def test_read_response_tuple_raises_UnknownSmartMethod(self):
        """read_response_tuple raises UnknownSmartMethod if the server replied
        with 'UnknownMethod'.
        """
        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
        response_status = 'oE' # error flag
        # args: ('UnknownMethod', 'method-name')
        args = 's\0\0\0\x20l13:UnknownMethod11:method-namee'
        end = 'e' # end marker
        message_bytes = headers + response_status + args + end
        decoder, response_handler = self.make_conventional_response_decoder()
        decoder.accept_bytes(message_bytes)
        error = self.assertRaises(
            errors.UnknownSmartMethod, response_handler.read_response_tuple)
        self.assertEqual('method-name', error.verb)

    def test_read_response_tuple_error(self):
        """If the response has an error, it is raised as an exception."""
        headers = '\0\0\0\x02de'  # length-prefixed, bencoded empty dict
        response_status = 'oE' # error
        args = 's\0\0\0\x1al9:first arg10:second arge' # two args
        end = 'e' # end marker
        message_bytes = headers + response_status + args + end
        decoder, response_handler = self.make_conventional_response_decoder()
        decoder.accept_bytes(message_bytes)
        error = self.assertRaises(
            errors.ErrorFromSmartServer, response_handler.read_response_tuple)
        self.assertEqual(('first arg', 'second arg'), error.error_tuple)


class TestClientEncodingProtocolThree(TestSmartProtocol):

    request_encoder = protocol.ProtocolThreeRequester
    response_decoder = protocol.ProtocolThreeDecoder
    server_protocol_class = protocol.ProtocolThreeDecoder

    def make_client_encoder_and_output(self):
        result = self.make_client_protocol_and_output()
        requester, response_handler, output = result
        return requester, output

    def test_call_smoke_test(self):
        """A smoke test for ProtocolThreeRequester.call.

        This test checks that a particular simple invocation of call emits the
        correct bytes for that invocation.
        """
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({'header name': 'header value'})
        requester.call('one arg')
        self.assertEquals(
            'bzr message 3 (bzr 1.6)\n' # protocol version
            '\x00\x00\x00\x1fd11:header name12:header valuee' # headers
            's\x00\x00\x00\x0bl7:one arge' # args
            'e', # end
            output.getvalue())

    def test_call_with_body_bytes_smoke_test(self):
        """A smoke test for ProtocolThreeRequester.call_with_body_bytes.

        This test checks that a particular simple invocation of
        call_with_body_bytes emits the correct bytes for that invocation.
        """
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({'header name': 'header value'})
        requester.call_with_body_bytes(('one arg',), 'body bytes')
        self.assertEquals(
            'bzr message 3 (bzr 1.6)\n' # protocol version
            '\x00\x00\x00\x1fd11:header name12:header valuee' # headers
            's\x00\x00\x00\x0bl7:one arge' # args
            'b' # there is a prefixed body
            '\x00\x00\x00\nbody bytes' # the prefixed body
            'e', # end
            output.getvalue())

    def test_call_writes_just_once(self):
        """A bodyless request is written to the medium all at once."""
        medium_request = StubMediumRequest()
        encoder = protocol.ProtocolThreeRequester(medium_request)
        encoder.call('arg1', 'arg2', 'arg3')
        self.assertEqual(
            ['accept_bytes', 'finished_writing'], medium_request.calls)

    def test_call_with_body_bytes_writes_just_once(self):
        """A request with body bytes is written to the medium all at once."""
        medium_request = StubMediumRequest()
        encoder = protocol.ProtocolThreeRequester(medium_request)
        encoder.call_with_body_bytes(('arg', 'arg'), 'body bytes')
        self.assertEqual(
            ['accept_bytes', 'finished_writing'], medium_request.calls)

    def test_call_with_body_stream_smoke_test(self):
        """A smoke test for ProtocolThreeRequester.call_with_body_stream.

        This test checks that a particular simple invocation of
        call_with_body_stream emits the correct bytes for that invocation.
        """
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({'header name': 'header value'})
        stream = ['chunk 1', 'chunk two']
        requester.call_with_body_stream(('one arg',), stream)
        self.assertEquals(
            'bzr message 3 (bzr 1.6)\n' # protocol version
            '\x00\x00\x00\x1fd11:header name12:header valuee' # headers
            's\x00\x00\x00\x0bl7:one arge' # args
            'b\x00\x00\x00\x07chunk 1' # a prefixed body chunk
            'b\x00\x00\x00\x09chunk two' # a prefixed body chunk
            'e', # end
            output.getvalue())

    def test_call_with_body_stream_empty_stream(self):
        """call_with_body_stream with an empty stream."""
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({})
        stream = []
        requester.call_with_body_stream(('one arg',), stream)
        self.assertEquals(
            'bzr message 3 (bzr 1.6)\n' # protocol version
            '\x00\x00\x00\x02de' # headers
            's\x00\x00\x00\x0bl7:one arge' # args
            # no body chunks
            'e', # end
            output.getvalue())

    def test_call_with_body_stream_error(self):
        """call_with_body_stream will abort the streamed body with an
        error if the stream raises an error during iteration.

        The resulting request will still be a complete message.
        """
        requester, output = self.make_client_encoder_and_output()
        requester.set_headers({})
        def stream_that_fails():
            yield 'aaa'
            yield 'bbb'
            raise Exception('Boom!')
        self.assertRaises(Exception, requester.call_with_body_stream,
            ('one arg',), stream_that_fails())
        self.assertEquals(
            'bzr message 3 (bzr 1.6)\n' # protocol version
            '\x00\x00\x00\x02de' # headers
            's\x00\x00\x00\x0bl7:one arge' # args
            'b\x00\x00\x00\x03aaa' # body
            'b\x00\x00\x00\x03bbb' # more body
            'oE' # error flag
            's\x00\x00\x00\x09l5:errore' # error args: ('error',)
            'e', # end
            output.getvalue())


class StubMediumRequest(object):
    """A stub medium request that tracks the number of times accept_bytes is
    called.
    """

    def __init__(self):
        self.calls = []
        self._medium = 'dummy medium'

    def accept_bytes(self, bytes):
        self.calls.append('accept_bytes')

    def finished_writing(self):
        self.calls.append('finished_writing')


interrupted_body_stream = (
    'oS' # status flag (success)
    's\x00\x00\x00\x08l4:argse' # args struct ('args,')
    'b\x00\x00\x00\x03aaa' # body part ('aaa')
    'b\x00\x00\x00\x03bbb' # body part ('bbb')
    'oE' # status flag (error)
    's\x00\x00\x00\x10l5:error5:Boom!e' # err struct ('error', 'Boom!')
    'e' # EOM
    )


class TestResponseEncodingProtocolThree(tests.TestCase):

    def make_response_encoder(self):
        out_stream = StringIO()
        response_encoder = protocol.ProtocolThreeResponder(out_stream.write)
        return response_encoder, out_stream

    def test_send_error_unknown_method(self):
        encoder, out_stream = self.make_response_encoder()
        encoder.send_error(errors.UnknownSmartMethod('method name'))
        # Use assertEndsWith so that we don't compare the header, which varies
        # by bzrlib.__version__.
        self.assertEndsWith(
            out_stream.getvalue(),
            # error status
            'oE' +
            # tuple: 'UnknownMethod', 'method name'
            's\x00\x00\x00\x20l13:UnknownMethod11:method namee'
            # end of message
            'e')

    def test_send_broken_body_stream(self):
        encoder, out_stream = self.make_response_encoder()
        encoder._headers = {}
        def stream_that_fails():
            yield 'aaa'
            yield 'bbb'
            raise Exception('Boom!')
        response = _mod_request.SuccessfulSmartServerResponse(
            ('args',), body_stream=stream_that_fails())
        encoder.send_response(response)
        expected_response = (
            'bzr message 3 (bzr 1.6)\n'  # protocol marker
            '\x00\x00\x00\x02de' # headers dict (empty)
            + interrupted_body_stream)
        self.assertEqual(expected_response, out_stream.getvalue())


class TestResponseEncoderBufferingProtocolThree(tests.TestCase):
    """Tests for buffering of responses.

    We want to avoid doing many small writes when one would do, to avoid
    unnecessary network overhead.
    """

    def setUp(self):
        tests.TestCase.setUp(self)
        self.writes = []
        self.responder = protocol.ProtocolThreeResponder(self.writes.append)

    def assertWriteCount(self, expected_count):
        self.assertEqual(
            expected_count, len(self.writes),
            "Too many writes: %r" % (self.writes,))

    def test_send_error_writes_just_once(self):
        """An error response is written to the medium all at once."""
        self.responder.send_error(Exception('An exception string.'))
        self.assertWriteCount(1)

    def test_send_response_writes_just_once(self):
        """A normal response with no body is written to the medium all at once.
        """
        response = _mod_request.SuccessfulSmartServerResponse(('arg', 'arg'))
        self.responder.send_response(response)
        self.assertWriteCount(1)

    def test_send_response_with_body_writes_just_once(self):
        """A normal response with a monolithic body is written to the medium
        all at once.
        """
        response = _mod_request.SuccessfulSmartServerResponse(
            ('arg', 'arg'), body='body bytes')
        self.responder.send_response(response)
        self.assertWriteCount(1)

    def test_send_response_with_body_stream_buffers_writes(self):
        """A normal response with a stream body writes to the medium once."""
        # Construct a response with stream with 2 chunks in it.
        response = _mod_request.SuccessfulSmartServerResponse(
            ('arg', 'arg'), body_stream=['chunk1', 'chunk2'])
        self.responder.send_response(response)
        # We will write just once, despite the multiple chunks, due to
        # buffering.
        self.assertWriteCount(1)

    def test_send_response_with_body_stream_flushes_buffers_sometimes(self):
        """When there are many chunks (>100), multiple writes will occur rather
        than buffering indefinitely.
        """
        # Construct a response with stream with 40 chunks in it.  Every chunk
        # triggers 3 buffered writes, so we expect > 100 buffered writes, but <
        # 200.
        body_stream = ['chunk %d' % count for count in range(40)]
        response = _mod_request.SuccessfulSmartServerResponse(
            ('arg', 'arg'), body_stream=body_stream)
        self.responder.send_response(response)
        # The write buffer is flushed every 100 buffered writes, so we expect 2
        # actual writes.
        self.assertWriteCount(2)


class TestSmartClientUnicode(tests.TestCase):
    """_SmartClient tests for unicode arguments.

    Unicode arguments to call_with_body_bytes are not correct (remote method
    names, arguments, and bodies must all be expressed as byte strings), but
    _SmartClient should gracefully reject them, rather than getting into a
    broken state that prevents future correct calls from working.  That is, it
    should be possible to issue more requests on the medium afterwards, rather
    than allowing one bad call to call_with_body_bytes to cause later calls to
    mysteriously fail with TooManyConcurrentRequests.
    """

    def assertCallDoesNotBreakMedium(self, method, args, body):
        """Call a medium with the given method, args and body, then assert that
        the medium is left in a sane state, i.e. is capable of allowing further
        requests.
        """
        input = StringIO("\n")
        output = StringIO()
        client_medium = medium.SmartSimplePipesClientMedium(
            input, output, 'ignored base')
        smart_client = client._SmartClient(client_medium)
        self.assertRaises(TypeError,
            smart_client.call_with_body_bytes, method, args, body)
        self.assertEqual("", output.getvalue())
        self.assertEqual(None, client_medium._current_request)

    def test_call_with_body_bytes_unicode_method(self):
        self.assertCallDoesNotBreakMedium(u'method', ('args',), 'body')

    def test_call_with_body_bytes_unicode_args(self):
        self.assertCallDoesNotBreakMedium('method', (u'args',), 'body')
        self.assertCallDoesNotBreakMedium('method', ('arg1', u'arg2'), 'body')

    def test_call_with_body_bytes_unicode_body(self):
        self.assertCallDoesNotBreakMedium('method', ('args',), u'body')


class MockMedium(medium.SmartClientMedium):
    """A mock medium that can be used to test _SmartClient.

    It can be given a series of requests to expect (and responses it should
    return for them).  It can also be told when the client is expected to
    disconnect a medium.  Expectations must be satisfied in the order they are
    given, or else an AssertionError will be raised.

    Typical use looks like::

        medium = MockMedium()
        medium.expect_request(...)
        medium.expect_request(...)
        medium.expect_request(...)
    """

    def __init__(self):
        super(MockMedium, self).__init__('dummy base')
        self._mock_request = _MockMediumRequest(self)
        self._expected_events = []

    def expect_request(self, request_bytes, response_bytes,
                       allow_partial_read=False):
        """Expect 'request_bytes' to be sent, and reply with 'response_bytes'.

        No assumption is made about how many times accept_bytes should be
        called to send the request.  Similarly, no assumption is made about how
        many times read_bytes/read_line are called by protocol code to read a
        response.  e.g.::

            request.accept_bytes('ab')
            request.accept_bytes('cd')
            request.finished_writing()

        and::

            request.accept_bytes('abcd')
            request.finished_writing()

        Will both satisfy ``medium.expect_request('abcd', ...)``.  Thus tests
        using this should not break due to irrelevant changes in protocol
        implementations.

        :param allow_partial_read: if True, no assertion is raised if a
            response is not fully read.  Setting this is useful when the client
            is expected to disconnect without needing to read the complete
            response.  Default is False.
        """
        self._expected_events.append(('send request', request_bytes))
        if allow_partial_read:
            self._expected_events.append(
                ('read response (partial)', response_bytes))
        else:
            self._expected_events.append(('read response', response_bytes))

    def expect_disconnect(self):
        """Expect the client to call ``medium.disconnect()``."""
        self._expected_events.append('disconnect')

    def _assertEvent(self, observed_event):
        """Raise AssertionError unless observed_event matches the next expected
        event.

        :seealso: expect_request
        :seealso: expect_disconnect
        """
        try:
            expected_event = self._expected_events.pop(0)
        except IndexError:
            raise AssertionError(
                'Mock medium observed event %r, but no more events expected'
                % (observed_event,))
        if expected_event[0] == 'read response (partial)':
            if observed_event[0] != 'read response':
                raise AssertionError(
                    'Mock medium observed event %r, but expected event %r'
                    % (observed_event, expected_event))
        elif observed_event != expected_event:
            raise AssertionError(
                'Mock medium observed event %r, but expected event %r'
                % (observed_event, expected_event))
        if self._expected_events:
            next_event = self._expected_events[0]
            if next_event[0].startswith('read response'):
                self._mock_request._response = next_event[1]

    def get_request(self):
        return self._mock_request

    def disconnect(self):
        if self._mock_request._read_bytes:
            self._assertEvent(('read response', self._mock_request._read_bytes))
            self._mock_request._read_bytes = ''
        self._assertEvent('disconnect')


class _MockMediumRequest(object):
    """A mock ClientMediumRequest used by MockMedium."""

    def __init__(self, mock_medium):
        self._medium = mock_medium
        self._written_bytes = ''
        self._read_bytes = ''
        self._response = None

    def accept_bytes(self, bytes):
        self._written_bytes += bytes

    def finished_writing(self):
        self._medium._assertEvent(('send request', self._written_bytes))
        self._written_bytes = ''

    def finished_reading(self):
        self._medium._assertEvent(('read response', self._read_bytes))
        self._read_bytes = ''

    def read_bytes(self, size):
        resp = self._response
        bytes, resp = resp[:size], resp[size:]
        self._response = resp
        self._read_bytes += bytes
        return bytes

    def read_line(self):
        resp = self._response
        try:
            line, resp = resp.split('\n', 1)
            line += '\n'
        except ValueError:
            line, resp = resp, ''
        self._response = resp
        self._read_bytes += line
        return line


class Test_SmartClientVersionDetection(tests.TestCase):
    """Tests for _SmartClient's automatic protocol version detection.

    On the first remote call, _SmartClient will keep retrying the request with
    different protocol versions until it finds one that works.
    """

    def test_version_three_server(self):
        """With a protocol 3 server, only one request is needed."""
        medium = MockMedium()
        smart_client = client._SmartClient(medium, headers={})
        message_start = protocol.MESSAGE_VERSION_THREE + '\x00\x00\x00\x02de'
        medium.expect_request(
            message_start +
            's\x00\x00\x00\x1el11:method-name5:arg 15:arg 2ee',
            message_start + 's\0\0\0\x13l14:response valueee')
        result = smart_client.call('method-name', 'arg 1', 'arg 2')
        # The call succeeded without raising any exceptions from the mock
        # medium, and the smart_client returns the response from the server.
        self.assertEqual(('response value',), result)
        self.assertEqual([], medium._expected_events)
        # Also, the v3 works then the server should be assumed to support RPCs
        # introduced in 1.6.
        self.assertFalse(medium._is_remote_before((1, 6)))

    def test_version_two_server(self):
        """If the server only speaks protocol 2, the client will first try
        version 3, then fallback to protocol 2.

        Further, _SmartClient caches the detection, so future requests will all
        use protocol 2 immediately.
        """
        medium = MockMedium()
        smart_client = client._SmartClient(medium, headers={})
        # First the client should send a v3 request, but the server will reply
        # with a v2 error.
        medium.expect_request(
            'bzr message 3 (bzr 1.6)\n\x00\x00\x00\x02de' +
            's\x00\x00\x00\x1el11:method-name5:arg 15:arg 2ee',
            'bzr response 2\nfailed\n\n')
        # So then the client should disconnect to reset the connection, because
        # the client needs to assume the server cannot read any further
        # requests off the original connection.
        medium.expect_disconnect()
        # The client should then retry the original request in v2
        medium.expect_request(
            'bzr request 2\nmethod-name\x01arg 1\x01arg 2\n',
            'bzr response 2\nsuccess\nresponse value\n')
        result = smart_client.call('method-name', 'arg 1', 'arg 2')
        # The smart_client object will return the result of the successful
        # query.
        self.assertEqual(('response value',), result)

        # Now try another request, and this time the client will just use
        # protocol 2.  (i.e. the autodetection won't be repeated)
        medium.expect_request(
            'bzr request 2\nanother-method\n',
            'bzr response 2\nsuccess\nanother response\n')
        result = smart_client.call('another-method')
        self.assertEqual(('another response',), result)
        self.assertEqual([], medium._expected_events)

        # Also, because v3 is not supported, the client medium should assume
        # that RPCs introduced in 1.6 aren't supported either.
        self.assertTrue(medium._is_remote_before((1, 6)))

    def test_unknown_version(self):
        """If the server does not use any known (or at least supported)
        protocol version, a SmartProtocolError is raised.
        """
        medium = MockMedium()
        smart_client = client._SmartClient(medium, headers={})
        unknown_protocol_bytes = 'Unknown protocol!'
        # The client will try v3 and v2 before eventually giving up.
        medium.expect_request(
            'bzr message 3 (bzr 1.6)\n\x00\x00\x00\x02de' +
            's\x00\x00\x00\x1el11:method-name5:arg 15:arg 2ee',
            unknown_protocol_bytes)
        medium.expect_disconnect()
        medium.expect_request(
            'bzr request 2\nmethod-name\x01arg 1\x01arg 2\n',
            unknown_protocol_bytes)
        medium.expect_disconnect()
        self.assertRaises(
            errors.SmartProtocolError,
            smart_client.call, 'method-name', 'arg 1', 'arg 2')
        self.assertEqual([], medium._expected_events)

    def test_first_response_is_error(self):
        """If the server replies with an error, then the version detection
        should be complete.

        This test is very similar to test_version_two_server, but catches a bug
        we had in the case where the first reply was an error response.
        """
        medium = MockMedium()
        smart_client = client._SmartClient(medium, headers={})
        message_start = protocol.MESSAGE_VERSION_THREE + '\x00\x00\x00\x02de'
        # Issue a request that gets an error reply in a non-default protocol
        # version.
        medium.expect_request(
            message_start +
            's\x00\x00\x00\x10l11:method-nameee',
            'bzr response 2\nfailed\n\n')
        medium.expect_disconnect()
        medium.expect_request(
            'bzr request 2\nmethod-name\n',
            'bzr response 2\nfailed\nFooBarError\n')
        err = self.assertRaises(
            errors.ErrorFromSmartServer,
            smart_client.call, 'method-name')
        self.assertEqual(('FooBarError',), err.error_tuple)
        # Now the medium should have remembered the protocol version, so
        # subsequent requests will use the remembered version immediately.
        medium.expect_request(
            'bzr request 2\nmethod-name\n',
            'bzr response 2\nsuccess\nresponse value\n')
        result = smart_client.call('method-name')
        self.assertEqual(('response value',), result)
        self.assertEqual([], medium._expected_events)


class Test_SmartClient(tests.TestCase):

    def test_call_default_headers(self):
        """ProtocolThreeRequester.call by default sends a 'Software
        version' header.
        """
        smart_client = client._SmartClient('dummy medium')
        self.assertEqual(
            bzrlib.__version__, smart_client._headers['Software version'])
        # XXX: need a test that smart_client._headers is passed to the request
        # encoder.


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


class TestChunkedBodyDecoder(tests.TestCase):
    """Tests for ChunkedBodyDecoder.

    This is the body decoder used for protocol version two.
    """

    def test_construct(self):
        decoder = protocol.ChunkedBodyDecoder()
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(8, decoder.next_read_size())
        self.assertEqual(None, decoder.read_next_chunk())
        self.assertEqual('', decoder.unused_data)

    def test_empty_content(self):
        """'chunked\nEND\n' is the complete encoding of a zero-length body.
        """
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        decoder.accept_bytes('END\n')
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(None, decoder.read_next_chunk())
        self.assertEqual('', decoder.unused_data)

    def test_one_chunk(self):
        """A body in a single chunk is decoded correctly."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_length = 'f\n'
        chunk_content = '123456789abcdef'
        finish = 'END\n'
        decoder.accept_bytes(chunk_length + chunk_content + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(chunk_content, decoder.read_next_chunk())
        self.assertEqual('', decoder.unused_data)

    def test_incomplete_chunk(self):
        """When there are less bytes in the chunk than declared by the length,
        then we haven't finished reading yet.
        """
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_length = '8\n'
        three_bytes = '123'
        decoder.accept_bytes(chunk_length + three_bytes)
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(
            5 + 4, decoder.next_read_size(),
            "The next_read_size hint should be the number of missing bytes in "
            "this chunk plus 4 (the length of the end-of-body marker: "
            "'END\\n')")
        self.assertEqual(None, decoder.read_next_chunk())

    def test_incomplete_length(self):
        """A chunk length hasn't been read until a newline byte has been read.
        """
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        decoder.accept_bytes('9')
        self.assertEqual(
            1, decoder.next_read_size(),
            "The next_read_size hint should be 1, because we don't know the "
            "length yet.")
        decoder.accept_bytes('\n')
        self.assertEqual(
            9 + 4, decoder.next_read_size(),
            "The next_read_size hint should be the length of the chunk plus 4 "
            "(the length of the end-of-body marker: 'END\\n')")
        self.assertFalse(decoder.finished_reading)
        self.assertEqual(None, decoder.read_next_chunk())

    def test_two_chunks(self):
        """Content from multiple chunks is concatenated."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_one = '3\naaa'
        chunk_two = '5\nbbbbb'
        finish = 'END\n'
        decoder.accept_bytes(chunk_one + chunk_two + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual('aaa', decoder.read_next_chunk())
        self.assertEqual('bbbbb', decoder.read_next_chunk())
        self.assertEqual(None, decoder.read_next_chunk())
        self.assertEqual('', decoder.unused_data)

    def test_excess_bytes(self):
        """Bytes after the chunked body are reported as unused bytes."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunked_body = "5\naaaaaEND\n"
        excess_bytes = "excess bytes"
        decoder.accept_bytes(chunked_body + excess_bytes)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual('aaaaa', decoder.read_next_chunk())
        self.assertEqual(excess_bytes, decoder.unused_data)
        self.assertEqual(
            1, decoder.next_read_size(),
            "next_read_size hint should be 1 when finished_reading.")

    def test_multidigit_length(self):
        """Lengths in the chunk prefixes can have multiple digits."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        length = 0x123
        chunk_prefix = hex(length) + '\n'
        chunk_bytes = 'z' * length
        finish = 'END\n'
        decoder.accept_bytes(chunk_prefix + chunk_bytes + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(chunk_bytes, decoder.read_next_chunk())

    def test_byte_at_a_time(self):
        """A complete body fed to the decoder one byte at a time should not
        confuse the decoder.  That is, it should give the same result as if the
        bytes had been received in one batch.

        This test is the same as test_one_chunk apart from the way accept_bytes
        is called.
        """
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_length = 'f\n'
        chunk_content = '123456789abcdef'
        finish = 'END\n'
        for byte in (chunk_length + chunk_content + finish):
            decoder.accept_bytes(byte)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual(chunk_content, decoder.read_next_chunk())
        self.assertEqual('', decoder.unused_data)

    def test_read_pending_data_resets(self):
        """read_pending_data does not return the same bytes twice."""
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_one = '3\naaa'
        chunk_two = '3\nbbb'
        finish = 'END\n'
        decoder.accept_bytes(chunk_one)
        self.assertEqual('aaa', decoder.read_next_chunk())
        decoder.accept_bytes(chunk_two)
        self.assertEqual('bbb', decoder.read_next_chunk())
        self.assertEqual(None, decoder.read_next_chunk())

    def test_decode_error(self):
        decoder = protocol.ChunkedBodyDecoder()
        decoder.accept_bytes('chunked\n')
        chunk_one = 'b\nfirst chunk'
        error_signal = 'ERR\n'
        error_chunks = '5\npart1' + '5\npart2'
        finish = 'END\n'
        decoder.accept_bytes(chunk_one + error_signal + error_chunks + finish)
        self.assertTrue(decoder.finished_reading)
        self.assertEqual('first chunk', decoder.read_next_chunk())
        expected_failure = _mod_request.FailedSmartServerResponse(
            ('part1', 'part2'))
        self.assertEqual(expected_failure, decoder.read_next_chunk())

    def test_bad_header(self):
        """accept_bytes raises a SmartProtocolError if a chunked body does not
        start with the right header.
        """
        decoder = protocol.ChunkedBodyDecoder()
        self.assertRaises(
            errors.SmartProtocolError, decoder.accept_bytes, 'bad header\n')


class TestSuccessfulSmartServerResponse(tests.TestCase):

    def test_construct_no_body(self):
        response = _mod_request.SuccessfulSmartServerResponse(('foo', 'bar'))
        self.assertEqual(('foo', 'bar'), response.args)
        self.assertEqual(None, response.body)

    def test_construct_with_body(self):
        response = _mod_request.SuccessfulSmartServerResponse(('foo', 'bar'),
                                                              'bytes')
        self.assertEqual(('foo', 'bar'), response.args)
        self.assertEqual('bytes', response.body)
        # repr(response) doesn't trigger exceptions.
        repr(response)

    def test_construct_with_body_stream(self):
        bytes_iterable = ['abc']
        response = _mod_request.SuccessfulSmartServerResponse(
            ('foo', 'bar'), body_stream=bytes_iterable)
        self.assertEqual(('foo', 'bar'), response.args)
        self.assertEqual(bytes_iterable, response.body_stream)

    def test_construct_rejects_body_and_body_stream(self):
        """'body' and 'body_stream' are mutually exclusive."""
        self.assertRaises(
            errors.BzrError,
            _mod_request.SuccessfulSmartServerResponse, (), 'body', ['stream'])

    def test_is_successful(self):
        """is_successful should return True for SuccessfulSmartServerResponse."""
        response = _mod_request.SuccessfulSmartServerResponse(('error',))
        self.assertEqual(True, response.is_successful())


class TestFailedSmartServerResponse(tests.TestCase):

    def test_construct(self):
        response = _mod_request.FailedSmartServerResponse(('foo', 'bar'))
        self.assertEqual(('foo', 'bar'), response.args)
        self.assertEqual(None, response.body)
        response = _mod_request.FailedSmartServerResponse(('foo', 'bar'), 'bytes')
        self.assertEqual(('foo', 'bar'), response.args)
        self.assertEqual('bytes', response.body)
        # repr(response) doesn't trigger exceptions.
        repr(response)

    def test_is_successful(self):
        """is_successful should return False for FailedSmartServerResponse."""
        response = _mod_request.FailedSmartServerResponse(('error',))
        self.assertEqual(False, response.is_successful())


class FakeHTTPMedium(object):
    def __init__(self):
        self.written_request = None
        self._current_request = None
    def send_http_smart_request(self, bytes):
        self.written_request = bytes
        return None


class HTTPTunnellingSmokeTest(tests.TestCase):

    def setUp(self):
        super(HTTPTunnellingSmokeTest, self).setUp()
        # We use the VFS layer as part of HTTP tunnelling tests.
        self._captureVar('BZR_NO_SMART_VFS', None)

    def test_smart_http_medium_request_accept_bytes(self):
        medium = FakeHTTPMedium()
        request = SmartClientHTTPMediumRequest(medium)
        request.accept_bytes('abc')
        request.accept_bytes('def')
        self.assertEqual(None, medium.written_request)
        request.finished_writing()
        self.assertEqual('abcdef', medium.written_request)


class RemoteHTTPTransportTestCase(tests.TestCase):

    def test_remote_path_after_clone_child(self):
        # If a user enters "bzr+http://host/foo", we want to sent all smart
        # requests for child URLs of that to the original URL.  i.e., we want to
        # POST to "bzr+http://host/foo/.bzr/smart" and never something like
        # "bzr+http://host/foo/.bzr/branch/.bzr/smart".  So, a cloned
        # RemoteHTTPTransport remembers the initial URL, and adjusts the
        # relpaths it sends in smart requests accordingly.
        base_transport = remote.RemoteHTTPTransport('bzr+http://host/path')
        new_transport = base_transport.clone('child_dir')
        self.assertEqual(base_transport._http_transport,
                         new_transport._http_transport)
        self.assertEqual('child_dir/foo', new_transport._remote_path('foo'))
        self.assertEqual(
            'child_dir/',
            new_transport._client.remote_path_from_transport(new_transport))

    def test_remote_path_unnormal_base(self):
        # If the transport's base isn't normalised, the _remote_path should
        # still be calculated correctly.
        base_transport = remote.RemoteHTTPTransport('bzr+http://host/%7Ea/b')
        self.assertEqual('c', base_transport._remote_path('c'))

    def test_clone_unnormal_base(self):
        # If the transport's base isn't normalised, cloned transports should
        # still work correctly.
        base_transport = remote.RemoteHTTPTransport('bzr+http://host/%7Ea/b')
        new_transport = base_transport.clone('c')
        self.assertEqual('bzr+http://host/~a/b/c/', new_transport.base)
        self.assertEqual(
            'c/',
            new_transport._client.remote_path_from_transport(new_transport))

    def test__redirect_to(self):
        t = remote.RemoteHTTPTransport('bzr+http://www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'http://www.example.com/bar')
        self.assertEquals(type(r), type(t))

    def test__redirect_sibling_protocol(self):
        t = remote.RemoteHTTPTransport('bzr+http://www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'https://www.example.com/bar')
        self.assertEquals(type(r), type(t))
        self.assertStartsWith(r.base, 'bzr+https')

    def test__redirect_to_with_user(self):
        t = remote.RemoteHTTPTransport('bzr+http://joe@www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'http://www.example.com/bar')
        self.assertEquals(type(r), type(t))
        self.assertEquals('joe', t._user)
        self.assertEquals(t._user, r._user)

    def test_redirected_to_same_host_different_protocol(self):
        t = remote.RemoteHTTPTransport('bzr+http://joe@www.example.com/foo')
        r = t._redirected_to('http://www.example.com/foo',
                             'ftp://www.example.com/foo')
        self.assertNotEquals(type(r), type(t))


