# Copyright (C) 2009, 2010, 2011 Canonical Ltd
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


import doctest
import os
from StringIO import StringIO
import sys

from bzrlib import (
    config,
    crash,
    osutils,
    plugin,
    tests,
    )

from bzrlib.tests import features


class TestApportReporting(tests.TestCaseInTempDir):

    _test_needs_features = [features.apport]

    def test_apport_report(self):
        crash_dir = osutils.joinpath((self.test_base_dir, 'crash'))
        os.mkdir(crash_dir)
        self.overrideEnv('APPORT_CRASH_DIR', crash_dir)
        self.assertEquals(crash_dir, config.crash_dir())

        self.overrideAttr(
            plugin,
            'plugin_warnings',
            {'example': ['Failed to load plugin foo']})

        stderr = StringIO()

        try:
            raise AssertionError("my error")
        except AssertionError, e:
            pass

        crash_filename = crash.report_bug_to_apport(sys.exc_info(),
            stderr)

        # message explaining the crash
        self.assertContainsRe(stderr.getvalue(),
            "    apport-bug %s" % crash_filename)

        crash_file = open(crash_filename)
        try:
            report = crash_file.read()
        finally:
            crash_file.close()

        self.assertContainsRe(report,
            '(?m)^BzrVersion:') # should be in the traceback
        self.assertContainsRe(report, 'my error')
        self.assertContainsRe(report, 'AssertionError')
        # see https://bugs.launchpad.net/bzr/+bug/528114
        self.assertContainsRe(report, 'ExecutablePath')
        self.assertContainsRe(report, 'test_apport_report')
        # should also be in there
        self.assertContainsRe(report, '(?m)^CommandLine:')
        self.assertContainsRe(
            report,
            'Failed to load plugin foo')


class TestNonApportReporting(tests.TestCase):
    """Reporting of crash-type bugs without apport.
    
    This should work in all environments.
    """

    def setup_fake_plugins(self):
        def fake_plugins():
            fake = plugin.PlugIn('fake_plugin', plugin)
            fake.version_info = lambda: (1, 2, 3)
            return {"fake_plugin": fake}
        self.overrideAttr(plugin, 'plugins', fake_plugins)

    def test_report_bug_legacy(self):
        self.setup_fake_plugins()
        err_file = StringIO()
        try:
            raise AssertionError("my error")
        except AssertionError, e:
            pass
        crash.report_bug_legacy(sys.exc_info(), err_file)
        report = err_file.getvalue()
        for needle in [
            "bzr: ERROR: exceptions.AssertionError: my error",
            r"Traceback \(most recent call last\):",
            r"plugins: fake_plugin\[1\.2\.3\]",
            ]:
            self.assertContainsRe(
                    report,
                    needle)
