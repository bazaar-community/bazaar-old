# Copyright (C) 2005-2010 Canonical Ltd
#       Author: Robert Collins <robert.collins@canonical.com>
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
#

import sys
import logging
import unittest
import weakref

from bzrlib import pyutils

# Mark this python module as being part of the implementation
# of unittest: this gives us better tracebacks where the last
# shown frame is the test code, not our assertXYZ.
__unittest = 1


class LogCollector(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.records=[]
    def emit(self, record):
        self.records.append(record.getMessage())


def makeCollectingLogger():
    """I make a logger instance that collects its logs for programmatic analysis
    -> (logger, collector)"""
    logger=logging.Logger("collector")
    handler=LogCollector()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    return logger, handler


def visitTests(suite, visitor):
    """A foreign method for visiting the tests in a test suite."""
    for test in suite._tests:
        #Abusing types to avoid monkey patching unittest.TestCase.
        # Maybe that would be better?
        try:
            test.visit(visitor)
        except AttributeError:
            if isinstance(test, unittest.TestCase):
                visitor.visitCase(test)
            elif isinstance(test, unittest.TestSuite):
                visitor.visitSuite(test)
                visitTests(test, visitor)
            else:
                print "unvisitable non-unittest.TestCase element %r (%r)" % (test, test.__class__)


class TestSuite(unittest.TestSuite):
    """I am an extended TestSuite with a visitor interface.
    This is primarily to allow filtering of tests - and suites or
    more in the future. An iterator of just tests wouldn't scale..."""

    def visit(self, visitor):
        """visit the composite. Visiting is depth-first.
        current callbacks are visitSuite and visitCase."""
        visitor.visitSuite(self)
        visitTests(self, visitor)

    def run(self, result):
        """Run the tests in the suite, discarding references after running."""
        tests = list(self)
        tests.reverse()
        self._tests = []
        stored_count = 0
        while tests:
            if result.shouldStop:
                self._tests = reversed(tests)
                break
            case = _run_and_collect_case(tests.pop(), result)()
            new_stored_count = getattr(result, "_count_stored_tests", int)()
            if case is not None and isinstance(case, unittest.TestCase):
                if stored_count == new_stored_count:
                    # Testcase didn't fail, but somehow is still alive
                    print "Uncollected test case: %s" % (case.id(),)
                # Zombie the testcase but leave a working stub id method
                case.__dict__ = {"id": lambda _id=case.id(): _id}
            stored_count = new_stored_count
        return result


def _run_and_collect_case(case, res):
    """Run test case against result and use weakref to drop the refcount"""
    case.run(res)
    return weakref.ref(case)


class TestLoader(unittest.TestLoader):
    """Custom TestLoader to extend the stock python one."""

    suiteClass = TestSuite
    # Memoize test names by test class dict
    test_func_names = {}

    def loadTestsFromModuleNames(self, names):
        """use a custom means to load tests from modules.

        There is an undesirable glitch in the python TestLoader where a
        import error is ignore. We think this can be solved by ensuring the
        requested name is resolvable, if its not raising the original error.
        """
        result = self.suiteClass()
        for name in names:
            result.addTests(self.loadTestsFromModuleName(name))
        return result

    def loadTestsFromModuleName(self, name):
        result = self.suiteClass()
        module = pyutils.get_named_object(name)

        result.addTests(self.loadTestsFromModule(module))
        return result

    def loadTestsFromModule(self, module):
        """Load tests from a module object.

        This extension of the python test loader looks for an attribute
        load_tests in the module object, and if not found falls back to the
        regular python loadTestsFromModule.

        If a load_tests attribute is found, it is called and the result is
        returned.

        load_tests should be defined like so:
        >>> def load_tests(standard_tests, module, loader):
        >>>    pass

        standard_tests is the tests found by the stock TestLoader in the
        module, module and loader are the module and loader instances.

        For instance, to run every test twice, you might do:
        >>> def load_tests(standard_tests, module, loader):
        >>>     result = loader.suiteClass()
        >>>     for test in iter_suite_tests(standard_tests):
        >>>         result.addTests([test, test])
        >>>     return result
        """
        if sys.version_info < (2, 7):
            basic_tests = super(TestLoader, self).loadTestsFromModule(module)
        else:
            # GZ 2010-07-19: Python 2.7 unittest also uses load_tests but with
            #                a different and incompatible signature
            basic_tests = super(TestLoader, self).loadTestsFromModule(module,
                use_load_tests=False)
        load_tests = getattr(module, "load_tests", None)
        if load_tests is not None:
            return load_tests(basic_tests, module, self)
        else:
            return basic_tests

    def getTestCaseNames(self, test_case_class):
        test_fn_names = self.test_func_names.get(test_case_class, None)
        if test_fn_names is not None:
            # We already know them
            return test_fn_names

        test_fn_names = unittest.TestLoader.getTestCaseNames(self,
                                                             test_case_class)
        self.test_func_names[test_case_class] = test_fn_names
        return test_fn_names


class FilteredByModuleTestLoader(TestLoader):
    """A test loader that import only the needed modules."""

    def __init__(self, needs_module):
        """Constructor.

        :param needs_module: a callable taking a module name as a
            parameter returing True if the module should be loaded.
        """
        TestLoader.__init__(self)
        self.needs_module = needs_module

    def loadTestsFromModuleName(self, name):
        if self.needs_module(name):
            return TestLoader.loadTestsFromModuleName(self, name)
        else:
            return self.suiteClass()


class TestVisitor(object):
    """A visitor for Tests"""
    def visitSuite(self, aTestSuite):
        pass
    def visitCase(self, aTestCase):
        pass
