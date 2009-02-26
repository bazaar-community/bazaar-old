# Copyright (C) 2005, 2006, 2008 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
#            and others
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

"""These tests are tests about the source code of bzrlib itself.

They are useful for testing code quality, checking coverage metric etc.
"""

# import system imports here
import os
import parser
import re
import symbol
import sys
import token

#import bzrlib specific imports here
from bzrlib import (
    osutils,
    )
import bzrlib.branch
from bzrlib.tests import (
    TestCase,
    TestSkipped,
    )


# Files which are listed here will be skipped when testing for Copyright (or
# GPL) statements.
COPYRIGHT_EXCEPTIONS = ['bzrlib/lsprof.py']

LICENSE_EXCEPTIONS = ['bzrlib/lsprof.py']
# Technically, 'bzrlib/lsprof.py' should be 'bzrlib/util/lsprof.py',
# (we do not check bzrlib/util/, since that is code bundled from elsewhere)
# but for compatibility with previous releases, we don't want to move it.


class TestSourceHelper(TestCase):

    def source_file_name(self, package):
        """Return the path of the .py file for package."""
        if getattr(sys, "frozen", None) is not None:
            raise TestSkipped("can't test sources in frozen distributions.")
        path = package.__file__
        if path[-1] in 'co':
            return path[:-1]
        else:
            return path


class TestApiUsage(TestSourceHelper):

    def find_occurences(self, rule, filename):
        """Find the number of occurences of rule in a file."""
        occurences = 0
        source = file(filename, 'r')
        for line in source:
            if line.find(rule) > -1:
                occurences += 1
        return occurences

    def test_branch_working_tree(self):
        """Test that the number of uses of working_tree in branch is stable."""
        occurences = self.find_occurences('self.working_tree()',
                                          self.source_file_name(bzrlib.branch))
        # do not even think of increasing this number. If you think you need to
        # increase it, then you almost certainly are doing something wrong as
        # the relationship from working_tree to branch is one way.
        # Note that this is an exact equality so that when the number drops,
        #it is not given a buffer but rather has this test updated immediately.
        self.assertEqual(0, occurences)

    def test_branch_WorkingTree(self):
        """Test that the number of uses of working_tree in branch is stable."""
        occurences = self.find_occurences('WorkingTree',
                                          self.source_file_name(bzrlib.branch))
        # Do not even think of increasing this number. If you think you need to
        # increase it, then you almost certainly are doing something wrong as
        # the relationship from working_tree to branch is one way.
        # As of 20070809, there are no longer any mentions at all.
        self.assertEqual(0, occurences)


