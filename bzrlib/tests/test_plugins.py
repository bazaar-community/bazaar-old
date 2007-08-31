# Copyright (C) 2005, 2007 Canonical Ltd
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

"""Tests for plugins"""

# XXX: There are no plugin tests at the moment because the plugin module
# affects the global state of the process.  See bzrlib/plugins.py for more
# comments.

import os
from StringIO import StringIO
import sys
import zipfile

from bzrlib import plugin, tests
import bzrlib.plugin
import bzrlib.plugins
import bzrlib.commands
import bzrlib.help
from bzrlib.symbol_versioning import zero_ninetyone
from bzrlib.tests import TestCase, TestCaseInTempDir
from bzrlib.osutils import pathjoin, abspath


PLUGIN_TEXT = """\
import bzrlib.commands
class cmd_myplug(bzrlib.commands.Command):
    '''Just a simple test plugin.'''
    aliases = ['mplg']
    def run(self):
        print 'Hello from my plugin'
"""

# TODO: Write a test for plugin decoration of commands.

class TestLoadingPlugins(TestCaseInTempDir):

    activeattributes = {}

    def test_plugins_with_the_same_name_are_not_loaded(self):
        # This test tests that having two plugins in different directories does
        # not result in both being loaded when they have the same name.  get a
        # file name we can use which is also a valid attribute for accessing in
        # activeattributes. - we cannot give import parameters.
        tempattribute = "0"
        self.failIf(tempattribute in self.activeattributes)
        # set a place for the plugins to record their loading, and at the same
        # time validate that the location the plugins should record to is
        # valid and correct.
        bzrlib.tests.test_plugins.TestLoadingPlugins.activeattributes \
            [tempattribute] = []
        self.failUnless(tempattribute in self.activeattributes)
        # create two plugin directories
        os.mkdir('first')
        os.mkdir('second')
        # write a plugin that will record when its loaded in the 
        # tempattribute list.
        template = ("from bzrlib.tests.test_plugins import TestLoadingPlugins\n"
                    "TestLoadingPlugins.activeattributes[%r].append('%s')\n")

        outfile = open(os.path.join('first', 'plugin.py'), 'w')
        try:
            print >> outfile, template % (tempattribute, 'first')
        finally:
            outfile.close()

        outfile = open(os.path.join('second', 'plugin.py'), 'w')
        try:
            print >> outfile, template % (tempattribute, 'second')
        finally:
            outfile.close()

        try:
            bzrlib.plugin.load_from_path(['first', 'second'])
            self.assertEqual(['first'], self.activeattributes[tempattribute])
        finally:
            # remove the plugin 'plugin'
            del self.activeattributes[tempattribute]
            if 'bzrlib.plugins.plugin' in sys.modules:
                del sys.modules['bzrlib.plugins.plugin']
            if getattr(bzrlib.plugins, 'plugin', None):
                del bzrlib.plugins.plugin
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))

    def test_plugins_from_different_dirs_can_demand_load(self):
        # This test tests that having two plugins in different
        # directories with different names allows them both to be loaded, when
        # we do a direct import statement.
        # Determine a file name we can use which is also a valid attribute
        # for accessing in activeattributes. - we cannot give import parameters.
        tempattribute = "different-dirs"
        self.failIf(tempattribute in self.activeattributes)
        # set a place for the plugins to record their loading, and at the same
        # time validate that the location the plugins should record to is
        # valid and correct.
        bzrlib.tests.test_plugins.TestLoadingPlugins.activeattributes \
            [tempattribute] = []
        self.failUnless(tempattribute in self.activeattributes)
        # create two plugin directories
        os.mkdir('first')
        os.mkdir('second')
        # write plugins that will record when they are loaded in the 
        # tempattribute list.
        template = ("from bzrlib.tests.test_plugins import TestLoadingPlugins\n"
                    "TestLoadingPlugins.activeattributes[%r].append('%s')\n")

        outfile = open(os.path.join('first', 'pluginone.py'), 'w')
        try:
            print >> outfile, template % (tempattribute, 'first')
        finally:
            outfile.close()

        outfile = open(os.path.join('second', 'plugintwo.py'), 'w')
        try:
            print >> outfile, template % (tempattribute, 'second')
        finally:
            outfile.close()

        oldpath = bzrlib.plugins.__path__
        try:
            bzrlib.plugins.__path__ = ['first', 'second']
            exec "import bzrlib.plugins.pluginone"
            self.assertEqual(['first'], self.activeattributes[tempattribute])
            exec "import bzrlib.plugins.plugintwo"
            self.assertEqual(['first', 'second'],
                self.activeattributes[tempattribute])
        finally:
            # remove the plugin 'plugin'
            del self.activeattributes[tempattribute]
            if getattr(bzrlib.plugins, 'pluginone', None):
                del bzrlib.plugins.pluginone
            if getattr(bzrlib.plugins, 'plugintwo', None):
                del bzrlib.plugins.plugintwo
        self.failIf(getattr(bzrlib.plugins, 'pluginone', None))
        self.failIf(getattr(bzrlib.plugins, 'plugintwo', None))

    def test_plugins_can_load_from_directory_with_trailing_slash(self):
        # This test tests that a plugin can load from a directory when the
        # directory in the path has a trailing slash.
        # check the plugin is not loaded already
        self.failIf(getattr(bzrlib.plugins, 'ts_plugin', None))
        tempattribute = "trailing-slash"
        self.failIf(tempattribute in self.activeattributes)
        # set a place for the plugin to record its loading, and at the same
        # time validate that the location the plugin should record to is
        # valid and correct.
        bzrlib.tests.test_plugins.TestLoadingPlugins.activeattributes \
            [tempattribute] = []
        self.failUnless(tempattribute in self.activeattributes)
        # create a directory for the plugin
        os.mkdir('plugin_test')
        # write a plugin that will record when its loaded in the 
        # tempattribute list.
        template = ("from bzrlib.tests.test_plugins import TestLoadingPlugins\n"
                    "TestLoadingPlugins.activeattributes[%r].append('%s')\n")

        outfile = open(os.path.join('plugin_test', 'ts_plugin.py'), 'w')
        try:
            print >> outfile, template % (tempattribute, 'plugin')
        finally:
            outfile.close()

        try:
            bzrlib.plugin.load_from_path(['plugin_test'+os.sep])
            self.assertEqual(['plugin'], self.activeattributes[tempattribute])
        finally:
            # remove the plugin 'plugin'
            del self.activeattributes[tempattribute]
            if getattr(bzrlib.plugins, 'ts_plugin', None):
                del bzrlib.plugins.ts_plugin
        self.failIf(getattr(bzrlib.plugins, 'ts_plugin', None))


