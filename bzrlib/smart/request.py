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

"""Basic server-side logic for dealing with requests."""


import tempfile

from bzrlib import (
    bzrdir,
    errors,
    registry,
    revision,
    )
from bzrlib.bundle.serializer import write_bundle


class SmartServerRequest(object):
    """Base class for request handlers."""

    def __init__(self, backing_transport):
        """Constructor.

        :param backing_transport: the base transport to be used when performing
            this request.
        """
        self._backing_transport = backing_transport

    def _check_enabled(self):
        """Raises DisabledMethod if this method is disabled."""
        pass

    def do(self, *args):
        """Mandatory extension point for SmartServerRequest subclasses.
        
        Subclasses must implement this.
        
        This should return a SmartServerResponse if this command expects to
        receive no body.
        """
        raise NotImplementedError(self.do)

    def execute(self, *args):
        """Public entry point to execute this request.

        It will return a SmartServerResponse if the command does not expect a
        body.

        :param *args: the arguments of the request.
        """
        self._check_enabled()
        return self.do(*args)

    def do_body(self, body_bytes):
        """Called if the client sends a body with the request.
        
        Must return a SmartServerResponse.
        """
        # TODO: if a client erroneously sends a request that shouldn't have a
        # body, what to do?  Probably SmartServerRequestHandler should catch
        # this NotImplementedError and translate it into a 'bad request' error
        # to send to the client.
        raise NotImplementedError(self.do_body)


class SmartServerResponse(object):
    """Response generated by SmartServerRequestHandler."""

    def __init__(self, args, body=None):
        self.args = args
        self.body = body

    def __eq__(self, other):
        if other is None:
            return False
        return other.args == self.args and other.body == self.body

    def __repr__(self):
        return "<SmartServerResponse args=%r body=%r>" % (self.args, self.body)


class SuccessfulSmartServerResponse(SmartServerResponse):
    """A SmartServerResponse for a successfully completed request."""

    def is_successful(self):
        """SuccessfulSmartServerResponse are successful."""
        return True


class SmartServerRequestHandler(object):
    """Protocol logic for smart server.
    
    This doesn't handle serialization at all, it just processes requests and
    creates responses.
    """

    # IMPORTANT FOR IMPLEMENTORS: It is important that SmartServerRequestHandler
    # not contain encoding or decoding logic to allow the wire protocol to vary
    # from the object protocol: we will want to tweak the wire protocol separate
    # from the object model, and ideally we will be able to do that without
    # having a SmartServerRequestHandler subclass for each wire protocol, rather
    # just a Protocol subclass.

    # TODO: Better way of representing the body for commands that take it,
    # and allow it to be streamed into the server.

    def __init__(self, backing_transport, commands):
        """Constructor.

        :param backing_transport: a Transport to handle requests for.
        :param commands: a registry mapping command names to SmartServerRequest
            subclasses. e.g. bzrlib.transport.smart.vfs.vfs_commands.
        """
        self._backing_transport = backing_transport
        self._commands = commands
        self._body_bytes = ''
        self.response = None
        self.finished_reading = False
        self._command = None

    def accept_body(self, bytes):
        """Accept body data."""

        # TODO: This should be overriden for each command that desired body data
        # to handle the right format of that data, i.e. plain bytes, a bundle,
        # etc.  The deserialisation into that format should be done in the
        # Protocol object.

        # default fallback is to accumulate bytes.
        self._body_bytes += bytes
        
    def end_of_body(self):
        """No more body data will be received."""
        self._run_handler_code(self._command.do_body, (self._body_bytes,), {})
        # cannot read after this.
        self.finished_reading = True

    def dispatch_command(self, cmd, args):
        """Deprecated compatibility method.""" # XXX XXX
        try:
            command = self._commands.get(cmd)
        except LookupError:
            raise errors.SmartProtocolError("bad request %r" % (cmd,))
        self._command = command(self._backing_transport)
        self._run_handler_code(self._command.execute, args, {})

    def _run_handler_code(self, callable, args, kwargs):
        """Run some handler specific code 'callable'.

        If a result is returned, it is considered to be the commands response,
        and finished_reading is set true, and its assigned to self.response.

        Any exceptions caught are translated and a response object created
        from them.
        """
        result = self._call_converting_errors(callable, args, kwargs)

        if result is not None:
            self.response = result
            self.finished_reading = True

    def _call_converting_errors(self, callable, args, kwargs):
        """Call callable converting errors to Response objects."""
        # XXX: most of this error conversion is VFS-related, and thus ought to
        # be in SmartServerVFSRequestHandler somewhere.
        try:
            return callable(*args, **kwargs)
        except errors.NoSuchFile, e:
            return SmartServerResponse(('NoSuchFile', e.path))
        except errors.FileExists, e:
            return SmartServerResponse(('FileExists', e.path))
        except errors.DirectoryNotEmpty, e:
            return SmartServerResponse(('DirectoryNotEmpty', e.path))
        except errors.ShortReadvError, e:
            return SmartServerResponse(('ShortReadvError',
                e.path, str(e.offset), str(e.length), str(e.actual)))
        except UnicodeError, e:
            # If it is a DecodeError, than most likely we are starting
            # with a plain string
            str_or_unicode = e.object
            if isinstance(str_or_unicode, unicode):
                # XXX: UTF-8 might have \x01 (our seperator byte) in it.  We
                # should escape it somehow.
                val = 'u:' + str_or_unicode.encode('utf-8')
            else:
                val = 's:' + str_or_unicode.encode('base64')
            # This handles UnicodeEncodeError or UnicodeDecodeError
            return SmartServerResponse((e.__class__.__name__,
                    e.encoding, val, str(e.start), str(e.end), e.reason))
        except errors.TransportNotPossible, e:
            if e.msg == "readonly transport":
                return SmartServerResponse(('ReadOnlyError', ))
            else:
                raise


