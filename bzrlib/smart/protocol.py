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

"""Wire-level encoding and decoding of requests and responses for the smart
client and server.
"""

from cStringIO import StringIO
import time

from bzrlib import debug
from bzrlib import errors
from bzrlib.smart import request
from bzrlib.trace import log_exception_quietly, mutter


# Protocol version strings.  These are sent as prefixes of bzr requests and
# responses to identify the protocol version being used. (There are no version
# one strings because that version doesn't send any).
REQUEST_VERSION_TWO = 'bzr request 2\n'
RESPONSE_VERSION_TWO = 'bzr response 2\n'


def _recv_tuple(from_file):
    req_line = from_file.readline()
    return _decode_tuple(req_line)


def _decode_tuple(req_line):
    if req_line == None or req_line == '':
        return None
    if req_line[-1] != '\n':
        raise errors.SmartProtocolError("request %r not terminated" % req_line)
    return tuple(req_line[:-1].split('\x01'))


def _encode_tuple(args):
    """Encode the tuple args to a bytestream."""
    return '\x01'.join(args) + '\n'


class SmartProtocolBase(object):
    """Methods common to client and server"""

    # TODO: this only actually accomodates a single block; possibly should
    # support multiple chunks?
    def _encode_bulk_data(self, body):
        """Encode body as a bulk data chunk."""
        return ''.join(('%d\n' % len(body), body, 'done\n'))

    def _serialise_offsets(self, offsets):
        """Serialise a readv offset list."""
        txt = []
        for start, length in offsets:
            txt.append('%d,%d' % (start, length))
        return '\n'.join(txt)
        

class SmartServerRequestProtocolOne(SmartProtocolBase):
    """Server-side encoding and decoding logic for smart version 1."""
    
    def __init__(self, backing_transport, write_func):
        self._backing_transport = backing_transport
        self.excess_buffer = ''
        self._finished = False
        self.in_buffer = ''
        self.has_dispatched = False
        self.request = None
        self._body_decoder = None
        self._write_func = write_func

    def accept_bytes(self, bytes):
        """Take bytes, and advance the internal state machine appropriately.
        
        :param bytes: must be a byte string
        """
        assert isinstance(bytes, str)
        self.in_buffer += bytes
        if not self.has_dispatched:
            if '\n' not in self.in_buffer:
                # no command line yet
                return
            self.has_dispatched = True
            try:
                first_line, self.in_buffer = self.in_buffer.split('\n', 1)
                first_line += '\n'
                req_args = _decode_tuple(first_line)
                self.request = request.SmartServerRequestHandler(
                    self._backing_transport, commands=request.request_handlers)
                self.request.dispatch_command(req_args[0], req_args[1:])
                if self.request.finished_reading:
                    # trivial request
                    self.excess_buffer = self.in_buffer
                    self.in_buffer = ''
                    self._send_response(self.request.response)
            except KeyboardInterrupt:
                raise
            except Exception, exception:
                # everything else: pass to client, flush, and quit
                log_exception_quietly()
                self._send_response(request.FailedSmartServerResponse(
                    ('error', str(exception))))
                return

        if self.has_dispatched:
            if self._finished:
                # nothing to do.XXX: this routine should be a single state 
                # machine too.
                self.excess_buffer += self.in_buffer
                self.in_buffer = ''
                return
            if self._body_decoder is None:
                self._body_decoder = LengthPrefixedBodyDecoder()
            self._body_decoder.accept_bytes(self.in_buffer)
            self.in_buffer = self._body_decoder.unused_data
            body_data = self._body_decoder.read_pending_data()
            self.request.accept_body(body_data)
            if self._body_decoder.finished_reading:
                self.request.end_of_body()
                assert self.request.finished_reading, \
                    "no more body, request not finished"
            if self.request.response is not None:
                self._send_response(self.request.response)
                self.excess_buffer = self.in_buffer
                self.in_buffer = ''
            else:
                assert not self.request.finished_reading, \
                    "no response and we have finished reading."

    def _send_response(self, response):
        """Send a smart server response down the output stream."""
        assert not self._finished, 'response already sent'
        args = response.args
        body = response.body
        self._finished = True
        self._write_protocol_version()
        self._write_success_or_failure_prefix(response)
        self._write_func(_encode_tuple(args))
        if body is not None:
            assert isinstance(body, str), 'body must be a str'
            bytes = self._encode_bulk_data(body)
            self._write_func(bytes)

    def _write_protocol_version(self):
        """Write any prefixes this protocol requires.
        
        Version one doesn't send protocol versions.
        """

    def _write_success_or_failure_prefix(self, response):
        """Write the protocol specific success/failure prefix.

        For SmartServerRequestProtocolOne this is omitted but we
        call is_successful to ensure that the response is valid.
        """
        response.is_successful()

    def next_read_size(self):
        if self._finished:
            return 0
        if self._body_decoder is None:
            return 1
        else:
            return self._body_decoder.next_read_size()


