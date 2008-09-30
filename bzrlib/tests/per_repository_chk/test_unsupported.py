# Copyright (C) 2008 Canonical Ltd
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

"""Tests for repositories that do not support CHK indices.

CHK support is optional, and when it is not supported the methods and
attributes CHK support added should fail in known ways.
"""

from bzrlib.tests.per_repository_chk import TestCaseWithRepositoryCHK


class TestNoCHKSupport(TestCaseWithRepositoryCHK):

    def test_chk_bytes_attribute_is_None(self):
        repo = self.make_repository('.')
        self.assertEqual(None, repo.chk_bytes)
