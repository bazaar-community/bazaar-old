# Copyright (C) 2004, 2005, 2006 by Canonical Ltd
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


import os
import sys
import stat
from cStringIO import StringIO

import bzrlib
from bzrlib.errors import (NoSuchFile, FileExists,
                           TransportNotPossible,
                           ConnectionError,
                           DependencyNotPresent,
                           UnsupportedProtocol,
                           )
from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.transport import (_CoalescedOffset,
                              _get_protocol_handlers,
                              _get_transport_modules,
                              get_transport,
                              register_lazy_transport,
                              _set_protocol_handlers,
                              Transport,
                              )
from bzrlib.transport.memory import MemoryTransport
from bzrlib.transport.local import LocalTransport


class TestTransport(TestCase):
    """Test the non transport-concrete class functionality."""

    def test__get_set_protocol_handlers(self):
        handlers = _get_protocol_handlers()
        self.assertNotEqual({}, handlers)
        try:
            _set_protocol_handlers({})
            self.assertEqual({}, _get_protocol_handlers())
        finally:
            _set_protocol_handlers(handlers)

    def test_get_transport_modules(self):
        handlers = _get_protocol_handlers()
        class SampleHandler(object):
            """I exist, isnt that enough?"""
        try:
            my_handlers = {}
            _set_protocol_handlers(my_handlers)
            register_lazy_transport('foo', 'bzrlib.tests.test_transport', 'TestTransport.SampleHandler')
            register_lazy_transport('bar', 'bzrlib.tests.test_transport', 'TestTransport.SampleHandler')
            self.assertEqual([SampleHandler.__module__],
                             _get_transport_modules())
        finally:
            _set_protocol_handlers(handlers)

    def test_transport_dependency(self):
        """Transport with missing dependency causes no error"""
        saved_handlers = _get_protocol_handlers()
        try:
            register_lazy_transport('foo', 'bzrlib.tests.test_transport',
                    'BadTransportHandler')
            try:
                get_transport('foo://fooserver/foo')
            except UnsupportedProtocol, e:
                e_str = str(e)
                self.assertEquals('Unsupported protocol'
                                  ' for url "foo://fooserver/foo":'
                                  ' Unable to import library "some_lib":'
                                  ' testing missing dependency', str(e))
            else:
                self.fail('Did not raise UnsupportedProtocol')
        finally:
            # restore original values
            _set_protocol_handlers(saved_handlers)
            
    def test_transport_fallback(self):
        """Transport with missing dependency causes no error"""
        saved_handlers = _get_protocol_handlers()
        try:
            _set_protocol_handlers({})
            register_lazy_transport('foo', 'bzrlib.tests.test_transport',
                    'BackupTransportHandler')
            register_lazy_transport('foo', 'bzrlib.tests.test_transport',
                    'BadTransportHandler')
            t = get_transport('foo://fooserver/foo')
            self.assertTrue(isinstance(t, BackupTransportHandler))
        finally:
            _set_protocol_handlers(saved_handlers)


class TestCoalesceOffsets(TestCase):
    
    def check(self, expected, offsets, limit=0, fudge=0):
        coalesce = Transport._coalesce_offsets
        exp = [_CoalescedOffset(*x) for x in expected]
        out = list(coalesce(offsets, limit=limit, fudge_factor=fudge))
        self.assertEqual(exp, out)

    def test_coalesce_empty(self):
        self.check([], [])

    def test_coalesce_simple(self):
        self.check([(0, 10, [(0, 10)])], [(0, 10)])

    def test_coalesce_unrelated(self):
        self.check([(0, 10, [(0, 10)]),
                    (20, 10, [(0, 10)]),
                   ], [(0, 10), (20, 10)])
            
    def test_coalesce_unsorted(self):
        self.check([(20, 10, [(0, 10)]),
                    (0, 10, [(0, 10)]),
                   ], [(20, 10), (0, 10)])

    def test_coalesce_nearby(self):
        self.check([(0, 20, [(0, 10), (10, 10)])],
                   [(0, 10), (10, 10)])

    def test_coalesce_overlapped(self):
        self.check([(0, 15, [(0, 10), (5, 10)])],
                   [(0, 10), (5, 10)])

    def test_coalesce_limit(self):
        self.check([(10, 50, [(0, 10), (10, 10), (20, 10),
                              (30, 10), (40, 10)]),
                    (60, 50, [(0, 10), (10, 10), (20, 10),
                              (30, 10), (40, 10)]),
                   ], [(10, 10), (20, 10), (30, 10), (40, 10),
                       (50, 10), (60, 10), (70, 10), (80, 10),
                       (90, 10), (100, 10)],
                    limit=5)

    def test_coalesce_no_limit(self):
        self.check([(10, 100, [(0, 10), (10, 10), (20, 10),
                               (30, 10), (40, 10), (50, 10),
                               (60, 10), (70, 10), (80, 10),
                               (90, 10)]),
                   ], [(10, 10), (20, 10), (30, 10), (40, 10),
                       (50, 10), (60, 10), (70, 10), (80, 10),
                       (90, 10), (100, 10)])

    def test_coalesce_fudge(self):
        self.check([(10, 30, [(0, 10), (20, 10)]),
                    (100, 10, [(0, 10),]),
                   ], [(10, 10), (30, 10), (100, 10)],
                   fudge=10
                  )


