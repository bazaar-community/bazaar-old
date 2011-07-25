# Copyright (C) 2005-2011 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com>
#            and others
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

"""Configuration that affects the behaviour of Bazaar.

Currently this configuration resides in ~/.bazaar/bazaar.conf
and ~/.bazaar/locations.conf, which is written to by bzr.

In bazaar.conf the following options may be set:
[DEFAULT]
editor=name-of-program
email=Your Name <your@email.address>
check_signatures=require|ignore|check-available(default)
create_signatures=always|never|when-required(default)
gpg_signing_command=name-of-program
log_format=name-of-format
validate_signatures_in_log=true|false(default)
acceptable_keys=pattern1,pattern2

in locations.conf, you specify the url of a branch and options for it.
Wildcards may be used - * and ? as normal in shell completion. Options
set in both bazaar.conf and locations.conf are overridden by the locations.conf
setting.
[/home/robertc/source]
recurse=False|True(default)
email= as above
check_signatures= as above
create_signatures= as above.
validate_signatures_in_log=as above
acceptable_keys=as above

explanation of options
----------------------
editor - this option sets the pop up editor to use during commits.
email - this option sets the user id bzr will use when committing.
check_signatures - this option will control whether bzr will require good gpg
                   signatures, ignore them, or check them if they are
                   present.  Currently it is unused except that check_signatures
                   turns on create_signatures.
create_signatures - this option controls whether bzr will always create
                    gpg signatures or not on commits.  There is an unused
                    option which in future is expected to work if               
                    branch settings require signatures.
log_format - this option sets the default log format.  Possible values are
             long, short, line, or a plugin can register new formats.
validate_signatures_in_log - show GPG signature validity in log output
acceptable_keys - comma separated list of key patterns acceptable for
                  verify-signatures command

In bazaar.conf you can also define aliases in the ALIASES sections, example

[ALIASES]
lastlog=log --line -r-10..-1
ll=log --line -r-10..-1
h=help
up=pull
"""

import os
import string
import sys


from bzrlib.decorators import needs_write_lock
from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import fnmatch
import re
from cStringIO import StringIO

from bzrlib import (
    atomicfile,
    bzrdir,
    debug,
    errors,
    lazy_regex,
    lockdir,
    mail_client,
    mergetools,
    osutils,
    symbol_versioning,
    trace,
    transport,
    ui,
    urlutils,
    win32utils,
    )
