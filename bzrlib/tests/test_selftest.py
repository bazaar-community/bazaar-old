# Copyright (C) 2005, 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for the test framework
"""

import os
import sys
import unittest
import warnings

import bzrlib
from bzrlib.tests import (
                          _load_module_by_name,
                          ChrootedTestCase,
                          TestCase,
                          TestCaseInTempDir,
                          TestCaseWithTransport,
                          TestSkipped,
                          TextTestRunner,
                          )
import bzrlib.errors as errors


class SelftestTests(TestCase):

    def test_import_tests(self):
        mod = _load_module_by_name('bzrlib.tests.test_selftest')
        self.assertEqual(mod.SelftestTests, SelftestTests)

    def test_import_test_failure(self):
        self.assertRaises(ImportError,
                          _load_module_by_name,
                          'bzrlib.no-name-yet')


class MetaTestLog(TestCase):

    def test_logging(self):
        """Test logs are captured when a test fails."""
        self.log('a test message')
        self._log_file.flush()
        self.assertContainsRe(self._get_log(), 'a test message\n')


class TestTreeShape(TestCaseInTempDir):

    def test_unicode_paths(self):
        filename = u'hell\u00d8'
        try:
            self.build_tree_contents([(filename, 'contents of hello')])
        except UnicodeEncodeError:
            raise TestSkipped("can't build unicode working tree in "
                "filesystem encoding %s" % sys.getfilesystemencoding())
        self.failUnlessExists(filename)


class TestSkippedTest(TestCase):
    """Try running a test which is skipped, make sure it's reported properly."""

    def test_skipped_test(self):
        # must be hidden in here so it's not run as a real test
        def skipping_test():
            raise TestSkipped('test intentionally skipped')
        runner = TextTestRunner(stream=self._log_file)
        test = unittest.FunctionTestCase(skipping_test)
        result = runner.run(test)
        self.assertTrue(result.wasSuccessful())


class TestTransportProviderAdapter(TestCase):
    """A group of tests that test the transport implementation adaption core.

    This is a meta test that the tests are applied to all available 
    transports.

    This will be generalised in the future which is why it is in this 
    test file even though it is specific to transport tests at the moment.
    """

    def test_get_transport_permutations(self):
        # this checks that we the module get_test_permutations call
        # is made by the adapter get_transport_test_permitations method.
        class MockModule(object):
            def get_test_permutations(self):
                return sample_permutation
        sample_permutation = [(1,2), (3,4)]
        from bzrlib.transport import TransportTestProviderAdapter
        adapter = TransportTestProviderAdapter()
        self.assertEqual(sample_permutation,
                         adapter.get_transport_test_permutations(MockModule()))

    def test_adapter_checks_all_modules(self):
        # this checks that the adapter returns as many permurtations as
        # there are in all the registered# transport modules for there
        # - we assume if this matches its probably doing the right thing
        # especially in combination with the tests for setting the right
        # classes below.
        from bzrlib.transport import (TransportTestProviderAdapter,
                                      _get_transport_modules
                                      )
        modules = _get_transport_modules()
        permutation_count = 0
        for module in modules:
            try:
                permutation_count += len(reduce(getattr, 
                    (module + ".get_test_permutations").split('.')[1:],
                     __import__(module))())
            except errors.DependencyNotPresent:
                pass
        input_test = TestTransportProviderAdapter(
            "test_adapter_sets_transport_class")
        adapter = TransportTestProviderAdapter()
        self.assertEqual(permutation_count,
                         len(list(iter(adapter.adapt(input_test)))))

    def test_adapter_sets_transport_class(self):
        # Check that the test adapter inserts a transport and server into the
        # generated test.
        #
        # This test used to know about all the possible transports and the
        # order they were returned but that seems overly brittle (mbp
        # 20060307)
        input_test = TestTransportProviderAdapter(
            "test_adapter_sets_transport_class")
        from bzrlib.transport import TransportTestProviderAdapter
        suite = TransportTestProviderAdapter().adapt(input_test)
        tests = list(iter(suite))
        self.assertTrue(len(tests) > 6)
        # there are at least that many builtin transports
        one_test = tests[0]
        self.assertTrue(issubclass(one_test.transport_class, 
                                   bzrlib.transport.Transport))
        self.assertTrue(issubclass(one_test.transport_server, 
                                   bzrlib.transport.Server))


