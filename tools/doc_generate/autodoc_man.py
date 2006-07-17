# Copyright 2005 Canonical Ltd.

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""man.py - create man page from built-in bzr help and static text

TODO:
  * use usage information instead of simple "bzr foo" in COMMAND OVERVIEW
  * add command aliases
"""

import os
import sys
import textwrap
import time

import bzrlib
import bzrlib.help
import bzrlib.commands


def get_filename(options):
    """Provides name of manpage"""
    return "%s.1" % (options.bzr_name)


def infogen(options, outfile):
    """Assembles a man page"""
    t = time.time()
    tt = time.gmtime(t)
    params = \
           { "bzrcmd": options.bzr_name,
             "datestamp": time.strftime("%Y-%m-%d",tt),
             "timestamp": time.strftime("%Y-%m-%d %H:%M:%S +0000",tt),
             "version": bzrlib.__version__,
             }
    outfile.write(man_preamble % params)
    outfile.write(man_escape(man_head % params))
    outfile.write(man_escape(getcommand_list(params)))
    outfile.write(man_escape(getcommand_help(params)))
    outfile.write(man_escape(man_foot % params))


def man_escape(string):
    """Escapes strings for man page compatibility"""
    result = string.replace("\\","\\\\")
    result = result.replace("`","\\`")
    result = result.replace("'","\\'")
    result = result.replace("-","\\-")
    return result


def command_name_list():
    """Builds a list of command names from bzrlib"""
    command_names = bzrlib.commands.builtin_command_names()
    command_names.sort()
    return command_names


def getcommand_list (params):
    """Builds summary help for command names in manpage format"""
    bzrcmd = params["bzrcmd"]
    output = '.SH "COMMAND OVERVIEW"\n'
    for cmd_name in command_name_list():
        cmd_object = bzrlib.commands.get_cmd_object(cmd_name)
        if cmd_object.hidden:
            continue
        cmd_help = cmd_object.help()
        if cmd_help:
            firstline = cmd_help.split('\n', 1)[0]
            usage = bzrlib.help.command_usage(cmd_object)
            tmp = '.TP\n.B "%s"\n%s\n' % (usage, firstline)
            output = output + tmp
        else:
            raise RuntimeError, "Command '%s' has no help text" % (cmd_name)
    return output


def getcommand_help(params):
    """Shows individual options for a bzr command"""
    output='.SH "COMMAND REFERENCE"\n'
    for cmd_name in command_name_list():
        cmd_object = bzrlib.commands.get_cmd_object(cmd_name)
        if cmd_object.hidden:
            continue
        output = output + format_command(params, cmd_object)
    return output


def format_command (params, cmd):
    """Provides long help for each public command"""
    subsection_header = '.SS "%s"\n' % (bzrlib.help.command_usage(cmd))
    doc = "%s\n" % (cmd.__doc__)
    docsplit = cmd.__doc__.split('\n')
    doc = '\n'.join([docsplit[0]] + [line[4:] for line in docsplit[1:]])

    option_str = ""
    options = cmd.options()
    if options:
        option_str = "\nOptions:\n"
        for option_name, option in sorted(options.items()):
            l = '    --' + option_name
            if option.type is not None:
                l += ' ' + option.argname.upper()
            short_name = option.short_name()
            if short_name:
                assert len(short_name) == 1
                l += ', -' + short_name
            l += (30 - len(l)) * ' ' + option.help
            # TODO: Split help over multiple lines with
            # correct indenting and wrapping.
            wrapped = textwrap.fill(l, initial_indent='',
                                    subsequent_indent=30*' ')
            option_str = option_str + wrapped + '\n'       

    aliases_str = ""
    if cmd.aliases:
        if len(cmd.aliases) > 1:
            aliases_str += '\nAliases: '
        else:
            aliases_str += '\nAlias: '
        aliases_str += ', '.join(cmd.aliases)
        aliases_str += '\n'

    return subsection_header + option_str + aliases_str + "\n" + doc + "\n"


man_preamble = """\
Man page for %(bzrcmd)s (bazaar-ng)
.\\\"
.\\\" Large parts of this file are autogenerated from the output of
.\\\"     \"%(bzrcmd)s help commands\"
.\\\"     \"%(bzrcmd)s help <cmd>\"
.\\\"
.\\\" Generation time: %(timestamp)s
.\\\"
"""


man_head = """\
.TH bzr 1 "%(datestamp)s" "%(version)s" "bazaar-ng"
.SH "NAME"
%(bzrcmd)s - bazaar-ng next-generation distributed version control
.SH "SYNOPSIS"
.B "%(bzrcmd)s"
.I "command"
[
.I "command_options"
]
.br
.B "%(bzrcmd)s"
.B "help"
.br
.B "%(bzrcmd)s"
.B "help"
.I "command"
.SH "DESCRIPTION"
bazaar-ng (or
.B "%(bzrcmd)s"
) is a project of Canonical to develop an open source distributed version control system that is powerful, friendly, and scalable. Version control means a system that keeps track of previous revisions of software source code or similar information and helps people work on it in teams.
"""

man_foot = """\
.SH "ENVIRONMENT"
.TP
.I "BZRPATH"
Path where
.B "%(bzrcmd)s"
is to look for external command.
.TP
.I "BZREMAIL"
E-Mail address of the user. Overrides default user config.
.TP
.I "EMAIL"
E-Mail address of the user. Overriddes default user config.
.SH "FILES"
.TP
.I "~/.bazaar/bazaar.conf"
Contains the default user config. At least one section, [DEFAULT] is required.
A typical default config file may be similiar to:
.br
.br
.B [DEFAULT]
.br
.B email=John Doe <jdoe@isp.com>
.SH "SEE ALSO"
.UR http://www.bazaar-vcs.org/
.BR http://www.bazaar-vcs.org/
"""