class HelloRequest(SmartServerRequest):
    """Answer a version request with my version."""

    def do(self):
        return SmartServerResponse(('ok', '2'))


class GetBundleRequest(SmartServerRequest):
    """Get a bundle of from the null revision to the specified revision."""

    def do(self, path, revision_id):
        # open transport relative to our base
        t = self._backing_transport.clone(path)
        control, extra_path = bzrdir.BzrDir.open_containing_from_transport(t)
        repo = control.open_repository()
        tmpf = tempfile.TemporaryFile()
        base_revision = revision.NULL_REVISION
        write_bundle(repo, revision_id, base_revision, tmpf)
        tmpf.seek(0)
        return SmartServerResponse((), tmpf.read())


class SmartServerIsReadonly(SmartServerRequest):
    # XXX: this request method belongs somewhere else.

    def do(self):
        if self._backing_transport.is_readonly():
            answer = 'yes'
        else:
            answer = 'no'
        return SmartServerResponse((answer,))


request_handlers = registry.Registry()
request_handlers.register_lazy(
    'append', 'bzrlib.smart.vfs', 'AppendRequest')
request_handlers.register_lazy(
    'delete', 'bzrlib.smart.vfs', 'DeleteRequest')
request_handlers.register_lazy(
    'get', 'bzrlib.smart.vfs', 'GetRequest')
request_handlers.register_lazy(
    'get_bundle', 'bzrlib.smart.request', 'GetBundleRequest')
request_handlers.register_lazy(
    'has', 'bzrlib.smart.vfs', 'HasRequest')
request_handlers.register_lazy(
    'hello', 'bzrlib.smart.request', 'HelloRequest')
request_handlers.register_lazy(
    'iter_files_recursive', 'bzrlib.smart.vfs', 'IterFilesRecursiveRequest')
request_handlers.register_lazy(
    'list_dir', 'bzrlib.smart.vfs', 'ListDirRequest')
request_handlers.register_lazy(
    'mkdir', 'bzrlib.smart.vfs', 'MkdirRequest')
request_handlers.register_lazy(
    'move', 'bzrlib.smart.vfs', 'MoveRequest')
request_handlers.register_lazy(
    'put', 'bzrlib.smart.vfs', 'PutRequest')
request_handlers.register_lazy(
    'put_non_atomic', 'bzrlib.smart.vfs', 'PutNonAtomicRequest')
request_handlers.register_lazy(
    'readv', 'bzrlib.smart.vfs', 'ReadvRequest')
request_handlers.register_lazy(
    'rename', 'bzrlib.smart.vfs', 'RenameRequest')
request_handlers.register_lazy(
    'rmdir', 'bzrlib.smart.vfs', 'RmdirRequest')
request_handlers.register_lazy(
    'stat', 'bzrlib.smart.vfs', 'StatRequest')
