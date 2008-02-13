# Copyright (C) 2006, 2007, 2008 Canonical Ltd
#   Authors: Robert Collins <robert.collins@canonical.com> and others
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

"""Symbol versioning

The methods here allow for api symbol versioning.
"""

__all__ = ['deprecated_function',
           'deprecated_list',
           'deprecated_method',
           'DEPRECATED_PARAMETER',
           'deprecated_passed',
           'warn', 'set_warning_method', 'zero_seven',
           'zero_eight',
           'zero_nine',
           'zero_ten',
           'zero_eleven',
           'zero_twelve',
           'zero_thirteen',
           'zero_fourteen',
           'zero_fifteen',
           'zero_sixteen',
           'zero_seventeen',
           'zero_eighteen',
           'zero_ninety',
           'zero_ninetyone',
           'zero_ninetytwo',
           'zero_ninetythree',
           'one_zero',
           'one_one',
           'one_two',
           ]

from warnings import warn


DEPRECATED_PARAMETER = "A deprecated parameter marker."
zero_seven = "%s was deprecated in version 0.7."
zero_eight = "%s was deprecated in version 0.8."
zero_nine = "%s was deprecated in version 0.9."
zero_ten = "%s was deprecated in version 0.10."
zero_eleven = "%s was deprecated in version 0.11."
zero_twelve = "%s was deprecated in version 0.12."
zero_thirteen = "%s was deprecated in version 0.13."
zero_fourteen = "%s was deprecated in version 0.14."
zero_fifteen = "%s was deprecated in version 0.15."
zero_sixteen = "%s was deprecated in version 0.16."
zero_seventeen = "%s was deprecated in version 0.17."
zero_eighteen = "%s was deprecated in version 0.18."
zero_ninety = "%s was deprecated in version 0.90."
zero_ninetyone = "%s was deprecated in version 0.91."
zero_ninetytwo = "%s was deprecated in version 0.92."
one_zero = "%s was deprecated in version 1.0."
zero_ninetythree = one_zero # Maintained for backwards compatibility
one_one = "%s was deprecated in version 1.1."
one_two = "%s was deprecated in version 1.2."

def set_warning_method(method):
    """Set the warning method to be used by this module.

    It should take a message and a warning category as warnings.warn does.
    """
    global warn
    warn = method


# TODO - maybe this would be easier to use as one 'smart' method that
# guess if it is a method or a class or an attribute ? If so, we can
# add that on top of the primitives, once we have all three written
# - RBC 20050105


def deprecation_string(a_callable, deprecation_version):
    """Generate an automatic deprecation string for a_callable.

    :param a_callable: The callable to substitute into deprecation_version.
    :param deprecation_version: A deprecation format warning string. This should
        have a single %s operator in it. a_callable will be turned into a nice
        python symbol and then substituted into deprecation_version.
    """
    # We also want to handle old-style classes, in particular exception, and
    # they don't have an im_class attribute.
    if getattr(a_callable, 'im_class', None) is None:
        symbol = "%s.%s" % (a_callable.__module__,
                            a_callable.__name__)
    else:
        symbol = "%s.%s.%s" % (a_callable.im_class.__module__,
                               a_callable.im_class.__name__,
                               a_callable.__name__
                               )
    return deprecation_version % symbol


def deprecated_function(deprecation_version):
    """Decorate a function so that use of it will trigger a warning."""

    def function_decorator(callable):
        """This is the function python calls to perform the decoration."""
        
        def decorated_function(*args, **kwargs):
            """This is the decorated function."""
            warn(deprecation_string(callable, deprecation_version),
                DeprecationWarning, stacklevel=2)
            return callable(*args, **kwargs)
        _populate_decorated(callable, deprecation_version, "function",
                            decorated_function)
        return decorated_function
    return function_decorator


def deprecated_method(deprecation_version):
    """Decorate a method so that use of it will trigger a warning.

    To deprecate a static or class method, use 

        @staticmethod
        @deprecated_function
        def ...
    
    To deprecate an entire class, decorate __init__.
    """

    def method_decorator(callable):
        """This is the function python calls to perform the decoration."""
        
        def decorated_method(self, *args, **kwargs):
            """This is the decorated method."""
            if callable.__name__ == '__init__':
                symbol = "%s.%s" % (self.__class__.__module__,
                                    self.__class__.__name__,
                                    )
            else:
                symbol = "%s.%s.%s" % (self.__class__.__module__,
                                       self.__class__.__name__,
                                       callable.__name__
                                       )
            warn(deprecation_version % symbol, DeprecationWarning, stacklevel=2)
            return callable(self, *args, **kwargs)
        _populate_decorated(callable, deprecation_version, "method",
                            decorated_method)
        return decorated_method
    return method_decorator


