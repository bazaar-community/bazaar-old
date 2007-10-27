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

# TODO: Could remember a bias towards whether a particular store is typically
# compressed or not.

"""
Stores are the main data-storage mechanism for Bazaar.

A store is a simple write-once container indexed by a universally
unique ID.
"""

import os
from cStringIO import StringIO
import urllib
from zlib import adler32

import bzrlib
from bzrlib import (
    errors,
    osutils,
    symbol_versioning,
    urlutils,
    )
from bzrlib.errors import BzrError, UnlistableStore, TransportNotPossible
from bzrlib.symbol_versioning import (
    deprecated_function,
    )
from bzrlib.trace import mutter
from bzrlib.transport import Transport
from bzrlib.transport.local import LocalTransport

######################################################################
# stores

class StoreError(Exception):
    pass


class Store(object):
    """This class represents the abstract storage layout for saving information.
    
    Files can be added, but not modified once they are in.  Typically
    the hash is used as the name, or something else known to be unique,
    such as a UUID.
    """

    def __len__(self):
        raise NotImplementedError('Children should define their length')

    def get(self, fileid, suffix=None):
        """Returns a file reading from a particular entry.
        
        If suffix is present, retrieve the named suffix for fileid.
        """
        raise NotImplementedError

    def __getitem__(self, fileid):
        """DEPRECATED. Please use .get(fileid) instead."""
        raise NotImplementedError

    #def __contains__(self, fileid):
    #    """Deprecated, please use has_id"""
    #    raise NotImplementedError

    def __iter__(self):
        raise NotImplementedError

    def add(self, f, fileid):
        """Add a file object f to the store accessible from the given fileid"""
        raise NotImplementedError('Children of Store must define their method of adding entries.')

    def has_id(self, fileid, suffix=None):
        """Return True or false for the presence of fileid in the store.
        
        suffix, if present, is a per file suffix, i.e. for digital signature 
        data."""
        raise NotImplementedError

    def listable(self):
        """Return True if this store is able to be listed."""
        return (getattr(self, "__iter__", None) is not None)

    def copy_all_ids(self, store_from, pb=None):
        """Copy all the file ids from store_from into self."""
        if not store_from.listable():
            raise UnlistableStore(store_from)
        ids = []
        for count, file_id in enumerate(store_from):
            if pb:
                pb.update('listing files', count, count)
            ids.append(file_id)
        if pb:
            pb.clear()
        mutter('copy_all ids: %r', ids)
        self.copy_multi(store_from, ids, pb=pb)

    def copy_multi(self, other, ids, pb=None, permit_failure=False):
        """Copy texts for ids from other into self.

        If an id is present in self, it is skipped.  A count of copied
        ids is returned, which may be less than len(ids).

        :param other: Another Store object
        :param ids: A list of entry ids to be copied
        :param pb: A ProgressBar object, if none is given, the default will be created.
        :param permit_failure: Allow missing entries to be ignored
        :return: (n_copied, [failed]) The number of entries copied successfully,
            followed by a list of entries which could not be copied (because they
            were missing)
        """
        if pb:
            pb.update('preparing to copy')
        failed = set()
        count = 0
        for fileid in ids:
            count += 1
            if self.has_id(fileid):
                continue
            try:
                self._copy_one(fileid, None, other, pb)
                for suffix in self._suffixes:
                    try:
                        self._copy_one(fileid, suffix, other, pb)
                    except KeyError:
                        pass
                if pb:
                    pb.update('copy', count, len(ids))
            except KeyError:
                if permit_failure:
                    failed.add(fileid)
                else:
                    raise
        assert count == len(ids)
        if pb:
            pb.clear()
        return count, failed

    def _copy_one(self, fileid, suffix, other, pb):
        """Most generic copy-one object routine.
        
        Subclasses can override this to provide an optimised
        copy between their own instances. Such overriden routines
        should call this if they have no optimised facility for a 
        specific 'other'.
        """
        mutter('Store._copy_one: %r', fileid)
        f = other.get(fileid, suffix)
        self.add(f, fileid, suffix)


