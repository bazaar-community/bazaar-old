# Copyright (C) 2005-2010 Canonical Ltd
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


"""bzr python plugin support.

When load_plugins() is invoked, any python module in any directory in
$BZR_PLUGIN_PATH will be imported.  The module will be imported as
'bzrlib.plugins.$BASENAME(PLUGIN)'.  In the plugin's main body, it should
update any bzrlib registries it wants to extend.

See the plugin-api developer documentation for information about writing
plugins.

BZR_PLUGIN_PATH is also honoured for any plugins imported via
'import bzrlib.plugins.PLUGINNAME', as long as set_plugins_path has been
called.
"""

import os
import sys

from bzrlib import osutils

from bzrlib.lazy_import import lazy_import

lazy_import(globals(), """
import imp
import re
import types

from bzrlib import (
    _format_version_tuple,
    config,
    debug,
    errors,
    trace,
    )
from bzrlib import plugins as _mod_plugins
""")

from bzrlib.symbol_versioning import (
    deprecated_function,
    deprecated_in,
    )


DEFAULT_PLUGIN_PATH = None
_loaded = False
_plugins_disabled = False


def are_plugins_disabled():
    return _plugins_disabled


def disable_plugins():
    """Disable loading plugins.

    Future calls to load_plugins() will be ignored.
    """
    global _plugins_disabled
    _plugins_disabled = True
    load_plugins([])


def _strip_trailing_sep(path):
    return path.rstrip("\\/")


def set_plugins_path(path=None):
    """Set the path for plugins to be loaded from.

    :param path: The list of paths to search for plugins.  By default,
        path will be determined using get_standard_plugins_path.
        if path is [], no plugins can be loaded.
    """
    if path is None:
        path = get_standard_plugins_path()
    # Set up a blacklist for disabled plugins if any
    clean = []
    PluginBlackListImporter.blacklist = {}
    for p in path:
        if p.startswith('-'):
            PluginBlackListImporter.blacklist[
                'bzrlib.plugins.%s' % p[1:]] = True
        else:
             clean.append(p)
    _mod_plugins.__path__ = clean
    return path


def _append_new_path(paths, new_path):
    """Append a new path if it set and not already known."""
    if new_path is not None and new_path not in paths:
        paths.append(new_path)
    return paths


def get_core_plugin_path():
    core_path = None
    bzr_exe = bool(getattr(sys, 'frozen', None))
    if bzr_exe:    # expand path for bzr.exe
        # We need to use relative path to system-wide plugin
        # directory because bzrlib from standalone bzr.exe
        # could be imported by another standalone program
        # (e.g. bzr-config; or TortoiseBzr/Olive if/when they
        # will become standalone exe). [bialix 20071123]
        # __file__ typically is
        # C:\Program Files\Bazaar\lib\library.zip\bzrlib\plugin.pyc
        # then plugins directory is
        # C:\Program Files\Bazaar\plugins
        # so relative path is ../../../plugins
        core_path = osutils.abspath(osutils.pathjoin(
                osutils.dirname(__file__), '../../../plugins'))
    else:     # don't look inside library.zip
        # search the plugin path before the bzrlib installed dir
        core_path = os.path.dirname(_mod_plugins.__file__)
    return core_path


def get_site_plugin_path():
    """Returns the path for the site installed plugins."""
    if sys.platform == 'win32':
        # We don't have (yet) a good answer for windows since that is certainly
        # related to the way we build the installers. -- vila20090821
        return None
    site_path = None
    try:
        from distutils.sysconfig import get_python_lib
    except ImportError:
        # If distutuils is not available, we just don't know where they are
        pass
    else:
        site_path = osutils.pathjoin(get_python_lib(), 'bzrlib', 'plugins')
    return site_path


def get_user_plugin_path():
    return osutils.pathjoin(config.config_dir(), 'plugins')


def get_standard_plugins_path():
    """Determine a plugin path suitable for general use."""
    # Ad-Hoc default: core is not overriden by site but user can overrides both
    # The rationale is that:
    # - 'site' comes last, because these plugins should always be available and
    #   are supposed to be in sync with the bzr installed on site.
    # - 'core' comes before 'site' so that running bzr from sources or a user
    #   installed version overrides the site version.
    # - 'user' comes first, because... user is always right.
    # - the above rules clearly defines which plugin version will be loaded if
    #   several exist. Yet, it is sometimes desirable to disable some directory
    #   so that a set of plugins is disabled as once. This can be done via
    #   -site, -core, -user.

    env_paths = os.environ.get('BZR_PLUGIN_PATH', '+user').split(os.pathsep)
    defaults = ['+core', '+site']

    # The predefined references
    refs = dict(core=get_core_plugin_path(),
                site=get_site_plugin_path(),
                user=get_user_plugin_path())

    # Unset paths that should be removed
    for k,v in refs.iteritems():
        removed = '-%s' % k
        # defaults can never mention removing paths as that will make it
        # impossible for the user to revoke these removals.
        if removed in env_paths:
            env_paths.remove(removed)
            refs[k] = None

    # Expand references
    paths = []
    for p in env_paths + defaults:
        if p.startswith('+'):
            # Resolve references if they are known
            try:
                p = refs[p[1:]]
            except KeyError:
                # Leave them untouched so user can still use paths starting
                # with '+'
                pass
        _append_new_path(paths, p)

    # Get rid of trailing slashes, since Python can't handle them when
    # it tries to import modules.
    paths = map(_strip_trailing_sep, paths)
    return paths


