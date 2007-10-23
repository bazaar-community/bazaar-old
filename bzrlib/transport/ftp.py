# Copyright (C) 2005, 2006, 2007 Canonical Ltd
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
"""Implementation of Transport over ftp.

Written by Daniel Silverstone <dsilvers@digital-scurf.org> with serious
cargo-culting from the sftp transport and the http transport.

It provides the ftp:// and aftp:// protocols where ftp:// is passive ftp
and aftp:// is active ftp. Most people will want passive ftp for traversing
NAT and other firewalls, so it's best to use it unless you explicitly want
active, in which case aftp:// will be your friend.
"""

from cStringIO import StringIO
import asyncore
import errno
import ftplib
import os
import os.path
import urllib
import urlparse
import select
import stat
import threading
import time
import random
from warnings import warn

from bzrlib import (
    config,
    errors,
    osutils,
    urlutils,
    )
from bzrlib.trace import mutter, warning
from bzrlib.transport import (
    AppendBasedFileStream,
    ConnectedTransport,
    _file_streams,
    register_urlparse_netloc_protocol,
    Server,
    )
from bzrlib.transport.local import LocalURLServer
import bzrlib.ui


register_urlparse_netloc_protocol('aftp')


class FtpPathError(errors.PathError):
    """FTP failed for path: %(path)s%(extra)s"""


class FtpStatResult(object):
    def __init__(self, f, relpath):
        try:
            self.st_size = f.size(relpath)
            self.st_mode = stat.S_IFREG
        except ftplib.error_perm:
            pwd = f.pwd()
            try:
                f.cwd(relpath)
                self.st_mode = stat.S_IFDIR
            finally:
                f.cwd(pwd)


_number_of_retries = 2
_sleep_between_retries = 5

