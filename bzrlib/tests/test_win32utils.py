# Copyright (C) 2007 Canonical Ltd
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

import os
import sys

from bzrlib import (
    osutils,
    tests,
    win32utils,
    )
from bzrlib.tests import (
    Feature,
    TestCase,
    TestCaseInTempDir,
    TestSkipped,
    UnicodeFilenameFeature,
    )
from bzrlib.win32utils import glob_expand, get_app_path


class _BackslashDirSeparatorFeature(tests.Feature):

    def _probe(self):
        try:
            os.lstat(os.getcwd() + '\\')
        except OSError:
            return False
        else:
            return True

    def feature_name(self):
        return "Filesystem treats '\\' as a directory separator."

BackslashDirSeparatorFeature = _BackslashDirSeparatorFeature()


class _RequiredModuleFeature(Feature):

    def __init__(self, mod_name):
        self.mod_name = mod_name
        super(_RequiredModuleFeature, self).__init__()

    def _probe(self):
        try:
            __import__(self.mod_name)
            return True
        except ImportError:
            return False

    def feature_name(self):
        return self.mod_name

Win32RegistryFeature = _RequiredModuleFeature('_winreg')
CtypesFeature = _RequiredModuleFeature('ctypes')
Win32comShellFeature = _RequiredModuleFeature('win32com.shell')


# Tests
# -----

class TestWin32UtilsGlobExpand(TestCaseInTempDir):

    _test_needs_features = []

    def test_empty_tree(self):
        self.build_tree([])
        self._run_testset([
            [['a'], ['a']],
            [['?'], ['?']],
            [['*'], ['*']],
            [['a', 'a'], ['a', 'a']]])

    def build_ascii_tree(self):
        self.build_tree(['a', 'a1', 'a2', 'a11', 'a.1',
                         'b', 'b1', 'b2', 'b3',
                         'c/', 'c/c1', 'c/c2',
                         'd/', 'd/d1', 'd/d2', 'd/e/', 'd/e/e1'])

    def build_unicode_tree(self):
        self.requireFeature(UnicodeFilenameFeature)
        self.build_tree([u'\u1234', u'\u1234\u1234', u'\u1235/',
                         u'\u1235/\u1235'])

    def test_tree_ascii(self):
        """Checks the glob expansion and path separation char
        normalization"""
        self.build_ascii_tree()
        self._run_testset([
            # no wildcards
            [[u'a'], [u'a']],
            [[u'a', u'a' ], [u'a', u'a']],

            [[u'd'], [u'd']],
            [[u'd/'], [u'd/']],

            # wildcards
            [[u'a*'], [u'a', u'a1', u'a2', u'a11', u'a.1']],
            [[u'?'], [u'a', u'b', u'c', u'd']],
            [[u'a?'], [u'a1', u'a2']],
            [[u'a??'], [u'a11', u'a.1']],
            [[u'b[1-2]'], [u'b1', u'b2']],

            [[u'd/*'], [u'd/d1', u'd/d2', u'd/e']],
            [[u'?/*'], [u'c/c1', u'c/c2', u'd/d1', u'd/d2', u'd/e']],
            [[u'*/*'], [u'c/c1', u'c/c2', u'd/d1', u'd/d2', u'd/e']],
            [[u'*/'], [u'c/', u'd/']],
            ])

    def test_backslash_globbing(self):
        self.requireFeature(BackslashDirSeparatorFeature)
        self.build_ascii_tree()
        self._run_testset([
            [[u'd\\'], [u'd/']],
            [[u'd\\*'], [u'd/d1', u'd/d2', u'd/e']],
            [[u'?\\*'], [u'c/c1', u'c/c2', u'd/d1', u'd/d2', u'd/e']],
            [[u'*\\*'], [u'c/c1', u'c/c2', u'd/d1', u'd/d2', u'd/e']],
            [[u'*\\'], [u'c/', u'd/']],
            ])

    def test_case_insensitive_globbing(self):
        self.requireFeature(tests.CaseInsCasePresFilenameFeature)
        self.build_ascii_tree()
        self._run_testset([
            [[u'A'], [u'A']],
            [[u'A?'], [u'a1', u'a2']],
            ])

    def test_tree_unicode(self):
        """Checks behaviour with non-ascii filenames"""
        self.build_unicode_tree()
        self._run_testset([
            # no wildcards
            [[u'\u1234'], [u'\u1234']],
            [[u'\u1235'], [u'\u1235']],

            [[u'\u1235/'], [u'\u1235/']],
            [[u'\u1235/\u1235'], [u'\u1235/\u1235']],

            # wildcards
            [[u'?'], [u'\u1234', u'\u1235']],
            [[u'*'], [u'\u1234', u'\u1234\u1234', u'\u1235']],
            [[u'\u1234*'], [u'\u1234', u'\u1234\u1234']],

            [[u'\u1235/?'], [u'\u1235/\u1235']],
            [[u'\u1235/*'], [u'\u1235/\u1235']],
            [[u'?/'], [u'\u1235/']],
            [[u'*/'], [u'\u1235/']],
            [[u'?/?'], [u'\u1235/\u1235']],
            [[u'*/*'], [u'\u1235/\u1235']],
            ])

    def test_unicode_backslashes(self):
        self.requireFeature(BackslashDirSeparatorFeature)
        self.build_unicode_tree()
        self._run_testset([
            # no wildcards
            [[u'\u1235\\'], [u'\u1235/']],
            [[u'\u1235\\\u1235'], [u'\u1235/\u1235']],
            [[u'\u1235\\?'], [u'\u1235/\u1235']],
            [[u'\u1235\\*'], [u'\u1235/\u1235']],
            [[u'?\\'], [u'\u1235/']],
            [[u'*\\'], [u'\u1235/']],
            [[u'?\\?'], [u'\u1235/\u1235']],
            [[u'*\\*'], [u'\u1235/\u1235']],
            ])

    def _run_testset(self, testset):
        for pattern, expected in testset:
            result = glob_expand(pattern)
            expected.sort()
            result.sort()
            self.assertEqual(expected, result, 'pattern %s' % pattern)


