# Copyright (C) 2009 Canonical Ltd
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

"""The pure-python implementation of the StaticTuple type.

Note that it is generally just implemented as using tuples of tuples of
strings.
"""


class StaticTuple(tuple):
    """A static type, similar to a tuple of strings."""

    def __new__(cls, *args):
        # Make the empty StaticTuple a singleton
        if not args and _empty_tuple is not None:
            return _empty_tuple
        return tuple.__new__(cls, args)

    def __init__(self, *args):
        """Create a new 'StaticTuple'"""
        for bit in args:
            if type(bit) not in (str, StaticTuple):
                raise TypeError('key bits must be strings or StaticTuple')
        num_keys = len(args)
        if num_keys < 0 or num_keys > 255:
            raise ValueError('must have 1 => 256 key bits')
        # We don't need to pass args to tuple.__init__, because that was
        # already handled in __new__.
        tuple.__init__(self)

    def __repr__(self):
        return '%s%s' % (self.__class__.__name__, tuple.__repr__(self))

    def __add__(self, other):
        """Concatenate self with other"""
        return StaticTuple.from_sequence(tuple.__add__(self,other))

    def as_tuple(self):
        return self

    def intern(self):
        return _interned_tuples.setdefault(self, self)

    @staticmethod
    def from_sequence(seq):
        """Convert a sequence object into a StaticTuple instance."""
        if isinstance(seq, StaticTuple):
            # it already is
            return seq
        return StaticTuple(*seq)



# Have to set it to None first, so that __new__ can determine whether
# the _empty_tuple singleton has been created yet or not.
_empty_tuple = None
_empty_tuple = StaticTuple()
_interned_tuples = {}