class TestMemoryTransport(TestCase):

    def test_get_transport(self):
        MemoryTransport()

    def test_clone(self):
        transport = MemoryTransport()
        self.assertTrue(isinstance(transport, MemoryTransport))

    def test_abspath(self):
        transport = MemoryTransport()
        self.assertEqual("memory:///relpath", transport.abspath('relpath'))

    def test_relpath(self):
        transport = MemoryTransport()

    def test_append_and_get(self):
        transport = MemoryTransport()
        transport.append('path', StringIO('content'))
        self.assertEqual(transport.get('path').read(), 'content')
        transport.append('path', StringIO('content'))
        self.assertEqual(transport.get('path').read(), 'contentcontent')

    def test_put_and_get(self):
        transport = MemoryTransport()
        transport.put('path', StringIO('content'))
        self.assertEqual(transport.get('path').read(), 'content')
        transport.put('path', StringIO('content'))
        self.assertEqual(transport.get('path').read(), 'content')

    def test_append_without_dir_fails(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile,
                          transport.append, 'dir/path', StringIO('content'))

    def test_put_without_dir_fails(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile,
                          transport.put, 'dir/path', StringIO('content'))

    def test_get_missing(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile, transport.get, 'foo')

    def test_has_missing(self):
        transport = MemoryTransport()
        self.assertEquals(False, transport.has('foo'))

    def test_has_present(self):
        transport = MemoryTransport()
        transport.append('foo', StringIO('content'))
        self.assertEquals(True, transport.has('foo'))

    def test_mkdir(self):
        transport = MemoryTransport()
        transport.mkdir('dir')
        transport.append('dir/path', StringIO('content'))
        self.assertEqual(transport.get('dir/path').read(), 'content')

    def test_mkdir_missing_parent(self):
        transport = MemoryTransport()
        self.assertRaises(NoSuchFile,
                          transport.mkdir, 'dir/dir')

    def test_mkdir_twice(self):
        transport = MemoryTransport()
        transport.mkdir('dir')
        self.assertRaises(FileExists, transport.mkdir, 'dir')

    def test_parameters(self):
        transport = MemoryTransport()
        self.assertEqual(True, transport.listable())
        self.assertEqual(False, transport.should_cache())
        self.assertEqual(False, transport.is_readonly())

    def test_iter_files_recursive(self):
        transport = MemoryTransport()
        transport.mkdir('dir')
        transport.put('dir/foo', StringIO('content'))
        transport.put('dir/bar', StringIO('content'))
        transport.put('bar', StringIO('content'))
        paths = set(transport.iter_files_recursive())
        self.assertEqual(set(['dir/foo', 'dir/bar', 'bar']), paths)

    def test_stat(self):
        transport = MemoryTransport()
        transport.put('foo', StringIO('content'))
        transport.put('bar', StringIO('phowar'))
        self.assertEqual(7, transport.stat('foo').st_size)
        self.assertEqual(6, transport.stat('bar').st_size)

        
class ReadonlyDecoratorTransportTest(TestCase):
    """Readonly decoration specific tests."""

    def test_local_parameters(self):
        import bzrlib.transport.readonly as readonly
        # connect to . in readonly mode
        transport = readonly.ReadonlyTransportDecorator('readonly+.')
        self.assertEqual(True, transport.listable())
        self.assertEqual(False, transport.should_cache())
        self.assertEqual(True, transport.is_readonly())

    def test_http_parameters(self):
        import bzrlib.transport.readonly as readonly
        from bzrlib.transport.http import HttpServer
        # connect to . via http which is not listable
        server = HttpServer()
        server.setUp()
        try:
            transport = get_transport('readonly+' + server.get_url())
            self.failUnless(isinstance(transport,
                                       readonly.ReadonlyTransportDecorator))
            self.assertEqual(False, transport.listable())
            self.assertEqual(True, transport.should_cache())
            self.assertEqual(True, transport.is_readonly())
        finally:
            server.tearDown()