def deprecated_passed(parameter_value):
    """Return True if parameter_value was used."""
    # FIXME: it might be nice to have a parameter deprecation decorator. 
    # it would need to handle positional and *args and **kwargs parameters,
    # which means some mechanism to describe how the parameter was being
    # passed before deprecation, and some way to deprecate parameters that
    # were not at the end of the arg list. Thats needed for __init__ where
    # we cannot just forward to a new method name.I.e. in the following
    # examples we would want to have callers that pass any value to 'bad' be
    # given a warning - because we have applied:
    # @deprecated_parameter('bad', zero_seven)
    #
    # def __init__(self, bad=None)
    # def __init__(self, bad, other)
    # def __init__(self, **kwargs)
    # RBC 20060116
    return not parameter_value is DEPRECATED_PARAMETER


def _decorate_docstring(callable, deprecation_version, label,
                        decorated_callable):
    if callable.__doc__:
        docstring_lines = callable.__doc__.split('\n')
    else:
        docstring_lines = []
    if len(docstring_lines) == 0:
        decorated_callable.__doc__ = deprecation_version % ("This " + label)
    elif len(docstring_lines) == 1:
        decorated_callable.__doc__ = (callable.__doc__ 
                                    + "\n"
                                    + "\n"
                                    + deprecation_version % ("This " + label)
                                    + "\n")
    else:
        spaces = len(docstring_lines[-1])
        new_doc = callable.__doc__
        new_doc += "\n" + " " * spaces
        new_doc += deprecation_version % ("This " + label)
        new_doc += "\n" + " " * spaces
        decorated_callable.__doc__ = new_doc


def _populate_decorated(callable, deprecation_version, label,
                        decorated_callable):
    """Populate attributes like __name__ and __doc__ on the decorated callable.
    """
    _decorate_docstring(callable, deprecation_version, label,
                        decorated_callable)
    decorated_callable.__module__ = callable.__module__
    decorated_callable.__name__ = callable.__name__
    decorated_callable.is_deprecated = True


def _dict_deprecation_wrapper(wrapped_method):
    """Returns a closure that emits a warning and calls the superclass"""
    def cb(dep_dict, *args, **kwargs):
        msg = 'access to %s' % (dep_dict._variable_name, )
        msg = dep_dict._deprecation_version % (msg,)
        if dep_dict._advice:
            msg += ' ' + dep_dict._advice
        warn(msg, DeprecationWarning, stacklevel=2)
        return wrapped_method(dep_dict, *args, **kwargs)
    return cb


class DeprecatedDict(dict):
    """A dictionary that complains when read or written."""

    is_deprecated = True

    def __init__(self,
        deprecation_version,
        variable_name,
        initial_value,
        advice,
        ):
        """Create a dict that warns when read or modified.

        :param deprecation_version: something like zero_nine
        :param initial_value: The contents of the dict
        :param variable_name: This allows better warnings to be printed
        :param advice: String of advice on what callers should do instead 
            of using this variable.
        """
        self._deprecation_version = deprecation_version
        self._variable_name = variable_name
        self._advice = advice
        dict.__init__(self, initial_value)

    # This isn't every possible method but it should trap anyone using the
    # dict -- add more if desired
    __len__ = _dict_deprecation_wrapper(dict.__len__)
    __getitem__ = _dict_deprecation_wrapper(dict.__getitem__)
    __setitem__ = _dict_deprecation_wrapper(dict.__setitem__)
    __delitem__ = _dict_deprecation_wrapper(dict.__delitem__)
    keys = _dict_deprecation_wrapper(dict.keys)
    __contains__ = _dict_deprecation_wrapper(dict.__contains__)


def deprecated_list(deprecation_version, variable_name,
                    initial_value, extra=None):
    """Create a list that warns when modified

    :param deprecation_version: something like zero_nine
    :param initial_value: The contents of the list
    :param variable_name: This allows better warnings to be printed
    :param extra: Extra info to print when printing a warning
    """

    subst_text = 'Modifying %s' % (variable_name,)
    msg = deprecation_version % (subst_text,)
    if extra:
        msg += ' ' + extra

    class _DeprecatedList(list):
        __doc__ = list.__doc__ + msg

        is_deprecated = True

        def _warn_deprecated(self, func, *args, **kwargs):
            warn(msg, DeprecationWarning, stacklevel=3)
            return func(self, *args, **kwargs)
            
        def append(self, obj):
            """appending to %s is deprecated""" % (variable_name,)
            return self._warn_deprecated(list.append, obj)

        def insert(self, index, obj):
            """inserting to %s is deprecated""" % (variable_name,)
            return self._warn_deprecated(list.insert, index, obj)

        def extend(self, iterable):
            """extending %s is deprecated""" % (variable_name,)
            return self._warn_deprecated(list.extend, iterable)

        def remove(self, value):
            """removing from %s is deprecated""" % (variable_name,)
            return self._warn_deprecated(list.remove, value)

        def pop(self, index=None):
            """pop'ing from from %s is deprecated""" % (variable_name,)
            if index:
                return self._warn_deprecated(list.pop, index)
            else:
                # Can't pass None
                return self._warn_deprecated(list.pop)

    return _DeprecatedList(initial_value)