class TestAppPaths(TestCase):

    _test_needs_features = [Win32RegistryFeature]

    def test_iexplore(self):
        # typical windows users should have IE installed
        for a in ('iexplore', 'iexplore.exe'):
            p = get_app_path(a)
            d, b = os.path.split(p)
            self.assertEquals('iexplore.exe', b.lower())
            self.assertNotEquals('', d)

    def test_wordpad(self):
        # typical windows users should have wordpad in the system
        # but there is problem: its path has the format REG_EXPAND_SZ
        # so naive attempt to get the path is not working
        for a in ('wordpad', 'wordpad.exe'):
            p = get_app_path(a)
            d, b = os.path.split(p)
            self.assertEquals('wordpad.exe', b.lower())
            self.assertNotEquals('', d)

    def test_not_existing(self):
        p = get_app_path('not-existing')
        self.assertEquals('not-existing', p)


class TestLocationsCtypes(TestCase):

    _test_needs_features = [CtypesFeature]

    def assertPathsEqual(self, p1, p2):
        # TODO: The env var values in particular might return the "short"
        # version (ie, "C:\DOCUME~1\...").  Its even possible the returned
        # values will differ only by case - handle these situations as we
        # come across them.
        self.assertEquals(p1, p2)

    def test_appdata_not_using_environment(self):
        # Test that we aren't falling back to the environment
        first = win32utils.get_appdata_location()
        self._captureVar("APPDATA", None)
        self.assertPathsEqual(first, win32utils.get_appdata_location())

    def test_appdata_matches_environment(self):
        # Typically the APPDATA environment variable will match
        # get_appdata_location
        # XXX - See bug 262874, which asserts the correct encoding is 'mbcs',
        encoding = osutils.get_user_encoding()
        env_val = os.environ.get("APPDATA", None)
        if not env_val:
            raise TestSkipped("No APPDATA environment variable exists")
        self.assertPathsEqual(win32utils.get_appdata_location(),
                              env_val.decode(encoding))

    def test_local_appdata_not_using_environment(self):
        # Test that we aren't falling back to the environment
        first = win32utils.get_local_appdata_location()
        self._captureVar("LOCALAPPDATA", None)
        self.assertPathsEqual(first, win32utils.get_local_appdata_location())

    def test_local_appdata_matches_environment(self):
        # LOCALAPPDATA typically only exists on Vista, so we only attempt to
        # compare when it exists.
        lad = win32utils.get_local_appdata_location()
        env = os.environ.get("LOCALAPPDATA")
        if env:
            # XXX - See bug 262874, which asserts the correct encoding is 'mbcs'
            encoding = osutils.get_user_encoding()
            self.assertPathsEqual(lad, env.decode(encoding))


class TestLocationsPywin32(TestLocationsCtypes):

    _test_needs_features = [Win32comShellFeature]

    def setUp(self):
        super(TestLocationsPywin32, self).setUp()
        # We perform the exact same tests after disabling the use of ctypes.
        # This causes the implementation to fall back to pywin32.
        self.old_ctypes = win32utils.has_ctypes
        win32utils.has_ctypes = False
        self.addCleanup(self.restoreCtypes)

    def restoreCtypes(self):
        win32utils.has_ctypes = self.old_ctypes


class TestSetHidden(TestCaseInTempDir):

    def test_unicode_dir(self):
        # we should handle unicode paths without errors
        self.requireFeature(UnicodeFilenameFeature)
        os.mkdir(u'\u1234')
        win32utils.set_file_attr_hidden(u'\u1234')

    def test_dot_bzr_in_unicode_dir(self):
        # we should not raise traceback if we try to set hidden attribute
        # on .bzr directory below unicode path
        self.requireFeature(UnicodeFilenameFeature)
        os.makedirs(u'\u1234\\.bzr')
        path = osutils.abspath(u'\u1234\\.bzr')
        win32utils.set_file_attr_hidden(path)



