# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
# -*- coding: utf-8 -*-
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


"""BzrDir implementation tests for bzr.

These test the conformance of all the bzrdir variations to the expected API.
Specific tests for individual formats are in the tests/test_bzrdir.py file
rather than in tests/branch_implementations/*.py.
"""

from bzrlib.bzrdir import BzrDirFormat
from bzrlib.tests import (
                          default_transport,
                          multiply_tests,
                          TestCaseWithTransport,
                          )
from bzrlib.transport.memory import MemoryServer


def make_scenarios(vfs_factory, transport_server, transport_readonly_server,
    formats, name_suffix=''):
    """Transform the input to a list of scenarios.

    :param formats: A list of bzrdir_format objects.
    :param vfs_server: A factory to create a Transport Server which has
        all the VFS methods working, and is writable.
    """
    result = []
    for format in formats:
        scenario_name = format.__class__.__name__
        scenario_name += name_suffix
        scenario = (scenario_name, {
            "vfs_transport_factory": vfs_factory,
            "transport_server": transport_server,
            "transport_readonly_server": transport_readonly_server,
            "bzrdir_format": format,
            })
        result.append(scenario)
    return result


class TestCaseWithBzrDir(TestCaseWithTransport):

    def setUp(self):
        super(TestCaseWithBzrDir, self).setUp()
        self.bzrdir = None

    def get_bzrdir(self):
        if self.bzrdir is None:
            self.bzrdir = self.make_bzrdir(None)
        return self.bzrdir

    def make_bzrdir(self, relpath, format=None):
        if format is None:
            format = self.bzrdir_format
        return super(TestCaseWithBzrDir, self).make_bzrdir(
            relpath, format=format)


def load_tests(standard_tests, module, loader):
    test_bzrdir_implementations = [
        'bzrlib.tests.bzrdir_implementations.test_bzrdir',
        'bzrlib.tests.bzrdir_implementations.test_push',
        ]
    submod_tests = loader.loadTestsFromModuleNames(test_bzrdir_implementations)
    formats = BzrDirFormat.known_formats()
    scenarios = make_scenarios(
        default_transport,
        None,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        formats)
    # This will always add scenarios using the smart server.
    from bzrlib.smart.server import (
        ReadonlySmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing_v2_only,
        SmartTCPServer_for_testing,
        SmartTCPServer_for_testing_v2_only,
        )
    from bzrlib.remote import RemoteBzrDirFormat
    # test the remote server behaviour when backed with a MemoryTransport
    # Once for the current version
    scenarios.extend(make_scenarios(
        MemoryServer,
        SmartTCPServer_for_testing,
        ReadonlySmartTCPServer_for_testing,
        [(RemoteBzrDirFormat())],
        name_suffix='-default'))
    # And once with < 1.6 - the 'v2' protocol.
    scenarios.extend(make_scenarios(
        MemoryServer,
        SmartTCPServer_for_testing_v2_only,
        ReadonlySmartTCPServer_for_testing_v2_only,
        [(RemoteBzrDirFormat())],
        name_suffix='-v2'))
    # add the tests for the sub modules
    return multiply_tests(submod_tests, scenarios, standard_tests)
