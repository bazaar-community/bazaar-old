# Copyright (C) 2010 Canonical Ltd.
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

"""Registry for external merge tools, e.g. kdiff3, meld, etc."""

import os
import shutil
import subprocess
import sys
import tempfile

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    cmdline,
    config,
    errors,
    trace,
    ui,
    workingtree,
)
""")

from bzrlib.commands import Command
from bzrlib.option import Option


substitution_help = {
    u'%b' : u'file.BASE',
    u'%t' : u'file.THIS',
    u'%o' : u'file.OTHER',
    u'%r' : u'file (output)',
    u'%T' : u'file.THIS (temp copy, used to overwrite "file" if merge succeeds)'
}


def subprocess_invoker(executable, args, cleanup):
    retcode = subprocess.call([executable] + args)
    cleanup(retcode)
    return retcode


_WIN32_PATH_EXT = [unicode(ext.lower())
                   for ext in os.getenv('PATHEXT', '').split(';')]


def tool_name_from_executable(executable):
    name = os.path.basename(executable)
    if sys.platform == 'win32':
        root, ext = os.path.splitext(name)
        if ext.lower() in _WIN32_PATH_EXT:
            name = root
    return name


class MergeTool(object):
    def __init__(self, name, commandline):
        """Initializes the merge tool with a name and a command-line (a string
        or sequence of strings).
        """
        self.set_commandline(commandline)
        self.set_name(name) # needs commandline set first when name is None

    def __repr__(self):
        return '<MergeTool %s: %r>' % (self._name, self._commandline)

    def __eq__(self, other):
        if type(other) == MergeTool:
            return cmp(self, other) == 0
        else:
            return False

    def __ne__(self, other):
        if type(other) == MergeTool:
            return cmp(self, other) != 0
        else:
            return True

    def __cmp__(self, other):
        if type(other == MergeTool):
            return cmp((self._name, self._commandline),
                (other._name, other._commandline))

    def __str__(self):
        return self.get_commandline()

    def get_name(self):
        return self._name

    def set_name(self, name):
        if name is None:
            self._name = tool_name_from_executable(self.get_executable())
        else:
            self._name = name

    def get_commandline(self, quote=False):
        if quote:
            args = _quote_args(self._commandline)
        else:
            args = self._commandline
        return u' '.join(args)

    def get_commandline_as_list(self):
        return self._commandline

    def set_commandline(self, commandline):
        if isinstance(commandline, basestring):
            self._commandline = cmdline.split(commandline)
        elif isinstance(commandline, (tuple, list)):
            self._commandline = list(commandline)
        else:
            raise TypeError('%r is not valid for commandline; must be string '
                            'or sequence of strings' % commandline)

    def get_executable(self):
        if len(self._commandline) < 1:
            return u''
        return self._commandline[0]

    def set_executable(self, executable):
        self._commandline[:1] = [executable]

    def is_available(self):
        executable = self.get_executable()
        return os.path.exists(executable) or _find_executable(executable)

    def invoke(self, filename, invoker=None):
        if invoker is None:
            invoker = subprocess_invoker
        args, tmp_file = self._subst_filename(self._commandline, filename)
        def cleanup(retcode):
            if tmp_file is not None:
                if retcode == 0: # on success, replace file with temp file
                    shutil.move(tmp_file, filename)
                else: # otherwise, delete temp file
                    os.remove(tmp_file)
        return invoker(args[0], args[1:], cleanup)

    def _subst_filename(self, args, filename):
        tmp_file = None
        subst_args = []
        for arg in args:
            arg = arg.replace(u'%b', filename + u'.BASE')
            arg = arg.replace(u'%t', filename + u'.THIS')
            arg = arg.replace(u'%o', filename + u'.OTHER')
            arg = arg.replace(u'%r', filename)
            if u'%T' in arg:
                tmp_file = tempfile.mktemp(u"_bzr_mergetools_%s.THIS" %
                                           os.path.basename(filename))
                shutil.copy(filename + u".THIS", tmp_file)
                arg = arg.replace(u'%T', tmp_file)
            subst_args.append(arg)
        return subst_args, tmp_file


_KNOWN_MERGE_TOOLS = (
    u'bcompare %t %o %b %r',
    u'kdiff3 %b %t %o -o %r',
    u'xxdiff -m -O -M %r %t %b %o',
    u'meld %b %T %o',
    u'opendiff %t %o -ancestor %b -merge %r',
    u'winmergeu %r',
)


def detect_merge_tools():
    tools = [MergeTool(None, commandline) for commandline in _KNOWN_MERGE_TOOLS]
    return [tool for tool in tools if tool.is_available()]


def get_merge_tools(conf=None):
    """Returns list of MergeTool objects."""
    if conf is None:
        conf = config.GlobalConfig()
    names = conf.get_user_option_as_list('mergetools')
    if names is None:
        return []
    return [MergeTool(name, conf.get_user_option('mergetools.%s' % name) or name)
            for name in names]


def set_merge_tools(merge_tools, conf=None):
    if conf is None:
        conf = config.GlobalConfig()
    tools = {}
    for tool in merge_tools:
        if not tool.get_name() in tools and len(tool.get_commandline_as_list()) > 0:
            tools[tool.get_name()] = tool
    names = sorted(tools.keys())
    conf.set_user_option("mergetools", names)
    for name in names:
        tool = tools[name]
        conf.set_user_option("mergetools.%s" % name,
                             tool.get_commandline(quote=True))


def find_merge_tool(name, conf=None):
    if conf is None:
        conf = config.GlobalConfig()
    merge_tools = get_merge_tools(conf)
    for merge_tool in merge_tools:
        if merge_tool.get_name() == name:
            return merge_tool
    return None


def find_first_available_merge_tool(conf=None):
    if conf is None:
        conf = config.GlobalConfig()
    merge_tools = get_merge_tools(conf)
    for merge_tool in merge_tools:
        if merge_tool.is_available():
            return merge_tool
    return None


def get_default_merge_tool(conf=None):
    if conf is None:
        conf = config.GlobalConfig()
    name = conf.get_user_option('default_mergetool')
    if name is None:
        trace.mutter('no default merge tool defined')
        return None
    merge_tool = find_merge_tool(name, conf)
    trace.mutter('found default merge tool: %r', merge_tool)
    return merge_tool


def set_default_merge_tool(name, conf=None):
    if conf is None:
        conf = config.GlobalConfig()
    if name is None:
        conf.remove_user_option('default_mergetool')
    else:
        if isinstance(name, MergeTool):
            name = name.get_name()
        if find_merge_tool(name, conf) is None:
            raise errors.BzrError('invalid merge tool name: %r' % name)
        trace.mutter('setting default merge tool: %s', name)
        conf.set_user_option('default_mergetool', name)


def resolve_using_merge_tool(tool_name, conflicts):
    merge_tool = find_merge_tool(tool_name)
    if merge_tool is None:
        available = '\n  '.join([mt.get_name() for mt in get_merge_tools()
                                 if mt.is_available()])
        raise errors.BzrCommandError('Unrecognized merge tool: %s\n\n'
                                     'Available merge tools:\n'
                                     '  %s' % (tool_name, available))
    for conflict in conflicts:
        merge_tool.invoke(conflict.path)


def _quote_args(args):
    return [_quote_arg(arg) for arg in args]


def _quote_arg(arg):
    if u' ' in arg and not _is_arg_quoted(arg):
        return u'"%s"' % _escape_quotes(arg)
    else:
        return arg


def _is_arg_quoted(arg):
    return (arg[0] == u"'" and arg[-1] == u"'") or \
           (arg[0] == u'"' and arg[-1] == u'"')


def _escape_quotes(arg):
    return arg.replace(u'"', u'\\"')


# courtesy of 'techtonik' at http://snippets.dzone.com/posts/show/6313
def _find_executable(executable, path=None):
    """Try to find 'executable' in the directories listed in 'path' (a
    string listing directories separated by 'os.pathsep'; defaults to
    os.environ['PATH']).  Returns the complete filename or None if not
    found
    """
    if path is None:
        path = os.environ['PATH']
    paths = path.split(os.pathsep)
    extlist = ['']
    if sys.platform == 'win32':
        pathext = os.environ['PATHEXT'].lower().split(os.pathsep)
        (base, ext) = os.path.splitext(executable)
        if ext.lower() not in pathext:
            extlist = pathext
    for ext in extlist:
        execname = executable + ext
        if os.path.isfile(execname):
            return execname
        else:
            for p in paths:
                f = os.path.join(p, execname)
                if os.path.isfile(f):
                    return f
    else:
        return None