class TestAllPlugins(TestCaseInTempDir):

    def test_plugin_appears_in_all_plugins(self):
        # This test tests a new plugin appears in bzrlib.plugin.all_plugins().
        # check the plugin is not loaded already
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))
        # write a plugin that _cannot_ fail to load.
        print >> file('plugin.py', 'w'), ""
        try:
            bzrlib.plugin.load_from_path(['.'])
            all_plugins = self.applyDeprecated(zero_ninetyone,
                bzrlib.plugin.all_plugins)
            self.failUnless('plugin' in all_plugins)
            self.failUnless(getattr(bzrlib.plugins, 'plugin', None))
            self.assertEqual(all_plugins['plugin'], bzrlib.plugins.plugin)
        finally:
            # remove the plugin 'plugin'
            if 'bzrlib.plugins.plugin' in sys.modules:
                del sys.modules['bzrlib.plugins.plugin']
            if getattr(bzrlib.plugins, 'plugin', None):
                del bzrlib.plugins.plugin
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))


class TestPlugins(TestCaseInTempDir):

    def setup_plugin(self, source=""):
        # This test tests a new plugin appears in bzrlib.plugin.plugins().
        # check the plugin is not loaded already
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))
        # write a plugin that _cannot_ fail to load.
        print >> file('plugin.py', 'w'), source
        self.addCleanup(self.teardown_plugin)
        bzrlib.plugin.load_from_path(['.'])
    
    def teardown_plugin(self):
        # remove the plugin 'plugin'
        if 'bzrlib.plugins.plugin' in sys.modules:
            del sys.modules['bzrlib.plugins.plugin']
        if getattr(bzrlib.plugins, 'plugin', None):
            del bzrlib.plugins.plugin
        self.failIf(getattr(bzrlib.plugins, 'plugin', None))

    def test_plugin_appears_in_plugins(self):
        self.setup_plugin()
        self.failUnless('plugin' in bzrlib.plugin.plugins())
        self.failUnless(getattr(bzrlib.plugins, 'plugin', None))
        plugins = bzrlib.plugin.plugins()
        plugin = plugins['plugin']
        self.assertIsInstance(plugin, bzrlib.plugin.PlugIn)
        self.assertEqual(bzrlib.plugins.plugin, plugin.module)

    def test_trivial_plugin_get_path(self):
        self.setup_plugin()
        plugins = bzrlib.plugin.plugins()
        plugin = plugins['plugin']
        plugin_path = self.test_dir + '/plugin.py'
        self.assertEqual(plugin_path, plugin.path())

    def test_no_test_suite_gives_None_for_test_suite(self):
        self.setup_plugin()
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual(None, plugin.test_suite())

    def test_test_suite_gives_test_suite_result(self):
        source = """def test_suite(): return 'foo'"""
        self.setup_plugin(source)
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual('foo', plugin.test_suite())

    def test_no_version_info(self):
        self.setup_plugin()
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual(None, plugin.version_info())

    def test_with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'dev', 4)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual((1, 2, 3, 'dev', 4), plugin.version_info())

    def test_short_version_info_gets_padded(self):
        # the gtk plugin has version_info = (1,2,3) rather than the 5-tuple.
        # so we adapt it
        self.setup_plugin("version_info = (1, 2, 3)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual((1, 2, 3, 'final', 0), plugin.version_info())

    def test_no_version_info___version__(self):
        self.setup_plugin()
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("unknown", plugin.__version__)

    def test___version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'dev', 4)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1.2.3dev4", plugin.__version__)

    def test_final__version__with_version_info(self):
        self.setup_plugin("version_info = (1, 2, 3, 'final', 4)")
        plugin = bzrlib.plugin.plugins()['plugin']
        self.assertEqual("1.2.3", plugin.__version__)