class TestUnicodeShlex(tests.TestCase):

    def assertAsTokens(self, expected, line):
        s = win32utils.UnicodeShlex(line)
        self.assertEqual(expected, list(s))

    def test_simple(self):
        self.assertAsTokens([(False, u'foo'), (False, u'bar'), (False, u'baz')],
                            u'foo bar baz')

    def test_ignore_multiple_spaces(self):
        self.assertAsTokens([(False, u'foo'), (False, u'bar')], u'foo  bar')

    def test_ignore_leading_space(self):
        self.assertAsTokens([(False, u'foo'), (False, u'bar')], u'  foo bar')

    def test_ignore_trailing_space(self):
        self.assertAsTokens([(False, u'foo'), (False, u'bar')], u'foo bar  ')

    def test_posix_quotations(self):
        self.assertAsTokens([(True, u'foo bar')], u'"foo bar"')
        self.assertAsTokens([(False, u"'fo''o"), (False, u"b''ar'")],
            u"'fo''o b''ar'")
        self.assertAsTokens([(True, u'foo bar')], u'"fo""o b""ar"')
        self.assertAsTokens([(True, u"fo'o"), (True, u"b'ar")],
            u'"fo"\'o b\'"ar"')

    def test_nested_quotations(self):
        self.assertAsTokens([(True, u'foo"" bar')], u"\"foo\\\"\\\" bar\"")
        self.assertAsTokens([(True, u'foo\'\' bar')], u"\"foo'' bar\"")

    def test_empty_result(self):
        self.assertAsTokens([], u'')
        self.assertAsTokens([], u'    ')

    def test_quoted_empty(self):
        self.assertAsTokens([(True, '')], u'""')
        self.assertAsTokens([(False, u"''")], u"''")

    def test_unicode_chars(self):
        self.assertAsTokens([(False, u'f\xb5\xee'), (False, u'\u1234\u3456')],
                             u'f\xb5\xee \u1234\u3456')

    def test_newline_in_quoted_section(self):
        self.assertAsTokens([(True, u'foo\nbar\nbaz\n')], u'"foo\nbar\nbaz\n"')

    def test_escape_chars(self):
        self.assertAsTokens([(False, u'foo\\bar')], u'foo\\bar')

    def test_escape_quote(self):
        self.assertAsTokens([(True, u'foo"bar')], u'"foo\\"bar"')

    def test_double_escape(self):
        self.assertAsTokens([(True, u'foo\\bar')], u'"foo\\\\bar"')
        self.assertAsTokens([(False, u'foo\\\\bar')], u"foo\\\\bar")


class Test_CommandLineToArgv(tests.TestCaseInTempDir):

    def assertCommandLine(self, expected, line):
        # Strictly speaking we should respect parameter order versus glob
        # expansions, but it's not really worth the effort here
        self.assertEqual(expected,
                         sorted(win32utils._command_line_to_argv(line)))

    def test_glob_paths(self):
        self.build_tree(['a/', 'a/b.c', 'a/c.c', 'a/c.h'])
        self.assertCommandLine([u'a/b.c', u'a/c.c'], 'a/*.c')
        self.build_tree(['b/', 'b/b.c', 'b/d.c', 'b/d.h'])
        self.assertCommandLine([u'a/b.c', u'b/b.c'], '*/b.c')
        self.assertCommandLine([u'a/b.c', u'a/c.c', u'b/b.c', u'b/d.c'],
                               '*/*.c')
        # Bash style, just pass through the argument if nothing matches
        self.assertCommandLine([u'*/*.qqq'], '*/*.qqq')

    def test_quoted_globs(self):
        self.build_tree(['a/', 'a/b.c', 'a/c.c', 'a/c.h'])
        self.assertCommandLine([u'a/*.c'], '"a/*.c"')
        self.assertCommandLine([u"'a/*.c'"], "'a/*.c'")

    def test_slashes_changed(self):
        # Quoting doesn't change the supplied args
        self.assertCommandLine([u'a\\*.c'], '"a\\*.c"')
        # Expands the glob, but nothing matches, swaps slashes
        self.assertCommandLine([u'a/*.c'], 'a\\*.c')
        self.assertCommandLine([u'a/?.c'], 'a\\?.c')
        # No glob, doesn't touch slashes
        self.assertCommandLine([u'a\\foo.c'], 'a\\foo.c')

    def test_no_single_quote_supported(self):
        self.assertCommandLine(["add", "let's-do-it.txt"],
            "add let's-do-it.txt")

    def test_case_insensitive_globs(self):
        self.requireFeature(tests.CaseInsCasePresFilenameFeature)
        self.build_tree(['a/', 'a/b.c', 'a/c.c', 'a/c.h'])
        self.assertCommandLine([u'A/b.c'], 'A/B*')

    def test_backslashes(self):
        self.requireFeature(BackslashDirSeparatorFeature)
        self.build_tree(['a/', 'a/b.c', 'a/c.c', 'a/c.h'])
        self.assertCommandLine([u'a/b.c'], 'a\\b*')