class SmartServerRequestProtocolTwo(SmartServerRequestProtocolOne):
    r"""Version two of the server side of the smart protocol.
   
    This prefixes responses with the value of RESPONSE_VERSION_TWO.
    """

    def _write_success_or_failure_prefix(self, response):
        """Write the protocol specific success/failure prefix."""
        if response.is_successful():
            self._write_func('success\n')
        else:
            self._write_func('failed\n')

    def _write_protocol_version(self):
        r"""Write any prefixes this protocol requires.
        
        Version two sends the value of RESPONSE_VERSION_TWO.
        """
        self._write_func(RESPONSE_VERSION_TWO)


class LengthPrefixedBodyDecoder(object):
    """Decodes the length-prefixed bulk data."""
    
    def __init__(self):
        self.bytes_left = None
        self.finished_reading = False
        self.unused_data = ''
        self.state_accept = self._state_accept_expecting_length
        self.state_read = self._state_read_no_data
        self._in_buffer = ''
        self._trailer_buffer = ''
    
    def accept_bytes(self, bytes):
        """Decode as much of bytes as possible.

        If 'bytes' contains too much data it will be appended to
        self.unused_data.

        finished_reading will be set when no more data is required.  Further
        data will be appended to self.unused_data.
        """
        # accept_bytes is allowed to change the state
        current_state = self.state_accept
        self.state_accept(bytes)
        while current_state != self.state_accept:
            current_state = self.state_accept
            self.state_accept('')

    def next_read_size(self):
        if self.bytes_left is not None:
            # Ideally we want to read all the remainder of the body and the
            # trailer in one go.
            return self.bytes_left + 5
        elif self.state_accept == self._state_accept_reading_trailer:
            # Just the trailer left
            return 5 - len(self._trailer_buffer)
        elif self.state_accept == self._state_accept_expecting_length:
            # There's still at least 6 bytes left ('\n' to end the length, plus
            # 'done\n').
            return 6
        else:
            # Reading excess data.  Either way, 1 byte at a time is fine.
            return 1
        
    def read_pending_data(self):
        """Return any pending data that has been decoded."""
        return self.state_read()

    def _state_accept_expecting_length(self, bytes):
        self._in_buffer += bytes
        pos = self._in_buffer.find('\n')
        if pos == -1:
            return
        self.bytes_left = int(self._in_buffer[:pos])
        self._in_buffer = self._in_buffer[pos+1:]
        self.bytes_left -= len(self._in_buffer)
        self.state_accept = self._state_accept_reading_body
        self.state_read = self._state_read_in_buffer

    def _state_accept_reading_body(self, bytes):
        self._in_buffer += bytes
        self.bytes_left -= len(bytes)
        if self.bytes_left <= 0:
            # Finished with body
            if self.bytes_left != 0:
                self._trailer_buffer = self._in_buffer[self.bytes_left:]
                self._in_buffer = self._in_buffer[:self.bytes_left]
            self.bytes_left = None
            self.state_accept = self._state_accept_reading_trailer
        
    def _state_accept_reading_trailer(self, bytes):
        self._trailer_buffer += bytes
        # TODO: what if the trailer does not match "done\n"?  Should this raise
        # a ProtocolViolation exception?
        if self._trailer_buffer.startswith('done\n'):
            self.unused_data = self._trailer_buffer[len('done\n'):]
            self.state_accept = self._state_accept_reading_unused
            self.finished_reading = True
    
    def _state_accept_reading_unused(self, bytes):
        self.unused_data += bytes

    def _state_read_no_data(self):
        return ''

    def _state_read_in_buffer(self):
        result = self._in_buffer
        self._in_buffer = ''
        return result


