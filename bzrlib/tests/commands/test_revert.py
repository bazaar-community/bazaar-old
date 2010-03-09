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
from bzrlib import (
    branch,
    builtins,
    errors,
    lock,
    )
from bzrlib.tests import transport_util


class TestRevert(
    transport_util.TestCaseWithConnectionHookedTransport):

    def setUp(self):
        super(TestRevert, self).setUp()
        self.local_wt = self.make_branch_and_tree('local')

    def test_revert_tree_write_lock_and_branch_read_lock(self):

        self.start_logging_connections()

        # make sure that the cwd is the branch
        os.chdir('local')

        # install lock hooks to find out about cmd_revert's locking actions
        locks_acquired = []
        locks_released = []
        lock.Lock.hooks.install_named_hook('lock_acquired',
            locks_acquired.append, None)
        lock.Lock.hooks.install_named_hook('lock_released',
            locks_released.append, None)

        # execute the revert command (There is nothing to actually revert,
        # but locks are acquired either way.)
        revert = builtins.cmd_revert()
        revert.run()

        # make sure that only one lock is acquired and released.
        self.assertEqual(1, len(locks_acquired))
        self.assertEqual(1, len(locks_released))

        # make sure that the nonces are the same, since otherwise
        # this would not be the same lock.
        self.assertEqual(locks_acquired[0].details, locks_released[0].details)

        # make sure that the locks are checkout locks.
        self.assertEndsWith(locks_acquired[0].lock_url, "/checkout/lock")
        self.assertEndsWith(locks_released[0].lock_url, "/checkout/lock")