class TransportStore(Store):
    """A TransportStore is a Store superclass for Stores that use Transports."""

    def add(self, f, fileid, suffix=None):
        """Add contents of a file into the store.

        f -- A file-like object
        """
        mutter("add store entry %r", fileid)
        names = self._id_to_names(fileid, suffix)
        if self._transport.has_any(names):
            raise BzrError("store %r already contains id %r" 
                           % (self._transport.base, fileid))

        # Most of the time, just adding the file will work
        # if we find a time where it fails, (because the dir
        # doesn't exist), then create the dir, and try again
        self._add(names[0], f)

    def _add(self, relpath, f):
        """Actually add the file to the given location.
        This should be overridden by children.
        """
        raise NotImplementedError('children need to implement this function.')

    def _check_fileid(self, fileid):
        if not isinstance(fileid, basestring):
            raise TypeError('Fileids should be a string type: %s %r' % (type(fileid), fileid))
        if '\\' in fileid or '/' in fileid:
            raise ValueError("invalid store id %r" % fileid)

    def _id_to_names(self, fileid, suffix):
        """Return the names in the expected order"""
        if suffix is not None:
            fn = self._relpath(fileid, [suffix])
        else:
            fn = self._relpath(fileid)

        # FIXME RBC 20051128 this belongs in TextStore.
        fn_gz = fn + '.gz'
        if self._compressed:
            return fn_gz, fn
        else:
            return fn, fn_gz

    def has_id(self, fileid, suffix=None):
        """See Store.has_id."""
        return self._transport.has_any(self._id_to_names(fileid, suffix))

    def _get_name(self, fileid, suffix=None):
        """A special check, which returns the name of an existing file.
        
        This is similar in spirit to 'has_id', but it is designed
        to return information about which file the store has.
        """
        for name in self._id_to_names(fileid, suffix=suffix):
            if self._transport.has(name):
                return name
        return None

    def _get(self, filename):
        """Return an vanilla file stream for clients to read from.

        This is the body of a template method on 'get', and should be 
        implemented by subclasses.
        """
        raise NotImplementedError

    def get(self, fileid, suffix=None):
        """See Store.get()."""
        names = self._id_to_names(fileid, suffix)
        for name in names:
            try:
                return self._get(name)
            except errors.NoSuchFile:
                pass
        raise KeyError(fileid)

    def __init__(self, a_transport, prefixed=False, compressed=False,
                 dir_mode=None, file_mode=None,
                 escaped=False):
        assert isinstance(a_transport, Transport)
        super(TransportStore, self).__init__()
        self._transport = a_transport
        self._prefixed = prefixed
        # FIXME RBC 20051128 this belongs in TextStore.
        self._compressed = compressed
        self._suffixes = set()
        self._escaped = escaped

        # It is okay for these to be None, it just means they
        # will just use the filesystem defaults
        self._dir_mode = dir_mode
        self._file_mode = file_mode

    def _unescape(self, file_id):
        """If filename escaping is enabled for this store, unescape and return the filename."""
        if self._escaped:
            return urllib.unquote(file_id)
        else:
            return file_id

    def _iter_files_recursive(self):
        """Iterate through the files in the transport."""
        for quoted_relpath in self._transport.iter_files_recursive():
            # transport iterator always returns quoted paths, regardless of
            # escaping
            yield urllib.unquote(quoted_relpath)

    def __iter__(self):
        for relpath in self._iter_files_recursive():
            # worst case is one of each suffix.
            name = os.path.basename(relpath)
            if name.endswith('.gz'):
                name = name[:-3]
            skip = False
            for count in range(len(self._suffixes)):
                for suffix in self._suffixes:
                    if name.endswith('.' + suffix):
                        skip = True
            if not skip:
                yield self._unescape(name)

    def __len__(self):
        return len(list(self.__iter__()))

    def _relpath(self, fileid, suffixes=None):
        self._check_fileid(fileid)
        if suffixes:
            for suffix in suffixes:
                if not suffix in self._suffixes:
                    raise ValueError("Unregistered suffix %r" % suffix)
                self._check_fileid(suffix)
        else:
            suffixes = []
        fileid = self._escape_file_id(fileid)
        if self._prefixed:
            # hash_prefix adds the '/' separator
            prefix = self.hash_prefix(fileid, escaped=True)
        else:
            prefix = ''
        path = prefix + fileid
        full_path = u'.'.join([path] + suffixes)
        return urlutils.escape(full_path)

    def _escape_file_id(self, file_id):
        """Turn a file id into a filesystem safe string.

        This is similar to a plain urllib.quote, except
        it uses specific safe characters, so that it doesn't
        have to translate a lot of valid file ids.
        """
        if not self._escaped:
            return file_id
        if isinstance(file_id, unicode):
            file_id = file_id.encode('utf-8')
        # @ does not get escaped. This is because it is a valid
        # filesystem character we use all the time, and it looks
        # a lot better than seeing %40 all the time.
        safe = "abcdefghijklmnopqrstuvwxyz0123456789-_@,."
        r = [((c in safe) and c or ('%%%02x' % ord(c)))
             for c in file_id]
        return ''.join(r)

    def hash_prefix(self, fileid, escaped=False):
        # fileid should be unescaped
        if not escaped and self._escaped:
            fileid = self._escape_file_id(fileid)
        return "%02x/" % (adler32(fileid) & 0xff)

    def __repr__(self):
        if self._transport is None:
            return "%s(None)" % (self.__class__.__name__)
        else:
            return "%s(%r)" % (self.__class__.__name__, self._transport.base)

    __str__ = __repr__

    def listable(self):
        """Return True if this store is able to be listed."""
        return self._transport.listable()

    def register_suffix(self, suffix):
        """Register a suffix as being expected in this store."""
        self._check_fileid(suffix)
        if suffix == 'gz':
            raise ValueError('You cannot register the "gz" suffix.')
        self._suffixes.add(suffix)

    def total_size(self):
        """Return (count, bytes)

        This is the (compressed) size stored on disk, not the size of
        the content."""
        total = 0
        count = 0
        for relpath in self._transport.iter_files_recursive():
            count += 1
            total += self._transport.stat(relpath).st_size
                
        return count, total