def load_plugins(path=None):
    """Load bzrlib plugins.

    The environment variable BZR_PLUGIN_PATH is considered a delimited
    set of paths to look through. Each entry is searched for *.py
    files (and whatever other extensions are used in the platform,
    such as *.pyd).

    load_from_path() provides the underlying mechanism and is called with
    the default directory list to provide the normal behaviour.

    :param path: The list of paths to search for plugins.  By default,
        path will be determined using get_standard_plugins_path.
        if path is [], no plugins can be loaded.
    """
    global _loaded
    if _loaded:
        # People can make sure plugins are loaded, they just won't be twice
        return
    _loaded = True

    # scan for all plugins in the path.
    load_from_path(set_plugins_path(path))


def load_from_path(dirs):
    """Load bzrlib plugins found in each dir in dirs.

    Loading a plugin means importing it into the python interpreter.
    The plugin is expected to make calls to register commands when
    it's loaded (or perhaps access other hooks in future.)

    Plugins are loaded into bzrlib.plugins.NAME, and can be found there
    for future reference.

    The python module path for bzrlib.plugins will be modified to be 'dirs'.
    """
    # We need to strip the trailing separators here as well as in the
    # set_plugins_path function because calling code can pass anything in to
    # this function, and since it sets plugins.__path__, it should set it to
    # something that will be valid for Python to use (in case people try to
    # run "import bzrlib.plugins.PLUGINNAME" after calling this function).
    _mod_plugins.__path__ = map(_strip_trailing_sep, dirs)
    for d in dirs:
        if not d:
            continue
        trace.mutter('looking for plugins in %s', d)
        if os.path.isdir(d):
            load_from_dir(d)


# backwards compatability: load_from_dirs was the old name
# This was changed in 0.15
load_from_dirs = load_from_path


def load_from_dir(d):
    """Load the plugins in directory d.

    d must be in the plugins module path already.
    """
    # Get the list of valid python suffixes for __init__.py?
    # this includes .py, .pyc, and .pyo (depending on if we are running -O)
    # but it doesn't include compiled modules (.so, .dll, etc)
    valid_suffixes = [suffix for suffix, mod_type, flags in imp.get_suffixes()
                              if flags in (imp.PY_SOURCE, imp.PY_COMPILED)]
    package_entries = ['__init__'+suffix for suffix in valid_suffixes]
    plugin_names = set()
    for f in os.listdir(d):
        path = osutils.pathjoin(d, f)
        if os.path.isdir(path):
            for entry in package_entries:
                # This directory should be a package, and thus added to
                # the list
                if os.path.isfile(osutils.pathjoin(path, entry)):
                    break
            else: # This directory is not a package
                continue
        else:
            for suffix_info in imp.get_suffixes():
                if f.endswith(suffix_info[0]):
                    f = f[:-len(suffix_info[0])]
                    if suffix_info[2] == imp.C_EXTENSION and f.endswith('module'):
                        f = f[:-len('module')]
                    break
            else:
                continue
        if f == '__init__':
            continue # We don't load __init__.py again in the plugin dir
        elif getattr(_mod_plugins, f, None):
            trace.mutter('Plugin name %s already loaded', f)
        else:
            # trace.mutter('add plugin name %s', f)
            plugin_names.add(f)

    for name in plugin_names:
        if ('bzrlib.plugins.%s' % name) in PluginBlackListImporter.blacklist:
            continue
        try:
            exec "import bzrlib.plugins.%s" % name in {}
        except KeyboardInterrupt:
            raise
        except errors.IncompatibleAPI, e:
            trace.warning("Unable to load plugin %r. It requested API version "
                "%s of module %s but the minimum exported version is %s, and "
                "the maximum is %s" %
                (name, e.wanted, e.api, e.minimum, e.current))
        except Exception, e:
            trace.warning("%s" % e)
            ## import pdb; pdb.set_trace()
            if re.search('\.|-| ', name):
                sanitised_name = re.sub('[-. ]', '_', name)
                if sanitised_name.startswith('bzr_'):
                    sanitised_name = sanitised_name[len('bzr_'):]
                trace.warning("Unable to load %r in %r as a plugin because the "
                        "file path isn't a valid module name; try renaming "
                        "it to %r." % (name, d, sanitised_name))
            else:
                trace.warning('Unable to load plugin %r from %r' % (name, d))
            trace.log_exception_quietly()
            if 'error' in debug.debug_flags:
                trace.print_exception(sys.exc_info(), sys.stderr)


