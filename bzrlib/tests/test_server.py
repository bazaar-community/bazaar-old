# Copyright (C) 2010 Canonical Ltd
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

import errno
import socket
import SocketServer
import select
import sys
import threading


from bzrlib import (
    osutils,
    transport,
    urlutils,
    )
from bzrlib.transport import (
    chroot,
    pathfilter,
    )
from bzrlib.smart import server


class TestServer(transport.Server):
    """A Transport Server dedicated to tests.

    The TestServer interface provides a server for a given transport. We use
    these servers as loopback testing tools. For any given transport the
    Servers it provides must either allow writing, or serve the contents
    of os.getcwdu() at the time start_server is called.

    Note that these are real servers - they must implement all the things
    that we want bzr transports to take advantage of.
    """

    def get_url(self):
        """Return a url for this server.

        If the transport does not represent a disk directory (i.e. it is
        a database like svn, or a memory only transport, it should return
        a connection to a newly established resource for this Server.
        Otherwise it should return a url that will provide access to the path
        that was os.getcwdu() when start_server() was called.

        Subsequent calls will return the same resource.
        """
        raise NotImplementedError

    def get_bogus_url(self):
        """Return a url for this protocol, that will fail to connect.

        This may raise NotImplementedError to indicate that this server cannot
        provide bogus urls.
        """
        raise NotImplementedError


class LocalURLServer(TestServer):
    """A pretend server for local transports, using file:// urls.

    Of course no actual server is required to access the local filesystem, so
    this just exists to tell the test code how to get to it.
    """

    def start_server(self):
        pass

    def get_url(self):
        """See Transport.Server.get_url."""
        return urlutils.local_path_to_url('')


class DecoratorServer(TestServer):
    """Server for the TransportDecorator for testing with.

    To use this when subclassing TransportDecorator, override override the
    get_decorator_class method.
    """

    def start_server(self, server=None):
        """See bzrlib.transport.Server.start_server.

        :server: decorate the urls given by server. If not provided a
        LocalServer is created.
        """
        if server is not None:
            self._made_server = False
            self._server = server
        else:
            self._made_server = True
            self._server = LocalURLServer()
            self._server.start_server()

    def stop_server(self):
        if self._made_server:
            self._server.stop_server()

    def get_decorator_class(self):
        """Return the class of the decorators we should be constructing."""
        raise NotImplementedError(self.get_decorator_class)

    def get_url_prefix(self):
        """What URL prefix does this decorator produce?"""
        return self.get_decorator_class()._get_url_prefix()

    def get_bogus_url(self):
        """See bzrlib.transport.Server.get_bogus_url."""
        return self.get_url_prefix() + self._server.get_bogus_url()

    def get_url(self):
        """See bzrlib.transport.Server.get_url."""
        return self.get_url_prefix() + self._server.get_url()


class BrokenRenameServer(DecoratorServer):
    """Server for the BrokenRenameTransportDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import brokenrename
        return brokenrename.BrokenRenameTransportDecorator


class FakeNFSServer(DecoratorServer):
    """Server for the FakeNFSTransportDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import fakenfs
        return fakenfs.FakeNFSTransportDecorator


class FakeVFATServer(DecoratorServer):
    """A server that suggests connections through FakeVFATTransportDecorator

    For use in testing.
    """

    def get_decorator_class(self):
        from bzrlib.transport import fakevfat
        return fakevfat.FakeVFATTransportDecorator


class LogDecoratorServer(DecoratorServer):
    """Server for testing."""

    def get_decorator_class(self):
        from bzrlib.transport import log
        return log.TransportLogDecorator


class NoSmartTransportServer(DecoratorServer):
    """Server for the NoSmartTransportDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import nosmart
        return nosmart.NoSmartTransportDecorator


class ReadonlyServer(DecoratorServer):
    """Server for the ReadonlyTransportDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import readonly
        return readonly.ReadonlyTransportDecorator


