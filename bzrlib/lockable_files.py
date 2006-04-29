# Copyright (C) 2005, 2006 Canonical Ltd

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

from cStringIO import StringIO
import codecs
#import traceback

import bzrlib
from bzrlib.decorators import *
import bzrlib.errors as errors
from bzrlib.errors import LockError, ReadOnlyError
from bzrlib.lockdir import LockDir
from bzrlib.osutils import file_iterator, safe_unicode
from bzrlib.symbol_versioning import *
from bzrlib.trace import mutter, note
import bzrlib.transactions as transactions

# XXX: The tracking here of lock counts and whether the lock is held is
# somewhat redundant with what's done in LockDir; the main difference is that
# LockableFiles permits reentrancy.

class LockableFiles(object):
    """Object representing a set of related files locked within the same scope.

    These files are used by a WorkingTree, Repository or Branch, and should
    generally only be touched by that object.

    LockableFiles also provides some policy on top of Transport for encoding
    control files as utf-8.

    LockableFiles manage a lock count and can be locked repeatedly by
    a single caller.  (The underlying lock implementation generally does not
    support this.)

    Instances of this class are often called control_files.
    
    This object builds on top of a Transport, which is used to actually write
    the files to disk, and an OSLock or LockDir, which controls how access to
    the files is controlled.  The particular type of locking used is set when
    the object is constructed.  In older formats OSLocks are used everywhere.
    in newer formats a LockDir is used for Repositories and Branches, and 
    OSLocks for the local filesystem.
    """

    # _lock_mode: None, or 'r' or 'w'

    # _lock_count: If _lock_mode is true, a positive count of the number of
    # times the lock has been taken *by this process*.   
    
    # If set to False (by a plugin, etc) BzrBranch will not set the
    # mode on created files or directories
    _set_file_mode = True
    _set_dir_mode = True

    def __init__(self, transport, lock_name, lock_class):
        """Create a LockableFiles group

        :param transport: Transport pointing to the directory holding the 
            control files and lock.
        :param lock_name: Name of the lock guarding these files.
        :param lock_class: Class of lock strategy to use: typically
            either LockDir or TransportLock.
        """
        object.__init__(self)
        self._transport = transport
        self.lock_name = lock_name
        self._transaction = None
        self._find_modes()
        self._lock_mode = None
        self._lock_count = 0
        esc_name = self._escape(lock_name)
        self._lock = lock_class(transport, esc_name,
                                file_modebits=self._file_mode,
                                dir_modebits=self._dir_mode)

    def create_lock(self):
        """Create the lock.

        This should normally be called only when the LockableFiles directory
        is first created on disk.
        """
        self._lock.create(mode=self._dir_mode)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__,
                           self._transport)
    def __str__(self):
        return 'LockableFiles(%s, %s)' % (self.lock_name, self._transport.base)

    def __del__(self):
        if self.is_locked():
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
        return bzrlib.transport.urlescape(safe_unicode(file_or_path))

    def _find_modes(self):
        """Determine the appropriate modes for files and directories."""
        try:
            st = self._transport.stat('.')
        except errors.TransportNotPossible:
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

    @deprecated_method(zero_eight)
    def controlfile(self, file_or_path, mode='r'):
        """Open a control file for this branch.

        There are two classes of file in a lockable directory: text
        and binary.  binary files are untranslated byte streams.  Text
        control files are stored with Unix newlines and in UTF-8, even
        if the platform or locale defaults are different.

        Such files are not openable in write mode : they are managed via
        put and put_utf8 which atomically replace old versions using
        atomicfile.
        """

        relpath = self._escape(file_or_path)
        # TODO: codecs.open() buffers linewise, so it was overloaded with
        # a much larger buffer, do we need to do the same for getreader/getwriter?
        if mode == 'rb': 
            return self.get(relpath)
        elif mode == 'wb':
            raise BzrError("Branch.controlfile(mode='wb') is not supported, use put[_utf8]")
        elif mode == 'r':
            return self.get_utf8(relpath)
        elif mode == 'w':
            raise BzrError("Branch.controlfile(mode='w') is not supported, use put[_utf8]")
        else:
            raise BzrError("invalid controlfile mode %r" % mode)

    @needs_read_lock
    def get(self, relpath):
        """Get a file as a bytestream."""
        relpath = self._escape(relpath)
        return self._transport.get(relpath)

    @needs_read_lock
    def get_utf8(self, relpath):
        """Get a file as a unicode stream."""
        relpath = self._escape(relpath)
        # DO NOT introduce an errors=replace here.
        return codecs.getreader('utf-8')(self._transport.get(relpath))

    @needs_write_lock
    def put(self, path, file):
        """Write a file.
        
        :param path: The path to put the file, relative to the .bzr control
                     directory
        :param f: A file-like or string object whose contents should be copied.
        """
        self._transport.put(self._escape(path), file, mode=self._file_mode)

    @needs_write_lock
    def put_utf8(self, path, a_string):
        """Write a string, encoding as utf-8.

        :param path: The path to put the string, relative to the transport root.
        :param string: A file-like or string object whose contents should be copied.
        """
        # IterableFile would not be needed if Transport.put took iterables
        # instead of files.  ADHB 2005-12-25
        # RBC 20060103 surely its not needed anyway, with codecs transcode
        # file support ?
        # JAM 20060103 We definitely don't want encode(..., 'replace')
        # these are valuable files which should have exact contents.
        if not isinstance(a_string, basestring):
            raise errors.BzrBadParameterNotString(a_string)
        self.put(path, StringIO(a_string.encode('utf-8')))

    def lock_write(self):
        # mutter("lock write: %s (%s)", self, self._lock_count)
        # TODO: Upgrade locking to support using a Transport,
        # and potentially a remote locking protocol
        if self._lock_mode:
            if self._lock_mode != 'w' or not self.get_transaction().writeable():
                raise ReadOnlyError(self)
            self._lock_count += 1
        else:
            self._lock.lock_write()
            #note('write locking %s', self)
            #traceback.print_stack()
            self._lock_mode = 'w'
            self._lock_count = 1
            self._set_transaction(transactions.WriteTransaction())

    def lock_read(self):
        # mutter("lock read: %s (%s)", self, self._lock_count)
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w'), \
                   "invalid lock mode %r" % self._lock_mode
            self._lock_count += 1
        else:
            self._lock.lock_read()
            #note('read locking %s', self)
            #traceback.print_stack()
            self._lock_mode = 'r'
            self._lock_count = 1
            self._set_transaction(transactions.ReadOnlyTransaction())
            # 5K may be excessive, but hey, its a knob.
            self.get_transaction().set_cache_size(5000)
                        
    def unlock(self):
        # mutter("unlock: %s (%s)", self, self._lock_count)
        if not self._lock_mode:
            raise errors.LockNotHeld(self)
        if self._lock_count > 1:
            self._lock_count -= 1
        else:
            #note('unlocking %s', self)
            #traceback.print_stack()
            self._finish_transaction()
            self._lock.unlock()
            self._lock_mode = self._lock_count = None

    def is_transport_locked(self):
        """Return true if a lock exists on the transport."""
        l = LockDir(self._transport, self.lock_name)
        return l.peek() is not None

    def is_locked(self):
        """Return true if this LockableFiles group is locked"""
        return self._lock_count >= 1

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


class TransportLock(object):
    """Locking method which uses transport-dependent locks.

    On the local filesystem these transform into OS-managed locks.

    These do not guard against concurrent access via different
    transports.

    This is suitable for use only in WorkingTrees (which are at present
    always local).
    """
    def __init__(self, transport, escaped_name, file_modebits, dir_modebits):
        self._transport = transport
        self._escaped_name = escaped_name
        self._file_modebits = file_modebits
        self._dir_modebits = dir_modebits

    def lock_write(self):
        self._lock = self._transport.lock_write(self._escaped_name)

    def lock_read(self):
        self._lock = self._transport.lock_read(self._escaped_name)

    def unlock(self):
        self._lock.unlock()
        self._lock = None

    def create(self, mode=None):
        """Create lock mechanism"""
        # for old-style locks, create the file now
        self._transport.put(self._escaped_name, StringIO(), 
                            mode=self._file_modebits)