class TestPluginHelp(TestCaseInTempDir):

    def split_help_commands(self):
        help = {}
        current = None
        for line in self.run_bzr('help commands')[0].splitlines():
            if not line.startswith(' '):
                current = line.split()[0]
            help[current] = help.get(current, '') + line

        return help

    def test_plugin_help_builtins_unaffected(self):
        # Check we don't get false positives
        help_commands = self.split_help_commands()
        for cmd_name in bzrlib.commands.builtin_command_names():
            if cmd_name in bzrlib.commands.plugin_command_names():
                continue
            try:
                help = bzrlib.commands.get_cmd_object(cmd_name).get_help_text()
            except NotImplementedError:
                # some commands have no help
                pass
            else:
                self.assertNotContainsRe(help, 'plugin "[^"]*"')

            if cmd_name in help_commands.keys():
                # some commands are hidden
                help = help_commands[cmd_name]
                self.assertNotContainsRe(help, 'plugin "[^"]*"')

    def test_plugin_help_shows_plugin(self):
        # Create a test plugin
        os.mkdir('plugin_test')
        f = open(pathjoin('plugin_test', 'myplug.py'), 'w')
        f.write(PLUGIN_TEXT)
        f.close()

        try:
            # Check its help
            bzrlib.plugin.load_from_path(['plugin_test'])
            bzrlib.commands.register_command( bzrlib.plugins.myplug.cmd_myplug)
            help = self.run_bzr('help myplug')[0]
            self.assertContainsRe(help, 'plugin "myplug"')
            help = self.split_help_commands()['myplug']
            self.assertContainsRe(help, '\[myplug\]')
        finally:
            # unregister command
            if bzrlib.commands.plugin_cmds.get('myplug', None):
                del bzrlib.commands.plugin_cmds['myplug']
            # remove the plugin 'myplug'
            if getattr(bzrlib.plugins, 'myplug', None):
                delattr(bzrlib.plugins, 'myplug')


class TestPluginFromZip(TestCaseInTempDir):

    def make_zipped_plugin(self, zip_name, filename):
        z = zipfile.ZipFile(zip_name, 'w')
        z.writestr(filename, PLUGIN_TEXT)
        z.close()

    def check_plugin_load(self, zip_name, plugin_name):
        self.assertFalse(plugin_name in dir(bzrlib.plugins),
                         'Plugin already loaded')
        old_path = bzrlib.plugins.__path__
        try:
            # this is normally done by load_plugins -> set_plugins_path
            bzrlib.plugins.__path__ = [zip_name]
            bzrlib.plugin.load_from_zip(zip_name)
            self.assertTrue(plugin_name in dir(bzrlib.plugins),
                            'Plugin is not loaded')
        finally:
            # unregister plugin
            if getattr(bzrlib.plugins, plugin_name, None):
                delattr(bzrlib.plugins, plugin_name)
                del sys.modules['bzrlib.plugins.' + plugin_name]
            bzrlib.plugins.__path__ = old_path

    def test_load_module(self):
        self.make_zipped_plugin('./test.zip', 'ziplug.py')
        self.check_plugin_load('./test.zip', 'ziplug')

    def test_load_package(self):
        self.make_zipped_plugin('./test.zip', 'ziplug/__init__.py')
        self.check_plugin_load('./test.zip', 'ziplug')


