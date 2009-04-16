# Copyright (C) 2006, 2008 Canonical Ltd
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

"""A simple least-recently-used (LRU) cache."""

from bzrlib import (
    symbol_versioning,
    trace,
    )


class _LRUNode(object):
    """This maintains the linked-list which is the lru internals."""

    __slots__ = ('prev', 'next_key', 'key', 'value', 'cleanup', 'size')

    def __init__(self, key, value, cleanup=None):
        self.prev = None
        self.next_key = None
        self.key = key
        self.value = value
        self.cleanup = cleanup
        # TODO: We could compute this 'on-the-fly' like we used to, and remove
        #       one pointer from this object, we just need to decide if it
        #       actually costs us much of anything in normal usage
        self.size = None

    def __repr__(self):
        if self.prev is None:
            prev_key = None
        else:
            prev_key = self.prev_key
        return '%s(%r n:%r p:%r)' % (self.__class__.__name__, self.key,
                                     self.next_key, prev_key)

    def run_cleanup(self):
        if self.cleanup is not None:
            self.cleanup(self.key, self.value)
        self.cleanup = None
        # Just make sure to break any refcycles, etc
        self.value = None


class LRUCache(object):
    """A class which manages a cache of entries, removing unused ones."""

    def __init__(self, max_cache=100, after_cleanup_count=None,
                 after_cleanup_size=symbol_versioning.DEPRECATED_PARAMETER):
        if symbol_versioning.deprecated_passed(after_cleanup_size):
            symbol_versioning.warn('LRUCache.__init__(after_cleanup_size) was'
                                   ' deprecated in 1.11. Use'
                                   ' after_cleanup_count instead.',
                                   DeprecationWarning)
            after_cleanup_count = after_cleanup_size
        self._cache = {}
        # The "HEAD" of the lru linked list
        self._most_recently_used = None
        # The "TAIL" of the lru linked list
        self._last_recently_used = None
        self._update_max_cache(max_cache, after_cleanup_count)

    def __contains__(self, key):
        return key in self._cache

    def __getitem__(self, key):
        cache = self._cache
        node = cache[key]
        # Inlined from _record_access to decrease the overhead of __getitem__
        # We also have more knowledge about structure if __getitem__ is
        # succeeding, then we know that self._most_recently_used must not be
        # None, etc.
        mru = self._most_recently_used
        if node is mru:
            # Nothing to do, this node is already at the head of the queue
            return node.value
        # Remove this node from the old location
        node_prev = node.prev
        next_key = node.next_key
        if next_key is None:
            # 'node' is the _last_recently_used, because it doesn't have a
            # 'next' item. So move the current lru to the previous node.
            self._last_recently_used = node_prev
        else:
            node_next = cache[next_key]
            node_next.prev = node_prev
        node_prev.next_key = next_key
        # Insert this node at the front of the list
        node.next_key = mru.key
        mru.prev = node
        self._most_recently_used = node
        node.prev = None
        return node.value

    def __len__(self):
        return len(self._cache)

    def _walk_lru(self):
        """Walk the LRU list, only meant to be used in tests."""
        node = self._most_recently_used
        if node is not None:
            if node.prev is not None:
                raise AssertionError('the _most_recently_used entry is not'
                                     ' supposed to have a previous entry'
                                     ' %s' % (node,))
        while node is not None:
            if node.next_key is None:
                if node is not self._last_recently_used:
                    raise AssertionError('only the last node should have'
                                         ' no next value: %s' % (node,))
                node_next = None
            else:
                node_next = self._cache[node.next_key]
                if node_next.prev is not node:
                    raise AssertionError('inconsistency found, node.next.prev'
                                         ' != node: %s' % (node,))
            if node.prev is None:
                if node is not self._most_recently_used:
                    raise AssertionError('only the _most_recently_used should'
                                         ' not have a previous node: %s'
                                         % (node,))
            else:
                if node.prev.next_key != node.key:
                    raise AssertionError('inconsistency found, node.prev.next'
                                         ' != node: %s' % (node,))
            yield node
            node = node_next

    def add(self, key, value, cleanup=None):
        """Add a new value to the cache.

        Also, if the entry is ever removed from the cache, call
        cleanup(key, value).

        :param key: The key to store it under
        :param value: The object to store
        :param cleanup: None or a function taking (key, value) to indicate
                        'value' should be cleaned up.
        """
        if key is None:
            # We use None to indicate non-entries in our key following code.
            raise ValueError('LRUCache cannot map None as a key')
        if key in self._cache:
            node = self._cache[key]
            node.run_cleanup()
            node.value = value
            node.cleanup = cleanup
        else:
            node = _LRUNode(key, value, cleanup=cleanup)
            self._cache[key] = node
        self._record_access(node)

        if len(self._cache) > self._max_cache:
            # Trigger the cleanup
            self.cleanup()

    def cache_size(self):
        """Get the number of entries we will cache."""
        return self._max_cache

    def get(self, key, default=None):
        node = self._cache.get(key, None)
        if node is None:
            return default
        self._record_access(node)
        return node.value

    def keys(self):
        """Get the list of keys currently cached.

        Note that values returned here may not be available by the time you
        request them later. This is simply meant as a peak into the current
        state.

        :return: An unordered list of keys that are currently cached.
        """
        return self._cache.keys()

    def items(self):
        """Get the key:value pairs as a dict."""
        return dict((k, n.value) for k, n in self._cache.iteritems())

    def cleanup(self):
        """Clear the cache until it shrinks to the requested size.

        This does not completely wipe the cache, just makes sure it is under
        the after_cleanup_count.
        """
        # Make sure the cache is shrunk to the correct size
        while len(self._cache) > self._after_cleanup_count:
            self._remove_lru()

    def __setitem__(self, key, value):
        """Add a value to the cache, there will be no cleanup function."""
        self.add(key, value, cleanup=None)

    def _record_access(self, node):
        """Record that key was accessed."""
        # Move 'node' to the front of the queue
        if self._most_recently_used is None:
            self._most_recently_used = node
            self._last_recently_used = node
            return
        elif node is self._most_recently_used:
            # Nothing to do, this node is already at the head of the queue
            return
        # We've taken care of the tail pointer, remove the node, and insert it
        # at the front
        # REMOVE
        if node is self._last_recently_used:
            self._last_recently_used = node.prev
        if node.prev is not None:
            node.prev.next_key = node.next_key
        if node.next_key is not None:
            node_next = self._cache[node.next_key]
            node_next.prev = node.prev
        # INSERT
        node.next_key = self._most_recently_used.key
        self._most_recently_used.prev = node
        self._most_recently_used = node
        node.prev = None

    def _remove_node(self, node):
        if node is self._last_recently_used:
            self._last_recently_used = node.prev
        self._cache.pop(node.key)
        # If we have removed all entries, remove the head pointer as well
        if self._last_recently_used is None:
            self._most_recently_used = None
        node.run_cleanup()
        # Now remove this node from the linked list
        if node.prev is not None:
            node.prev.next_key = node.next_key
        if node.next_key is not None:
            node_next = self._cache[node.next_key]
            node_next.prev = node.prev
        # And remove this node's pointers
        node.prev = None
        node.next_key = None

    def _remove_lru(self):
        """Remove one entry from the lru, and handle consequences.

        If there are no more references to the lru, then this entry should be
        removed from the cache.
        """
        self._remove_node(self._last_recently_used)

    def clear(self):
        """Clear out all of the cache."""
        # Clean up in LRU order
        while self._cache:
            self._remove_lru()

    def resize(self, max_cache, after_cleanup_count=None):
        """Change the number of entries that will be cached."""
        self._update_max_cache(max_cache,
                               after_cleanup_count=after_cleanup_count)

    def _update_max_cache(self, max_cache, after_cleanup_count=None):
        self._max_cache = max_cache
        if after_cleanup_count is None:
            self._after_cleanup_count = self._max_cache * 8 / 10
        else:
            self._after_cleanup_count = min(after_cleanup_count,
                                            self._max_cache)
        self.cleanup()


