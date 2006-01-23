# Copyright (C) 2005 by Canonical Ltd
# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Branch implementation tests for bzr.

These test the conformance of all the branch variations to the expected API.
Specific tests for individual formats are in the tests/test_branch file 
rather than in tests/branch_implementations/*.py.
"""

from bzrlib.branch import BranchTestProviderAdapter, BzrBranchFormat
from bzrlib.tests import adapt_modules, TestLoader, TestSuite
from bzrlib.tests import TestCaseInTempDir, BzrTestBase
from bzrlib.transport.local import LocalRelpathServer

def test_suite():
    result = TestSuite()
    test_branch_implementations = [
        'bzrlib.tests.branch_implementations.test_branch',
        ]
    adapter = BranchTestProviderAdapter(
        LocalRelpathServer,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        BzrBranchFormat._formats.values())
    loader = TestLoader()
    adapt_modules(test_branch_implementations, adapter, loader, result)
    return result