class TestBranchProviderAdapter(TestCase):
    """A group of tests that test the branch implementation test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.branch import BranchTestProviderAdapter
        input_test = TestBranchProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [("c", "C"), ("d", "D")]
        adapter = BranchTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].branch_format, formats[0][0])
        self.assertEqual(tests[0].bzrdir_format, formats[0][1])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].branch_format, formats[1][0])
        self.assertEqual(tests[1].bzrdir_format, formats[1][1])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestBzrDirProviderAdapter(TestCase):
    """A group of tests that test the bzr dir implementation test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.bzrdir import BzrDirTestProviderAdapter
        input_test = TestBzrDirProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = ["c", "d"]
        adapter = BzrDirTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].bzrdir_format, formats[0])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].bzrdir_format, formats[1])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestRepositoryProviderAdapter(TestCase):
    """A group of tests that test the repository implementation test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.repository import RepositoryTestProviderAdapter
        input_test = TestRepositoryProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [("c", "C"), ("d", "D")]
        adapter = RepositoryTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].bzrdir_format, formats[0][1])
        self.assertEqual(tests[0].repository_format, formats[0][0])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].bzrdir_format, formats[1][1])
        self.assertEqual(tests[1].repository_format, formats[1][0])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestInterRepositoryProviderAdapter(TestCase):
    """A group of tests that test the InterRepository test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.repository import InterRepositoryTestProviderAdapter
        input_test = TestInterRepositoryProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [(str, "C1", "C2"), (int, "D1", "D2")]
        adapter = InterRepositoryTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].interrepo_class, formats[0][0])
        self.assertEqual(tests[0].repository_format, formats[0][1])
        self.assertEqual(tests[0].repository_format_to, formats[0][2])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].interrepo_class, formats[1][0])
        self.assertEqual(tests[1].repository_format, formats[1][1])
        self.assertEqual(tests[1].repository_format_to, formats[1][2])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestInterVersionedFileProviderAdapter(TestCase):
    """A group of tests that test the InterVersionedFile test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.versionedfile import InterVersionedFileTestProviderAdapter
        input_test = TestInterRepositoryProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [(str, "C1", "C2"), (int, "D1", "D2")]
        adapter = InterVersionedFileTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].interversionedfile_class, formats[0][0])
        self.assertEqual(tests[0].versionedfile_factory, formats[0][1])
        self.assertEqual(tests[0].versionedfile_factory_to, formats[0][2])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].interversionedfile_class, formats[1][0])
        self.assertEqual(tests[1].versionedfile_factory, formats[1][1])
        self.assertEqual(tests[1].versionedfile_factory_to, formats[1][2])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestRevisionStoreProviderAdapter(TestCase):
    """A group of tests that test the RevisionStore test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.store.revision import RevisionStoreTestProviderAdapter
        input_test = TestRevisionStoreProviderAdapter(
            "test_adapted_tests")
        # revision stores need a store factory - i.e. RevisionKnit
        #, a readonly and rw transport 
        # transport servers:
        server1 = "a"
        server2 = "b"
        store_factories = ["c", "d"]
        adapter = RevisionStoreTestProviderAdapter(server1, server2, store_factories)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].store_factory, store_factories[0][0])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].store_factory, store_factories[1][0])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestWorkingTreeProviderAdapter(TestCase):
    """A group of tests that test the workingtree implementation test adapter."""

    def test_adapted_tests(self):
        # check that constructor parameters are passed through to the adapted
        # test.
        from bzrlib.workingtree import WorkingTreeTestProviderAdapter
        input_test = TestWorkingTreeProviderAdapter(
            "test_adapted_tests")
        server1 = "a"
        server2 = "b"
        formats = [("c", "C"), ("d", "D")]
        adapter = WorkingTreeTestProviderAdapter(server1, server2, formats)
        suite = adapter.adapt(input_test)
        tests = list(iter(suite))
        self.assertEqual(2, len(tests))
        self.assertEqual(tests[0].workingtree_format, formats[0][0])
        self.assertEqual(tests[0].bzrdir_format, formats[0][1])
        self.assertEqual(tests[0].transport_server, server1)
        self.assertEqual(tests[0].transport_readonly_server, server2)
        self.assertEqual(tests[1].workingtree_format, formats[1][0])
        self.assertEqual(tests[1].bzrdir_format, formats[1][1])
        self.assertEqual(tests[1].transport_server, server1)
        self.assertEqual(tests[1].transport_readonly_server, server2)