class LRUSizeCache(LRUCache):
    """An LRUCache that removes things based on the size of the values.

    This differs in that it doesn't care how many actual items there are,
    it just restricts the cache to be cleaned up after so much data is stored.

    The size of items added will be computed using compute_size(value), which
    defaults to len() if not supplied.
    """

    def __init__(self, max_size=1024*1024, after_cleanup_size=None,
                 compute_size=None):
        """Create a new LRUSizeCache.

        :param max_size: The max number of bytes to store before we start
            clearing out entries.
        :param after_cleanup_size: After cleaning up, shrink everything to this
            size.
        :param compute_size: A function to compute the size of the values. We
            use a function here, so that you can pass 'len' if you are just
            using simple strings, or a more complex function if you are using
            something like a list of strings, or even a custom object.
            The function should take the form "compute_size(value) => integer".
            If not supplied, it defaults to 'len()'
        """
        self._value_size = 0
        self._compute_size = compute_size
        if compute_size is None:
            self._compute_size = len
        self._update_max_size(max_size, after_cleanup_size=after_cleanup_size)
        LRUCache.__init__(self, max_cache=max(int(max_size/512), 1))

    def add(self, key, value, cleanup=None):
        """Add a new value to the cache.

        Also, if the entry is ever removed from the cache, call
        cleanup(key, value).

        :param key: The key to store it under
        :param value: The object to store
        :param cleanup: None or a function taking (key, value) to indicate
                        'value' should be cleaned up.
        """
        node = self._cache.get(key, None)
        value_len = self._compute_size(value)
        if value_len >= self._after_cleanup_size:
            # The new value is 'too big to fit', as it would fill up/overflow
            # the cache all by itself
            trace.mutter('Adding the key %r to an LRUSizeCache failed.'
                         ' value %d is too big to fit in a the cache'
                         ' with size %d %d', key, value_len,
                         self._after_cleanup_size, self._max_size)
            if node is not None:
                # We won't be replacing the old node, so just remove it
                self._remove_node(node)
            if cleanup is not None:
                cleanup(key, value)
            return
        if node is None:
            node = _LRUNode(key, value, cleanup=cleanup)
            self._cache[key] = node
        else:
            self._value_size -= node.size
        node.size = value_len
        self._value_size += value_len
        self._record_access(node)

        if self._value_size > self._max_size:
            # Time to cleanup
            self.cleanup()

    def cleanup(self):
        """Clear the cache until it shrinks to the requested size.

        This does not completely wipe the cache, just makes sure it is under
        the after_cleanup_size.
        """
        # Make sure the cache is shrunk to the correct size
        while self._value_size > self._after_cleanup_size:
            self._remove_lru()

    def _remove_node(self, node):
        self._value_size -= node.size
        LRUCache._remove_node(self, node)

    def resize(self, max_size, after_cleanup_size=None):
        """Change the number of bytes that will be cached."""
        self._update_max_size(max_size, after_cleanup_size=after_cleanup_size)
        max_cache = max(int(max_size/512), 1)
        self._update_max_cache(max_cache)

    def _update_max_size(self, max_size, after_cleanup_size=None):
        self._max_size = max_size
        if after_cleanup_size is None:
            self._after_cleanup_size = self._max_size * 8 / 10
        else:
            self._after_cleanup_size = min(after_cleanup_size, self._max_size)