class SmartClientRequestProtocolOne(SmartProtocolBase):
    """The client-side protocol for smart version 1."""

    def __init__(self, request):
        """Construct a SmartClientRequestProtocolOne.

        :param request: A SmartClientMediumRequest to serialise onto and
            deserialise from.
        """
        self._request = request
        self._body_buffer = None
        self._request_start_time = None

    def call(self, *args):
        if 'hpss' in debug.debug_flags:
            mutter('hpss call:   %s', repr(args)[1:-1])
            self._request_start_time = time.time()
        self._write_args(args)
        self._request.finished_writing()

    def call_with_body_bytes(self, args, body):
        """Make a remote call of args with body bytes 'body'.

        After calling this, call read_response_tuple to find the result out.
        """
        if 'hpss' in debug.debug_flags:
            mutter('hpss call w/body: %s (%r...)', repr(args)[1:-1], body[:20])
            mutter('              %d bytes', len(body))
            self._request_start_time = time.time()
        self._write_args(args)
        bytes = self._encode_bulk_data(body)
        self._request.accept_bytes(bytes)
        self._request.finished_writing()

    def call_with_body_readv_array(self, args, body):
        """Make a remote call with a readv array.

        The body is encoded with one line per readv offset pair. The numbers in
        each pair are separated by a comma, and no trailing \n is emitted.
        """
        if 'hpss' in debug.debug_flags:
            mutter('hpss call w/readv: %s', repr(args)[1:-1])
            self._request_start_time = time.time()
        self._write_args(args)
        readv_bytes = self._serialise_offsets(body)
        bytes = self._encode_bulk_data(readv_bytes)
        self._request.accept_bytes(bytes)
        self._request.finished_writing()
        if 'hpss' in debug.debug_flags:
            mutter('              %d bytes in readv request', len(readv_bytes))

    def cancel_read_body(self):
        """After expecting a body, a response code may indicate one otherwise.

        This method lets the domain client inform the protocol that no body
        will be transmitted. This is a terminal method: after calling it the
        protocol is not able to be used further.
        """
        self._request.finished_reading()

    def read_response_tuple(self, expect_body=False):
        """Read a response tuple from the wire.

        This should only be called once.
        """
        result = self._recv_tuple()
        if 'hpss' in debug.debug_flags:
            if self._request_start_time is not None:
                mutter('   result:   %6.3fs  %s',
                       time.time() - self._request_start_time,
                       repr(result)[1:-1])
                self._request_start_time = None
            else:
                mutter('   result:   %s', repr(result)[1:-1])
        if not expect_body:
            self._request.finished_reading()
        return result

    def read_body_bytes(self, count=-1):
        """Read bytes from the body, decoding into a byte stream.
        
        We read all bytes at once to ensure we've checked the trailer for 
        errors, and then feed the buffer back as read_body_bytes is called.
        """
        if self._body_buffer is not None:
            return self._body_buffer.read(count)
        _body_decoder = LengthPrefixedBodyDecoder()

        while not _body_decoder.finished_reading:
            bytes_wanted = _body_decoder.next_read_size()
            bytes = self._request.read_bytes(bytes_wanted)
            _body_decoder.accept_bytes(bytes)
        self._request.finished_reading()
        self._body_buffer = StringIO(_body_decoder.read_pending_data())
        # XXX: TODO check the trailer result.
        if 'hpss' in debug.debug_flags:
            mutter('              %d body bytes read',
                   len(self._body_buffer.getvalue()))
        return self._body_buffer.read(count)

    def _recv_tuple(self):
        """Receive a tuple from the medium request."""
        return _decode_tuple(self._recv_line())

    def _recv_line(self):
        """Read an entire line from the medium request."""
        line = ''
        while not line or line[-1] != '\n':
            # TODO: this is inefficient - but tuples are short.
            new_char = self._request.read_bytes(1)
            if new_char == '':
                # end of file encountered reading from server
                raise errors.ConnectionReset(
                    "please check connectivity and permissions",
                    "(and try -Dhpss if further diagnosis is required)")
            line += new_char
        return line

    def query_version(self):
        """Return protocol version number of the server."""
        self.call('hello')
        resp = self.read_response_tuple()
        if resp == ('ok', '1'):
            return 1
        elif resp == ('ok', '2'):
            return 2
        else:
            raise errors.SmartProtocolError("bad response %r" % (resp,))

    def _write_args(self, args):
        self._write_protocol_version()
        bytes = _encode_tuple(args)
        self._request.accept_bytes(bytes)

    def _write_protocol_version(self):
        """Write any prefixes this protocol requires.
        
        Version one doesn't send protocol versions.
        """


class SmartClientRequestProtocolTwo(SmartClientRequestProtocolOne):
    """Version two of the client side of the smart protocol.
    
    This prefixes the request with the value of REQUEST_VERSION_TWO.
    """

    def read_response_tuple(self, expect_body=False):
        """Read a response tuple from the wire.

        This should only be called once.
        """
        version = self._request.read_line()
        if version != RESPONSE_VERSION_TWO:
            raise errors.SmartProtocolError('bad protocol marker %r' % version)
        response_status = self._recv_line()
        if response_status not in ('success\n', 'failed\n'):
            raise errors.SmartProtocolError(
                'bad protocol status %r' % response_status)
        self.response_status = response_status == 'success\n'
        return SmartClientRequestProtocolOne.read_response_tuple(self, expect_body)

    def _write_protocol_version(self):
        r"""Write any prefixes this protocol requires.
        
        Version two sends the value of REQUEST_VERSION_TWO.
        """
        self._request.accept_bytes(REQUEST_VERSION_TWO)

