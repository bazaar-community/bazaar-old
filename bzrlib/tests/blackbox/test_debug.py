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

"""Blackbox tests for -D debug options"""

import os
import signal
import sys
import time

from bzrlib.tests import TestCaseInTempDir


class TestDebugOption(TestCaseInTempDir):

    def test_dash_derror(self):
        """With -Derror, tracebacks are shown even for user errors"""
        out, err = self.run_bzr("-Derror branch nonexistent-location",
                                retcode=3)
        # error output should contain a traceback; we used to look for code in
        # here but it may be missing if the source is not in sync with the
        # pyc file.
        self.assertContainsRe(err, "Traceback \\(most recent call last\\)")

    def test_dash_dlock(self):
        # With -Dlock, locking and unlocking is recorded into the log
        self.run_bzr("-Dlock init foo")
        log = u"".join(self.getDetails()['log'].iter_text())
        self.assertContainsRe(log, "lock_write")
