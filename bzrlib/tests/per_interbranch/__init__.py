# Copyright (C) 2009, 2010 Canonical Ltd
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


"""InterBranch implementation tests for bzr.

These test the conformance of all the interbranch variations to the
expected API including generally applicable corner cases.
Specific tests for individual formats are in the tests for the formats
itself rather than in tests/per_interbranch/*.py.
"""


from bzrlib import (
    branchbuilder,
    )
from bzrlib.branch import (
                           GenericInterBranch,
                           InterBranch,
                           )
from bzrlib.tests import (
    TestCaseWithTransport,
    multiply_tests,
    )


def make_scenarios(test_list):
    """Transform the input test list to a list of scenarios.

    :param formats: A list of tuples:
        (interbranch_class, branch_format_from, branch_format_to).
    """
    result = []
    for interbranch_class, branch_format_from, branch_format_to in test_list:
        id = '%s,%s,%s' % (interbranch_class.__name__,
                            branch_format_from.__class__.__name__,
                            branch_format_to.__class__.__name__)
        scenario = (id,
            {
             "branch_format_from": branch_format_from,
             "interbranch_class": interbranch_class,
             "branch_format_to": branch_format_to,
             })
        result.append(scenario)
    return result


def default_test_list():
    """Generate the default list of interbranch permutations to test."""
    result = []
    # test the default InterBranch between format 6 and the current
    # default format.
    for optimiser_class in InterBranch._optimisers:
        for format_from_test, format_to_test in \
            optimiser_class._get_branch_formats_to_test():
            result.append((optimiser_class, format_from_test, format_to_test))
    # if there are specific combinations we want to use, we can add them
    # here.
    return result


class TestCaseWithInterBranch(TestCaseWithTransport):

    def make_from_branch(self, relpath):
        return self.make_branch(relpath, format=self.branch_format_from._matchingbzrdir)

    def make_from_branch_and_memory_tree(self, relpath):
        """Create a branch on the default transport and a MemoryTree for it."""
        return self.make_branch_and_memory_tree(
            relpath, format=self.branch_format_from._matchingbzrdir)

    def make_from_branch_and_tree(self, relpath):
        """Create a branch on the default transport and a working tree for it."""
        return self.make_branch_and_tree(relpath,
            format=self.branch_format_from._matchingbzrdir)

    def make_from_branch_builder(self, relpath):
        return branchbuilder.BranchBuilder(self.get_transport(relpath),
            format=self.branch_format_from._matchingbzrdir)

    def make_to_branch(self, relpath):
        return self.make_branch(relpath, format=self.branch_format_to._matchingbzrdir)

    def make_to_branch_and_memory_tree(self, relpath):
        """Create a branch on the default transport and a MemoryTree for it."""
        return self.make_branch_and_memory_tree(
            relpath, format=self.branch_format_to._matchingbzrdir)

    def make_to_branch_and_tree(self, relpath):
        """Create a branch on the default transport and a working tree for it."""
        return self.make_branch_and_tree(relpath,
            format=self.branch_format_to._matchingbzrdir)

    def _sprout(self, origdir, to_url, format):
        if format.supports_workingtrees:
            newbranch = self.make_branch(to_url, format=format)
        else:
            newbranch = self.make_branch(to_url+".branch", format=format)
        origbranch = origdir.open_branch()
        newbranch.repository.fetch(origbranch.repository)
        origbranch.copy_content_into(newbranch)
        if format.supports_workingtrees:
            wt = newbranch.bzrdir.create_workingtree()
        else:
            wt = newbranch.create_checkout(to_url, lightweight=True)
        return wt.bzrdir

    def sprout_to(self, origdir, to_url):
        """Sprout a bzrdir, using to_format for the new branch."""
        return self._sprout(origdir, to_url, self.branch_format_to._matchingbzrdir)

    def sprout_from(self, origdir, to_url):
        """Sprout a bzrdir, using from_format for the new bzrdir."""
        return self._sprout(origdir, to_url,
            self.branch_format_from._matchingbzrdir)


class StubWithFormat(object):
    """A stub object used to check that convenience methods call Inter's."""

    _format = object()


class StubMatchingInter(object):
    """An inter for tests.

    This is not a subclass of InterBranch so that missing methods are caught
    and added rather than actually trying to do something.
    """

    _uses = []

    def __init__(self, source, target):
        self.source = source
        self.target = target

    @classmethod
    def is_compatible(klass, source, target):
        return StubWithFormat._format in (source._format, target._format)

    def copy_content_into(self, *args, **kwargs):
        self.__class__._uses.append(
            (self, 'copy_content_into', args, kwargs))


def load_tests(standard_tests, module, loader):
    submod_tests = loader.loadTestsFromModuleNames([
        'bzrlib.tests.per_interbranch.test_fetch',
        'bzrlib.tests.per_interbranch.test_get',
        'bzrlib.tests.per_interbranch.test_copy_content_into',
        'bzrlib.tests.per_interbranch.test_pull',
        'bzrlib.tests.per_interbranch.test_push',
        ])
    scenarios = make_scenarios(default_test_list())
    return multiply_tests(submod_tests, scenarios, standard_tests)
