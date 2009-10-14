# Copyright (C) 2009 Canonical Ltd
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


"""Tests specific to Repository implementations that use foreign VCS'es."""


from bzrlib.tests import (
    TestCase,
    )


class TestRepositoryFormat(TestCase):

    def test_format_string(self):
        self.assertRaises(NotImplementedError, 
            self.repository_format.get_format_string)

    def test_network_name(self):
        self.assertIsInstance(self.repository_format.network_name(),
            str)

    def test_format_description(self):
        self.assertIsInstance(self.repository_format.get_format_description(),
            str)