class TraceServer(DecoratorServer):
    """Server for the TransportTraceDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import trace
        return trace.TransportTraceDecorator


class UnlistableServer(DecoratorServer):
    """Server for the UnlistableTransportDecorator for testing with."""

    def get_decorator_class(self):
        from bzrlib.transport import unlistable
        return unlistable.UnlistableTransportDecorator


class TestingPathFilteringServer(pathfilter.PathFilteringServer):

    def __init__(self):
        """TestingPathFilteringServer is not usable until start_server
        is called."""

    def start_server(self, backing_server=None):
        """Setup the Chroot on backing_server."""
        if backing_server is not None:
            self.backing_transport = transport.get_transport(
                backing_server.get_url())
        else:
            self.backing_transport = transport.get_transport('.')
        self.backing_transport.clone('added-by-filter').ensure_base()
        self.filter_func = lambda x: 'added-by-filter/' + x
        super(TestingPathFilteringServer, self).start_server()

    def get_bogus_url(self):
        raise NotImplementedError


class TestingChrootServer(chroot.ChrootServer):

    def __init__(self):
        """TestingChrootServer is not usable until start_server is called."""
        super(TestingChrootServer, self).__init__(None)

    def start_server(self, backing_server=None):
        """Setup the Chroot on backing_server."""
        if backing_server is not None:
            self.backing_transport = transport.get_transport(
                backing_server.get_url())
        else:
            self.backing_transport = transport.get_transport('.')
        super(TestingChrootServer, self).start_server()

    def get_bogus_url(self):
        raise NotImplementedError


class ThreadWithException(threading.Thread):
    """A catching exception thread.

    If an exception occurs during the thread execution, it's caught and
    re-raised when the thread is joined().
    """

    def __init__(self, *args, **kwargs):
        # There are cases where the calling thread must wait, yet, if an
        # exception occurs, the event should be set so the caller is not
        # blocked. The main example is a calling thread that want to wait for
        # the called thread to be in a given state before continuing.
        try:
            event = kwargs.pop('event')
        except KeyError:
            # If the caller didn't pass a specific event, create our own
            event = threading.Event()
        super(ThreadWithException, self).__init__(*args, **kwargs)
        self.set_event(event)
        self.exception = None

    def set_event(self, event):
        self.ready = event

    def run(self):
        """Overrides Thread.run to capture any exception."""
        self.ready.clear()
        try:
            super(ThreadWithException, self).run()
        except:
            self.exception = sys.exc_info()
        finally:
            # Make sure the calling thread is released
            self.ready.set()


    def join(self, timeout=5):
        """Overrides Thread.join to raise any exception caught.


        Calling join(timeout=0) will raise the caught exception or return None
        if the thread is still alive.

        The default timeout is set to 5 and should expire only when a thread
        serving a client connection is hung.
        """
        super(ThreadWithException, self).join(timeout)
        if self.exception is not None:
            exc_class, exc_value, exc_tb = self.exception
            self.execption = None # The exception should be raised only once
            raise exc_class, exc_value, exc_tb
        if timeout and self.isAlive():
            # The timeout expired without joining the thread, the thread is
            # therefore stucked and that's a failure as far as the test is
            # concerned. We used to hang here.
            raise AssertionError('thread %s hung' % (self.name,))

    def pending_exception(self):
        """Raise the caught exception.

        This does nothing if no exception occurred.
        """
        self.join(timeout=0)


class TestingTCPServerMixin:
    """Mixin to support running SocketServer.TCPServer in a thread.

    Tests are connecting from the main thread, the server has to be run in a
    separate thread.
    """

    # FIXME: sibling_class is a hack -- vila 20100604
    def __init__(self, sibling_class):
        self.sibling_class = sibling_class
        self.started = threading.Event()
        self.serving = threading.Event()
        self.stopped = threading.Event()
        # We collect the resources used by the clients so we can release them
        # when shutting down
        self.clients = []

    def server_bind(self):
        # We need to override the SocketServer bind, yet, we still want to use
        # it so we need to use the sibling class to call it explicitly
        self.sibling_class.server_bind(self)
        # The following has been fixed in 2.5 so we need to provide it for
        # older python versions.
        if sys.version < (2, 5):
            self.server_address = self.socket.getsockname()

    def serve(self):
        self.serving.set()
        self.stopped.clear()
        # We are listening and ready to accept connections
        self.started.set()
        while self.serving.isSet():
            # Really a connection but the python framework is generic and
            # call them requests
            self.handle_request()
        # Let's close the listening socket
        self.server_close()
        self.stopped.set()

    def handle_request(self):
        """Handle one request.

        The python version swallows some socket exceptions and we don't use
        timeout, so we override to better control the server behavior.
        """
        request, client_address = self.get_request()
        if self.verify_request(request, client_address):
            try:
                self.process_request(request, client_address)
            except:
                self.handle_error(request, client_address)
                self.close_request(request)

    def verify_request(self, request, client_address):
        """Verify the request.

        Return True if we should proceed with this request, False if we should
        not even touch a single byte in the socket ! This is useful when we
        stop the server with a dummy last connection.
        """
        return self.serving.isSet()

    def handle_error(self, request, client_address):
        # Stop serving and re-raise the last exception seen
        self.serving.clear()
#        self.sibling_class.handle_error(self, request, client_address)
        raise

    # The following methods are called by the main thread

    def stop_client_connections(self):
        while self.clients:
            c = self.clients.pop()
            self.shutdown_client(c)

    def shutdown_client_socket(self, sock):
        """Properly shutdown a client socket.

        Under some circumstances (as in bug #383920), we need to force the
        shutdown as python delays it until gc occur otherwise and the client
        may hang.

        This should be called only when no other thread is trying to use the
        socket.
        """
        try:
            # The request process has been completed, the thread is about to
            # die, let's shutdown the socket if we can.
            sock.shutdown(socket.SHUT_RDWR)
            sock.close()
        except (socket.error, select.error), e:
            if e[0] in (errno.EBADF, errno.ENOTCONN):
                # Right, the socket is already down
                pass
            else:
                raise


class TestingTCPServer(TestingTCPServerMixin, SocketServer.TCPServer):

    def __init__(self, server_address, request_handler_class):
        TestingTCPServerMixin.__init__(self, SocketServer.TCPServer)
        SocketServer.TCPServer.__init__(self, server_address,
                                        request_handler_class)

    def get_request(self):
        """Get the request and client address from the socket."""
        sock, addr = self.sibling_class.get_request(self)
        self.clients.append((sock, addr))
        return sock, addr

    # The following methods are called by the main thread

    def shutdown_client(self, client):
        sock, addr = client
        self.shutdown_client_socket(sock)



class TestingThreadingTCPServer(TestingTCPServerMixin,
                                SocketServer.ThreadingTCPServer):

    def __init__(self, server_address, request_handler_class):
        TestingTCPServerMixin.__init__(self, SocketServer.ThreadingTCPServer)
        SocketServer.TCPServer.__init__(self, server_address,
                                        request_handler_class)

    def get_request (self):
        """Get the request and client address from the socket."""
        sock, addr = self.sibling_class.get_request(self)
        # The thread is not create yet, it will be updated in process_request
        self.clients.append((sock, addr, None))
        return sock, addr

    def process_request_thread(self, started, stopped, request, client_address):
        started.set()
        SocketServer.ThreadingTCPServer.process_request_thread(
            self, request, client_address)
        self.close_request(request)
        stopped.set()

    def process_request(self, request, client_address):
        """Start a new thread to process the request."""
        started = threading.Event()
        stopped = threading.Event()
        t = ThreadWithException(
            event=stopped,
            target = self.process_request_thread,
            args = (started, stopped, request, client_address))
        t.name = '%s -> %s' % (client_address, self.server_address)
        # Update the client description
        self.clients.pop()
        self.clients.append((request, client_address, t))
        t.start()
        started.wait()
        # If an exception occured during the thread start, it will get raised.
        t.pending_exception()

    # The following methods are called by the main thread

    def shutdown_client(self, client):
        sock, addr, t = client
        self.shutdown_client_socket(sock)
        if t is not None:
            # The thread has been created only if the request is processed but
            # after the connection is inited. This could happen during server
            # shutdown. If an exception occurred in the thread it will be
            # re-raised
            t.join()


class TestingTCPServerInAThread(transport.Server):
    """A server in a thread that re-raise thread exceptions."""

    def __init__(self, server_address, server_class, request_handler_class):
        self.server_class = server_class
        self.request_handler_class = request_handler_class
        self.host, self.port = server_address
        self.server = None

    def __repr__(self):
        return "%s(%s:%s)" % (self.__class__.__name__, self.host, self.port)

    def create_server(self):
        return self.server_class((self.host, self.port),
                                 self.request_handler_class)

    def start_server(self):
        self.server = self.create_server()
        self._server_thread = ThreadWithException(
            event=self.server.started, target=self.run_server)
        self._server_thread.start()
        # Wait for the server thread to start (i.e release the lock)
        self.server.started.wait()
        # Get the real address, especially the port
        self.host, self.port = self.server.server_address
        self._server_thread.name = '(%s:%s)' % (self.host, self.port)
        # If an exception occured during the server start, it will get raised,
        # otherwise, the server is blocked on its accept() call.
        self._server_thread.pending_exception()
        # From now on, we'll use a different event to ensure the server can set
        # its exception
        self._server_thread.set_event(self.server.stopped)

    def run_server(self):
        self.server.serve()

    def stop_server(self):
        if self.server is None:
            return
        try:
            # The server has been started successfully, shut it down now.  As
            # soon as we stop serving, no more connection are accepted except
            # one to get out of the blocking listen.
            self.server.serving.clear()
            # The server is listening for a last connection, let's give it:
            last_conn = None
            try:
                last_conn = osutils.connect_socket((self.host, self.port))
            except socket.error, e:
                # But ignore connection errors as the point is to unblock the
                # server thread, it may happen that it's not blocked or even
                # not started.
                pass
            # We start shutting down the client while the server itself is
            # shutting down.
            self.server.stop_client_connections()
            # Now we wait for the thread running self.server.serve() to finish
            self.server.stopped.wait()
            if last_conn is not None:
                # Close the last connection without trying to use it. The
                # server will not process a single byte on that socket to avoid
                # complications (SSL starts with a handshake for example).
                last_conn.close()
            # Check for any exception that could have occurred in the server
            # thread
            self._server_thread.join()
        finally:
            # Make sure we can be called twice safely, note that this means
            # that we will raise a single exception even if several occurred in
            # the various threads involved.
            self.server = None


class SmartTCPServer_for_testing(server.SmartTCPServer):
    """Server suitable for use by transport tests.

    This server is backed by the process's cwd.
    """

    def __init__(self, thread_name_suffix=''):
        super(SmartTCPServer_for_testing, self).__init__(None)
        self.client_path_extra = None
        self.thread_name_suffix = thread_name_suffix
        # We collect the sockets/threads used by the clients so we can
        # close/join them when shutting down
        self.clients = []

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        return transport.get_transport(backing_transport_server.get_url())

    def start_server(self, backing_transport_server=None,
              client_path_extra='/extra/'):
        """Set up server for testing.

        :param backing_transport_server: backing server to use.  If not
            specified, a LocalURLServer at the current working directory will
            be used.
        :param client_path_extra: a path segment starting with '/' to append to
            the root URL for this server.  For instance, a value of '/foo/bar/'
            will mean the root of the backing transport will be published at a
            URL like `bzr://127.0.0.1:nnnn/foo/bar/`, rather than
            `bzr://127.0.0.1:nnnn/`.  Default value is `extra`, so that tests
            by default will fail unless they do the necessary path translation.
        """
        if not client_path_extra.startswith('/'):
            raise ValueError(client_path_extra)
        from bzrlib.transport.chroot import ChrootServer
        if backing_transport_server is None:
            backing_transport_server = LocalURLServer()
        self.chroot_server = ChrootServer(
            self.get_backing_transport(backing_transport_server))
        self.chroot_server.start_server()
        self.backing_transport = transport.get_transport(
            self.chroot_server.get_url())
        self.root_client_path = self.client_path_extra = client_path_extra
        self.start_background_thread(self.thread_name_suffix)

    def serve_conn(self, conn, thread_name_suffix):
        conn_thread = super(SmartTCPServer_for_testing, self).serve_conn(
            conn, thread_name_suffix)
        self.clients.append((conn, conn_thread))
        return conn_thread

    def shutdown_client(self, client_socket):
        """Properly shutdown a client socket.

        Under some circumstances (as in bug #383920), we need to force the
        shutdown as python delays it until gc occur otherwise and the client
        may hang.

        This should be called only when no other thread is trying to use the
        socket.
        """
        try:
            # The request process has been completed, the thread is about to
            # die, let's shutdown the socket if we can.
            client_socket.shutdown(socket.SHUT_RDWR)
        except (socket.error, select.error), e:
            if e[0] in (errno.EBADF, errno.ENOTCONN):
                # Right, the socket is already down
                pass
            else:
                raise

    def stop_server(self):
        self.stop_background_thread()
        # Let's close all our pending clients too
        for sock, thread in self.clients:
            self.shutdown_client(sock)
            thread.join()
            del thread
        self.clients = []
        self.chroot_server.stop_server()

    def get_url(self):
        url = super(SmartTCPServer_for_testing, self).get_url()
        return url[:-1] + self.client_path_extra

    def get_bogus_url(self):
        """Return a URL which will fail to connect"""
        return 'bzr://127.0.0.1:1/'


class ReadonlySmartTCPServer_for_testing(SmartTCPServer_for_testing):
    """Get a readonly server for testing."""

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        url = 'readonly+' + backing_transport_server.get_url()
        return transport.get_transport(url)


class SmartTCPServer_for_testing_v2_only(SmartTCPServer_for_testing):
    """A variation of SmartTCPServer_for_testing that limits the client to
    using RPCs in protocol v2 (i.e. bzr <= 1.5).
    """

    def get_url(self):
        url = super(SmartTCPServer_for_testing_v2_only, self).get_url()
        url = 'bzr-v2://' + url[len('bzr://'):]
        return url


class ReadonlySmartTCPServer_for_testing_v2_only(
    SmartTCPServer_for_testing_v2_only):
    """Get a readonly server for testing."""

    def get_backing_transport(self, backing_transport_server):
        """Get a backing transport from a server we are decorating."""
        url = 'readonly+' + backing_transport_server.get_url()
        return transport.get_transport(url)