def plugins():
    """Return a dictionary of the plugins.

    Each item in the dictionary is a PlugIn object.
    """
    result = {}
    for name, plugin in _mod_plugins.__dict__.items():
        if isinstance(plugin, types.ModuleType):
            result[name] = PlugIn(name, plugin)
    return result


class PluginsHelpIndex(object):
    """A help index that returns help topics for plugins."""

    def __init__(self):
        self.prefix = 'plugins/'

    def get_topics(self, topic):
        """Search for topic in the loaded plugins.

        This will not trigger loading of new plugins.

        :param topic: A topic to search for.
        :return: A list which is either empty or contains a single
            RegisteredTopic entry.
        """
        if not topic:
            return []
        if topic.startswith(self.prefix):
            topic = topic[len(self.prefix):]
        plugin_module_name = 'bzrlib.plugins.%s' % topic
        try:
            module = sys.modules[plugin_module_name]
        except KeyError:
            return []
        else:
            return [ModuleHelpTopic(module)]


class ModuleHelpTopic(object):
    """A help topic which returns the docstring for a module."""

    def __init__(self, module):
        """Constructor.

        :param module: The module for which help should be generated.
        """
        self.module = module

    def get_help_text(self, additional_see_also=None, verbose=True):
        """Return a string with the help for this topic.

        :param additional_see_also: Additional help topics to be
            cross-referenced.
        """
        if not self.module.__doc__:
            result = "Plugin '%s' has no docstring.\n" % self.module.__name__
        else:
            result = self.module.__doc__
        if result[-1] != '\n':
            result += '\n'
        # there is code duplicated here and in bzrlib/help_topic.py's
        # matching Topic code. This should probably be factored in
        # to a helper function and a common base class.
        if additional_see_also is not None:
            see_also = sorted(set(additional_see_also))
        else:
            see_also = None
        if see_also:
            result += 'See also: '
            result += ', '.join(see_also)
            result += '\n'
        return result

    def get_help_topic(self):
        """Return the modules help topic - its __name__ after bzrlib.plugins.."""
        return self.module.__name__[len('bzrlib.plugins.'):]


class PlugIn(object):
    """The bzrlib representation of a plugin.

    The PlugIn object provides a way to manipulate a given plugin module.
    """

    def __init__(self, name, module):
        """Construct a plugin for module."""
        self.name = name
        self.module = module

    def path(self):
        """Get the path that this plugin was loaded from."""
        if getattr(self.module, '__path__', None) is not None:
            return os.path.abspath(self.module.__path__[0])
        elif getattr(self.module, '__file__', None) is not None:
            path = os.path.abspath(self.module.__file__)
            if path[-4:] in ('.pyc', '.pyo'):
                pypath = path[:-4] + '.py'
                if os.path.isfile(pypath):
                    path = pypath
            return path
        else:
            return repr(self.module)

    def __str__(self):
        return "<%s.%s object at %s, name=%s, module=%s>" % (
            self.__class__.__module__, self.__class__.__name__, id(self),
            self.name, self.module)

    __repr__ = __str__

    def test_suite(self):
        """Return the plugin's test suite."""
        if getattr(self.module, 'test_suite', None) is not None:
            return self.module.test_suite()
        else:
            return None

    def load_plugin_tests(self, loader):
        """Return the adapted plugin's test suite.

        :param loader: The custom loader that should be used to load additional
            tests.

        """
        if getattr(self.module, 'load_tests', None) is not None:
            return loader.loadTestsFromModule(self.module)
        else:
            return None

    def version_info(self):
        """Return the plugin's version_tuple or None if unknown."""
        version_info = getattr(self.module, 'version_info', None)
        if version_info is not None:
            try:
                if isinstance(version_info, types.StringType):
                    version_info = version_info.split('.')
                elif len(version_info) == 3:
                    version_info = tuple(version_info) + ('final', 0)
            except TypeError, e:
                # The given version_info isn't even iteratible
                trace.log_exception_quietly()
                version_info = (version_info,)
        return version_info

    def _get__version__(self):
        version_info = self.version_info()
        if version_info is None or len(version_info) == 0:
            return "unknown"
        try:
            version_string = _format_version_tuple(version_info)
        except (ValueError, TypeError, IndexError), e:
            trace.log_exception_quietly()
            # try to return something usefull for bad plugins, in stead of
            # stack tracing.
            version_string = '.'.join(map(str, version_info))
        return version_string

    __version__ = property(_get__version__)


class _PluginBlackListImporter(object):

    def __init__(self):
        self.blacklist = {}

    def find_module(self, fullname, parent_path=None):
        if fullname in self.blacklist:
            raise ImportError('%s is disabled' % fullname)
        return None

PluginBlackListImporter = _PluginBlackListImporter()
sys.meta_path.append(PluginBlackListImporter)