# FIXME: there are inconsistencies in the way temporary errors are
# handled. Sometimes we reconnect, sometimes we raise an exception. Care should
# be taken to analyze the implications for write operations (read operations
# are safe to retry). Overall even some read operations are never
# retried. --vila 20070720 (Bug #127164)
class FtpTransport(ConnectedTransport):
    """This is the transport agent for ftp:// access."""

    def __init__(self, base, _from_transport=None):
        """Set the base path where files will be stored."""
        assert base.startswith('ftp://') or base.startswith('aftp://')
        super(FtpTransport, self).__init__(base,
                                           _from_transport=_from_transport)
        self._unqualified_scheme = 'ftp'
        if self._scheme == 'aftp':
            self.is_active = True
        else:
            self.is_active = False

    def _get_FTP(self):
        """Return the ftplib.FTP instance for this object."""
        # Ensures that a connection is established
        connection = self._get_connection()
        if connection is None:
            # First connection ever
            connection, credentials = self._create_connection()
            self._set_connection(connection, credentials)
        return connection

    def _create_connection(self, credentials=None):
        """Create a new connection with the provided credentials.

        :param credentials: The credentials needed to establish the connection.

        :return: The created connection and its associated credentials.

        The credentials are only the password as it may have been entered
        interactively by the user and may be different from the one provided
        in base url at transport creation time.
        """
        if credentials is None:
            user, password = self._user, self._password
        else:
            user, password = credentials

        auth = config.AuthenticationConfig()
        if user is None:
            user = auth.get_user('ftp', self._host, port=self._port)
            if user is None:
                # Default to local user
                user = getpass.getuser()

        mutter("Constructing FTP instance against %r" %
               ((self._host, self._port, user, '********',
                self.is_active),))
        try:
            connection = ftplib.FTP()
            connection.connect(host=self._host, port=self._port)
            if user and user != 'anonymous' and \
                    password is None: # '' is a valid password
                password = auth.get_password('ftp', self._host, user,
                                             port=self._port)
            connection.login(user=user, passwd=password)
            connection.set_pasv(not self.is_active)
        except ftplib.error_perm, e:
            raise errors.TransportError(msg="Error setting up connection:"
                                        " %s" % str(e), orig_error=e)
        return connection, (user, password)

    def _reconnect(self):
        """Create a new connection with the previously used credentials"""
        credentials = self._get_credentials()
        connection, credentials = self._create_connection(credentials)
        self._set_connection(connection, credentials)

    def _translate_perm_error(self, err, path, extra=None,
                              unknown_exc=FtpPathError):
        """Try to translate an ftplib.error_perm exception.

        :param err: The error to translate into a bzr error
        :param path: The path which had problems
        :param extra: Extra information which can be included
        :param unknown_exc: If None, we will just raise the original exception
                    otherwise we raise unknown_exc(path, extra=extra)
        """
        s = str(err).lower()
        if not extra:
            extra = str(err)
        else:
            extra += ': ' + str(err)
        if ('no such file' in s
            or 'could not open' in s
            or 'no such dir' in s
            or 'could not create file' in s # vsftpd
            or 'file doesn\'t exist' in s
            or 'file/directory not found' in s # filezilla server
            ):
            raise errors.NoSuchFile(path, extra=extra)
        if ('file exists' in s):
            raise errors.FileExists(path, extra=extra)
        if ('not a directory' in s):
            raise errors.PathError(path, extra=extra)

        mutter('unable to understand error for path: %s: %s', path, err)

        if unknown_exc:
            raise unknown_exc(path, extra=extra)
        # TODO: jam 20060516 Consider re-raising the error wrapped in 
        #       something like TransportError, but this loses the traceback
        #       Also, 'sftp' has a generic 'Failure' mode, which we use failure_exc
        #       to handle. Consider doing something like that here.
        #raise TransportError(msg='Error for path: %s' % (path,), orig_error=e)
        raise

    def _remote_path(self, relpath):
        # XXX: It seems that ftplib does not handle Unicode paths
        # at the same time, medusa won't handle utf8 paths So if
        # we .encode(utf8) here (see ConnectedTransport
        # implementation), then we get a Server failure.  while
        # if we use str(), we get a UnicodeError, and the test
        # suite just skips testing UnicodePaths.
        relative = str(urlutils.unescape(relpath))
        remote_path = self._combine_paths(self._path, relative)
        return remote_path

    def has(self, relpath):
        """Does the target location exist?"""
        # FIXME jam 20060516 We *do* ask about directories in the test suite
        #       We don't seem to in the actual codebase
        # XXX: I assume we're never asked has(dirname) and thus I use
        # the FTP size command and assume that if it doesn't raise,
        # all is good.
        abspath = self._remote_path(relpath)
        try:
            f = self._get_FTP()
            mutter('FTP has check: %s => %s', relpath, abspath)
            s = f.size(abspath)
            mutter("FTP has: %s", abspath)
            return True
        except ftplib.error_perm, e:
            if ('is a directory' in str(e).lower()):
                mutter("FTP has dir: %s: %s", abspath, e)
                return True
            mutter("FTP has not: %s: %s", abspath, e)
            return False

    def get(self, relpath, decode=False, retries=0):
        """Get the file at the given relative path.

        :param relpath: The relative path to the file
        :param retries: Number of retries after temporary failures so far
                        for this operation.

        We're meant to return a file-like object which bzr will
        then read from. For now we do this via the magic of StringIO
        """
        # TODO: decode should be deprecated
        try:
            mutter("FTP get: %s", self._remote_path(relpath))
            f = self._get_FTP()
            ret = StringIO()
            f.retrbinary('RETR '+self._remote_path(relpath), ret.write, 8192)
            ret.seek(0)
            return ret
        except ftplib.error_perm, e:
            raise errors.NoSuchFile(self.abspath(relpath), extra=str(e))
        except ftplib.error_temp, e:
            if retries > _number_of_retries:
                raise errors.TransportError(msg="FTP temporary error during GET %s. Aborting."
                                     % self.abspath(relpath),
                                     orig_error=e)
            else:
                warning("FTP temporary error: %s. Retrying.", str(e))
                self._reconnect()
                return self.get(relpath, decode, retries+1)
        except EOFError, e:
            if retries > _number_of_retries:
                raise errors.TransportError("FTP control connection closed during GET %s."
                                     % self.abspath(relpath),
                                     orig_error=e)
            else:
                warning("FTP control connection closed. Trying to reopen.")
                time.sleep(_sleep_between_retries)
                self._reconnect()
                return self.get(relpath, decode, retries+1)

    def put_file(self, relpath, fp, mode=None, retries=0):
        """Copy the file-like or string object into the location.

        :param relpath: Location to put the contents, relative to base.
        :param fp:       File-like or string object.
        :param retries: Number of retries after temporary failures so far
                        for this operation.

        TODO: jam 20051215 ftp as a protocol seems to support chmod, but
        ftplib does not
        """
        abspath = self._remote_path(relpath)
        tmp_abspath = '%s.tmp.%.9f.%d.%d' % (abspath, time.time(),
                        os.getpid(), random.randint(0,0x7FFFFFFF))
        bytes = None
        if getattr(fp, 'read', None) is None:
            # hand in a string IO
            bytes = fp
            fp = StringIO(bytes)
        else:
            # capture the byte count; .read() may be read only so
            # decorate it.
            class byte_counter(object):
                def __init__(self, fp):
                    self.fp = fp
                    self.counted_bytes = 0
                def read(self, count):
                    result = self.fp.read(count)
                    self.counted_bytes += len(result)
                    return result
            fp = byte_counter(fp)
        try:
            mutter("FTP put: %s", abspath)
            f = self._get_FTP()
            try:
                f.storbinary('STOR '+tmp_abspath, fp)
                self._rename_and_overwrite(tmp_abspath, abspath, f)
                if bytes is not None:
                    return len(bytes)
                else:
                    return fp.counted_bytes
            except (ftplib.error_temp,EOFError), e:
                warning("Failure during ftp PUT. Deleting temporary file.")
                try:
                    f.delete(tmp_abspath)
                except:
                    warning("Failed to delete temporary file on the"
                            " server.\nFile: %s", tmp_abspath)
                    raise e
                raise
        except ftplib.error_perm, e:
            self._translate_perm_error(e, abspath, extra='could not store',
                                       unknown_exc=errors.NoSuchFile)
        except ftplib.error_temp, e:
            if retries > _number_of_retries:
                raise errors.TransportError("FTP temporary error during PUT %s. Aborting."
                                     % self.abspath(relpath), orig_error=e)
            else:
                warning("FTP temporary error: %s. Retrying.", str(e))
                self._reconnect()
                self.put_file(relpath, fp, mode, retries+1)
        except EOFError:
            if retries > _number_of_retries:
                raise errors.TransportError("FTP control connection closed during PUT %s."
                                     % self.abspath(relpath), orig_error=e)
            else:
                warning("FTP control connection closed. Trying to reopen.")
                time.sleep(_sleep_between_retries)
                self._reconnect()
                self.put_file(relpath, fp, mode, retries+1)

    def mkdir(self, relpath, mode=None):
        """Create a directory at the given path."""
        abspath = self._remote_path(relpath)
        try:
            mutter("FTP mkd: %s", abspath)
            f = self._get_FTP()
            f.mkd(abspath)
        except ftplib.error_perm, e:
            self._translate_perm_error(e, abspath,
                unknown_exc=errors.FileExists)

    def open_write_stream(self, relpath, mode=None):
        """See Transport.open_write_stream."""
        self.put_bytes(relpath, "", mode)
        result = AppendBasedFileStream(self, relpath)
        _file_streams[self.abspath(relpath)] = result
        return result

    def recommended_page_size(self):
        """See Transport.recommended_page_size().

        For FTP we suggest a large page size to reduce the overhead
        introduced by latency.
        """
        return 64 * 1024

    def rmdir(self, rel_path):
        """Delete the directory at rel_path"""
        abspath = self._remote_path(rel_path)
        try:
            mutter("FTP rmd: %s", abspath)
            f = self._get_FTP()
            f.rmd(abspath)
        except ftplib.error_perm, e:
            self._translate_perm_error(e, abspath, unknown_exc=errors.PathError)

    def append_file(self, relpath, f, mode=None):
        """Append the text in the file-like object into the final
        location.
        """
        abspath = self._remote_path(relpath)
        if self.has(relpath):
            ftp = self._get_FTP()
            result = ftp.size(abspath)
        else:
            result = 0

        mutter("FTP appe to %s", abspath)
        self._try_append(relpath, f.read(), mode)

        return result

    def _try_append(self, relpath, text, mode=None, retries=0):
        """Try repeatedly to append the given text to the file at relpath.
        
        This is a recursive function. On errors, it will be called until the
        number of retries is exceeded.
        """
        try:
            abspath = self._remote_path(relpath)
            mutter("FTP appe (try %d) to %s", retries, abspath)
            ftp = self._get_FTP()
            ftp.voidcmd("TYPE I")
            cmd = "APPE %s" % abspath
            conn = ftp.transfercmd(cmd)
            conn.sendall(text)
            conn.close()
            if mode:
                self._setmode(relpath, mode)
            ftp.getresp()
        except ftplib.error_perm, e:
            self._translate_perm_error(e, abspath, extra='error appending',
                unknown_exc=errors.NoSuchFile)
        except ftplib.error_temp, e:
            if retries > _number_of_retries:
                raise errors.TransportError("FTP temporary error during APPEND %s." \
                        "Aborting." % abspath, orig_error=e)
            else:
                warning("FTP temporary error: %s. Retrying.", str(e))
                self._reconnect()
                self._try_append(relpath, text, mode, retries+1)

    def _setmode(self, relpath, mode):
        """Set permissions on a path.

        Only set permissions if the FTP server supports the 'SITE CHMOD'
        extension.
        """
        try:
            mutter("FTP site chmod: setting permissions to %s on %s",
                str(mode), self._remote_path(relpath))
            ftp = self._get_FTP()
            cmd = "SITE CHMOD %s %s" % (self._remote_path(relpath), str(mode))
            ftp.sendcmd(cmd)
        except ftplib.error_perm, e:
            # Command probably not available on this server
            warning("FTP Could not set permissions to %s on %s. %s",
                    str(mode), self._remote_path(relpath), str(e))

    # TODO: jam 20060516 I believe ftp allows you to tell an ftp server
    #       to copy something to another machine. And you may be able
    #       to give it its own address as the 'to' location.
    #       So implement a fancier 'copy()'

    def rename(self, rel_from, rel_to):
        abs_from = self._remote_path(rel_from)
        abs_to = self._remote_path(rel_to)
        mutter("FTP rename: %s => %s", abs_from, abs_to)
        f = self._get_FTP()
        return self._rename(abs_from, abs_to, f)

    def _rename(self, abs_from, abs_to, f):
        try:
            f.rename(abs_from, abs_to)
        except ftplib.error_perm, e:
            self._translate_perm_error(e, abs_from,
                ': unable to rename to %r' % (abs_to))

    def move(self, rel_from, rel_to):
        """Move the item at rel_from to the location at rel_to"""
        abs_from = self._remote_path(rel_from)
        abs_to = self._remote_path(rel_to)
        try:
            mutter("FTP mv: %s => %s", abs_from, abs_to)
            f = self._get_FTP()
            self._rename_and_overwrite(abs_from, abs_to, f)
        except ftplib.error_perm, e:
            self._translate_perm_error(e, abs_from,
                extra='unable to rename to %r' % (rel_to,), 
                unknown_exc=errors.PathError)

    def _rename_and_overwrite(self, abs_from, abs_to, f):
        """Do a fancy rename on the remote server.

        Using the implementation provided by osutils.
        """
        osutils.fancy_rename(abs_from, abs_to,
            rename_func=lambda p1, p2: self._rename(p1, p2, f),
            unlink_func=lambda p: self._delete(p, f))

    def delete(self, relpath):
        """Delete the item at relpath"""
        abspath = self._remote_path(relpath)
        f = self._get_FTP()
        self._delete(abspath, f)

    def _delete(self, abspath, f):
        try:
            mutter("FTP rm: %s", abspath)
            f.delete(abspath)
        except ftplib.error_perm, e:
            self._translate_perm_error(e, abspath, 'error deleting',
                unknown_exc=errors.NoSuchFile)

    def external_url(self):
        """See bzrlib.transport.Transport.external_url."""
        # FTP URL's are externally usable.
        return self.base

    def listable(self):
        """See Transport.listable."""
        return True

    def list_dir(self, relpath):
        """See Transport.list_dir."""
        basepath = self._remote_path(relpath)
        mutter("FTP nlst: %s", basepath)
        f = self._get_FTP()
        try:
            paths = f.nlst(basepath)
        except ftplib.error_perm, e:
            self._translate_perm_error(e, relpath, extra='error with list_dir')
        # If FTP.nlst returns paths prefixed by relpath, strip 'em
        if paths and paths[0].startswith(basepath):
            entries = [path[len(basepath)+1:] for path in paths]
        else:
            entries = paths
        # Remove . and .. if present
        return [urlutils.escape(entry) for entry in entries
                if entry not in ('.', '..')]

    def iter_files_recursive(self):
        """See Transport.iter_files_recursive.

        This is cargo-culted from the SFTP transport"""
        mutter("FTP iter_files_recursive")
        queue = list(self.list_dir("."))
        while queue:
            relpath = queue.pop(0)
            st = self.stat(relpath)
            if stat.S_ISDIR(st.st_mode):
                for i, basename in enumerate(self.list_dir(relpath)):
                    queue.insert(i, relpath+"/"+basename)
            else:
                yield relpath

    def stat(self, relpath):
        """Return the stat information for a file."""
        abspath = self._remote_path(relpath)
        try:
            mutter("FTP stat: %s", abspath)
            f = self._get_FTP()
            return FtpStatResult(f, abspath)
        except ftplib.error_perm, e:
            self._translate_perm_error(e, abspath, extra='error w/ stat')

    def lock_read(self, relpath):
        """Lock the given file for shared (read) access.
        :return: A lock object, which should be passed to Transport.unlock()
        """
        # The old RemoteBranch ignore lock for reading, so we will
        # continue that tradition and return a bogus lock object.
        class BogusLock(object):
            def __init__(self, path):
                self.path = path
            def unlock(self):
                pass
        return BogusLock(relpath)

    def lock_write(self, relpath):
        """Lock the given file for exclusive (write) access.
        WARNING: many transports do not support this, so trying avoid using it

        :return: A lock object, which should be passed to Transport.unlock()
        """
        return self.lock_read(relpath)