class TestTestCaseWithTransport(TestCaseWithTransport):
    """Tests for the convenience functions TestCaseWithTransport introduces."""

    def test_get_readonly_url_none(self):
        from bzrlib.transport import get_transport
        from bzrlib.transport.memory import MemoryServer
        from bzrlib.transport.readonly import ReadonlyTransportDecorator
        self.transport_server = MemoryServer
        self.transport_readonly_server = None
        # calling get_readonly_transport() constructs a decorator on the url
        # for the server
        url = self.get_readonly_url()
        url2 = self.get_readonly_url('foo/bar')
        t = get_transport(url)
        t2 = get_transport(url2)
        self.failUnless(isinstance(t, ReadonlyTransportDecorator))
        self.failUnless(isinstance(t2, ReadonlyTransportDecorator))
        self.assertEqual(t2.base[:-1], t.abspath('foo/bar'))

    def test_get_readonly_url_http(self):
        from bzrlib.transport import get_transport
        from bzrlib.transport.local import LocalRelpathServer
        from bzrlib.transport.http import HttpServer, HttpTransportBase
        self.transport_server = LocalRelpathServer
        self.transport_readonly_server = HttpServer
        # calling get_readonly_transport() gives us a HTTP server instance.
        url = self.get_readonly_url()
        url2 = self.get_readonly_url('foo/bar')
        # the transport returned may be any HttpTransportBase subclass
        t = get_transport(url)
        t2 = get_transport(url2)
        self.failUnless(isinstance(t, HttpTransportBase))
        self.failUnless(isinstance(t2, HttpTransportBase))
        self.assertEqual(t2.base[:-1], t.abspath('foo/bar'))

    def test_is_directory(self):
        """Test assertIsDirectory assertion"""
        t = self.get_transport()
        self.build_tree(['a_dir/', 'a_file'], transport=t)
        self.assertIsDirectory('a_dir', t)
        self.assertRaises(AssertionError, self.assertIsDirectory, 'a_file', t)
        self.assertRaises(AssertionError, self.assertIsDirectory, 'not_here', t)


class TestChrootedTest(ChrootedTestCase):

    def test_root_is_root(self):
        from bzrlib.transport import get_transport
        t = get_transport(self.get_readonly_url())
        url = t.base
        self.assertEqual(url, t.clone('..').base)


class TestExtraAssertions(TestCase):
    """Tests for new test assertions in bzrlib test suite"""

    def test_assert_isinstance(self):
        self.assertIsInstance(2, int)
        self.assertIsInstance(u'', basestring)
        self.assertRaises(AssertionError, self.assertIsInstance, None, int)
        self.assertRaises(AssertionError, self.assertIsInstance, 23.3, int)

    def test_assertEndsWith(self):
        self.assertEndsWith('foo', 'oo')
        self.assertRaises(AssertionError, self.assertEndsWith, 'o', 'oo')


class TestConvenienceMakers(TestCaseWithTransport):
    """Test for the make_* convenience functions."""

    def test_make_branch_and_tree_with_format(self):
        # we should be able to supply a format to make_branch_and_tree
        self.make_branch_and_tree('a', format=bzrlib.bzrdir.BzrDirMetaFormat1())
        self.make_branch_and_tree('b', format=bzrlib.bzrdir.BzrDirFormat6())
        self.assertIsInstance(bzrlib.bzrdir.BzrDir.open('a')._format,
                              bzrlib.bzrdir.BzrDirMetaFormat1)
        self.assertIsInstance(bzrlib.bzrdir.BzrDir.open('b')._format,
                              bzrlib.bzrdir.BzrDirFormat6)