class TestSource(TestSourceHelper):

    def get_bzrlib_dir(self):
        """Get the path to the root of bzrlib"""
        source = self.source_file_name(bzrlib)
        source_dir = os.path.dirname(source)

        # Avoid the case when bzrlib is packaged in a zip file
        if not os.path.isdir(source_dir):
            raise TestSkipped('Cannot find bzrlib source directory. Expected %s'
                              % source_dir)
        return source_dir

    def get_source_files(self):
        """Yield all source files for bzr and bzrlib

        :param our_files_only: If true, exclude files from included libraries
            or plugins.
        """
        bzrlib_dir = self.get_bzrlib_dir()

        # This is the front-end 'bzr' script
        bzr_path = self.get_bzr_path()
        yield bzr_path

        for root, dirs, files in os.walk(bzrlib_dir):
            for d in dirs:
                if d.endswith('.tmp'):
                    dirs.remove(d)
            for f in files:
                if not f.endswith('.py'):
                    continue
                yield osutils.pathjoin(root, f)

    def get_source_file_contents(self):
        for fname in self.get_source_files():
            f = open(fname, 'rb')
            try:
                text = f.read()
            finally:
                f.close()
            yield fname, text

    def is_our_code(self, fname):
        """Return true if it's a "real" part of bzrlib rather than external code"""
        if '/util/' in fname or '/plugins/' in fname:
            return False
        else:
            return True

    def is_copyright_exception(self, fname):
        """Certain files are allowed to be different"""
        if not self.is_our_code(fname):
            # We don't ask that external utilities or plugins be
            # (C) Canonical Ltd
            return True
        for exc in COPYRIGHT_EXCEPTIONS:
            if fname.endswith(exc):
                return True
        return False

    def is_license_exception(self, fname):
        """Certain files are allowed to be different"""
        if not self.is_our_code(fname):
            return True
        for exc in LICENSE_EXCEPTIONS:
            if fname.endswith(exc):
                return True
        return False

    def test_tmpdir_not_in_source_files(self):
        """When scanning for source files, we don't descend test tempdirs"""
        for filename in self.get_source_files():
            if re.search(r'test....\.tmp', filename):
                self.fail("get_source_file() returned filename %r "
                          "from within a temporary directory"
                          % filename)

    def test_copyright(self):
        """Test that all .py files have a valid copyright statement"""
        # These are files which contain a different copyright statement
        # and that is okay.
        incorrect = []

        copyright_re = re.compile('#\\s*copyright.*(?=\n)', re.I)
        copyright_canonical_re = re.compile(
            r'# Copyright \(C\) ' # Opening "# Copyright (C)"
            r'(\d+)(, \d+)*' # Followed by a series of dates
            r'.*Canonical Ltd' # And containing 'Canonical Ltd'
            )

        for fname, text in self.get_source_file_contents():
            if self.is_copyright_exception(fname):
                continue
            match = copyright_canonical_re.search(text)
            if not match:
                match = copyright_re.search(text)
                if match:
                    incorrect.append((fname, 'found: %s' % (match.group(),)))
                else:
                    incorrect.append((fname, 'no copyright line found\n'))
            else:
                if 'by Canonical' in match.group():
                    incorrect.append((fname,
                        'should not have: "by Canonical": %s'
                        % (match.group(),)))

        if incorrect:
            help_text = ["Some files have missing or incorrect copyright"
                         " statements.",
                         "",
                         "Please either add them to the list of"
                         " COPYRIGHT_EXCEPTIONS in"
                         " bzrlib/tests/test_source.py",
                         # this is broken to prevent a false match
                         "or add '# Copyright (C)"
                         " 2007 Canonical Ltd' to these files:",
                         "",
                        ]
            for fname, comment in incorrect:
                help_text.append(fname)
                help_text.append((' '*4) + comment)

            self.fail('\n'.join(help_text))

    def test_gpl(self):
        """Test that all .py files have a GPL disclaimer"""
        incorrect = []

        gpl_txt = """
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
"""
        gpl_re = re.compile(re.escape(gpl_txt), re.MULTILINE)

        for fname, text in self.get_source_file_contents():
            if self.is_license_exception(fname):
                continue
            if not gpl_re.search(text):
                incorrect.append(fname)

        if incorrect:
            help_text = ['Some files have missing or incomplete GPL statement',
                         "",
                         "Please either add them to the list of"
                         " LICENSE_EXCEPTIONS in"
                         " bzrlib/tests/test_source.py",
                         "Or add the following text to the beginning:",
                         gpl_txt
                        ]
            for fname in incorrect:
                help_text.append((' '*4) + fname)

            self.fail('\n'.join(help_text))

    def _push_file(self, dict_, fname, line_no):
        if fname not in dict_:
            dict_[fname] = [line_no]
        else:
            dict_[fname].append(line_no)

    def _format_message(self, dict_, message):
        files = ["%s: %s" % (f, ', '.join([str(i+1) for i in lines]))
                for f, lines in dict_.items()]
        files.sort()
        return message + '\n\n    %s' % ('\n    '.join(files))

    def test_coding_style(self):
        """Check if bazaar code conforms to some coding style conventions.

        Currently we check for:
         * any tab characters
         * trailing white space
         * non-unix newlines
         * no newline at end of files
         * lines longer than 79 chars
           (only print how many files and lines are in violation)
        """
        tabs = {}
        trailing_ws = {}
        illegal_newlines = {}
        long_lines = {}
        no_newline_at_eof = []
        for fname, text in self.get_source_file_contents():
            if not self.is_our_code(fname):
                continue
            lines = text.splitlines(True)
            last_line_no = len(lines) - 1
            for line_no, line in enumerate(lines):
                if '\t' in line:
                    self._push_file(tabs, fname, line_no)
                if not line.endswith('\n') or line.endswith('\r\n'):
                    if line_no != last_line_no: # not no_newline_at_eof
                        self._push_file(illegal_newlines, fname, line_no)
                if line.endswith(' \n'):
                    self._push_file(trailing_ws, fname, line_no)
                if len(line) > 80:
                    self._push_file(long_lines, fname, line_no)
            if not lines[-1].endswith('\n'):
                no_newline_at_eof.append(fname)
        problems = []
        if tabs:
            problems.append(self._format_message(tabs,
                'Tab characters were found in the following source files.'
                '\nThey should either be replaced by "\\t" or by spaces:'))
        if trailing_ws:
            problems.append(self._format_message(trailing_ws,
                'Trailing white space was found in the following source files:'
                ))
        if illegal_newlines:
            problems.append(self._format_message(illegal_newlines,
                'Non-unix newlines were found in the following source files:'))
        if long_lines:
            print ("There are %i lines longer than 79 characters in %i files."
                % (sum([len(lines) for f, lines in long_lines.items()]),
                    len(long_lines)))
        if no_newline_at_eof:
            no_newline_at_eof.sort()
            problems.append("The following source files doesn't have a "
                "newline at the end:"
               '\n\n    %s'
               % ('\n    '.join(no_newline_at_eof)))
        if problems:
            self.fail('\n\n'.join(problems))

    def test_no_asserts(self):
        """bzr shouldn't use the 'assert' statement."""
        # assert causes too much variation between -O and not, and tends to
        # give bad errors to the user
        def search(x):
            # scan down through x for assert statements, report any problems
            # this is a bit cheesy; it may get some false positives?
            if x[0] == symbol.assert_stmt:
                return True
            elif x[0] == token.NAME:
                # can't search further down
                return False
            for sub in x[1:]:
                if sub and search(sub):
                    return True
            return False
        badfiles = []
        for fname, text in self.get_source_file_contents():
            if not self.is_our_code(fname):
                continue
            ast = parser.ast2tuple(parser.suite(''.join(text)))
            if search(ast):
                badfiles.append(fname)
        if badfiles:
            self.fail(
                "these files contain an assert statement and should not:\n%s"
                % '\n'.join(badfiles))
