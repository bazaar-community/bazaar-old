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


"""Locking using OS file locks or file existence.

Note: This method of locking is generally deprecated in favour of LockDir, but
is used to lock local WorkingTrees, and by some old formats.  It's accessed
through Transport.lock_read(), etc.

This module causes two methods, lock() and unlock() to be defined in
any way that works on the current platform.

It is not specified whether these locks are reentrant (i.e. can be
taken repeatedly by a single process) or whether they exclude
different threads in a single process.  That reentrancy is provided by 
LockableFiles.

This defines two classes: ReadLock and WriteLock, which can be
implemented in different ways on different platforms.  Both have an
unlock() method.
"""

import errno
import os
import sys

from bzrlib.errors import LockError
from bzrlib.osutils import realpath
from bzrlib.trace import mutter


class _base_Lock(object):

    def _open(self, filename, filemode):
        try:
            self.f = open(filename, filemode)
            return self.f
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise

            # maybe this is an old branch (before may 2005)
            mutter("trying to create missing branch lock %r", filename)
            
            self.f = open(filename, 'wb+')
            return self.f

    def __del__(self):
        if self.f:
            from warnings import warn
            warn("lock on %r not released" % self.f)
            self.unlock()
            
    def unlock(self):
        raise NotImplementedError()


############################################################
# msvcrt locks


try:
    import fcntl

    class _fcntl_FileLock(_base_Lock):

        f = None

        def _unlock(self):
            fcntl.lockf(self.f, fcntl.LOCK_UN)
            self._clear_f()

        def _clear_f(self):
            """Clear the self.f attribute cleanly."""
            self.f.close()
            del self.f 


    class _fcntl_WriteLock(_fcntl_FileLock):

        open_locks = {}

        def __init__(self, filename):
            # standard IO errors get exposed directly.
            self._open(filename, 'rb+')
            try:
                self.filename = realpath(filename)
                if self.filename in self.open_locks:
                    self._clear_f() 
                    raise LockError("Lock already held.")
                # reserve a slot for this lock - even if the lockf call fails, 
                # at thisi point unlock() will be called, because self.f is set.
                # TODO: make this fully threadsafe, if we decide we care.
                self.open_locks[self.filename] = self.filename
                fcntl.lockf(self.f, fcntl.LOCK_EX)
            except IOError, e:
                # we should be more precise about whats a locking
                # error and whats a random-other error
                raise LockError(e)

        def unlock(self):
            del self.open_locks[self.filename]
            self._unlock()


    class _fcntl_ReadLock(_fcntl_FileLock):

        def __init__(self, filename):
            # standard IO errors get exposed directly.
            self._open(filename, 'rb')
            try:
                fcntl.lockf(self.f, fcntl.LOCK_SH)
            except IOError, e:
                # we should be more precise about whats a locking
                # error and whats a random-other error
                raise LockError(e)

        def unlock(self):
            self._unlock()


    WriteLock = _fcntl_WriteLock
    ReadLock = _fcntl_ReadLock


except ImportError:
    try:
        import win32con, win32file, pywintypes


        LOCK_SH = 0 # the default
        LOCK_EX = win32con.LOCKFILE_EXCLUSIVE_LOCK
        LOCK_NB = win32con.LOCKFILE_FAIL_IMMEDIATELY

        class _w32c_FileLock(_base_Lock):
            def _lock(self, filename, openmode, lockmode):
                try:
                    self._open(filename, openmode)
                    self.hfile = win32file._get_osfhandle(self.f.fileno())
                    overlapped = pywintypes.OVERLAPPED()
                    win32file.LockFileEx(self.hfile, lockmode, 0, 0x7fff0000, overlapped)
                except Exception, e:
                    if self.f:
                        self.f.close()
                        self.f = None
                    raise LockError(e)

            def unlock(self):
                try:
                    overlapped = pywintypes.OVERLAPPED()
                    win32file.UnlockFileEx(self.hfile, 0, 0x7fff0000, overlapped)
                    self.f.close()
                    self.f = None
                except Exception, e:
                    raise LockError(e)


        class _w32c_ReadLock(_w32c_FileLock):
            def __init__(self, filename):
                _w32c_FileLock._lock(self, filename, 'rb',
                                     LOCK_NB)

        class _w32c_WriteLock(_w32c_FileLock):
            def __init__(self, filename):
                _w32c_FileLock._lock(self, filename, 'rb+',
                                     LOCK_EX + LOCK_NB)


        WriteLock = _w32c_WriteLock
        ReadLock = _w32c_ReadLock

    except ImportError:
        try:
            import msvcrt


            # Unfortunately, msvcrt.locking() doesn't distinguish between
            # read locks and write locks. Also, the way the combinations
            # work to get non-blocking is not the same, so we
            # have to write extra special functions here.


            class _msvc_FileLock(_base_Lock):
                LOCK_SH = 1
                LOCK_EX = 2
                LOCK_NB = 4
                def unlock(self):
                    _msvc_unlock(self.f)
                    self.f.close()
                    self.f = None


            class _msvc_ReadLock(_msvc_FileLock):
                def __init__(self, filename):
                    _msvc_lock(self._open(filename, 'rb'), self.LOCK_SH)


            class _msvc_WriteLock(_msvc_FileLock):
                def __init__(self, filename):
                    _msvc_lock(self._open(filename, 'rb+'), self.LOCK_EX)


            def _msvc_lock(f, flags):
                try:
                    # Unfortunately, msvcrt.LK_RLCK is equivalent to msvcrt.LK_LOCK
                    # according to the comments, LK_RLCK is open the lock for writing.

                    # Unfortunately, msvcrt.locking() also has the side effect that it
                    # will only block for 10 seconds at most, and then it will throw an
                    # exception, this isn't terrible, though.
                    if type(f) == file:
                        fpos = f.tell()
                        fn = f.fileno()
                        f.seek(0)
                    else:
                        fn = f
                        fpos = os.lseek(fn, 0,0)
                        os.lseek(fn, 0,0)

                    if flags & _msvc_FileLock.LOCK_SH:
                        if flags & _msvc_FileLock.LOCK_NB:
                            lock_mode = msvcrt.LK_NBLCK
                        else:
                            lock_mode = msvcrt.LK_LOCK
                    elif flags & _msvc_FileLock.LOCK_EX:
                        if flags & _msvc_FileLock.LOCK_NB:
                            lock_mode = msvcrt.LK_NBRLCK
                        else:
                            lock_mode = msvcrt.LK_RLCK
                    else:
                        raise ValueError('Invalid lock mode: %r' % flags)
                    try:
                        msvcrt.locking(fn, lock_mode, -1)
                    finally:
                        os.lseek(fn, fpos, 0)
                except Exception, e:
                    raise LockError(e)

            def _msvc_unlock(f):
                try:
                    if type(f) == file:
                        fpos = f.tell()
                        fn = f.fileno()
                        f.seek(0)
                    else:
                        fn = f
                        fpos = os.lseek(fn, 0,0)
                        os.lseek(fn, 0,0)

                    try:
                        msvcrt.locking(fn, msvcrt.LK_UNLCK, -1)
                    finally:
                        os.lseek(fn, fpos, 0)
                except Exception, e:
                    raise LockError(e)


            WriteLock = _msvc_WriteLock
            ReadLock = _msvc_ReadLock
        except ImportError:
            raise NotImplementedError("please write a locking method "
                                      "for platform %r" % sys.platform)
