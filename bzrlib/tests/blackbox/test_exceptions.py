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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Tests for display of exceptions."""

from cStringIO import StringIO
import os
import sys

from bzrlib import (
    bzrdir,
    errors,
    repository,
    trace,
    )

from bzrlib.tests import TestCaseInTempDir, TestCase
from bzrlib.errors import NotBranchError


class TestExceptionReporting(TestCase):

    def test_exception_exitcode(self):
        # we must use a subprocess, because the normal in-memory mechanism
        # allows errors to propagate up through the test suite
        out, err = self.run_bzr_subprocess(['assert-fail'],
            universal_newlines=True,
            retcode=errors.EXIT_INTERNAL_ERROR)
        self.assertEqual(4, errors.EXIT_INTERNAL_ERROR)
        self.assertContainsRe(err,
                r'exceptions\.AssertionError: always fails\n')
        self.assertContainsRe(err, r'Bazaar has encountered an internal error')


class TestDeprecationWarning(TestCaseInTempDir):

    def test_repository_deprecation_warning(self):
        """Old formats give a warning"""
        # the warning's normally off for testing but we reenable it
        repository._deprecation_warning_done = False
        try:
            os.mkdir('foo')
            bzrdir.BzrDirFormat5().initialize('foo')
            out, err = self.run_bzr("status foo")
            self.assertContainsRe(self.get_log(), "bzr upgrade")
        finally:
            repository._deprecation_warning_done = True

