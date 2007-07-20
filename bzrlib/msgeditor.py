# Copyright (C) 2005, 2006 Canonical Ltd
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


"""Commit message editor support."""

import codecs
import errno
import os
from subprocess import call
import sys

import bzrlib
import bzrlib.config as config
from bzrlib.errors import BzrError
from bzrlib.trace import warning, mutter


def _get_editor():
    """Return a sequence of possible editor binaries for the current platform"""
    try:
        yield os.environ["BZR_EDITOR"]
    except KeyError:
        pass

    e = config.GlobalConfig().get_editor()
    if e is not None:
        yield e
        
    for varname in 'VISUAL', 'EDITOR':
        if varname in os.environ:
            yield os.environ[varname]

    if sys.platform == 'win32':
        for editor in 'wordpad.exe', 'notepad.exe':
            yield editor
    else:
        for editor in ['/usr/bin/editor', 'vi', 'pico', 'nano', 'joe']:
            yield editor


def _run_editor(filename):
    """Try to execute an editor to edit the commit message."""
    for e in _get_editor():
        edargs = e.split(' ')
        try:
            ## mutter("trying editor: %r", (edargs +[filename]))
            x = call(edargs + [filename])
        except OSError, e:
           # We're searching for an editor, so catch safe errors and continue
           if e.errno in (errno.ENOENT, ):
               continue
           raise
        if x == 0:
            return True
        elif x == 127:
            continue
        else:
            break
    raise BzrError("Could not start any editor.\nPlease specify one with:\n"
                   " - $BZR_EDITOR\n - editor=/some/path in %s\n"
                   " - $VISUAL\n - $EDITOR" % \
                    config.config_filename())


DEFAULT_IGNORE_LINE = "%(bar)s %(msg)s %(bar)s" % \
    { 'bar' : '-' * 14, 'msg' : 'This line and the following will be ignored' }


def edit_commit_message(infotext, ignoreline=DEFAULT_IGNORE_LINE,
                        start_message=None, output_encoding=None):
    """Let the user edit a commit message in a temp file.

    This is run if they don't give a message or
    message-containing file on the command line.

    :param infotext:    Text to be displayed at bottom of message
                        for the user's reference;
                        currently similar to 'bzr status'.
                        May be a string, which will not be encoded
                        May be a unicode string, which will be encoded
                        May be a list of [unicode] string, which
                        will may be encoded depending if it is unicode

    :param ignoreline:  The separator to use above the infotext.

    :param start_message:   The text to place above the separator, if any.
                            This will not be removed from the message
                            after the user has edited it.

    :output_encoding:   Messages encoding

    :return:    commit message or None.
    """
    msgfilename = None
    if output_encoding is None:
        output_encoding = bzrlib.user_encoding
    try:
        msgfilename, hasinfo = _create_temp_file_with_commit_template(
                                    infotext, ignoreline, start_message,
                                    output_encoding)

        if not msgfilename or not _run_editor(msgfilename):
            return None
        
        started = False
        msg = []
        lastline, nlines = 0, 0
        # codecs.open() ALWAYS opens file in binary mode but we need text mode
        # 'rU' mode useful when bzr.exe used on Cygwin (bialix 20070430)
        f = file(msgfilename, 'rU')
        for line in codecs.getreader(output_encoding)(f):
            stripped_line = line.strip()
            # strip empty line before the log message starts
            if not started:
                if stripped_line != "":
                    started = True
                else:
                    continue
            # check for the ignore line only if there
            # is additional information at the end
            if hasinfo and stripped_line == ignoreline:
                break
            nlines += 1
            # keep track of the last line that had some content
            if stripped_line != "":
                lastline = nlines
            msg.append(line)
        f.close()

        if len(msg) == 0:
            return ""
        # delete empty lines at the end
        del msg[lastline:]
        # add a newline at the end, if needed
        if not msg[-1].endswith("\n"):
            return "%s%s" % ("".join(msg), "\n")
        else:
            return "".join(msg)
    finally:
        # delete the msg file in any case
        if msgfilename is not None:
            try:
                os.unlink(msgfilename)
            except IOError, e:
                warning("failed to unlink %s: %s; ignored", msgfilename, e)


def _create_temp_file_with_commit_template(infotext,
                                           ignoreline=DEFAULT_IGNORE_LINE,
                                           start_message=None,
                                           output_encoding=None):
    """Create temp file and write commit template in it.

    :param infotext:    Text to be displayed at bottom of message
                        for the user's reference;
                        currently similar to 'bzr status'.
                        May be a string, which will not be encoded
                        May be a unicode string, which will be encoded
                        May be a list of [unicode] string, which
                        will may be encoded depending if it is unicode

    :param ignoreline:  The separator to use above the infotext.

    :param start_message:   The text to place above the separator, if any.
                            This will not be removed from the message
                            after the user has edited it.

    :output_encoding:   Messages encoding

    :return:    2-tuple (temp file name, hasinfo)
    """
    import tempfile
    if output_encoding is None:
        output_encoding = bzrlib.user_encoding
    tmp_fileno, msgfilename = tempfile.mkstemp(prefix='bzr_log.',
                                               dir=u'.',
                                               text=True)
    msgfile = os.fdopen(tmp_fileno, 'w')
    try:
        if start_message is not None:
            msgfile.write("%s\n" % start_message.encode(
                                       output_encoding, 'replace'))

        if infotext is not None and len(infotext)>0:
            hasinfo = True
            msgfile.write("\n\n%s\n\n" % (ignoreline))
            if isinstance(infotext, basestring):
                infotext = [infotext]
            for s in infotext:
                if isinstance(s, unicode):
                    msgfile.write("%s" % (s.encode(output_encoding,
                                                'replace')))
                else:
                    msgfile.write(s)
        else:
            hasinfo = False
    finally:
        msgfile.close()

    return (msgfilename, hasinfo)


def make_commit_message_template(working_tree, specific_files, diff=False):
    """Prepare a template file for a commit into a branch.

    Returns a unicode string containing the template or a list of
    unicode/8-bit string.
    """
    # TODO: Should probably be given the WorkingTree not the branch
    #
    # TODO: make provision for this to be overridden or modified by a hook
    #
    # TODO: Rather than running the status command, should prepare a draft of
    # the revision to be committed, then pause and ask the user to
    # confirm/write a message.
    from StringIO import StringIO       # must be unicode-safe
    from bzrlib.status import show_tree_status
    status_tmp = StringIO()
    show_tree_status(working_tree, specific_files=specific_files, 
                     to_file=status_tmp)
    if diff:
        from bzrlib.diff import show_diff_trees
        stream = StringIO()
        status_tmp.write(u"\n")
        show_diff_trees(working_tree.basis_tree(), working_tree,
                    stream, specific_files)

        return [status_tmp.getvalue( ), stream.getvalue()]

    return status_tmp.getvalue()