from bzrlib.util.configobj import configobj
""")
from bzrlib import (
    commands,
    hooks,
    registry,
    )
from bzrlib.symbol_versioning import (
    deprecated_in,
    deprecated_method,
    )


CHECK_IF_POSSIBLE=0
CHECK_ALWAYS=1
CHECK_NEVER=2


SIGN_WHEN_REQUIRED=0
SIGN_ALWAYS=1
SIGN_NEVER=2


POLICY_NONE = 0
POLICY_NORECURSE = 1
POLICY_APPENDPATH = 2

_policy_name = {
    POLICY_NONE: None,
    POLICY_NORECURSE: 'norecurse',
    POLICY_APPENDPATH: 'appendpath',
    }
_policy_value = {
    None: POLICY_NONE,
    'none': POLICY_NONE,
    'norecurse': POLICY_NORECURSE,
    'appendpath': POLICY_APPENDPATH,
    }


STORE_LOCATION = POLICY_NONE
STORE_LOCATION_NORECURSE = POLICY_NORECURSE
STORE_LOCATION_APPENDPATH = POLICY_APPENDPATH
STORE_BRANCH = 3
STORE_GLOBAL = 4


class ConfigObj(configobj.ConfigObj):

    def __init__(self, infile=None, **kwargs):
        # We define our own interpolation mechanism calling it option expansion
        super(ConfigObj, self).__init__(infile=infile,
                                        interpolation=False,
                                        **kwargs)

    def get_bool(self, section, key):
        return self[section].as_bool(key)

    def get_value(self, section, name):
        # Try [] for the old DEFAULT section.
        if section == "DEFAULT":
            try:
                return self[name]
            except KeyError:
                pass
        return self[section][name]


# FIXME: Until we can guarantee that each config file is loaded once and
# only once for a given bzrlib session, we don't want to re-read the file every
# time we query for an option so we cache the value (bad ! watch out for tests
# needing to restore the proper value).This shouldn't be part of 2.4.0 final,
# yell at mgz^W vila and the RM if this is still present at that time
# -- vila 20110219
_expand_default_value = None
def _get_expand_default_value():
    global _expand_default_value
    if _expand_default_value is not None:
        return _expand_default_value
    conf = GlobalConfig()
    # Note that we must not use None for the expand value below or we'll run
    # into infinite recursion. Using False really would be quite silly ;)
    expand = conf.get_user_option_as_bool('bzr.config.expand', expand=True)
    if expand is None:
        # This is an opt-in feature, you *really* need to clearly say you want
        # to activate it !
        expand = False
    _expand_default_value = expand
    return expand


class Config(object):
    """A configuration policy - what username, editor, gpg needs etc."""

    def __init__(self):
        super(Config, self).__init__()

    def config_id(self):
        """Returns a unique ID for the config."""
        raise NotImplementedError(self.config_id)

    @deprecated_method(deprecated_in((2, 4, 0)))
    def get_editor(self):
        """Get the users pop up editor."""
        raise NotImplementedError

    def get_change_editor(self, old_tree, new_tree):
        from bzrlib import diff
        cmd = self._get_change_editor()
        if cmd is None:
            return None
        return diff.DiffFromTool.from_string(cmd, old_tree, new_tree,
                                             sys.stdout)

    def get_mail_client(self):
        """Get a mail client to use"""
        selected_client = self.get_user_option('mail_client')
        _registry = mail_client.mail_client_registry
        try:
            mail_client_class = _registry.get(selected_client)
        except KeyError:
            raise errors.UnknownMailClient(selected_client)
        return mail_client_class(self)

    def _get_signature_checking(self):
        """Template method to override signature checking policy."""

    def _get_signing_policy(self):
        """Template method to override signature creation policy."""

    option_ref_re = None

    def expand_options(self, string, env=None):
        """Expand option references in the string in the configuration context.

        :param string: The string containing option to expand.

        :param env: An option dict defining additional configuration options or
            overriding existing ones.

        :returns: The expanded string.
        """
        return self._expand_options_in_string(string, env)

    def _expand_options_in_list(self, slist, env=None, _ref_stack=None):
        """Expand options in  a list of strings in the configuration context.

        :param slist: A list of strings.

        :param env: An option dict defining additional configuration options or
            overriding existing ones.

        :param _ref_stack: Private list containing the options being
            expanded to detect loops.

        :returns: The flatten list of expanded strings.
        """
        # expand options in each value separately flattening lists
        result = []
        for s in slist:
            value = self._expand_options_in_string(s, env, _ref_stack)
            if isinstance(value, list):
                result.extend(value)
            else:
                result.append(value)
        return result

    def _expand_options_in_string(self, string, env=None, _ref_stack=None):
        """Expand options in the string in the configuration context.

        :param string: The string to be expanded.

        :param env: An option dict defining additional configuration options or
            overriding existing ones.

        :param _ref_stack: Private list containing the options being
            expanded to detect loops.

        :returns: The expanded string.
        """
        if string is None:
            # Not much to expand there
            return None
        if _ref_stack is None:
            # What references are currently resolved (to detect loops)
            _ref_stack = []
        if self.option_ref_re is None:
            # We want to match the most embedded reference first (i.e. for
            # '{{foo}}' we will get '{foo}',
            # for '{bar{baz}}' we will get '{baz}'
            self.option_ref_re = re.compile('({[^{}]+})')
        result = string
        # We need to iterate until no more refs appear ({{foo}} will need two
        # iterations for example).
        while True:
            raw_chunks = self.option_ref_re.split(result)
            if len(raw_chunks) == 1:
                # Shorcut the trivial case: no refs
                return result
            chunks = []
            list_value = False
            # Split will isolate refs so that every other chunk is a ref
            chunk_is_ref = False
            for chunk in raw_chunks:
                if not chunk_is_ref:
                    if chunk:
                        # Keep only non-empty strings (or we get bogus empty
                        # slots when a list value is involved).
                        chunks.append(chunk)
                    chunk_is_ref = True
                else:
                    name = chunk[1:-1]
                    if name in _ref_stack:
                        raise errors.OptionExpansionLoop(string, _ref_stack)
                    _ref_stack.append(name)
                    value = self._expand_option(name, env, _ref_stack)
                    if value is None:
                        raise errors.ExpandingUnknownOption(name, string)
                    if isinstance(value, list):
                        list_value = True
                        chunks.extend(value)
                    else:
                        chunks.append(value)
                    _ref_stack.pop()
                    chunk_is_ref = False
            if list_value:
                # Once a list appears as the result of an expansion, all
                # callers will get a list result. This allows a consistent
                # behavior even when some options in the expansion chain
                # defined as strings (no comma in their value) but their
                # expanded value is a list.
                return self._expand_options_in_list(chunks, env, _ref_stack)
            else:
                result = ''.join(chunks)
        return result

    def _expand_option(self, name, env, _ref_stack):
        if env is not None and name in env:
            # Special case, values provided in env takes precedence over
            # anything else
            value = env[name]
        else:
            # FIXME: This is a limited implementation, what we really need is a
            # way to query the bzr config for the value of an option,
            # respecting the scope rules (That is, once we implement fallback
            # configs, getting the option value should restart from the top
            # config, not the current one) -- vila 20101222
            value = self.get_user_option(name, expand=False)
            if isinstance(value, list):
                value = self._expand_options_in_list(value, env, _ref_stack)
            else:
                value = self._expand_options_in_string(value, env, _ref_stack)
        return value

    def _get_user_option(self, option_name):
        """Template method to provide a user option."""
        return None

    def get_user_option(self, option_name, expand=None):
        """Get a generic option - no special process, no default.

        :param option_name: The queried option.

        :param expand: Whether options references should be expanded.

        :returns: The value of the option.
        """
        if expand is None:
            expand = _get_expand_default_value()
        value = self._get_user_option(option_name)
        if expand:
            if isinstance(value, list):
                value = self._expand_options_in_list(value)
            elif isinstance(value, dict):
                trace.warning('Cannot expand "%s":'
                              ' Dicts do not support option expansion'
                              % (option_name,))
            else:
                value = self._expand_options_in_string(value)
        for hook in OldConfigHooks['get']:
            hook(self, option_name, value)
        return value

    def get_user_option_as_bool(self, option_name, expand=None, default=None):
        """Get a generic option as a boolean.

        :param expand: Allow expanding references to other config values.
        :param default: Default value if nothing is configured
        :return None if the option doesn't exist or its value can't be
            interpreted as a boolean. Returns True or False otherwise.
        """
        s = self.get_user_option(option_name, expand=expand)
        if s is None:
            # The option doesn't exist
            return default
        val = ui.bool_from_string(s)
        if val is None:
            # The value can't be interpreted as a boolean
            trace.warning('Value "%s" is not a boolean for "%s"',
                          s, option_name)
        return val

    def get_user_option_as_list(self, option_name, expand=None):
        """Get a generic option as a list - no special process, no default.

        :return None if the option doesn't exist. Returns the value as a list
            otherwise.
        """
        l = self.get_user_option(option_name, expand=expand)
        if isinstance(l, (str, unicode)):
            # A single value, most probably the user forgot (or didn't care to
            # add) the final ','
            l = [l]
        return l

    def gpg_signing_command(self):
        """What program should be used to sign signatures?"""
        result = self._gpg_signing_command()
        if result is None:
            result = "gpg"
        return result

    def _gpg_signing_command(self):
        """See gpg_signing_command()."""
        return None

    def log_format(self):
        """What log format should be used"""
        result = self._log_format()
        if result is None:
            result = "long"
        return result

    def _log_format(self):
        """See log_format()."""
        return None

    def validate_signatures_in_log(self):
        """Show GPG signature validity in log"""
        result = self._validate_signatures_in_log()
        if result == "true":
            result = True
        else:
            result = False
        return result

    def _validate_signatures_in_log(self):
        """See validate_signatures_in_log()."""
        return None

    def acceptable_keys(self):
        """Comma separated list of key patterns acceptable to 
        verify-signatures command"""
        result = self._acceptable_keys()
        return result

    def _acceptable_keys(self):
        """See acceptable_keys()."""
        return None

    def post_commit(self):
        """An ordered list of python functions to call.

        Each function takes branch, rev_id as parameters.
        """
        return self._post_commit()

    def _post_commit(self):
        """See Config.post_commit."""
        return None

    def user_email(self):
        """Return just the email component of a username."""
        return extract_email_address(self.username())

    def username(self):
        """Return email-style username.

        Something similar to 'Martin Pool <mbp@sourcefrog.net>'

        $BZR_EMAIL can be set to override this, then
        the concrete policy type is checked, and finally
        $EMAIL is examined.
        If no username can be found, errors.NoWhoami exception is raised.
        """
        v = os.environ.get('BZR_EMAIL')
        if v:
            return v.decode(osutils.get_user_encoding())
        v = self._get_user_id()
        if v:
            return v
        v = os.environ.get('EMAIL')
        if v:
            return v.decode(osutils.get_user_encoding())
        name, email = _auto_user_id()
        if name and email:
            return '%s <%s>' % (name, email)
        elif email:
            return email
        raise errors.NoWhoami()

    def ensure_username(self):
        """Raise errors.NoWhoami if username is not set.

        This method relies on the username() function raising the error.
        """
        self.username()

    def signature_checking(self):
        """What is the current policy for signature checking?."""
        policy = self._get_signature_checking()
        if policy is not None:
            return policy
        return CHECK_IF_POSSIBLE

    def signing_policy(self):
        """What is the current policy for signature checking?."""
        policy = self._get_signing_policy()
        if policy is not None:
            return policy
        return SIGN_WHEN_REQUIRED

    def signature_needed(self):
        """Is a signature needed when committing ?."""
        policy = self._get_signing_policy()
        if policy is None:
            policy = self._get_signature_checking()
            if policy is not None:
                #this warning should go away once check_signatures is
                #implemented (if not before)
                trace.warning("Please use create_signatures,"
                              " not check_signatures to set signing policy.")
        elif policy == SIGN_ALWAYS:
            return True
        return False

    def get_alias(self, value):
        return self._get_alias(value)

    def _get_alias(self, value):
        pass

    def get_nickname(self):
        return self._get_nickname()

    def _get_nickname(self):
        return None

    def get_bzr_remote_path(self):
        try:
            return os.environ['BZR_REMOTE_PATH']
        except KeyError:
            path = self.get_user_option("bzr_remote_path")
            if path is None:
                path = 'bzr'
            return path

    def suppress_warning(self, warning):
        """Should the warning be suppressed or emitted.

        :param warning: The name of the warning being tested.

        :returns: True if the warning should be suppressed, False otherwise.
        """
        warnings = self.get_user_option_as_list('suppress_warnings')
        if warnings is None or warning not in warnings:
            return False
        else:
            return True

    def get_merge_tools(self):
        tools = {}
        for (oname, value, section, conf_id, parser) in self._get_options():
            if oname.startswith('bzr.mergetool.'):
                tool_name = oname[len('bzr.mergetool.'):]
                tools[tool_name] = value
        trace.mutter('loaded merge tools: %r' % tools)
        return tools

    def find_merge_tool(self, name):
        # We fake a defaults mechanism here by checking if the given name can
        # be found in the known_merge_tools if it's not found in the config.
        # This should be done through the proposed config defaults mechanism
        # when it becomes available in the future.
        command_line = (self.get_user_option('bzr.mergetool.%s' % name,
                                             expand=False)
                        or mergetools.known_merge_tools.get(name, None))
        return command_line


class _ConfigHooks(hooks.Hooks):
    """A dict mapping hook names and a list of callables for configs.
    """

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        super(_ConfigHooks, self).__init__('bzrlib.config', 'ConfigHooks')
        self.add_hook('load',
                      'Invoked when a config store is loaded.'
                      ' The signature is (store).',
                      (2, 4))
        self.add_hook('save',
                      'Invoked when a config store is saved.'
                      ' The signature is (store).',
                      (2, 4))
        # The hooks for config options
        self.add_hook('get',
                      'Invoked when a config option is read.'
                      ' The signature is (stack, name, value).',
                      (2, 4))
        self.add_hook('set',
                      'Invoked when a config option is set.'
                      ' The signature is (stack, name, value).',
                      (2, 4))
        self.add_hook('remove',
                      'Invoked when a config option is removed.'
                      ' The signature is (stack, name).',
                      (2, 4))
ConfigHooks = _ConfigHooks()


class _OldConfigHooks(hooks.Hooks):
    """A dict mapping hook names and a list of callables for configs.
    """

    def __init__(self):
        """Create the default hooks.

        These are all empty initially, because by default nothing should get
        notified.
        """
        super(_OldConfigHooks, self).__init__('bzrlib.config', 'OldConfigHooks')
        self.add_hook('load',
                      'Invoked when a config store is loaded.'
                      ' The signature is (config).',
                      (2, 4))
        self.add_hook('save',
                      'Invoked when a config store is saved.'
                      ' The signature is (config).',
                      (2, 4))
        # The hooks for config options
        self.add_hook('get',
                      'Invoked when a config option is read.'
                      ' The signature is (config, name, value).',
                      (2, 4))
        self.add_hook('set',
                      'Invoked when a config option is set.'
                      ' The signature is (config, name, value).',
                      (2, 4))
        self.add_hook('remove',
                      'Invoked when a config option is removed.'
                      ' The signature is (config, name).',
                      (2, 4))
OldConfigHooks = _OldConfigHooks()


class IniBasedConfig(Config):
    """A configuration policy that draws from ini files."""

    def __init__(self, get_filename=symbol_versioning.DEPRECATED_PARAMETER,
                 file_name=None):
        """Base class for configuration files using an ini-like syntax.

        :param file_name: The configuration file path.
        """
        super(IniBasedConfig, self).__init__()
        self.file_name = file_name
        if symbol_versioning.deprecated_passed(get_filename):
            symbol_versioning.warn(
                'IniBasedConfig.__init__(get_filename) was deprecated in 2.3.'
                ' Use file_name instead.',
                DeprecationWarning,
                stacklevel=2)
            if get_filename is not None:
                self.file_name = get_filename()
        else:
            self.file_name = file_name
        self._content = None
        self._parser = None

    @classmethod
    def from_string(cls, str_or_unicode, file_name=None, save=False):
        """Create a config object from a string.

        :param str_or_unicode: A string representing the file content. This will
            be utf-8 encoded.

        :param file_name: The configuration file path.

        :param _save: Whether the file should be saved upon creation.
        """
        conf = cls(file_name=file_name)
        conf._create_from_string(str_or_unicode, save)
        return conf

    def _create_from_string(self, str_or_unicode, save):
        self._content = StringIO(str_or_unicode.encode('utf-8'))
        # Some tests use in-memory configs, some other always need the config
        # file to exist on disk.
        if save:
            self._write_config_file()

    def _get_parser(self, file=symbol_versioning.DEPRECATED_PARAMETER):
        if self._parser is not None:
            return self._parser
        if symbol_versioning.deprecated_passed(file):
            symbol_versioning.warn(
                'IniBasedConfig._get_parser(file=xxx) was deprecated in 2.3.'
                ' Use IniBasedConfig(_content=xxx) instead.',
                DeprecationWarning,
                stacklevel=2)
        if self._content is not None:
            co_input = self._content
        elif self.file_name is None:
            raise AssertionError('We have no content to create the config')
        else:
            co_input = self.file_name
        try:
            self._parser = ConfigObj(co_input, encoding='utf-8')
        except configobj.ConfigObjError, e:
            raise errors.ParseConfigError(e.errors, e.config.filename)
        except UnicodeDecodeError:
            raise errors.ConfigContentError(self.file_name)
        # Make sure self.reload() will use the right file name
        self._parser.filename = self.file_name
        for hook in OldConfigHooks['load']:
            hook(self)
        return self._parser

    def reload(self):
        """Reload the config file from disk."""
        if self.file_name is None:
            raise AssertionError('We need a file name to reload the config')
        if self._parser is not None:
            self._parser.reload()
        for hook in ConfigHooks['load']:
            hook(self)

    def _get_matching_sections(self):
        """Return an ordered list of (section_name, extra_path) pairs.

        If the section contains inherited configuration, extra_path is
        a string containing the additional path components.
        """
        section = self._get_section()
        if section is not None:
            return [(section, '')]
        else:
            return []

    def _get_section(self):
        """Override this to define the section used by the config."""
        return "DEFAULT"

    def _get_sections(self, name=None):
        """Returns an iterator of the sections specified by ``name``.

        :param name: The section name. If None is supplied, the default
            configurations are yielded.

        :return: A tuple (name, section, config_id) for all sections that will
            be walked by user_get_option() in the 'right' order. The first one
            is where set_user_option() will update the value.
        """
        parser = self._get_parser()
        if name is not None:
            yield (name, parser[name], self.config_id())
        else:
            # No section name has been given so we fallback to the configobj
            # itself which holds the variables defined outside of any section.
            yield (None, parser, self.config_id())

    def _get_options(self, sections=None):
        """Return an ordered list of (name, value, section, config_id) tuples.

        All options are returned with their associated value and the section
        they appeared in. ``config_id`` is a unique identifier for the
        configuration file the option is defined in.

        :param sections: Default to ``_get_matching_sections`` if not
            specified. This gives a better control to daughter classes about
            which sections should be searched. This is a list of (name,
            configobj) tuples.
        """
        opts = []
        if sections is None:
            parser = self._get_parser()
            sections = []
            for (section_name, _) in self._get_matching_sections():
                try:
                    section = parser[section_name]
                except KeyError:
                    # This could happen for an empty file for which we define a
                    # DEFAULT section. FIXME: Force callers to provide sections
                    # instead ? -- vila 20100930
                    continue
                sections.append((section_name, section))
        config_id = self.config_id()
        for (section_name, section) in sections:
            for (name, value) in section.iteritems():
                yield (name, parser._quote(value), section_name,
                       config_id, parser)

    def _get_option_policy(self, section, option_name):
        """Return the policy for the given (section, option_name) pair."""
        return POLICY_NONE

    def _get_change_editor(self):
        return self.get_user_option('change_editor')

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        policy = self._get_user_option('check_signatures')
        if policy:
            return self._string_to_signature_policy(policy)

    def _get_signing_policy(self):
        """See Config._get_signing_policy"""
        policy = self._get_user_option('create_signatures')
        if policy:
            return self._string_to_signing_policy(policy)

    def _get_user_id(self):
        """Get the user id from the 'email' key in the current section."""
        return self._get_user_option('email')

    def _get_user_option(self, option_name):
        """See Config._get_user_option."""
        for (section, extra_path) in self._get_matching_sections():
            try:
                value = self._get_parser().get_value(section, option_name)
            except KeyError:
                continue
            policy = self._get_option_policy(section, option_name)
            if policy == POLICY_NONE:
                return value
            elif policy == POLICY_NORECURSE:
                # norecurse items only apply to the exact path
                if extra_path:
                    continue
                else:
                    return value
            elif policy == POLICY_APPENDPATH:
                if extra_path:
                    value = urlutils.join(value, extra_path)
                return value
            else:
                raise AssertionError('Unexpected config policy %r' % policy)
        else:
            return None

    def _gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        return self._get_user_option('gpg_signing_command')

    def _log_format(self):
        """See Config.log_format."""
        return self._get_user_option('log_format')

    def _validate_signatures_in_log(self):
        """See Config.validate_signatures_in_log."""
        return self._get_user_option('validate_signatures_in_log')

    def _acceptable_keys(self):
        """See Config.acceptable_keys."""
        return self._get_user_option('acceptable_keys')

    def _post_commit(self):
        """See Config.post_commit."""
        return self._get_user_option('post_commit')

    def _string_to_signature_policy(self, signature_string):
        """Convert a string to a signing policy."""
        if signature_string.lower() == 'check-available':
            return CHECK_IF_POSSIBLE
        if signature_string.lower() == 'ignore':
            return CHECK_NEVER
        if signature_string.lower() == 'require':
            return CHECK_ALWAYS
        raise errors.BzrError("Invalid signatures policy '%s'"
                              % signature_string)

    def _string_to_signing_policy(self, signature_string):
        """Convert a string to a signing policy."""
        if signature_string.lower() == 'when-required':
            return SIGN_WHEN_REQUIRED
        if signature_string.lower() == 'never':
            return SIGN_NEVER
        if signature_string.lower() == 'always':
            return SIGN_ALWAYS
        raise errors.BzrError("Invalid signing policy '%s'"
                              % signature_string)

    def _get_alias(self, value):
        try:
            return self._get_parser().get_value("ALIASES",
                                                value)
        except KeyError:
            pass

    def _get_nickname(self):
        return self.get_user_option('nickname')

    def remove_user_option(self, option_name, section_name=None):
        """Remove a user option and save the configuration file.

        :param option_name: The option to be removed.

        :param section_name: The section the option is defined in, default to
            the default section.
        """
        self.reload()
        parser = self._get_parser()
        if section_name is None:
            section = parser
        else:
            section = parser[section_name]
        try:
            del section[option_name]
        except KeyError:
            raise errors.NoSuchConfigOption(option_name)
        self._write_config_file()
        for hook in OldConfigHooks['remove']:
            hook(self, option_name)

    def _write_config_file(self):
        if self.file_name is None:
            raise AssertionError('We cannot save, self.file_name is None')
        conf_dir = os.path.dirname(self.file_name)
        ensure_config_dir_exists(conf_dir)
        atomic_file = atomicfile.AtomicFile(self.file_name)
        self._get_parser().write(atomic_file)
        atomic_file.commit()
        atomic_file.close()
        osutils.copy_ownership_from_path(self.file_name)
        for hook in OldConfigHooks['save']:
            hook(self)


class LockableConfig(IniBasedConfig):
    """A configuration needing explicit locking for access.

    If several processes try to write the config file, the accesses need to be
    serialized.

    Daughter classes should decorate all methods that update a config with the
    ``@needs_write_lock`` decorator (they call, directly or indirectly, the
    ``_write_config_file()`` method. These methods (typically ``set_option()``
    and variants must reload the config file from disk before calling
    ``_write_config_file()``), this can be achieved by calling the
    ``self.reload()`` method. Note that the lock scope should cover both the
    reading and the writing of the config file which is why the decorator can't
    be applied to ``_write_config_file()`` only.

    This should be enough to implement the following logic:
    - lock for exclusive write access,
    - reload the config file from disk,
    - set the new value
    - unlock

    This logic guarantees that a writer can update a value without erasing an
    update made by another writer.
    """

    lock_name = 'lock'

    def __init__(self, file_name):
        super(LockableConfig, self).__init__(file_name=file_name)
        self.dir = osutils.dirname(osutils.safe_unicode(self.file_name))
        # FIXME: It doesn't matter that we don't provide possible_transports
        # below since this is currently used only for local config files ;
        # local transports are not shared. But if/when we start using
        # LockableConfig for other kind of transports, we will need to reuse
        # whatever connection is already established -- vila 20100929
        self.transport = transport.get_transport(self.dir)
        self._lock = lockdir.LockDir(self.transport, self.lock_name)

    def _create_from_string(self, unicode_bytes, save):
        super(LockableConfig, self)._create_from_string(unicode_bytes, False)
        if save:
            # We need to handle the saving here (as opposed to IniBasedConfig)
            # to be able to lock
            self.lock_write()
            self._write_config_file()
            self.unlock()

    def lock_write(self, token=None):
        """Takes a write lock in the directory containing the config file.

        If the directory doesn't exist it is created.
        """
        ensure_config_dir_exists(self.dir)
        return self._lock.lock_write(token)

    def unlock(self):
        self._lock.unlock()

    def break_lock(self):
        self._lock.break_lock()

    @needs_write_lock
    def remove_user_option(self, option_name, section_name=None):
        super(LockableConfig, self).remove_user_option(option_name,
                                                       section_name)

    def _write_config_file(self):
        if self._lock is None or not self._lock.is_held:
            # NB: if the following exception is raised it probably means a
            # missing @needs_write_lock decorator on one of the callers.
            raise errors.ObjectNotLocked(self)
        super(LockableConfig, self)._write_config_file()


class GlobalConfig(LockableConfig):
    """The configuration that should be used for a specific location."""

    def __init__(self):
        super(GlobalConfig, self).__init__(file_name=config_filename())

    def config_id(self):
        return 'bazaar'

    @classmethod
    def from_string(cls, str_or_unicode, save=False):
        """Create a config object from a string.

        :param str_or_unicode: A string representing the file content. This
            will be utf-8 encoded.

        :param save: Whether the file should be saved upon creation.
        """
        conf = cls()
        conf._create_from_string(str_or_unicode, save)
        return conf

    @deprecated_method(deprecated_in((2, 4, 0)))
    def get_editor(self):
        return self._get_user_option('editor')

    @needs_write_lock
    def set_user_option(self, option, value):
        """Save option and its value in the configuration."""
        self._set_option(option, value, 'DEFAULT')

    def get_aliases(self):
        """Return the aliases section."""
        if 'ALIASES' in self._get_parser():
            return self._get_parser()['ALIASES']
        else:
            return {}

    @needs_write_lock
    def set_alias(self, alias_name, alias_command):
        """Save the alias in the configuration."""
        self._set_option(alias_name, alias_command, 'ALIASES')

    @needs_write_lock
    def unset_alias(self, alias_name):
        """Unset an existing alias."""
        self.reload()
        aliases = self._get_parser().get('ALIASES')
        if not aliases or alias_name not in aliases:
            raise errors.NoSuchAlias(alias_name)
        del aliases[alias_name]
        self._write_config_file()

    def _set_option(self, option, value, section):
        self.reload()
        self._get_parser().setdefault(section, {})[option] = value
        self._write_config_file()
        for hook in OldConfigHooks['set']:
            hook(self, option, value)

    def _get_sections(self, name=None):
        """See IniBasedConfig._get_sections()."""
        parser = self._get_parser()
        # We don't give access to options defined outside of any section, we
        # used the DEFAULT section by... default.
        if name in (None, 'DEFAULT'):
            # This could happen for an empty file where the DEFAULT section
            # doesn't exist yet. So we force DEFAULT when yielding
            name = 'DEFAULT'
            if 'DEFAULT' not in parser:
               parser['DEFAULT']= {}
        yield (name, parser[name], self.config_id())

    @needs_write_lock
    def remove_user_option(self, option_name, section_name=None):
        if section_name is None:
            # We need to force the default section.
            section_name = 'DEFAULT'
        # We need to avoid the LockableConfig implementation or we'll lock
        # twice
        super(LockableConfig, self).remove_user_option(option_name,
                                                       section_name)

def _iter_for_location_by_parts(sections, location):
    """Keep only the sessions matching the specified location.

    :param sections: An iterable of section names.

    :param location: An url or a local path to match against.

    :returns: An iterator of (section, extra_path, nb_parts) where nb is the
        number of path components in the section name, section is the section
        name and extra_path is the difference between location and the section
        name.

    ``location`` will always be a local path and never a 'file://' url but the
    section names themselves can be in either form.
    """
    location_parts = location.rstrip('/').split('/')

    for section in sections:
        # location is a local path if possible, so we need to convert 'file://'
        # urls in section names to local paths if necessary.

        # This also avoids having file:///path be a more exact
        # match than '/path'.

        # FIXME: This still raises an issue if a user defines both file:///path
        # *and* /path. Should we raise an error in this case -- vila 20110505

        if section.startswith('file://'):
            section_path = urlutils.local_path_from_url(section)
        else:
            section_path = section
        section_parts = section_path.rstrip('/').split('/')

        matched = True
        if len(section_parts) > len(location_parts):
            # More path components in the section, they can't match
            matched = False
        else:
            # Rely on zip truncating in length to the length of the shortest
            # argument sequence.
            names = zip(location_parts, section_parts)
            for name in names:
                if not fnmatch.fnmatch(name[0], name[1]):
                    matched = False
                    break
        if not matched:
            continue
        # build the path difference between the section and the location
        extra_path = '/'.join(location_parts[len(section_parts):])
        yield section, extra_path, len(section_parts)


class LocationConfig(LockableConfig):
    """A configuration object that gives the policy for a location."""

    def __init__(self, location):
        super(LocationConfig, self).__init__(
            file_name=locations_config_filename())
        # local file locations are looked up by local path, rather than
        # by file url. This is because the config file is a user
        # file, and we would rather not expose the user to file urls.
        if location.startswith('file://'):
            location = urlutils.local_path_from_url(location)
        self.location = location

    def config_id(self):
        return 'locations'

    @classmethod
    def from_string(cls, str_or_unicode, location, save=False):
        """Create a config object from a string.

        :param str_or_unicode: A string representing the file content. This will
            be utf-8 encoded.

        :param location: The location url to filter the configuration.

        :param save: Whether the file should be saved upon creation.
        """
        conf = cls(location)
        conf._create_from_string(str_or_unicode, save)
        return conf

    def _get_matching_sections(self):
        """Return an ordered list of section names matching this location."""
        matches = list(_iter_for_location_by_parts(self._get_parser(),
                                                   self.location))
        # put the longest (aka more specific) locations first
        matches.sort(
            key=lambda (section, extra_path, length): (length, section),
            reverse=True)
        for (section, extra_path, length) in matches:
            yield section, extra_path
            # should we stop looking for parent configs here?
            try:
                if self._get_parser()[section].as_bool('ignore_parents'):
                    break
            except KeyError:
                pass

    def _get_sections(self, name=None):
        """See IniBasedConfig._get_sections()."""
        # We ignore the name here as the only sections handled are named with
        # the location path and we don't expose embedded sections either.
        parser = self._get_parser()
        for name, extra_path in self._get_matching_sections():
            yield (name, parser[name], self.config_id())

    def _get_option_policy(self, section, option_name):
        """Return the policy for the given (section, option_name) pair."""
        # check for the old 'recurse=False' flag
        try:
            recurse = self._get_parser()[section].as_bool('recurse')
        except KeyError:
            recurse = True
        if not recurse:
            return POLICY_NORECURSE

        policy_key = option_name + ':policy'
        try:
            policy_name = self._get_parser()[section][policy_key]
        except KeyError:
            policy_name = None

        return _policy_value[policy_name]

    def _set_option_policy(self, section, option_name, option_policy):
        """Set the policy for the given option name in the given section."""
        # The old recurse=False option affects all options in the
        # section.  To handle multiple policies in the section, we
        # need to convert it to a policy_norecurse key.
        try:
            recurse = self._get_parser()[section].as_bool('recurse')
        except KeyError:
            pass
        else:
            symbol_versioning.warn(
                'The recurse option is deprecated as of 0.14.  '
                'The section "%s" has been converted to use policies.'
                % section,
                DeprecationWarning)
            del self._get_parser()[section]['recurse']
            if not recurse:
                for key in self._get_parser()[section].keys():
                    if not key.endswith(':policy'):
                        self._get_parser()[section][key +
                                                    ':policy'] = 'norecurse'

        policy_key = option_name + ':policy'
        policy_name = _policy_name[option_policy]
        if policy_name is not None:
            self._get_parser()[section][policy_key] = policy_name
        else:
            if policy_key in self._get_parser()[section]:
                del self._get_parser()[section][policy_key]

    @needs_write_lock
    def set_user_option(self, option, value, store=STORE_LOCATION):
        """Save option and its value in the configuration."""
        if store not in [STORE_LOCATION,
                         STORE_LOCATION_NORECURSE,
                         STORE_LOCATION_APPENDPATH]:
            raise ValueError('bad storage policy %r for %r' %
                (store, option))
        self.reload()
        location = self.location
        if location.endswith('/'):
            location = location[:-1]
        parser = self._get_parser()
        if not location in parser and not location + '/' in parser:
            parser[location] = {}
        elif location + '/' in parser:
            location = location + '/'
        parser[location][option]=value
        # the allowed values of store match the config policies
        self._set_option_policy(location, option, store)
        self._write_config_file()
        for hook in OldConfigHooks['set']:
            hook(self, option, value)


class BranchConfig(Config):
    """A configuration object giving the policy for a branch."""

    def __init__(self, branch):
        super(BranchConfig, self).__init__()
        self._location_config = None
        self._branch_data_config = None
        self._global_config = None
        self.branch = branch
        self.option_sources = (self._get_location_config,
                               self._get_branch_data_config,
                               self._get_global_config)

    def config_id(self):
        return 'branch'

    def _get_branch_data_config(self):
        if self._branch_data_config is None:
            self._branch_data_config = TreeConfig(self.branch)
            self._branch_data_config.config_id = self.config_id
        return self._branch_data_config

    def _get_location_config(self):
        if self._location_config is None:
            self._location_config = LocationConfig(self.branch.base)
        return self._location_config

    def _get_global_config(self):
        if self._global_config is None:
            self._global_config = GlobalConfig()
        return self._global_config

    def _get_best_value(self, option_name):
        """This returns a user option from local, tree or global config.

        They are tried in that order.  Use get_safe_value if trusted values
        are necessary.
        """
        for source in self.option_sources:
            value = getattr(source(), option_name)()
            if value is not None:
                return value
        return None

    def _get_safe_value(self, option_name):
        """This variant of get_best_value never returns untrusted values.

        It does not return values from the branch data, because the branch may
        not be controlled by the user.

        We may wish to allow locations.conf to control whether branches are
        trusted in the future.
        """
        for source in (self._get_location_config, self._get_global_config):
            value = getattr(source(), option_name)()
            if value is not None:
                return value
        return None

    def _get_user_id(self):
        """Return the full user id for the branch.

        e.g. "John Hacker <jhacker@example.com>"
        This is looked up in the email controlfile for the branch.
        """
        try:
            return (self.branch._transport.get_bytes("email")
                    .decode(osutils.get_user_encoding())
                    .rstrip("\r\n"))
        except errors.NoSuchFile, e:
            pass

        return self._get_best_value('_get_user_id')

    def _get_change_editor(self):
        return self._get_best_value('_get_change_editor')

    def _get_signature_checking(self):
        """See Config._get_signature_checking."""
        return self._get_best_value('_get_signature_checking')

    def _get_signing_policy(self):
        """See Config._get_signing_policy."""
        return self._get_best_value('_get_signing_policy')

    def _get_user_option(self, option_name):
        """See Config._get_user_option."""
        for source in self.option_sources:
            value = source()._get_user_option(option_name)
            if value is not None:
                return value
        return None

    def _get_sections(self, name=None):
        """See IniBasedConfig.get_sections()."""
        for source in self.option_sources:
            for section in source()._get_sections(name):
                yield section

    def _get_options(self, sections=None):
        opts = []
        # First the locations options
        for option in self._get_location_config()._get_options():
            yield option
        # Then the branch options
        branch_config = self._get_branch_data_config()
        if sections is None:
            sections = [('DEFAULT', branch_config._get_parser())]
        # FIXME: We shouldn't have to duplicate the code in IniBasedConfig but
        # Config itself has no notion of sections :( -- vila 20101001
        config_id = self.config_id()
        for (section_name, section) in sections:
            for (name, value) in section.iteritems():
                yield (name, value, section_name,
                       config_id, branch_config._get_parser())
        # Then the global options
        for option in self._get_global_config()._get_options():
            yield option

    def set_user_option(self, name, value, store=STORE_BRANCH,
        warn_masked=False):
        if store == STORE_BRANCH:
            self._get_branch_data_config().set_option(value, name)
        elif store == STORE_GLOBAL:
            self._get_global_config().set_user_option(name, value)
        else:
            self._get_location_config().set_user_option(name, value, store)
        if not warn_masked:
            return
        if store in (STORE_GLOBAL, STORE_BRANCH):
            mask_value = self._get_location_config().get_user_option(name)
            if mask_value is not None:
                trace.warning('Value "%s" is masked by "%s" from'
                              ' locations.conf', value, mask_value)
            else:
                if store == STORE_GLOBAL:
                    branch_config = self._get_branch_data_config()
                    mask_value = branch_config.get_user_option(name)
                    if mask_value is not None:
                        trace.warning('Value "%s" is masked by "%s" from'
                                      ' branch.conf', value, mask_value)

    def remove_user_option(self, option_name, section_name=None):
        self._get_branch_data_config().remove_option(option_name, section_name)

    def _gpg_signing_command(self):
        """See Config.gpg_signing_command."""
        return self._get_safe_value('_gpg_signing_command')

    def _post_commit(self):
        """See Config.post_commit."""
        return self._get_safe_value('_post_commit')

    def _get_nickname(self):
        value = self._get_explicit_nickname()
        if value is not None:
            return value
        return urlutils.unescape(self.branch.base.split('/')[-2])

    def has_explicit_nickname(self):
        """Return true if a nickname has been explicitly assigned."""
        return self._get_explicit_nickname() is not None

    def _get_explicit_nickname(self):
        return self._get_best_value('_get_nickname')

    def _log_format(self):
        """See Config.log_format."""
        return self._get_best_value('_log_format')

    def _validate_signatures_in_log(self):
        """See Config.validate_signatures_in_log."""
        return self._get_best_value('_validate_signatures_in_log')

    def _acceptable_keys(self):
        """See Config.acceptable_keys."""
        return self._get_best_value('_acceptable_keys')


def ensure_config_dir_exists(path=None):
    """Make sure a configuration directory exists.
    This makes sure that the directory exists.
    On windows, since configuration directories are 2 levels deep,
    it makes sure both the directory and the parent directory exists.
    """
    if path is None:
        path = config_dir()
    if not os.path.isdir(path):
        if sys.platform == 'win32':
            parent_dir = os.path.dirname(path)
            if not os.path.isdir(parent_dir):
                trace.mutter('creating config parent directory: %r', parent_dir)
                os.mkdir(parent_dir)
        trace.mutter('creating config directory: %r', path)
        os.mkdir(path)
        osutils.copy_ownership_from_path(path)


def config_dir():
    """Return per-user configuration directory.

    By default this is %APPDATA%/bazaar/2.0 on Windows, ~/.bazaar on Mac OS X
    and Linux.  On Linux, if there is a $XDG_CONFIG_HOME/bazaar directory,
    that will be used instead.

    TODO: Global option --config-dir to override this.
    """
    base = os.environ.get('BZR_HOME', None)
    if sys.platform == 'win32':
        # environ variables on Windows are in user encoding/mbcs. So decode
        # before using one
        if base is not None:
            base = base.decode('mbcs')
        if base is None:
            base = win32utils.get_appdata_location_unicode()
        if base is None:
            base = os.environ.get('HOME', None)
            if base is not None:
                base = base.decode('mbcs')
        if base is None:
            raise errors.BzrError('You must have one of BZR_HOME, APPDATA,'
                                  ' or HOME set')
        return osutils.pathjoin(base, 'bazaar', '2.0')
    elif sys.platform == 'darwin':
        if base is None:
            # this takes into account $HOME
            base = os.path.expanduser("~")
        return osutils.pathjoin(base, '.bazaar')
    else:
        if base is None:

            xdg_dir = os.environ.get('XDG_CONFIG_HOME', None)
            if xdg_dir is None:
                xdg_dir = osutils.pathjoin(os.path.expanduser("~"), ".config")
            xdg_dir = osutils.pathjoin(xdg_dir, 'bazaar')
            if osutils.isdir(xdg_dir):
                trace.mutter(
                    "Using configuration in XDG directory %s." % xdg_dir)
                return xdg_dir

            base = os.path.expanduser("~")
        return osutils.pathjoin(base, ".bazaar")


def config_filename():
    """Return per-user configuration ini file filename."""
    return osutils.pathjoin(config_dir(), 'bazaar.conf')


def locations_config_filename():
    """Return per-user configuration ini file filename."""
    return osutils.pathjoin(config_dir(), 'locations.conf')


def authentication_config_filename():
    """Return per-user authentication ini file filename."""
    return osutils.pathjoin(config_dir(), 'authentication.conf')


def user_ignore_config_filename():
    """Return the user default ignore filename"""
    return osutils.pathjoin(config_dir(), 'ignore')


def crash_dir():
    """Return the directory name to store crash files.

    This doesn't implicitly create it.

    On Windows it's in the config directory; elsewhere it's /var/crash
    which may be monitored by apport.  It can be overridden by
    $APPORT_CRASH_DIR.
    """
    if sys.platform == 'win32':
        return osutils.pathjoin(config_dir(), 'Crash')
    else:
        # XXX: hardcoded in apport_python_hook.py; therefore here too -- mbp
        # 2010-01-31
        return os.environ.get('APPORT_CRASH_DIR', '/var/crash')


def xdg_cache_dir():
    # See http://standards.freedesktop.org/basedir-spec/latest/ar01s03.html
    # Possibly this should be different on Windows?
    e = os.environ.get('XDG_CACHE_DIR', None)
    if e:
        return e
    else:
        return os.path.expanduser('~/.cache')


def _get_default_mail_domain():
    """If possible, return the assumed default email domain.

    :returns: string mail domain, or None.
    """
    if sys.platform == 'win32':
        # No implementation yet; patches welcome
        return None
    try:
        f = open('/etc/mailname')
    except (IOError, OSError), e:
        return None
    try:
        domain = f.read().strip()
        return domain
    finally:
        f.close()


def _auto_user_id():
    """Calculate automatic user identification.

    :returns: (realname, email), either of which may be None if they can't be
    determined.

    Only used when none is set in the environment or the id file.

    This only returns an email address if we can be fairly sure the 
    address is reasonable, ie if /etc/mailname is set on unix.

    This doesn't use the FQDN as the default domain because that may be 
    slow, and it doesn't use the hostname alone because that's not normally 
    a reasonable address.
    """
    if sys.platform == 'win32':
        # No implementation to reliably determine Windows default mail
        # address; please add one.
        return None, None

    default_mail_domain = _get_default_mail_domain()
    if not default_mail_domain:
        return None, None

    import pwd
    uid = os.getuid()
    try:
        w = pwd.getpwuid(uid)
    except KeyError:
        trace.mutter('no passwd entry for uid %d?' % uid)
        return None, None

    # we try utf-8 first, because on many variants (like Linux),
    # /etc/passwd "should" be in utf-8, and because it's unlikely to give
    # false positives.  (many users will have their user encoding set to
    # latin-1, which cannot raise UnicodeError.)
    try:
        gecos = w.pw_gecos.decode('utf-8')
        encoding = 'utf-8'
    except UnicodeError:
        try:
            encoding = osutils.get_user_encoding()
            gecos = w.pw_gecos.decode(encoding)
        except UnicodeError, e:
            trace.mutter("cannot decode passwd entry %s" % w)
            return None, None
    try:
        username = w.pw_name.decode(encoding)
    except UnicodeError, e:
        trace.mutter("cannot decode passwd entry %s" % w)
        return None, None

    comma = gecos.find(',')
    if comma == -1:
        realname = gecos
    else:
        realname = gecos[:comma]

    return realname, (username + '@' + default_mail_domain)


def parse_username(username):
    """Parse e-mail username and return a (name, address) tuple."""
    match = re.match(r'(.*?)\s*<?([\w+.-]+@[\w+.-]+)>?', username)
    if match is None:
        return (username, '')
    else:
        return (match.group(1), match.group(2))


def extract_email_address(e):
    """Return just the address part of an email string.

    That is just the user@domain part, nothing else.
    This part is required to contain only ascii characters.
    If it can't be extracted, raises an error.

    >>> extract_email_address('Jane Tester <jane@test.com>')
    "jane@test.com"
    """
    name, email = parse_username(e)
    if not email:
        raise errors.NoEmailInUsername(e)
    return email


class TreeConfig(IniBasedConfig):
    """Branch configuration data associated with its contents, not location"""

    # XXX: Really needs a better name, as this is not part of the tree! -- mbp 20080507

    def __init__(self, branch):
        self._config = branch._get_config()
        self.branch = branch

    def _get_parser(self, file=None):
        if file is not None:
            return IniBasedConfig._get_parser(file)
        return self._config._get_configobj()

    def get_option(self, name, section=None, default=None):
        self.branch.lock_read()
        try:
            return self._config.get_option(name, section, default)
        finally:
            self.branch.unlock()

    def set_option(self, value, name, section=None):
        """Set a per-branch configuration option"""
        # FIXME: We shouldn't need to lock explicitly here but rather rely on
        # higher levels providing the right lock -- vila 20101004
        self.branch.lock_write()
        try:
            self._config.set_option(value, name, section)
        finally:
            self.branch.unlock()

    def remove_option(self, option_name, section_name=None):
        # FIXME: We shouldn't need to lock explicitly here but rather rely on
        # higher levels providing the right lock -- vila 20101004
        self.branch.lock_write()
        try:
            self._config.remove_option(option_name, section_name)
        finally:
            self.branch.unlock()


class AuthenticationConfig(object):
    """The authentication configuration file based on a ini file.

    Implements the authentication.conf file described in
    doc/developers/authentication-ring.txt.
    """

    def __init__(self, _file=None):
        self._config = None # The ConfigObj
        if _file is None:
            self._filename = authentication_config_filename()
            self._input = self._filename = authentication_config_filename()
        else:
            # Tests can provide a string as _file
            self._filename = None
            self._input = _file

    def _get_config(self):
        if self._config is not None:
            return self._config
        try:
            # FIXME: Should we validate something here ? Includes: empty
            # sections are useless, at least one of
            # user/password/password_encoding should be defined, etc.

            # Note: the encoding below declares that the file itself is utf-8
            # encoded, but the values in the ConfigObj are always Unicode.
            self._config = ConfigObj(self._input, encoding='utf-8')
        except configobj.ConfigObjError, e:
            raise errors.ParseConfigError(e.errors, e.config.filename)
        except UnicodeError:
            raise errors.ConfigContentError(self._filename)
        return self._config

    def _save(self):
        """Save the config file, only tests should use it for now."""
        conf_dir = os.path.dirname(self._filename)
        ensure_config_dir_exists(conf_dir)
        f = file(self._filename, 'wb')
        try:
            self._get_config().write(f)
        finally:
            f.close()

    def _set_option(self, section_name, option_name, value):
        """Set an authentication configuration option"""
        conf = self._get_config()
        section = conf.get(section_name)
        if section is None:
            conf[section] = {}
            section = conf[section]
        section[option_name] = value
        self._save()

    def get_credentials(self, scheme, host, port=None, user=None, path=None,
                        realm=None):
        """Returns the matching credentials from authentication.conf file.

        :param scheme: protocol

        :param host: the server address

        :param port: the associated port (optional)

        :param user: login (optional)

        :param path: the absolute path on the server (optional)
        
        :param realm: the http authentication realm (optional)

        :return: A dict containing the matching credentials or None.
           This includes:
           - name: the section name of the credentials in the
             authentication.conf file,
           - user: can't be different from the provided user if any,
           - scheme: the server protocol,
           - host: the server address,
           - port: the server port (can be None),
           - path: the absolute server path (can be None),
           - realm: the http specific authentication realm (can be None),
           - password: the decoded password, could be None if the credential
             defines only the user
           - verify_certificates: https specific, True if the server
             certificate should be verified, False otherwise.
        """
        credentials = None
        for auth_def_name, auth_def in self._get_config().items():
            if type(auth_def) is not configobj.Section:
                raise ValueError("%s defined outside a section" % auth_def_name)

            a_scheme, a_host, a_user, a_path = map(
                auth_def.get, ['scheme', 'host', 'user', 'path'])

            try:
                a_port = auth_def.as_int('port')
            except KeyError:
                a_port = None
            except ValueError:
                raise ValueError("'port' not numeric in %s" % auth_def_name)
            try:
                a_verify_certificates = auth_def.as_bool('verify_certificates')
            except KeyError:
                a_verify_certificates = True
            except ValueError:
                raise ValueError(
                    "'verify_certificates' not boolean in %s" % auth_def_name)

            # Attempt matching
            if a_scheme is not None and scheme != a_scheme:
                continue
            if a_host is not None:
                if not (host == a_host
                        or (a_host.startswith('.') and host.endswith(a_host))):
                    continue
            if a_port is not None and port != a_port:
                continue
            if (a_path is not None and path is not None
                and not path.startswith(a_path)):
                continue
            if (a_user is not None and user is not None
                and a_user != user):
                # Never contradict the caller about the user to be used
                continue
            if a_user is None:
                # Can't find a user
                continue
            # Prepare a credentials dictionary with additional keys
            # for the credential providers
            credentials = dict(name=auth_def_name,
                               user=a_user,
                               scheme=a_scheme,
                               host=host,
                               port=port,
                               path=path,
                               realm=realm,
                               password=auth_def.get('password', None),
                               verify_certificates=a_verify_certificates)
            # Decode the password in the credentials (or get one)
            self.decode_password(credentials,
                                 auth_def.get('password_encoding', None))
            if 'auth' in debug.debug_flags:
                trace.mutter("Using authentication section: %r", auth_def_name)
            break

        if credentials is None:
            # No credentials were found in authentication.conf, try the fallback
            # credentials stores.
            credentials = credential_store_registry.get_fallback_credentials(
                scheme, host, port, user, path, realm)

        return credentials

    def set_credentials(self, name, host, user, scheme=None, password=None,
                        port=None, path=None, verify_certificates=None,
                        realm=None):
        """Set authentication credentials for a host.

        Any existing credentials with matching scheme, host, port and path
        will be deleted, regardless of name.

        :param name: An arbitrary name to describe this set of credentials.
        :param host: Name of the host that accepts these credentials.
        :param user: The username portion of these credentials.
        :param scheme: The URL scheme (e.g. ssh, http) the credentials apply
            to.
        :param password: Password portion of these credentials.
        :param port: The IP port on the host that these credentials apply to.
        :param path: A filesystem path on the host that these credentials
            apply to.
        :param verify_certificates: On https, verify server certificates if
            True.
        :param realm: The http authentication realm (optional).
        """
        values = {'host': host, 'user': user}
        if password is not None:
            values['password'] = password
        if scheme is not None:
            values['scheme'] = scheme
        if port is not None:
            values['port'] = '%d' % port
        if path is not None:
            values['path'] = path
        if verify_certificates is not None:
            values['verify_certificates'] = str(verify_certificates)
        if realm is not None:
            values['realm'] = realm
        config = self._get_config()
        for_deletion = []
        for section, existing_values in config.items():
            for key in ('scheme', 'host', 'port', 'path', 'realm'):
                if existing_values.get(key) != values.get(key):
                    break
            else:
                del config[section]
        config.update({name: values})
        self._save()

    def get_user(self, scheme, host, port=None, realm=None, path=None,
                 prompt=None, ask=False, default=None):
        """Get a user from authentication file.

        :param scheme: protocol

        :param host: the server address

        :param port: the associated port (optional)

        :param realm: the realm sent by the server (optional)

        :param path: the absolute path on the server (optional)

        :param ask: Ask the user if there is no explicitly configured username 
                    (optional)

        :param default: The username returned if none is defined (optional).

        :return: The found user.
        """
        credentials = self.get_credentials(scheme, host, port, user=None,
                                           path=path, realm=realm)
        if credentials is not None:
            user = credentials['user']
        else:
            user = None
        if user is None:
            if ask:
                if prompt is None:
                    # Create a default prompt suitable for most cases
                    prompt = u'%s' % (scheme.upper(),) + u' %(host)s username'
                # Special handling for optional fields in the prompt
                if port is not None:
                    prompt_host = '%s:%d' % (host, port)
                else:
                    prompt_host = host
                user = ui.ui_factory.get_username(prompt, host=prompt_host)
            else:
                user = default
        return user

    def get_password(self, scheme, host, user, port=None,
                     realm=None, path=None, prompt=None):
        """Get a password from authentication file or prompt the user for one.

        :param scheme: protocol

        :param host: the server address

        :param port: the associated port (optional)

        :param user: login

        :param realm: the realm sent by the server (optional)

        :param path: the absolute path on the server (optional)

        :return: The found password or the one entered by the user.
        """
        credentials = self.get_credentials(scheme, host, port, user, path,
                                           realm)
        if credentials is not None:
            password = credentials['password']
            if password is not None and scheme is 'ssh':
                trace.warning('password ignored in section [%s],'
                              ' use an ssh agent instead'
                              % credentials['name'])
                password = None
        else:
            password = None
        # Prompt user only if we could't find a password
        if password is None:
            if prompt is None:
                # Create a default prompt suitable for most cases
                prompt = u'%s' % scheme.upper() + u' %(user)s@%(host)s password'
            # Special handling for optional fields in the prompt
            if port is not None:
                prompt_host = '%s:%d' % (host, port)
            else:
                prompt_host = host
            password = ui.ui_factory.get_password(prompt,
                                                  host=prompt_host, user=user)
        return password

    def decode_password(self, credentials, encoding):
        try:
            cs = credential_store_registry.get_credential_store(encoding)
        except KeyError:
            raise ValueError('%r is not a known password_encoding' % encoding)
        credentials['password'] = cs.decode_password(credentials)
        return credentials


class CredentialStoreRegistry(registry.Registry):
    """A class that registers credential stores.

    A credential store provides access to credentials via the password_encoding
    field in authentication.conf sections.

    Except for stores provided by bzr itself, most stores are expected to be
    provided by plugins that will therefore use
    register_lazy(password_encoding, module_name, member_name, help=help,
    fallback=fallback) to install themselves.

    A fallback credential store is one that is queried if no credentials can be
    found via authentication.conf.
    """

    def get_credential_store(self, encoding=None):
        cs = self.get(encoding)
        if callable(cs):
            cs = cs()
        return cs

    def is_fallback(self, name):
        """Check if the named credentials store should be used as fallback."""
        return self.get_info(name)

    def get_fallback_credentials(self, scheme, host, port=None, user=None,
                                 path=None, realm=None):
        """Request credentials from all fallback credentials stores.

        The first credentials store that can provide credentials wins.
        """
        credentials = None
        for name in self.keys():
            if not self.is_fallback(name):
                continue
            cs = self.get_credential_store(name)
            credentials = cs.get_credentials(scheme, host, port, user,
                                             path, realm)
            if credentials is not None:
                # We found some credentials
                break
        return credentials

    def register(self, key, obj, help=None, override_existing=False,
                 fallback=False):
        """Register a new object to a name.

        :param key: This is the key to use to request the object later.
        :param obj: The object to register.
        :param help: Help text for this entry. This may be a string or
                a callable. If it is a callable, it should take two
                parameters (registry, key): this registry and the key that
                the help was registered under.
        :param override_existing: Raise KeyErorr if False and something has
                already been registered for that key. If True, ignore if there
                is an existing key (always register the new value).
        :param fallback: Whether this credential store should be 
                used as fallback.
        """
        return super(CredentialStoreRegistry,
                     self).register(key, obj, help, info=fallback,
                                    override_existing=override_existing)

    def register_lazy(self, key, module_name, member_name,
                      help=None, override_existing=False,
                      fallback=False):
        """Register a new credential store to be loaded on request.

        :param module_name: The python path to the module. Such as 'os.path'.
        :param member_name: The member of the module to return.  If empty or
                None, get() will return the module itself.
        :param help: Help text for this entry. This may be a string or
                a callable.
        :param override_existing: If True, replace the existing object
                with the new one. If False, if there is already something
                registered with the same key, raise a KeyError
        :param fallback: Whether this credential store should be 
                used as fallback.
        """
        return super(CredentialStoreRegistry, self).register_lazy(
            key, module_name, member_name, help,
            info=fallback, override_existing=override_existing)


credential_store_registry = CredentialStoreRegistry()


class CredentialStore(object):
    """An abstract class to implement storage for credentials"""

    def decode_password(self, credentials):
        """Returns a clear text password for the provided credentials."""
        raise NotImplementedError(self.decode_password)

    def get_credentials(self, scheme, host, port=None, user=None, path=None,
                        realm=None):
        """Return the matching credentials from this credential store.

        This method is only called on fallback credential stores.
        """
        raise NotImplementedError(self.get_credentials)



class PlainTextCredentialStore(CredentialStore):
    __doc__ = """Plain text credential store for the authentication.conf file"""

    def decode_password(self, credentials):
        """See CredentialStore.decode_password."""
        return credentials['password']


credential_store_registry.register('plain', PlainTextCredentialStore,
                                   help=PlainTextCredentialStore.__doc__)
credential_store_registry.default_key = 'plain'


class BzrDirConfig(object):

    def __init__(self, bzrdir):
        self._bzrdir = bzrdir
        self._config = bzrdir._get_config()

    def set_default_stack_on(self, value):
        """Set the default stacking location.

        It may be set to a location, or None.

        This policy affects all branches contained by this bzrdir, except for
        those under repositories.
        """
        if self._config is None:
            raise errors.BzrError("Cannot set configuration in %s" % self._bzrdir)
        if value is None:
            self._config.set_option('', 'default_stack_on')
        else:
            self._config.set_option(value, 'default_stack_on')

    def get_default_stack_on(self):
        """Return the default stacking location.

        This will either be a location, or None.

        This policy affects all branches contained by this bzrdir, except for
        those under repositories.
        """
        if self._config is None:
            return None
        value = self._config.get_option('default_stack_on')
        if value == '':
            value = None
        return value


class TransportConfig(object):
    """A Config that reads/writes a config file on a Transport.

    It is a low-level object that considers config data to be name/value pairs
    that may be associated with a section.  Assigning meaning to these values
    is done at higher levels like TreeConfig.
    """

    def __init__(self, transport, filename):
        self._transport = transport
        self._filename = filename

    def get_option(self, name, section=None, default=None):
        """Return the value associated with a named option.

        :param name: The name of the value
        :param section: The section the option is in (if any)
        :param default: The value to return if the value is not set
        :return: The value or default value
        """
        configobj = self._get_configobj()
        if section is None:
            section_obj = configobj
        else:
            try:
                section_obj = configobj[section]
            except KeyError:
                return default
        value = section_obj.get(name, default)
        for hook in OldConfigHooks['get']:
            hook(self, name, value)
        return value

    def set_option(self, value, name, section=None):
        """Set the value associated with a named option.

        :param value: The value to set
        :param name: The name of the value to set
        :param section: The section the option is in (if any)
        """
        configobj = self._get_configobj()
        if section is None:
            configobj[name] = value
        else:
            configobj.setdefault(section, {})[name] = value
        for hook in OldConfigHooks['set']:
            hook(self, name, value)
        self._set_configobj(configobj)

    def remove_option(self, option_name, section_name=None):
        configobj = self._get_configobj()
        if section_name is None:
            del configobj[option_name]
        else:
            del configobj[section_name][option_name]
        for hook in OldConfigHooks['remove']:
            hook(self, option_name)
        self._set_configobj(configobj)

    def _get_config_file(self):
        try:
            f = StringIO(self._transport.get_bytes(self._filename))
            for hook in OldConfigHooks['load']:
                hook(self)
            return f
        except errors.NoSuchFile:
            return StringIO()

    def _external_url(self):
        return urlutils.join(self._transport.external_url(), self._filename)

    def _get_configobj(self):
        f = self._get_config_file()
        try:
            try:
                conf = ConfigObj(f, encoding='utf-8')
            except configobj.ConfigObjError, e:
                raise errors.ParseConfigError(e.errors, self._external_url())
            except UnicodeDecodeError:
                raise errors.ConfigContentError(self._external_url())
        finally:
            f.close()
        return conf

    def _set_configobj(self, configobj):
        out_file = StringIO()
        configobj.write(out_file)
        out_file.seek(0)
        self._transport.put_file(self._filename, out_file)
        for hook in OldConfigHooks['save']:
            hook(self)


class Option(object):
    """An option definition.

    The option *values* are stored in config files and found in sections.

    Here we define various properties about the option itself, its default
    value, in which config files it can be stored, etc (TBC).
    """

    def __init__(self, name, default=None):
        self.name = name
        self.default = default

    def get_default(self):
        return self.default


# Options registry

option_registry = registry.Registry()


option_registry.register(
    'editor', Option('editor'),
    help='The command called to launch an editor to enter a message.')

option_registry.register(
    'dirstate.fdatasync', Option('dirstate.fdatasync', default=True),
    help='Flush dirstate changes onto physical disk?')

option_registry.register(
    'repository.fdatasync',
    Option('repository.fdatasync', default=True),
    help='Flush repository changes onto physical disk?')


class Section(object):
    """A section defines a dict of option name => value.

    This is merely a read-only dict which can add some knowledge about the
    options. It is *not* a python dict object though and doesn't try to mimic
    its API.
    """

    def __init__(self, section_id, options):
        self.id = section_id
        # We re-use the dict-like object received
        self.options = options

    def get(self, name, default=None):
        return self.options.get(name, default)

    def __repr__(self):
        # Mostly for debugging use
        return "<config.%s id=%s>" % (self.__class__.__name__, self.id)


_NewlyCreatedOption = object()
"""Was the option created during the MutableSection lifetime"""


class MutableSection(Section):
    """A section allowing changes and keeping track of the original values."""

    def __init__(self, section_id, options):
        super(MutableSection, self).__init__(section_id, options)
        self.orig = {}

    def set(self, name, value):
        if name not in self.options:
            # This is a new option
            self.orig[name] = _NewlyCreatedOption
        elif name not in self.orig:
            self.orig[name] = self.get(name, None)
        self.options[name] = value

    def remove(self, name):
        if name not in self.orig:
            self.orig[name] = self.get(name, None)
        del self.options[name]


class Store(object):
    """Abstract interface to persistent storage for configuration options."""

    readonly_section_class = Section
    mutable_section_class = MutableSection

    def is_loaded(self):
        """Returns True if the Store has been loaded.

        This is used to implement lazy loading and ensure the persistent
        storage is queried only when needed.
        """
        raise NotImplementedError(self.is_loaded)

    def load(self):
        """Loads the Store from persistent storage."""
        raise NotImplementedError(self.load)

    def _load_from_string(self, bytes):
        """Create a store from a string in configobj syntax.

        :param bytes: A string representing the file content.
        """
        raise NotImplementedError(self._load_from_string)

    def unload(self):
        """Unloads the Store.

        This should make is_loaded() return False. This is used when the caller
        knows that the persistent storage has changed or may have change since
        the last load.
        """
        raise NotImplementedError(self.unload)

    def save(self):
        """Saves the Store to persistent storage."""
        raise NotImplementedError(self.save)

    def external_url(self):
        raise NotImplementedError(self.external_url)

    def get_sections(self):
        """Returns an ordered iterable of existing sections.

        :returns: An iterable of (name, dict).
        """
        raise NotImplementedError(self.get_sections)

    def get_mutable_section(self, section_name=None):
        """Returns the specified mutable section.

        :param section_name: The section identifier
        """
        raise NotImplementedError(self.get_mutable_section)

    def __repr__(self):
        # Mostly for debugging use
        return "<config.%s(%s)>" % (self.__class__.__name__,
                                    self.external_url())


class IniFileStore(Store):
    """A config Store using ConfigObj for storage.

    :ivar transport: The transport object where the config file is located.

    :ivar file_name: The config file basename in the transport directory.

    :ivar _config_obj: Private member to hold the ConfigObj instance used to
        serialize/deserialize the config file.
    """

    def __init__(self, transport, file_name):
        """A config Store using ConfigObj for storage.

        :param transport: The transport object where the config file is located.

        :param file_name: The config file basename in the transport directory.
        """
        super(IniFileStore, self).__init__()
        self.transport = transport
        self.file_name = file_name
        self._config_obj = None

    def is_loaded(self):
        return self._config_obj != None

    def unload(self):
        self._config_obj = None

    def load(self):
        """Load the store from the associated file."""
        if self.is_loaded():
            return
        content = self.transport.get_bytes(self.file_name)
        self._load_from_string(content)
        for hook in ConfigHooks['load']:
            hook(self)

    def _load_from_string(self, bytes):
        """Create a config store from a string.

        :param bytes: A string representing the file content.
        """
        if self.is_loaded():
            raise AssertionError('Already loaded: %r' % (self._config_obj,))
        co_input = StringIO(bytes)
        try:
            # The config files are always stored utf8-encoded
            self._config_obj = ConfigObj(co_input, encoding='utf-8')
        except configobj.ConfigObjError, e:
            self._config_obj = None
            raise errors.ParseConfigError(e.errors, self.external_url())
        except UnicodeDecodeError:
            raise errors.ConfigContentError(self.external_url())

    def save(self):
        if not self.is_loaded():
            # Nothing to save
            return
        out = StringIO()
        self._config_obj.write(out)
        self.transport.put_bytes(self.file_name, out.getvalue())
        for hook in ConfigHooks['save']:
            hook(self)

    def external_url(self):
        # FIXME: external_url should really accepts an optional relpath
        # parameter (bug #750169) :-/ -- vila 2011-04-04
        # The following will do in the interim but maybe we don't want to
        # expose a path here but rather a config ID and its associated
        # object </hand wawe>.
        return urlutils.join(self.transport.external_url(), self.file_name)

    def get_sections(self):
        """Get the configobj section in the file order.

        :returns: An iterable of (name, dict).
        """
        # We need a loaded store
        try:
            self.load()
        except errors.NoSuchFile:
            # If the file doesn't exist, there is no sections
            return
        cobj = self._config_obj
        if cobj.scalars:
            yield self.readonly_section_class(None, cobj)
        for section_name in cobj.sections:
            yield self.readonly_section_class(section_name, cobj[section_name])

    def get_mutable_section(self, section_name=None):
        # We need a loaded store
        try:
            self.load()
        except errors.NoSuchFile:
            # The file doesn't exist, let's pretend it was empty
            self._load_from_string('')
        if section_name is None:
            section = self._config_obj
        else:
            section = self._config_obj.setdefault(section_name, {})
        return self.mutable_section_class(section_name, section)


# Note that LockableConfigObjStore inherits from ConfigObjStore because we need
# unlockable stores for use with objects that can already ensure the locking
# (think branches). If different stores (not based on ConfigObj) are created,
# they may face the same issue.


class LockableIniFileStore(IniFileStore):
    """A ConfigObjStore using locks on save to ensure store integrity."""

    def __init__(self, transport, file_name, lock_dir_name=None):
        """A config Store using ConfigObj for storage.

        :param transport: The transport object where the config file is located.

        :param file_name: The config file basename in the transport directory.
        """
        if lock_dir_name is None:
            lock_dir_name = 'lock'
        self.lock_dir_name = lock_dir_name
        super(LockableIniFileStore, self).__init__(transport, file_name)
        self._lock = lockdir.LockDir(self.transport, self.lock_dir_name)

    def lock_write(self, token=None):
        """Takes a write lock in the directory containing the config file.

        If the directory doesn't exist it is created.
        """
        # FIXME: This doesn't check the ownership of the created directories as
        # ensure_config_dir_exists does. It should if the transport is local
        # -- vila 2011-04-06
        self.transport.create_prefix()
        return self._lock.lock_write(token)

    def unlock(self):
        self._lock.unlock()

    def break_lock(self):
        self._lock.break_lock()

    @needs_write_lock
    def save(self):
        # We need to be able to override the undecorated implementation
        self.save_without_locking()

    def save_without_locking(self):
        super(LockableIniFileStore, self).save()


# FIXME: global, bazaar, shouldn't that be 'user' instead or even
# 'user_defaults' as opposed to 'user_overrides', 'system_defaults'
# (/etc/bzr/bazaar.conf) and 'system_overrides' ? -- vila 2011-04-05

# FIXME: Moreover, we shouldn't need classes for these stores either, factory
# functions or a registry will make it easier and clearer for tests, focusing
# on the relevant parts of the API that needs testing -- vila 20110503 (based
# on a poolie's remark)
class GlobalStore(LockableIniFileStore):

    def __init__(self, possible_transports=None):
        t = transport.get_transport(config_dir(),
                                    possible_transports=possible_transports)
        super(GlobalStore, self).__init__(t, 'bazaar.conf')


class LocationStore(LockableIniFileStore):

    def __init__(self, possible_transports=None):
        t = transport.get_transport(config_dir(),
                                    possible_transports=possible_transports)
        super(LocationStore, self).__init__(t, 'locations.conf')


class BranchStore(IniFileStore):

    def __init__(self, branch):
        super(BranchStore, self).__init__(branch.control_transport,
                                          'branch.conf')
        self.branch = branch

    def lock_write(self, token=None):
        return self.branch.lock_write(token)

    def unlock(self):
        return self.branch.unlock()

    @needs_write_lock
    def save(self):
        # We need to be able to override the undecorated implementation
        self.save_without_locking()

    def save_without_locking(self):
        super(BranchStore, self).save()


class SectionMatcher(object):
    """Select sections into a given Store.

    This intended to be used to postpone getting an iterable of sections from a
    store.
    """

    def __init__(self, store):
        self.store = store

    def get_sections(self):
        # This is where we require loading the store so we can see all defined
        # sections.
        sections = self.store.get_sections()
        # Walk the revisions in the order provided
        for s in sections:
            if self.match(s):
                yield s

    def match(self, secion):
        raise NotImplementedError(self.match)


class LocationSection(Section):

    def __init__(self, section, length, extra_path):
        super(LocationSection, self).__init__(section.id, section.options)
        self.length = length
        self.extra_path = extra_path

    def get(self, name, default=None):
        value = super(LocationSection, self).get(name, default)
        if value is not None:
            policy_name = self.get(name + ':policy', None)
            policy = _policy_value.get(policy_name, POLICY_NONE)
            if policy == POLICY_APPENDPATH:
                value = urlutils.join(value, self.extra_path)
        return value


class LocationMatcher(SectionMatcher):

    def __init__(self, store, location):
        super(LocationMatcher, self).__init__(store)
        if location.startswith('file://'):
            location = urlutils.local_path_from_url(location)
        self.location = location

    def _get_matching_sections(self):
        """Get all sections matching ``location``."""
        # We slightly diverge from LocalConfig here by allowing the no-name
        # section as the most generic one and the lower priority.
        no_name_section = None
        sections = []
        # Filter out the no_name_section so _iter_for_location_by_parts can be
        # used (it assumes all sections have a name).
        for section in self.store.get_sections():
            if section.id is None:
                no_name_section = section
            else:
                sections.append(section)
        # Unfortunately _iter_for_location_by_parts deals with section names so
        # we have to resync.
        filtered_sections = _iter_for_location_by_parts(
            [s.id for s in sections], self.location)
        iter_sections = iter(sections)
        matching_sections = []
        if no_name_section is not None:
            matching_sections.append(
                LocationSection(no_name_section, 0, self.location))
        for section_id, extra_path, length in filtered_sections:
            # a section id is unique for a given store so it's safe to iterate
            # again
            section = iter_sections.next()
            if section_id == section.id:
                matching_sections.append(
                    LocationSection(section, length, extra_path))
        return matching_sections

    def get_sections(self):
        # Override the default implementation as we want to change the order
        matching_sections = self._get_matching_sections()
        # We want the longest (aka more specific) locations first
        sections = sorted(matching_sections,
                          key=lambda section: (section.length, section.id),
                          reverse=True)
        # Sections mentioning 'ignore_parents' restrict the selection
        for section in sections:
            # FIXME: We really want to use as_bool below -- vila 2011-04-07
            ignore = section.get('ignore_parents', None)
            if ignore is not None:
                ignore = ui.bool_from_string(ignore)
            if ignore:
                break
            # Finally, we have a valid section
            yield section


class Stack(object):
    """A stack of configurations where an option can be defined"""

    def __init__(self, sections_def, store=None, mutable_section_name=None):
        """Creates a stack of sections with an optional store for changes.

        :param sections_def: A list of Section or callables that returns an
            iterable of Section. This defines the Sections for the Stack and
            can be called repeatedly if needed.

        :param store: The optional Store where modifications will be
            recorded. If none is specified, no modifications can be done.

        :param mutable_section_name: The name of the MutableSection where
            changes are recorded. This requires the ``store`` parameter to be
            specified.
        """
        self.sections_def = sections_def
        self.store = store
        self.mutable_section_name = mutable_section_name

    def get(self, name):
        """Return the *first* option value found in the sections.

        This is where we guarantee that sections coming from Store are loaded
        lazily: the loading is delayed until we need to either check that an
        option exists or get its value, which in turn may require to discover
        in which sections it can be defined. Both of these (section and option
        existence) require loading the store (even partially).
        """
        # FIXME: No caching of options nor sections yet -- vila 20110503
        value = None
        # Ensuring lazy loading is achieved by delaying section matching (which
        # implies querying the persistent storage) until it can't be avoided
        # anymore by using callables to describe (possibly empty) section
        # lists.
        for section_or_callable in self.sections_def:
            # Each section can expand to multiple ones when a callable is used
            if callable(section_or_callable):
                sections = section_or_callable()
            else:
                sections = [section_or_callable]
            for section in sections:
                value = section.get(name)
                if value is not None:
                    break
            if value is not None:
                break
        if value is None:
            # If the option is registered, it may provide a default value
            try:
                opt = option_registry.get(name)
            except KeyError:
                # Not registered
                opt = None
            if opt is not None:
                value = opt.get_default()
        for hook in ConfigHooks['get']:
            hook(self, name, value)
        return value

    def _get_mutable_section(self):
        """Get the MutableSection for the Stack.

        This is where we guarantee that the mutable section is lazily loaded:
        this means we won't load the corresponding store before setting a value
        or deleting an option. In practice the store will often be loaded but
        this allows helps catching some programming errors.
        """
        section = self.store.get_mutable_section(self.mutable_section_name)
        return section

    def set(self, name, value):
        """Set a new value for the option."""
        section = self._get_mutable_section()
        section.set(name, value)
        for hook in ConfigHooks['set']:
            hook(self, name, value)

    def remove(self, name):
        """Remove an existing option."""
        section = self._get_mutable_section()
        section.remove(name)
        for hook in ConfigHooks['remove']:
            hook(self, name)

    def __repr__(self):
        # Mostly for debugging use
        return "<config.%s(%s)>" % (self.__class__.__name__, id(self))


class _CompatibleStack(Stack):
    """Place holder for compatibility with previous design.

    This is intended to ease the transition from the Config-based design to the
    Stack-based design and should not be used nor relied upon by plugins.

    One assumption made here is that the daughter classes will all use Stores
    derived from LockableIniFileStore).

    It implements set() by re-loading the store before applying the
    modification and saving it.

    The long term plan being to implement a single write by store to save
    all modifications, this class should not be used in the interim.
    """

    def set(self, name, value):
        # Force a reload
        self.store.unload()
        super(_CompatibleStack, self).set(name, value)
        # Force a write to persistent storage
        self.store.save()


class GlobalStack(_CompatibleStack):

    def __init__(self):
        # Get a GlobalStore
        gstore = GlobalStore()
        super(GlobalStack, self).__init__([gstore.get_sections], gstore)


class LocationStack(_CompatibleStack):

    def __init__(self, location):
        """Make a new stack for a location and global configuration.
        
        :param location: A URL prefix to """
        lstore = LocationStore()
        matcher = LocationMatcher(lstore, location)
        gstore = GlobalStore()
        super(LocationStack, self).__init__(
            [matcher.get_sections, gstore.get_sections], lstore)

class BranchStack(_CompatibleStack):

    def __init__(self, branch):
        bstore = BranchStore(branch)
        lstore = LocationStore()
        matcher = LocationMatcher(lstore, branch.base)
        gstore = GlobalStore()
        super(BranchStack, self).__init__(
            [matcher.get_sections, bstore.get_sections, gstore.get_sections],
            bstore)
        self.branch = branch


class cmd_config(commands.Command):
    __doc__ = """Display, set or remove a configuration option.

    Display the active value for a given option.

    If --all is specified, NAME is interpreted as a regular expression and all
    matching options are displayed mentioning their scope. The active value
    that bzr will take into account is the first one displayed for each option.

    If no NAME is given, --all .* is implied.

    Setting a value is achieved by using name=value without spaces. The value
    is set in the most relevant scope and can be checked by displaying the
    option again.
    """

    takes_args = ['name?']

    takes_options = [
        'directory',
        # FIXME: This should be a registry option so that plugins can register
        # their own config files (or not) -- vila 20101002
        commands.Option('scope', help='Reduce the scope to the specified'
                        ' configuration file',
                        type=unicode),
        commands.Option('all',
            help='Display all the defined values for the matching options.',
            ),
        commands.Option('remove', help='Remove the option from'
                        ' the configuration file'),
        ]

    _see_also = ['configuration']

    @commands.display_command
    def run(self, name=None, all=False, directory=None, scope=None,
            remove=False):
        if directory is None:
            directory = '.'
        directory = urlutils.normalize_url(directory)
        if remove and all:
            raise errors.BzrError(
                '--all and --remove are mutually exclusive.')
        elif remove:
            # Delete the option in the given scope
            self._remove_config_option(name, directory, scope)
        elif name is None:
            # Defaults to all options
            self._show_matching_options('.*', directory, scope)
        else:
            try:
                name, value = name.split('=', 1)
            except ValueError:
                # Display the option(s) value(s)
                if all:
                    self._show_matching_options(name, directory, scope)
                else:
                    self._show_value(name, directory, scope)
            else:
                if all:
                    raise errors.BzrError(
                        'Only one option can be set.')
                # Set the option value
                self._set_config_option(name, value, directory, scope)

    def _get_configs(self, directory, scope=None):
        """Iterate the configurations specified by ``directory`` and ``scope``.

        :param directory: Where the configurations are derived from.

        :param scope: A specific config to start from.
        """
        if scope is not None:
            if scope == 'bazaar':
                yield GlobalConfig()
            elif scope == 'locations':
                yield LocationConfig(directory)
            elif scope == 'branch':
                (_, br, _) = bzrdir.BzrDir.open_containing_tree_or_branch(
                    directory)
                yield br.get_config()
        else:
            try:
                (_, br, _) = bzrdir.BzrDir.open_containing_tree_or_branch(
                    directory)
                yield br.get_config()
            except errors.NotBranchError:
                yield LocationConfig(directory)
                yield GlobalConfig()

    def _show_value(self, name, directory, scope):
        displayed = False
        for c in self._get_configs(directory, scope):
            if displayed:
                break
            for (oname, value, section, conf_id, parser) in c._get_options():
                if name == oname:
                    # Display only the first value and exit

                    # FIXME: We need to use get_user_option to take policies
                    # into account and we need to make sure the option exists
                    # too (hence the two for loops), this needs a better API
                    # -- vila 20101117
                    value = c.get_user_option(name)
                    # Quote the value appropriately
                    value = parser._quote(value)
                    self.outf.write('%s\n' % (value,))
                    displayed = True
                    break
        if not displayed:
            raise errors.NoSuchConfigOption(name)

    def _show_matching_options(self, name, directory, scope):
        name = lazy_regex.lazy_compile(name)
        # We want any error in the regexp to be raised *now* so we need to
        # avoid the delay introduced by the lazy regexp.  But, we still do
        # want the nicer errors raised by lazy_regex.
        name._compile_and_collapse()
        cur_conf_id = None
        cur_section = None
        for c in self._get_configs(directory, scope):
            for (oname, value, section, conf_id, parser) in c._get_options():
                if name.search(oname):
                    if cur_conf_id != conf_id:
                        # Explain where the options are defined
                        self.outf.write('%s:\n' % (conf_id,))
                        cur_conf_id = conf_id
                        cur_section = None
                    if (section not in (None, 'DEFAULT')
                        and cur_section != section):
                        # Display the section if it's not the default (or only)
                        # one.
                        self.outf.write('  [%s]\n' % (section,))
                        cur_section = section
                    self.outf.write('  %s = %s\n' % (oname, value))

    def _set_config_option(self, name, value, directory, scope):
        for conf in self._get_configs(directory, scope):
            conf.set_user_option(name, value)
            break
        else:
            raise errors.NoSuchConfig(scope)

    def _remove_config_option(self, name, directory, scope):
        if name is None:
            raise errors.BzrCommandError(
                '--remove expects an option to remove.')
        removed = False
        for conf in self._get_configs(directory, scope):
            for (section_name, section, conf_id) in conf._get_sections():
                if scope is not None and conf_id != scope:
                    # Not the right configuration file
                    continue
                if name in section:
                    if conf_id != conf.config_id():
                        conf = self._get_configs(directory, conf_id).next()
                    # We use the first section in the first config where the
                    # option is defined to remove it
                    conf.remove_user_option(name, section_name)
                    removed = True
                    break
            break
        else:
            raise errors.NoSuchConfig(scope)
        if not removed:
            raise errors.NoSuchConfigOption(name)

# Test registries
#
# We need adapters that can build a Store or a Stack in a test context. Test
# classes, based on TestCaseWithTransport, can use the registry to parametrize
# themselves. The builder will receive a test instance and should return a
# ready-to-use store or stack.  Plugins that define new store/stacks can also
# register themselves here to be tested against the tests defined in
# bzrlib.tests.test_config. Note that the builder can be called multiple times
# for the same tests.

# The registered object should be a callable receiving a test instance
# parameter (inheriting from tests.TestCaseWithTransport) and returning a Store
# object.
test_store_builder_registry = registry.Registry()

# The registered object should be a callable receiving a test instance
# parameter (inheriting from tests.TestCaseWithTransport) and returning a Stack
# object.
test_stack_builder_registry = registry.Registry()