class FtpServer(Server):
    """Common code for FTP server facilities."""

    def __init__(self):
        self._root = None
        self._ftp_server = None
        self._port = None
        self._async_thread = None
        # ftp server logs
        self.logs = []

    def get_url(self):
        """Calculate an ftp url to this server."""
        return 'ftp://foo:bar@localhost:%d/' % (self._port)

#    def get_bogus_url(self):
#        """Return a URL which cannot be connected to."""
#        return 'ftp://127.0.0.1:1'

    def log(self, message):
        """This is used by medusa.ftp_server to log connections, etc."""
        self.logs.append(message)

    def setUp(self, vfs_server=None):
        if not _have_medusa:
            raise RuntimeError('Must have medusa to run the FtpServer')

        assert vfs_server is None or isinstance(vfs_server, LocalURLServer), \
            "FtpServer currently assumes local transport, got %s" % vfs_server

        self._root = os.getcwdu()
        self._ftp_server = _ftp_server(
            authorizer=_test_authorizer(root=self._root),
            ip='localhost',
            port=0, # bind to a random port
            resolver=None,
            logger_object=self # Use FtpServer.log() for messages
            )
        self._port = self._ftp_server.getsockname()[1]
        # Don't let it loop forever, or handle an infinite number of requests.
        # In this case it will run for 1000s, or 10000 requests
        self._async_thread = threading.Thread(
                target=FtpServer._asyncore_loop_ignore_EBADF,
                kwargs={'timeout':0.1, 'count':10000})
        self._async_thread.setDaemon(True)
        self._async_thread.start()

    def tearDown(self):
        """See bzrlib.transport.Server.tearDown."""
        self._ftp_server.close()
        asyncore.close_all()
        self._async_thread.join()

    @staticmethod
    def _asyncore_loop_ignore_EBADF(*args, **kwargs):
        """Ignore EBADF during server shutdown.

        We close the socket to get the server to shutdown, but this causes
        select.select() to raise EBADF.
        """
        try:
            asyncore.loop(*args, **kwargs)
            # FIXME: If we reach that point, we should raise an exception
            # explaining that the 'count' parameter in setUp is too low or
            # testers may wonder why their test just sits there waiting for a
            # server that is already dead. Note that if the tester waits too
            # long under pdb the server will also die.
        except select.error, e:
            if e.args[0] != errno.EBADF:
                raise


