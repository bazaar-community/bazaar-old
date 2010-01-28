# Copyright (C) 2010 by Canonical Ltd
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

# FIXME: This is totally incomplete but I'm only the patch pilot :-)
# -- vila 100120

from bzrlib import (
    option,
    tests,
    )
from bzrlib.merge import Merger
from bzrlib.plugins import news_merge
import bzrlib.plugins.news_merge.news_merge
from bzrlib.tests import test_merge_core


class TestFilenameMatchesConfig(tests.TestCaseWithTransport):

    def test_affected_files_cached(self):
        """Ensures that the config variable is cached"""
        def make_news_hook(merger):
            result = news_merge.news_merge.NewsMerger(merger)
            self.merger = result
            return result
        Merger.hooks.install_named_hook( 'merge_file_content', make_news_hook,
            'test NEWS file merge')
        builder = test_merge_core.MergeBuilder(self.test_base_dir)
        self.addCleanup(builder.cleanup)
        builder.add_file('NEWS', builder.tree_root, 'name1', 'text1', True)
        builder.change_contents('NEWS', other='text4', this='text3')
        conflicts = builder.merge()
        # The hook should set the variable
        self.assertIsNot(None, self.merger.affected_files)
