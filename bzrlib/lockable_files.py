# Copyright (C) 2005 Canonical Ltd

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


import bzrlib
import bzrlib.errors as errors
from bzrlib.errors import LockError, ReadOnlyError
from bzrlib.trace import mutter
import bzrlib.transactions as transactions
from osutils import file_iterator

class LockableFiles(object):
    """Object representing a set of lockable files

    _lock_mode
        None, or 'r' or 'w'

    _lock_count
        If _lock_mode is true, a positive count of the number of times the
        lock has been taken.

    _lock
        Lock object from bzrlib.lock.
    """

    _lock_mode = None
    _lock_count = None
    _lock = None
    # If set to False (by a plugin, etc) BzrBranch will not set the
    # mode on created files or directories
    _set_file_mode = True
    _set_dir_mode = True

    def __init__(self, transport, lock_name):
        object.__init__(self)
        self._transport = transport
        self.lock_name = lock_name
        self._transaction = None
        self._find_modes()

    def __del__(self):
        if self._lock_mode or self._lock:
            # XXX: This should show something every time, and be suitable for
            # headless operation and embedding
            from warnings import warn
            warn("file group %r was not explicitly unlocked" % self)
            self._lock.unlock()

    def _escape(self, file_or_path):
        if not isinstance(file_or_path, basestring):
            file_or_path = '/'.join(file_or_path)
        if file_or_path == '':
            return u''
        return bzrlib.transport.urlescape(unicode(file_or_path))

    def _find_modes(self):
        """Determine the appropriate modes for files and directories."""
        try:
            try:
                st = self._transport.stat(u'.')
            except errors.NoSuchFile:
                # The .bzr/ directory doesn't exist, try to
                # inherit the permissions from the parent directory
                # but only try 1 level up
                temp_transport = self._transport.clone('..')
                st = temp_transport.stat(u'.')
        except (errors.TransportNotPossible, errors.NoSuchFile):
            self._dir_mode = 0755
            self._file_mode = 0644
        else:
            self._dir_mode = st.st_mode & 07777
            # Remove the sticky and execute bits for files
            self._file_mode = self._dir_mode & ~07111
        if not self._set_dir_mode:
            self._dir_mode = None
        if not self._set_file_mode:
            self._file_mode = None

    def controlfilename(self, file_or_path):
        """Return location relative to branch."""
        return self._transport.abspath(self._escape(file_or_path))

    def controlfile(self, file_or_path, mode='r'):
        """Open a control file for this branch.

        There are two classes of file in the control directory: text
        and binary.  binary files are untranslated byte streams.  Text
        control files are stored with Unix newlines and in UTF-8, even
        if the platform or locale defaults are different.

        Controlfiles should almost never be opened in write mode but
        rather should be atomically copied and replaced using atomicfile.
        """
        import codecs

        relpath = self._escape(file_or_path)
        #TODO: codecs.open() buffers linewise, so it was overloaded with
        # a much larger buffer, do we need to do the same for getreader/getwriter?
        if mode == 'rb': 
            return self._transport.get(relpath)
        elif mode == 'wb':
            raise BzrError("Branch.controlfile(mode='wb') is not supported, use put[_utf8]")
        elif mode == 'r':
            # XXX: Do we really want errors='replace'?   Perhaps it should be
            # an error, or at least reported, if there's incorrectly-encoded
            # data inside a file.
            # <https://launchpad.net/products/bzr/+bug/3823>
            return codecs.getreader('utf-8')(self._transport.get(relpath), errors='replace')
        elif mode == 'w':
            raise BzrError("Branch.controlfile(mode='w') is not supported, use put[_utf8]")
        else:
            raise BzrError("invalid controlfile mode %r" % mode)

    def put(self, path, file):
        """Write a file.
        
        :param path: The path to put the file, relative to the .bzr control
                     directory
        :param f: A file-like or string object whose contents should be copied.
        """
        if not self._lock_mode == 'w':
            raise ReadOnlyError()
        self._transport.put(self._escape(path), file, mode=self._file_mode)

    def put_utf8(self, path, file, mode=None):
        """Write a file, encoding as utf-8.

        :param path: The path to put the file, relative to the .bzr control
                     directory
        :param f: A file-like or string object whose contents should be copied.
        """
        import codecs
        from iterablefile import IterableFile
        ctrl_files = []
        if hasattr(file, 'read'):
            iterator = file_iterator(file)
        else:
            iterator = file
        # IterableFile would not be needed if Transport.put took iterables
        # instead of files.  ADHB 2005-12-25
        # RBC 20060103 surely its not needed anyway, with codecs transcode
        # file support ?
        # JAM 20060103 We definitely don't want encode(..., 'replace')
        # these are valuable files which should have exact contents.
        encoded_file = IterableFile(b.encode('utf-8') for b in 
                                    iterator)
        self.put(path, encoded_file)

    def lock_write(self):
        mutter("lock write: %s (%s)", self, self._lock_count)
        # TODO: Upgrade locking to support using a Transport,
        # and potentially a remote locking protocol
        if self._lock_mode:
            if self._lock_mode != 'w':
                raise LockError("can't upgrade to a write lock from %r" %
                                self._lock_mode)
            self._lock_count += 1
        else:
            self._lock = self._transport.lock_write(
                    self._escape(self.lock_name))
            self._lock_mode = 'w'
            self._lock_count = 1
            self._set_transaction(transactions.PassThroughTransaction())

    def lock_read(self):
        mutter("lock read: %s (%s)", self, self._lock_count)
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w'), \
                   "invalid lock mode %r" % self._lock_mode
            self._lock_count += 1
        else:
            self._lock = self._transport.lock_read(
                    self._escape(self.lock_name))
            self._lock_mode = 'r'
            self._lock_count = 1
            self._set_transaction(transactions.ReadOnlyTransaction())
            # 5K may be excessive, but hey, its a knob.
            self.get_transaction().set_cache_size(5000)
                        
    def unlock(self):
        mutter("unlock: %s (%s)", self, self._lock_count)
        if not self._lock_mode:
            raise LockError('branch %r is not locked' % (self))

        if self._lock_count > 1:
            self._lock_count -= 1
        else:
            self._finish_transaction()
            self._lock.unlock()
            self._lock = None
            self._lock_mode = self._lock_count = None

    def get_transaction(self):
        """Return the current active transaction.

        If no transaction is active, this returns a passthrough object
        for which all data is immediately flushed and no caching happens.
        """
        if self._transaction is None:
            return transactions.PassThroughTransaction()
        else:
            return self._transaction

    def _set_transaction(self, new_transaction):
        """Set a new active transaction."""
        if self._transaction is not None:
            raise errors.LockError('Branch %s is in a transaction already.' %
                                   self)
        self._transaction = new_transaction

    def _finish_transaction(self):
        """Exit the current transaction."""
        if self._transaction is None:
            raise errors.LockError('Branch %s is not in a transaction' %
                                   self)
        transaction = self._transaction
        self._transaction = None
        transaction.finish()
