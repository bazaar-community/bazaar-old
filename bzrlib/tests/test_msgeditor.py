# Copyright (C) 2005-2011 Canonical Ltd
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

"""Test commit message editor.
"""

import os
import sys

from bzrlib import (
    commit,
    config,
    errors,
    msgeditor,
    osutils,
    tests,
    trace,
    )
from bzrlib.msgeditor import (
    make_commit_message_template_encoded,
    edit_commit_message_encoded
)
from bzrlib.tests import (
    TestCaseInTempDir,
    TestCaseWithTransport,
    TestNotApplicable,
    TestSkipped,
    multiply_tests,
    probe_bad_non_ascii,
    split_suite_by_re,
    )
from bzrlib.tests.EncodingAdapter import encoding_scenarios
from bzrlib.trace import mutter


def load_tests(standard_tests, module, loader):
    """Parameterize the test for tempfile creation with different encodings."""
    to_adapt, result = split_suite_by_re(standard_tests,
        "test__create_temp_file_with_commit_template_in_unicode_dir")
    return multiply_tests(to_adapt, encoding_scenarios, result)


class MsgEditorTest(TestCaseWithTransport):

    def make_uncommitted_tree(self):
        """Build a branch with uncommitted unicode named changes in the cwd."""
        working_tree = self.make_branch_and_tree('.')
        b = working_tree.branch
        filename = u'hell\u00d8'
        try:
            self.build_tree_contents([(filename, 'contents of hello')])
        except UnicodeEncodeError:
            raise TestSkipped("can't build unicode working tree in "
                "filesystem encoding %s" % sys.getfilesystemencoding())
        working_tree.add(filename)
        return working_tree

    def test_commit_template(self):
        """Test building a commit message template"""
        working_tree = self.make_uncommitted_tree()
        template = msgeditor.make_commit_message_template(working_tree,
                                                                 None)
        self.assertEqualDiff(template,
u"""\
added:
  hell\u00d8
""")

    def make_multiple_pending_tree(self):
        from bzrlib import config
        config.GlobalConfig().set_user_option('email',
                                              'Bilbo Baggins <bb@hobbit.net>')
        tree = self.make_branch_and_tree('a')
        tree.commit('Initial checkin.', timestamp=1230912900, timezone=0)
        tree2 = tree.bzrdir.clone('b').open_workingtree()
        tree.commit('Minor tweak.', timestamp=1231977840, timezone=0)
        tree2.commit('Feature X work.', timestamp=1233186240, timezone=0)
        tree3 = tree2.bzrdir.clone('c').open_workingtree()
        tree2.commit('Feature X finished.', timestamp=1233187680, timezone=0)
        tree3.commit('Feature Y, based on initial X work.',
                     timestamp=1233285960, timezone=0)
        tree.merge_from_branch(tree2.branch)
        tree.merge_from_branch(tree3.branch, force=True)
        return tree

    def test_commit_template_pending_merges(self):
        """Test building a commit message template when there are pending
        merges.  The commit message should show all pending merge revisions,
        as does 'status -v', not only the merge tips.
        """
        working_tree = self.make_multiple_pending_tree()
        template = msgeditor.make_commit_message_template(working_tree, None)
        self.assertEqualDiff(template,
u"""\
pending merges:
  Bilbo Baggins 2009-01-29 Feature X finished.
    Bilbo Baggins 2009-01-28 Feature X work.
  Bilbo Baggins 2009-01-30 Feature Y, based on initial X work.
""")

    def test_commit_template_encoded(self):
        """Test building a commit message template"""
        working_tree = self.make_uncommitted_tree()
        template = make_commit_message_template_encoded(working_tree,
                                                        None,
                                                        output_encoding='utf8')
        self.assertEqualDiff(template,
u"""\
added:
  hell\u00d8
""".encode("utf8"))


    def test_commit_template_and_diff(self):
        """Test building a commit message template"""
        working_tree = self.make_uncommitted_tree()
        template = make_commit_message_template_encoded(working_tree,
                                                        None,
                                                        diff=True,
                                                        output_encoding='utf8')

        self.assertTrue("""\
@@ -0,0 +1,1 @@
+contents of hello
""" in template)
        self.assertTrue(u"""\
added:
  hell\u00d8
""".encode('utf8') in template)

    def make_do_nothing_editor(self, basename='fed'):
        if sys.platform == "win32":
            name = basename + '.bat'
            f = file(name, 'w')
            f.write('@rem dummy fed')
            f.close()
            return name
        else:
            name = basename + '.sh'
            f = file(name, 'wb')
            f.write('#!/bin/sh\n')
            f.close()
            os.chmod(name, 0755)
            return './' + name

    def test_run_editor(self):
        self.overrideEnv('BZR_EDITOR', self.make_do_nothing_editor())
        self.assertEqual(True, msgeditor._run_editor(''),
                         'Unable to run dummy fake editor')

    def test_parse_editor_name(self):
        """Correctly interpret names with spaces.

        See <https://bugs.launchpad.net/bzr/+bug/220331>
        """
        self.overrideEnv('BZR_EDITOR',
            '"%s"' % self.make_do_nothing_editor('name with spaces'))
        self.assertEqual(True, msgeditor._run_editor('a_filename'))    

    def make_fake_editor(self, message='test message from fed\\n'):
        """Set up environment so that an editor will be a known script.

        Sets up BZR_EDITOR so that if an editor is spawned it will run a
        script that just adds a known message to the start of the file.
        """
        f = file('fed.py', 'wb')
        f.write('#!%s\n' % sys.executable)
        f.write("""\
# coding=utf-8
import sys
if len(sys.argv) == 2:
    fn = sys.argv[1]
    f = file(fn, 'rb')
    s = f.read()
    f.close()
    f = file(fn, 'wb')
    f.write('%s')
    f.write(s)
    f.close()
""" % (message, ))
        f.close()
        if sys.platform == "win32":
            # [win32] make batch file and set BZR_EDITOR
            f = file('fed.bat', 'w')
            f.write("""\
@echo off
"%s" fed.py %%1
""" % sys.executable)
            f.close()
            self.overrideEnv('BZR_EDITOR', 'fed.bat')
        else:
            # [non-win32] make python script executable and set BZR_EDITOR
            os.chmod('fed.py', 0755)
            self.overrideEnv('BZR_EDITOR', './fed.py')

    def test_edit_commit_message(self):
        working_tree = self.make_uncommitted_tree()
        self.make_fake_editor()

        mutter('edit_commit_message without infotext')
        self.assertEqual('test message from fed\n',
                         msgeditor.edit_commit_message(''))

        mutter('edit_commit_message with ascii string infotext')
        self.assertEqual('test message from fed\n',
                         msgeditor.edit_commit_message('spam'))

        mutter('edit_commit_message with unicode infotext')
        self.assertEqual('test message from fed\n',
                         msgeditor.edit_commit_message(u'\u1234'))

        tmpl = edit_commit_message_encoded(u'\u1234'.encode("utf8"))
        self.assertEqual('test message from fed\n', tmpl)

    def test_start_message(self):
        self.make_uncommitted_tree()
        self.make_fake_editor()
        self.assertEqual('test message from fed\nstart message\n',
                         msgeditor.edit_commit_message('',
                                              start_message='start message\n'))
        self.assertEqual('test message from fed\n',
                         msgeditor.edit_commit_message('',
                                              start_message=''))

    def test_deleted_commit_message(self):
        working_tree = self.make_uncommitted_tree()

        if sys.platform == 'win32':
            editor = 'cmd.exe /c del'
        else:
            editor = 'rm'
        self.overrideEnv('BZR_EDITOR', editor)

        self.assertRaises((IOError, OSError), msgeditor.edit_commit_message, '')

    def test__get_editor(self):
        self.overrideEnv('BZR_EDITOR', 'bzr_editor')
        self.overrideEnv('VISUAL', 'visual')
        self.overrideEnv('EDITOR', 'editor')

        conf = config.GlobalConfig.from_string('editor = config_editor\n',
                                               save=True)

        editors = list(msgeditor._get_editor())
        editors = [editor for (editor, cfg_src) in editors]

        self.assertEqual(['bzr_editor', 'config_editor', 'visual', 'editor'],
                         editors[:4])

        if sys.platform == 'win32':
            self.assertEqual(['wordpad.exe', 'notepad.exe'], editors[4:])
        else:
            self.assertEqual(['/usr/bin/editor', 'vi', 'pico', 'nano', 'joe'],
                             editors[4:])


    def test__run_editor_EACCES(self):
        """If running a configured editor raises EACESS, the user is warned."""
        self.overrideEnv('BZR_EDITOR', 'eacces.py')
        f = file('eacces.py', 'wb')
        f.write('# Not a real editor')
        f.close()
        # Make the fake editor unreadable (and unexecutable)
        os.chmod('eacces.py', 0)
        # Set $EDITOR so that _run_editor will terminate before trying real
        # editors.
        self.overrideEnv('EDITOR', self.make_do_nothing_editor())
        # Call _run_editor, capturing mutter.warning calls.
        warnings = []
        def warning(*args):
            if len(args) > 1:
                warnings.append(args[0] % args[1:])
            else:
                warnings.append(args[0])
        _warning = trace.warning
        trace.warning = warning
        try:
            msgeditor._run_editor('')
        finally:
            trace.warning = _warning
        self.assertStartsWith(warnings[0], 'Could not start editor "eacces.py"')

    def test__create_temp_file_with_commit_template(self):
        # check that commit template written properly
        # and has platform native line-endings (CRLF on win32)
        create_file = msgeditor._create_temp_file_with_commit_template
        msgfilename, hasinfo = create_file('infotext','----','start message')
        self.assertNotEqual(None, msgfilename)
        self.assertTrue(hasinfo)
        expected = os.linesep.join(['start message',
                                    '',
                                    '',
                                    '----',
                                    '',
                                    'infotext'])
        self.assertFileEqual(expected, msgfilename)

    def test__create_temp_file_with_commit_template_in_unicode_dir(self):
        self.requireFeature(tests.UnicodeFilenameFeature)
        if hasattr(self, 'info'):
            tmpdir = self.info['directory']
            os.mkdir(tmpdir)
            # Force the creation of temp file in a directory whose name
            # requires some encoding support
            msgeditor._create_temp_file_with_commit_template('infotext',
                                                             tmpdir=tmpdir)
        else:
            raise TestNotApplicable('Test run elsewhere with non-ascii data.')

    def test__create_temp_file_with_empty_commit_template(self):
        # empty file
        create_file = msgeditor._create_temp_file_with_commit_template
        msgfilename, hasinfo = create_file('')
        self.assertNotEqual(None, msgfilename)
        self.assertFalse(hasinfo)
        self.assertFileEqual('', msgfilename)

    def test_unsupported_encoding_commit_message(self):
        self.overrideEnv('LANG', 'C')
        # LANG env variable has no effect on Windows
        # but some characters anyway cannot be represented
        # in default user encoding
        char = probe_bad_non_ascii(osutils.get_user_encoding())
        if char is None:
            raise TestSkipped('Cannot find suitable non-ascii character '
                'for user_encoding (%s)' % osutils.get_user_encoding())

        self.make_fake_editor(message=char)

        working_tree = self.make_uncommitted_tree()
        self.assertRaises(errors.BadCommitMessageEncoding,
                          msgeditor.edit_commit_message, '')

    def test_set_commit_message_no_hooks(self):
        commit_obj = commit.Commit()
        self.assertIs(None,
            msgeditor.set_commit_message(commit_obj))

    def test_set_commit_message_hook(self):
        msgeditor.hooks.install_named_hook("set_commit_message",
                lambda commit_obj: "save me some typing\n", None)
        commit_obj = commit.Commit()
        self.assertEquals("save me some typing\n",
            msgeditor.set_commit_message(commit_obj))

    def test_generate_commit_message_template_no_hooks(self):
        commit_obj = commit.Commit()
        self.assertIs(None,
            msgeditor.generate_commit_message_template(commit_obj))

    def test_generate_commit_message_template_hook(self):
        msgeditor.hooks.install_named_hook("commit_message_template",
                lambda commit_obj, msg: "save me some typing\n", None)
        commit_obj = commit.Commit()
        self.assertEquals("save me some typing\n",
            msgeditor.generate_commit_message_template(commit_obj))


# GZ 2009-11-17: This wants moving to osutils when the errno checking code is
class TestPlatformErrnoWorkarounds(TestCaseInTempDir):
    """Ensuring workarounds enshrined in code actually serve a purpose"""

    def test_subprocess_call_bad_file(self):
        if sys.platform != "win32":
            raise TestNotApplicable("Workarounds for windows only")
        import subprocess, errno
        ERROR_BAD_EXE_FORMAT = 193
        file("textfile.txt", "w").close()
        e = self.assertRaises(WindowsError, subprocess.call, "textfile.txt")
        self.assertEqual(e.errno, errno.ENOEXEC)
        self.assertEqual(e.winerror, ERROR_BAD_EXE_FORMAT)