_ftp_channel = None
_ftp_server = None
_test_authorizer = None


def _setup_medusa():
    global _have_medusa, _ftp_channel, _ftp_server, _test_authorizer
    try:
        import medusa
        import medusa.filesys
        import medusa.ftp_server
    except ImportError:
        return False

    _have_medusa = True

    class test_authorizer(object):
        """A custom Authorizer object for running the test suite.

        The reason we cannot use dummy_authorizer, is because it sets the
        channel to readonly, which we don't always want to do.
        """

        def __init__(self, root):
            self.root = root
            # If secured_user is set secured_password will be checked
            self.secured_user = None
            self.secured_password = None

        def authorize(self, channel, username, password):
            """Return (success, reply_string, filesystem)"""
            if not _have_medusa:
                return 0, 'No Medusa.', None

            channel.persona = -1, -1
            if username == 'anonymous':
                channel.read_only = 1
            else:
                channel.read_only = 0

            # Check secured_user if set
            if (self.secured_user is not None
                and username == self.secured_user
                and password != self.secured_password):
                return 0, 'Password invalid.', None
            else:
                return 1, 'OK.', medusa.filesys.os_filesystem(self.root)


    class ftp_channel(medusa.ftp_server.ftp_channel):
        """Customized ftp channel"""

        def log(self, message):
            """Redirect logging requests."""
            mutter('_ftp_channel: %s', message)

        def log_info(self, message, type='info'):
            """Redirect logging requests."""
            mutter('_ftp_channel %s: %s', type, message)

        def cmd_rnfr(self, line):
            """Prepare for renaming a file."""
            self._renaming = line[1]
            self.respond('350 Ready for RNTO')
            # TODO: jam 20060516 in testing, the ftp server seems to
            #       check that the file already exists, or it sends
            #       550 RNFR command failed

        def cmd_rnto(self, line):
            """Rename a file based on the target given.

            rnto must be called after calling rnfr.
            """
            if not self._renaming:
                self.respond('503 RNFR required first.')
            pfrom = self.filesystem.translate(self._renaming)
            self._renaming = None
            pto = self.filesystem.translate(line[1])
            if os.path.exists(pto):
                self.respond('550 RNTO failed: file exists')
                return
            try:
                os.rename(pfrom, pto)
            except (IOError, OSError), e:
                # TODO: jam 20060516 return custom responses based on
                #       why the command failed
                # (bialix 20070418) str(e) on Python 2.5 @ Windows
                # sometimes don't provide expected error message;
                # so we obtain such message via os.strerror()
                self.respond('550 RNTO failed: %s' % os.strerror(e.errno))
            except:
                self.respond('550 RNTO failed')
                # For a test server, we will go ahead and just die
                raise
            else:
                self.respond('250 Rename successful.')

        def cmd_size(self, line):
            """Return the size of a file

            This is overloaded to help the test suite determine if the 
            target is a directory.
            """
            filename = line[1]
            if not self.filesystem.isfile(filename):
                if self.filesystem.isdir(filename):
                    self.respond('550 "%s" is a directory' % (filename,))
                else:
                    self.respond('550 "%s" is not a file' % (filename,))
            else:
                self.respond('213 %d' 
                    % (self.filesystem.stat(filename)[stat.ST_SIZE]),)

        def cmd_mkd(self, line):
            """Create a directory.

            Overloaded because default implementation does not distinguish
            *why* it cannot make a directory.
            """
            if len (line) != 2:
                self.command_not_understood(''.join(line))
            else:
                path = line[1]
                try:
                    self.filesystem.mkdir (path)
                    self.respond ('257 MKD command successful.')
                except (IOError, OSError), e:
                    # (bialix 20070418) str(e) on Python 2.5 @ Windows
                    # sometimes don't provide expected error message;
                    # so we obtain such message via os.strerror()
                    self.respond ('550 error creating directory: %s' %
                                  os.strerror(e.errno))
                except:
                    self.respond ('550 error creating directory.')


    class ftp_server(medusa.ftp_server.ftp_server):
        """Customize the behavior of the Medusa ftp_server.

        There are a few warts on the ftp_server, based on how it expects
        to be used.
        """
        _renaming = None
        ftp_channel_class = ftp_channel

        def __init__(self, *args, **kwargs):
            mutter('Initializing _ftp_server: %r, %r', args, kwargs)
            medusa.ftp_server.ftp_server.__init__(self, *args, **kwargs)

        def log(self, message):
            """Redirect logging requests."""
            mutter('_ftp_server: %s', message)

        def log_info(self, message, type='info'):
            """Override the asyncore.log_info so we don't stipple the screen."""
            mutter('_ftp_server %s: %s', type, message)

    _test_authorizer = test_authorizer
    _ftp_channel = ftp_channel
    _ftp_server = ftp_server

    return True


def get_test_permutations():
    """Return the permutations to be used in testing."""
    if not _setup_medusa():
        warn("You must install medusa (http://www.amk.ca/python/code/medusa.html) for FTP tests")
        return []
    else:
        return [(FtpTransport, FtpServer)]