class TestSetPluginsPath(TestCase):
    
    def test_set_plugins_path(self):
        """set_plugins_path should set the module __path__ correctly."""
        old_path = bzrlib.plugins.__path__
        try:
            bzrlib.plugins.__path__ = []
            expected_path = bzrlib.plugin.set_plugins_path()
            self.assertEqual(expected_path, bzrlib.plugins.__path__)
        finally:
            bzrlib.plugins.__path__ = old_path

    def test_set_plugins_path_with_trailing_slashes(self):
        """set_plugins_path should set the module __path__ based on
        BZR_PLUGIN_PATH."""
        old_path = bzrlib.plugins.__path__
        old_env = os.environ.get('BZR_PLUGIN_PATH')
        try:
            bzrlib.plugins.__path__ = []
            os.environ['BZR_PLUGIN_PATH'] = "first\\//\\" + os.pathsep + \
                "second/\\/\\/"
            bzrlib.plugin.set_plugins_path()
            expected_path = ['first', 'second',
                os.path.dirname(bzrlib.plugins.__file__)]
            self.assertEqual(expected_path, bzrlib.plugins.__path__)
        finally:
            bzrlib.plugins.__path__ = old_path
            if old_env != None:
                os.environ['BZR_PLUGIN_PATH'] = old_env
            else:
                del os.environ['BZR_PLUGIN_PATH']

class TestHelpIndex(tests.TestCase):
    """Tests for the PluginsHelpIndex class."""

    def test_default_constructable(self):
        index = plugin.PluginsHelpIndex()

    def test_get_topics_None(self):
        """Searching for None returns an empty list."""
        index = plugin.PluginsHelpIndex()
        self.assertEqual([], index.get_topics(None))

    def test_get_topics_for_plugin(self):
        """Searching for plugin name gets its docstring."""
        index = plugin.PluginsHelpIndex()
        # make a new plugin here for this test, even if we're run with
        # --no-plugins
        self.assertFalse(sys.modules.has_key('bzrlib.plugins.demo_module'))
        demo_module = FakeModule('', 'bzrlib.plugins.demo_module')
        sys.modules['bzrlib.plugins.demo_module'] = demo_module
        try:
            topics = index.get_topics('demo_module')
            self.assertEqual(1, len(topics))
            self.assertIsInstance(topics[0], plugin.ModuleHelpTopic)
            self.assertEqual(demo_module, topics[0].module)
        finally:
            del sys.modules['bzrlib.plugins.demo_module']

    def test_get_topics_no_topic(self):
        """Searching for something that is not a plugin returns []."""
        # test this by using a name that cannot be a plugin - its not
        # a valid python identifier.
        index = plugin.PluginsHelpIndex()
        self.assertEqual([], index.get_topics('nothing by this name'))

    def test_prefix(self):
        """PluginsHelpIndex has a prefix of 'plugins/'."""
        index = plugin.PluginsHelpIndex()
        self.assertEqual('plugins/', index.prefix)

    def test_get_plugin_topic_with_prefix(self):
        """Searching for plugins/demo_module returns help."""
        index = plugin.PluginsHelpIndex()
        self.assertFalse(sys.modules.has_key('bzrlib.plugins.demo_module'))
        demo_module = FakeModule('', 'bzrlib.plugins.demo_module')
        sys.modules['bzrlib.plugins.demo_module'] = demo_module
        try:
            topics = index.get_topics('plugins/demo_module')
            self.assertEqual(1, len(topics))
            self.assertIsInstance(topics[0], plugin.ModuleHelpTopic)
            self.assertEqual(demo_module, topics[0].module)
        finally:
            del sys.modules['bzrlib.plugins.demo_module']


class FakeModule(object):
    """A fake module to test with."""

    def __init__(self, doc, name):
        self.__doc__ = doc
        self.__name__ = name


class TestModuleHelpTopic(tests.TestCase):
    """Tests for the ModuleHelpTopic class."""

    def test_contruct(self):
        """Construction takes the module to document."""
        mod = FakeModule('foo', 'foo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual(mod, topic.module)

    def test_get_help_text_None(self):
        """A ModuleHelpTopic returns the docstring for get_help_text."""
        mod = FakeModule(None, 'demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("Plugin 'demo' has no docstring.\n",
            topic.get_help_text())

    def test_get_help_text_no_carriage_return(self):
        """ModuleHelpTopic.get_help_text adds a \n if needed."""
        mod = FakeModule('one line of help', 'demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("one line of help\n",
            topic.get_help_text())

    def test_get_help_text_carriage_return(self):
        """ModuleHelpTopic.get_help_text adds a \n if needed."""
        mod = FakeModule('two lines of help\nand more\n', 'demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("two lines of help\nand more\n",
            topic.get_help_text())

    def test_get_help_text_with_additional_see_also(self):
        mod = FakeModule('two lines of help\nand more', 'demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual("two lines of help\nand more\nSee also: bar, foo\n",
            topic.get_help_text(['foo', 'bar']))

    def test_get_help_topic(self):
        """The help topic for a plugin is its module name."""
        mod = FakeModule('two lines of help\nand more', 'bzrlib.plugins.demo')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual('demo', topic.get_help_topic())
        mod = FakeModule('two lines of help\nand more', 'bzrlib.plugins.foo_bar')
        topic = plugin.ModuleHelpTopic(mod)
        self.assertEqual('foo_bar', topic.get_help_topic())
