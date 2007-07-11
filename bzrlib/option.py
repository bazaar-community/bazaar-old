# Copyright (C) 2004, 2005, 2006, 2007 Canonical Ltd
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

# TODO: For things like --diff-prefix, we want a way to customize the display
# of the option argument.

import re

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import optparse

from bzrlib import (
    errors,
    log,
    registry,
    revisionspec,
    symbol_versioning,
    )
""")
from bzrlib.trace import warning


def _parse_revision_str(revstr):
    """This handles a revision string -> revno.

    This always returns a list.  The list will have one element for
    each revision specifier supplied.

    >>> _parse_revision_str('234')
    [<RevisionSpec_revno 234>]
    >>> _parse_revision_str('234..567')
    [<RevisionSpec_revno 234>, <RevisionSpec_revno 567>]
    >>> _parse_revision_str('..')
    [<RevisionSpec None>, <RevisionSpec None>]
    >>> _parse_revision_str('..234')
    [<RevisionSpec None>, <RevisionSpec_revno 234>]
    >>> _parse_revision_str('234..')
    [<RevisionSpec_revno 234>, <RevisionSpec None>]
    >>> _parse_revision_str('234..456..789') # Maybe this should be an error
    [<RevisionSpec_revno 234>, <RevisionSpec_revno 456>, <RevisionSpec_revno 789>]
    >>> _parse_revision_str('234....789') #Error ?
    [<RevisionSpec_revno 234>, <RevisionSpec None>, <RevisionSpec_revno 789>]
    >>> _parse_revision_str('revid:test@other.com-234234')
    [<RevisionSpec_revid revid:test@other.com-234234>]
    >>> _parse_revision_str('revid:test@other.com-234234..revid:test@other.com-234235')
    [<RevisionSpec_revid revid:test@other.com-234234>, <RevisionSpec_revid revid:test@other.com-234235>]
    >>> _parse_revision_str('revid:test@other.com-234234..23')
    [<RevisionSpec_revid revid:test@other.com-234234>, <RevisionSpec_revno 23>]
    >>> _parse_revision_str('date:2005-04-12')
    [<RevisionSpec_date date:2005-04-12>]
    >>> _parse_revision_str('date:2005-04-12 12:24:33')
    [<RevisionSpec_date date:2005-04-12 12:24:33>]
    >>> _parse_revision_str('date:2005-04-12T12:24:33')
    [<RevisionSpec_date date:2005-04-12T12:24:33>]
    >>> _parse_revision_str('date:2005-04-12,12:24:33')
    [<RevisionSpec_date date:2005-04-12,12:24:33>]
    >>> _parse_revision_str('-5..23')
    [<RevisionSpec_revno -5>, <RevisionSpec_revno 23>]
    >>> _parse_revision_str('-5')
    [<RevisionSpec_revno -5>]
    >>> _parse_revision_str('123a')
    Traceback (most recent call last):
      ...
    NoSuchRevisionSpec: No namespace registered for string: '123a'
    >>> _parse_revision_str('abc')
    Traceback (most recent call last):
      ...
    NoSuchRevisionSpec: No namespace registered for string: 'abc'
    >>> _parse_revision_str('branch:../branch2')
    [<RevisionSpec_branch branch:../branch2>]
    >>> _parse_revision_str('branch:../../branch2')
    [<RevisionSpec_branch branch:../../branch2>]
    >>> _parse_revision_str('branch:../../branch2..23')
    [<RevisionSpec_branch branch:../../branch2>, <RevisionSpec_revno 23>]
    """
    # TODO: Maybe move this into revisionspec.py
    revs = []
    # split on the first .. that is not followed by a / ?
    sep = re.compile("\\.\\.(?!/)")
    for x in sep.split(revstr):
        revs.append(revisionspec.RevisionSpec.from_string(x or None))
    return revs


def _parse_merge_type(typestring):
    return get_merge_type(typestring)

def get_merge_type(typestring):
    """Attempt to find the merge class/factory associated with a string."""
    from merge import merge_types
    try:
        return merge_types[typestring][0]
    except KeyError:
        templ = '%s%%7s: %%s' % (' '*12)
        lines = [templ % (f[0], f[1][1]) for f in merge_types.iteritems()]
        type_list = '\n'.join(lines)
        msg = "No known merge type %s. Supported types are:\n%s" %\
            (typestring, type_list)
        raise errors.BzrCommandError(msg)


class Option(object):
    """Description of a command line option
    
    :ivar _short_name: If this option has a single-letter name, this is it.
    Otherwise None.
    """

    # TODO: Some way to show in help a description of the option argument

    OPTIONS = {}

    def __init__(self, name, help='', type=None, argname=None,
                 short_name=None):
        """Make a new command option.

        name -- regular name of the command, used in the double-dash
            form and also as the parameter to the command's run() 
            method.

        help -- help message displayed in command help

        type -- function called to parse the option argument, or 
            None (default) if this option doesn't take an argument.

        argname -- name of option argument, if any
        """
        self.name = name
        self.help = help
        self.type = type
        self._short_name = short_name
        if type is None:
            assert argname is None
        elif argname is None:
            argname = 'ARG'
        self.argname = argname

    def short_name(self):
        if self._short_name:
            return self._short_name
        else:
            # remove this when SHORT_OPTIONS is removed
            # XXX: This is accessing a DeprecatedDict, so we call the super 
            # method to avoid warnings
            for (k, v) in dict.iteritems(Option.SHORT_OPTIONS):
                if v == self:
                    return k

    def set_short_name(self, short_name):
        self._short_name = short_name

    def get_negation_name(self):
        if self.name.startswith('no-'):
            return self.name[3:]
        else:
            return 'no-' + self.name

    def add_option(self, parser, short_name):
        """Add this option to an Optparse parser"""
        option_strings = ['--%s' % self.name]
        if short_name is not None:
            option_strings.append('-%s' % short_name)
        optargfn = self.type
        if optargfn is None:
            parser.add_option(action='store_true', dest=self.name, 
                              help=self.help,
                              default=OptionParser.DEFAULT_VALUE,
                              *option_strings)
            negation_strings = ['--%s' % self.get_negation_name()]
            parser.add_option(action='store_false', dest=self.name, 
                              help=optparse.SUPPRESS_HELP, *negation_strings)
        else:
            parser.add_option(action='callback', 
                              callback=self._optparse_callback, 
                              type='string', metavar=self.argname.upper(),
                              help=self.help,
                              default=OptionParser.DEFAULT_VALUE, 
                              *option_strings)

    def _optparse_callback(self, option, opt, value, parser):
        setattr(parser.values, self.name, self.type(value))

    def iter_switches(self):
        """Iterate through the list of switches provided by the option
        
        :return: an iterator of (name, short_name, argname, help)
        """
        argname =  self.argname
        if argname is not None:
            argname = argname.upper()
        yield self.name, self.short_name(), argname, self.help


class ListOption(Option):
    """Option used to provide a list of values.

    On the command line, arguments are specified by a repeated use of the
    option. '-' is a special argument that resets the list. For example,
      --foo=a --foo=b
    sets the value of the 'foo' option to ['a', 'b'], and
      --foo=a --foo=b --foo=- --foo=c
    sets the value of the 'foo' option to ['c'].
    """

    def add_option(self, parser, short_name):
        """Add this option to an Optparse parser."""
        option_strings = ['--%s' % self.name]
        if short_name is not None:
            option_strings.append('-%s' % short_name)
        parser.add_option(action='callback',
                          callback=self._optparse_callback,
                          type='string', metavar=self.argname.upper(),
                          help=self.help, default=[],
                          *option_strings)

    def _optparse_callback(self, option, opt, value, parser):
        values = getattr(parser.values, self.name)
        if value == '-':
            del values[:]
        else:
            values.append(self.type(value))


class RegistryOption(Option):
    """Option based on a registry

    The values for the options correspond to entries in the registry.  Input
    must be a registry key.  After validation, it is converted into an object
    using Registry.get or a caller-provided converter.
    """

    def validate_value(self, value):
        """Validate a value name"""
        if value not in self.registry:
            raise errors.BadOptionValue(self.name, value)

    def convert(self, value):
        """Convert a value name into an output type"""
        self.validate_value(value)
        if self.converter is None:
            return self.registry.get(value)
        else:
            return self.converter(value)

    def __init__(self, name, help, registry, converter=None,
        value_switches=False, title=None, enum_switch=True):
        """
        Constructor.

        :param name: The option name.
        :param help: Help for the option.
        :param registry: A Registry containing the values
        :param converter: Callable to invoke with the value name to produce
            the value.  If not supplied, self.registry.get is used.
        :param value_switches: If true, each possible value is assigned its
            own switch.  For example, instead of '--format knit',
            '--knit' can be used interchangeably.
        :param enum_switch: If true, a switch is provided with the option name,
            which takes a value.
        """
        Option.__init__(self, name, help, type=self.convert)
        self.registry = registry
        self.name = name
        self.converter = converter
        self.value_switches = value_switches
        self.enum_switch = enum_switch
        self.title = title
        if self.title is None:
            self.title = name

    @staticmethod
    def from_kwargs(name_, help=None, title=None, value_switches=False,
                    enum_switch=True, **kwargs):
        """Convenience method to generate string-map registry options

        name, help, value_switches and enum_switch are passed to the
        RegistryOption constructor.  Any other keyword arguments are treated
        as values for the option, and they value is treated as the help.
        """
        reg = registry.Registry()
        for name, help in kwargs.iteritems():
            name = name.replace('_', '-')
            reg.register(name, name, help=help)
        return RegistryOption(name_, help, reg, title=title,
            value_switches=value_switches, enum_switch=enum_switch)

    def add_option(self, parser, short_name):
        """Add this option to an Optparse parser"""
        if self.value_switches:
            parser = parser.add_option_group(self.title)
        if self.enum_switch:
            Option.add_option(self, parser, short_name)
        if self.value_switches:
            for key in self.registry.keys():
                option_strings = ['--%s' % key]
                if getattr(self.registry.get_info(key), 'hidden', False):
                    help = optparse.SUPPRESS_HELP
                else:
                    help = self.registry.get_help(key)
                parser.add_option(action='callback',
                              callback=self._optparse_value_callback(key),
                                  help=help,
                                  *option_strings)

    def _optparse_value_callback(self, cb_value):
        def cb(option, opt, value, parser):
            setattr(parser.values, self.name, self.type(cb_value))
        return cb

    def iter_switches(self):
        """Iterate through the list of switches provided by the option

        :return: an iterator of (name, short_name, argname, help)
        """
        for value in Option.iter_switches(self):
            yield value
        if self.value_switches:
            for key in sorted(self.registry.keys()):
                yield key, None, None, self.registry.get_help(key)


class OptionParser(optparse.OptionParser):
    """OptionParser that raises exceptions instead of exiting"""

    DEFAULT_VALUE = object()

    def error(self, message):
        raise errors.BzrCommandError(message)


def get_optparser(options):
    """Generate an optparse parser for bzrlib-style options"""

    parser = OptionParser()
    parser.remove_option('--help')
    for option in options.itervalues():
        option.add_option(parser, option.short_name())
    return parser


def _global_option(name, **kwargs):
    """Register o as a global option."""
    Option.OPTIONS[name] = Option(name, **kwargs)


def _global_registry_option(name, help, registry, **kwargs):
    Option.OPTIONS[name] = RegistryOption(name, help, registry, **kwargs)


class MergeTypeRegistry(registry.Registry):

    pass


_merge_type_registry = MergeTypeRegistry()
_merge_type_registry.register_lazy('merge3', 'bzrlib.merge', 'Merge3Merger',
                                   "Native diff3-style merge")
_merge_type_registry.register_lazy('diff3', 'bzrlib.merge', 'Diff3Merger',
                                   "Merge using external diff3")
_merge_type_registry.register_lazy('weave', 'bzrlib.merge', 'WeaveMerger',
                                   "Weave-based merge")

_global_option('all')
_global_option('overwrite', help='Ignore differences between branches and '
               'overwrite unconditionally.')
_global_option('basis', type=str)
_global_option('bound')
_global_option('diff-options', type=str)
_global_option('help',
               help='Show help message.',
               short_name='h')
_global_option('file', type=unicode, short_name='F')
_global_option('force')
_global_option('format', type=unicode)
_global_option('forward')
_global_option('message', type=unicode,
               short_name='m')
_global_option('no-recurse')
_global_option('profile',
               help='Show performance profiling information.')
_global_option('revision',
               type=_parse_revision_str,
               short_name='r',
               help='See \'help revisionspec\' for details.')
_global_option('show-ids',
               help='Show internal object ids.')
_global_option('timezone',
               type=str,
               help='Display timezone as local, original, or utc.')
_global_option('unbound')
_global_option('verbose',
               help='Display more information.',
               short_name='v')
_global_option('version')
_global_option('email')
_global_option('update')
_global_registry_option('log-format', "Use specified log format.",
                        log.log_formatter_registry, value_switches=True,
                        title='Log format')
_global_option('long',
        help='Use detailed log format.  Same as --log-format long.',
        short_name='l')
_global_option('short',
        help='Use moderately short log format. Same as --log-format short.')
_global_option('line', help='Use log format with one line per revision. Same as --log-format line.')
_global_option('root', type=str)
_global_option('no-backup')
_global_registry_option('merge-type', 'Select a particular merge algorithm.',
                        _merge_type_registry, value_switches=True,
                        title='Merge algorithm')
_global_option('pattern', type=str)
_global_option('quiet', short_name='q')
_global_option('remember', help='Remember the specified location as a'
               ' default.')
_global_option('reprocess', help='Reprocess to reduce spurious conflicts.')
_global_option('kind', type=str)
_global_option('dry-run',
               help="Show what would be done, but don't actually do anything.")
_global_option('name-from-revision', help='The path name in the old tree.')


# prior to 0.14 these were always globally registered; the old dict is
# available for plugins that use it but it should not be used.
Option.SHORT_OPTIONS = symbol_versioning.DeprecatedDict(
    symbol_versioning.zero_fourteen,
    'SHORT_OPTIONS',
    {
        'F': Option.OPTIONS['file'],
        'h': Option.OPTIONS['help'],
        'm': Option.OPTIONS['message'],
        'r': Option.OPTIONS['revision'],
        'v': Option.OPTIONS['verbose'],
        'l': Option.OPTIONS['long'],
        'q': Option.OPTIONS['quiet'],
    },
    'Set the short option name when constructing the Option.',
    )
