# Copyright (C) 2006 by Canonical Ltd
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

"""Classes to provide name-to-object registry-like support."""


class Registry(object):
    """A class that registers objects to a name."""

    def __init__(self, first_is_default=False):
        """Create a new Registry.

        :param first_is_default: If True, then the first key to be registered
            will be set as the default key for get() to use.
        """
        self._first_is_default = first_is_default
        self._default_key = None
        self._dict = {}

    def register(self, key, object):
        """Register a new object to a name.

        :param key: This is the key to use to request the object later.
        :param object: The object to register.
        """
        if self._first_is_default and not self._dict:
            self._default_key = key
        self._dict[key] = object

    def get(self, key=None):
        """Return the object register()'ed to the given key.

        :param key: The key to obtain the object for. If no object has been
            registered to that key, the object registered for self.default_key
            will be returned instead, if it exists. Otherwise KeyError will be
            raised.
        :return: The previously registered object.
        """
        try:
            return self._dict[key]
        except KeyError:
            if self.default_key is not None:
                return self._dict[self.default_key]
            else:
                raise

    def keys(self):
        """Get a list of registered entries"""
        return sorted(self._dict.keys())

    def _set_default_key(self, key):
        if not self._dict.has_key(key):
            raise KeyError('No object registered under key %s.' % key)
        else:
            self._default_key = key

    def _get_default_key(self):
        return self._default_key

    default_key = property(_get_default_key, _set_default_key)
    """Current value of the default key. Can be set to any existing key."""


class LazyImportRegistry(Registry):
    """A class to register modules/members to be loaded on request."""

    def register(self, key, module_name, member_name):
        """Register a new object to be loaded on request.

        :param module_name: The python path to the module. Such as 'os.path'.
        :param member_name: The member of the module to return, if empty or None
            get() will return the module itself.
        """
        Registry.register(self, key, (module_name, member_name))

    def get(self, key=None):
        """Load the module and return the object specified by the given key.

        May raise ImportError if there are any problems, or AttributeError if
        the module does not have the supplied member.
        """
        module_name, member_name = Registry.get(self, key)
        module = __import__(module_name, globals(), locals(), [member_name])
        if member_name:
            return getattr(module, member_name)
        return module
