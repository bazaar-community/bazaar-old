# Copyright (C) 2009, 2010 Canonical Ltd
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


from bzrlib import config, errors, osutils
from bzrlib.tests import (
    TestCase,
    TestCaseWithTransport,
    )
from bzrlib.tests.features import (
    ModuleAvailableFeature,
    )


launchpadlib_feature = ModuleAvailableFeature('launchpadlib')


class TestDependencyManagement(TestCase):
    """Tests for managing the dependency on launchpadlib."""

    _test_needs_features = [launchpadlib_feature]

    def setUp(self):
        super(TestDependencyManagement, self).setUp()
        from bzrlib.plugins.launchpad import lp_api
        self.lp_api = lp_api

    def patch(self, obj, name, value):
        """Temporarily set the 'name' attribute of 'obj' to 'value'."""
        self.overrideAttr(obj, name, value)

    def test_get_launchpadlib_version(self):
        # parse_launchpadlib_version returns a tuple of a version number of
        # the style used by launchpadlib.
        version_info = self.lp_api.parse_launchpadlib_version('1.5.1')
        self.assertEqual((1, 5, 1), version_info)

    def test_supported_launchpadlib_version(self):
        # If the installed version of launchpadlib is greater than the minimum
        # required version of launchpadlib, check_launchpadlib_compatibility
        # doesn't raise an error.
        launchpadlib = launchpadlib_feature.module
        self.patch(launchpadlib, '__version__', '1.5.1')
        self.lp_api.MINIMUM_LAUNCHPADLIB_VERSION = (1, 5, 1)
        # Doesn't raise an exception.
        self.lp_api.check_launchpadlib_compatibility()

    def test_unsupported_launchpadlib_version(self):
        # If the installed version of launchpadlib is less than the minimum
        # required version of launchpadlib, check_launchpadlib_compatibility
        # raises an IncompatibleAPI error.
        launchpadlib = launchpadlib_feature.module
        self.patch(launchpadlib, '__version__', '1.5.0')
        self.lp_api.MINIMUM_LAUNCHPADLIB_VERSION = (1, 5, 1)
        self.assertRaises(
            errors.IncompatibleAPI,
            self.lp_api.check_launchpadlib_compatibility)


class TestCacheDirectory(TestCase):
    """Tests for get_cache_directory."""

    _test_needs_features = [launchpadlib_feature]

    def test_get_cache_directory(self):
        # get_cache_directory returns the path to a directory inside the
        # Bazaar configuration directory.
        from bzrlib.plugins.launchpad import lp_api
        expected_path = osutils.pathjoin(config.config_dir(), 'launchpad')
        self.assertEqual(expected_path, lp_api.get_cache_directory())


class TestLaunchpadMirror(TestCaseWithTransport):
    """Tests for the 'bzr lp-mirror' command."""

    # Testing the lp-mirror command is quite hard, since it must talk to a
    # Launchpad server. Here, we just test that the command exists.

    _test_needs_features = [launchpadlib_feature]

    def test_command_exists(self):
        out, err = self.run_bzr(['launchpad-mirror', '--help'], retcode=0)
        self.assertEqual('', err)

    def test_alias_exists(self):
        out, err = self.run_bzr(['lp-mirror', '--help'], retcode=0)
        self.assertEqual('', err)
