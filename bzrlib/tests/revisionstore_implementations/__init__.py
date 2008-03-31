# Copyright (C) 2006 Canonical Ltd
# Authors: Robert Collins <robert.collins@canonical.com>
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


"""RevisionStore implemnetation tests for bzr.

These test the conformance of all the revision store implementations to the 
expected API including generally applicable corner cases.
Specific tests for individual cases are in the tests/test_revisionstore.py file 
rather than in tests/revisionstore_implementations/*.py.
"""

from bzrlib.tests import (
                          adapt_modules,
                          default_transport,
                          TestScenarioApplier,
                          )


class RevisionStoreTestProviderAdapter(TestScenarioApplier):
    """A tool to generate a suite testing multiple repository stores.

    This is done by copying the test once for each repository store
    and injecting the transport_server, transport_readonly_server,
    and revision-store-factory into each copy.
    Each copy is also given a new id() to make it easy to identify.
    """

    def __init__(self, transport_server, transport_readonly_server, factories):
        self._transport_server = transport_server
        self._transport_readonly_server = transport_readonly_server
        self.scenarios = self.factories_to_scenarios(factories)
    
    def factories_to_scenarios(self, factories):
        """Transform the input factories to a list of scenarios.

        :param factories: A list of factories.
        """
        result = []
        for factory in factories:
            scenario = (factory, {
                "transport_server":self._transport_server,
                "transport_readonly_server":self._transport_readonly_server,
                "store_factory":factory,
                })
            result.append(scenario)
        return result

    @staticmethod
    def default_test_list():
        """Generate the default list of revision store permutations to test."""
        from bzrlib.store.revision.text import TextRevisionStoreTestFactory
        from bzrlib.store.revision.knit import KnitRevisionStoreFactory
        result = []
        # test the fallback InterVersionedFile from weave to annotated knits
        result.append(TextRevisionStoreTestFactory())
        result.append(KnitRevisionStoreFactory())
        return result


def load_tests(basic_tests, module, loader):
    result = loader.suiteClass()
    # add the tests for this module
    result.addTests(basic_tests)

    test_revisionstore_implementations = [
        'bzrlib.tests.revisionstore_implementations.test_all',
        ]
    adapter = RevisionStoreTestProviderAdapter(
        default_transport,
        # None here will cause a readonly decorator to be created
        # by the TestCaseWithTransport.get_readonly_transport method.
        None,
        RevisionStoreTestProviderAdapter.default_test_list()
        )
    adapt_modules(test_revisionstore_implementations, adapter, loader, result)
    return result