class FakeNFSDecoratorTests(TestCaseInTempDir):
    """NFS decorator specific tests."""

    def get_nfs_transport(self, url):
        import bzrlib.transport.fakenfs as fakenfs
        # connect to url with nfs decoration
        return fakenfs.FakeNFSTransportDecorator('fakenfs+' + url)

    def test_local_parameters(self):
        # the listable, should_cache and is_readonly parameters
        # are not changed by the fakenfs decorator
        transport = self.get_nfs_transport('.')
        self.assertEqual(True, transport.listable())
        self.assertEqual(False, transport.should_cache())
        self.assertEqual(False, transport.is_readonly())

    def test_http_parameters(self):
        # the listable, should_cache and is_readonly parameters
        # are not changed by the fakenfs decorator
        from bzrlib.transport.http import HttpServer
        # connect to . via http which is not listable
        server = HttpServer()
        server.setUp()
        try:
            transport = self.get_nfs_transport(server.get_url())
            self.assertIsInstance(
                transport, bzrlib.transport.fakenfs.FakeNFSTransportDecorator)
            self.assertEqual(False, transport.listable())
            self.assertEqual(True, transport.should_cache())
            self.assertEqual(True, transport.is_readonly())
        finally:
            server.tearDown()

    def test_fakenfs_server_default(self):
        # a FakeNFSServer() should bring up a local relpath server for itself
        import bzrlib.transport.fakenfs as fakenfs
        server = fakenfs.FakeNFSServer()
        server.setUp()
        try:
            # the server should be a relpath localhost server
            self.assertEqual(server.get_url(), 'fakenfs+.')
            # and we should be able to get a transport for it
            transport = get_transport(server.get_url())
            # which must be a FakeNFSTransportDecorator instance.
            self.assertIsInstance(
                transport, fakenfs.FakeNFSTransportDecorator)
        finally:
            server.tearDown()

    def test_fakenfs_rename_semantics(self):
        # a FakeNFS transport must mangle the way rename errors occur to
        # look like NFS problems.
        transport = self.get_nfs_transport('.')
        self.build_tree(['from/', 'from/foo', 'to/', 'to/bar'],
                        transport=transport)
        self.assertRaises(bzrlib.errors.ResourceBusy,
                          transport.rename, 'from', 'to')


class FakeVFATDecoratorTests(TestCaseInTempDir):
    """Tests for simulation of VFAT restrictions"""

    def get_vfat_transport(self, url):
        """Return vfat-backed transport for test directory"""
        from bzrlib.transport.fakevfat import FakeVFATTransportDecorator
        return FakeVFATTransportDecorator('vfat+' + url)

    def test_transport_creation(self):
        from bzrlib.transport.fakevfat import FakeVFATTransportDecorator
        transport = self.get_vfat_transport('.')
        self.assertIsInstance(transport, FakeVFATTransportDecorator)

    def test_transport_mkdir(self):
        transport = self.get_vfat_transport('.')
        transport.mkdir('HELLO')
        self.assertTrue(transport.has('hello'))
        self.assertTrue(transport.has('Hello'))

    def test_forbidden_chars(self):
        transport = self.get_vfat_transport('.')
        self.assertRaises(ValueError, transport.has, "<NU>")


class BadTransportHandler(Transport):
    def __init__(self, base_url):
        raise DependencyNotPresent('some_lib', 'testing missing dependency')


class BackupTransportHandler(Transport):
    """Test transport that works as a backup for the BadTransportHandler"""
    pass


class TestTransportImplementation(TestCaseInTempDir):
    """Implementation verification for transports.
    
    To verify a transport we need a server factory, which is a callable
    that accepts no parameters and returns an implementation of
    bzrlib.transport.Server.
    
    That Server is then used to construct transport instances and test
    the transport via loopback activity.

    Currently this assumes that the Transport object is connected to the 
    current working directory.  So that whatever is done 
    through the transport, should show up in the working 
    directory, and vice-versa. This is a bug, because its possible to have
    URL schemes which provide access to something that may not be 
    result in storage on the local disk, i.e. due to file system limits, or 
    due to it being a database or some other non-filesystem tool.

    This also tests to make sure that the functions work with both
    generators and lists (assuming iter(list) is effectively a generator)
    """
    
    def setUp(self):
        super(TestTransportImplementation, self).setUp()
        self._server = self.transport_server()
        self._server.setUp()

    def tearDown(self):
        super(TestTransportImplementation, self).tearDown()
        self._server.tearDown()
        
    def get_transport(self):
        """Return a connected transport to the local directory."""
        base_url = self._server.get_url()
        # try getting the transport via the regular interface:
        t = get_transport(base_url)
        if not isinstance(t, self.transport_class): 
            # we did not get the correct transport class type. Override the
            # regular connection behaviour by direct construction.
            t = self.transport_class(base_url)
        return t
