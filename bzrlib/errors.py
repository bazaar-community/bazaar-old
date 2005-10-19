# -*- coding: UTF-8 -*-

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

"""Exceptions for bzr, and reporting of them.

Exceptions are caught at a high level to report errors to the user, and
might also be caught inside the program.  Therefore it needs to be
possible to convert them to a meaningful string, and also for them to be
interrogated by the program.

Exceptions are defined such that the arguments given to the constructor
are stored in the object as properties of the same name.  When the
object is printed as a string, the doc string of the class is used as
a format string with the property dictionary available to it.

This means that exceptions can used like this:

>>> import sys
>>> try:
...   raise NotBranchError(path='/foo/bar')
... except:
...   print sys.exc_type
...   print sys.exc_value
...   print sys.exc_value.path
bzrlib.errors.NotBranchError
Not a branch: /foo/bar
/foo/bar

Therefore:

 * create a new exception class for any class of error that can be
   usefully distinguished.

 * the printable form of an exception is generated by the base class
   __str__ method
"""

# based on Scott James Remnant's hct error classes

# TODO: is there any value in providing the .args field used by standard
# python exceptions?   A list of values with no names seems less useful 
# to me.

# TODO: Perhaps convert the exception to a string at the moment it's 
# constructed to make sure it will succeed.  But that says nothing about
# exceptions that are never raised.

# TODO: Convert all the other error classes here to BzrNewError, and eliminate
# the old one.


class BzrError(StandardError):
    def __str__(self):
        # XXX: Should we show the exception class in 
        # exceptions that don't provide their own message?  
        # maybe it should be done at a higher level
        ## n = self.__class__.__name__ + ': '
        n = ''
        if len(self.args) == 1:
            return str(self.args[0])
        elif len(self.args) == 2:
            # further explanation or suggestions
            try:
                return n + '\n  '.join([self.args[0]] + self.args[1])
            except TypeError:
                return n + "%r" % self
        else:
            return n + `self.args`


class BzrNewError(BzrError):
    """bzr error"""
    # base classes should override the docstring with their human-
    # readable explanation

    def __init__(self, **kwds):
        for key, value in kwds.items():
            setattr(self, key, value)

    def __str__(self):
        try:
            return self.__doc__ % self.__dict__
        except (NameError, ValueError, KeyError), e:
            return 'Unprintable exception %s: %s' \
                % (self.__class__.__name__, str(e))


class BzrCheckError(BzrNewError):
    """Internal check failed: %(message)s"""
    def __init__(self, message):
        self.message = message


class InvalidEntryName(BzrNewError):
    """Invalid entry name: %(name)s"""
    def __init__(self, name):
        self.name = name


class InvalidRevisionNumber(BzrNewError):
    """Invalid revision number %(revno)d"""
    def __init__(self, revno):
        self.revno = revno


class InvalidRevisionId(BzrNewError):
    """Invalid revision-id"""


class BzrCommandError(BzrError):
    # Error from malformed user command
    def __str__(self):
        return self.args[0]

class StrictCommitFailed(Exception):
    """Commit refused because there are unknowns in the tree."""

class NotBranchError(BzrNewError):
    """Not a branch: %(path)s"""
    def __init__(self, path):
        BzrNewError.__init__(self)
        self.path = path


class UnsupportedFormatError(BzrError):
    """Specified path is a bzr branch that we cannot read."""
    def __str__(self):
        return 'unsupported branch format: %s' % self.args[0]


class NotVersionedError(BzrNewError):
    """%(path)s is not versioned"""
    def __init__(self, path):
        BzrNewError.__init__(self)
        self.path = path


class BadFileKindError(BzrError):
    """Specified file is of a kind that cannot be added.

    (For example a symlink or device file.)"""


class ForbiddenFileError(BzrError):
    """Cannot operate on a file because it is a control file."""


class LockError(Exception):
    """Lock error"""
    # All exceptions from the lock/unlock functions should be from
    # this exception class.  They will be translated as necessary. The
    # original exception is available as e.original_error


class CommitNotPossible(LockError):
    """A commit was attempted but we do not have a write lock open."""


class AlreadyCommitted(LockError):
    """A rollback was requested, but is not able to be accomplished."""


class ReadOnlyError(LockError):
    """A write attempt was made in a read only transaction."""


class PointlessCommit(BzrNewError):
    """No changes to commit"""


class NoSuchRevision(BzrError):
    def __init__(self, branch, revision):
        self.branch = branch
        self.revision = revision
        msg = "Branch %s has no revision %s" % (branch, revision)
        BzrError.__init__(self, msg)


class HistoryMissing(BzrError):
    def __init__(self, branch, object_type, object_id):
        self.branch = branch
        BzrError.__init__(self,
                          '%s is missing %s {%s}'
                          % (branch, object_type, object_id))


class DivergedBranches(BzrError):
    def __init__(self, branch1, branch2):
        BzrError.__init__(self, "These branches have diverged.")
        self.branch1 = branch1
        self.branch2 = branch2


class UnrelatedBranches(BzrCommandError):
    def __init__(self):
        msg = "Branches have no common ancestor, and no base revision"\
            " specified."
        BzrCommandError.__init__(self, msg)

class NoCommonAncestor(BzrError):
    def __init__(self, revision_a, revision_b):
        msg = "Revisions have no common ancestor: %s %s." \
            % (revision_a, revision_b) 
        BzrError.__init__(self, msg)

class NoCommonRoot(BzrError):
    def __init__(self, revision_a, revision_b):
        msg = "Revisions are not derived from the same root: %s %s." \
            % (revision_a, revision_b) 
        BzrError.__init__(self, msg)

class NotAncestor(BzrError):
    def __init__(self, rev_id, not_ancestor_id):
        msg = "Revision %s is not an ancestor of %s" % (not_ancestor_id, 
                                                        rev_id)
        BzrError.__init__(self, msg)
        self.rev_id = rev_id
        self.not_ancestor_id = not_ancestor_id


class NotAncestor(BzrError):
    def __init__(self, rev_id, not_ancestor_id):
        self.rev_id = rev_id
        self.not_ancestor_id = not_ancestor_id
        msg = "Revision %s is not an ancestor of %s" % (not_ancestor_id, 
                                                        rev_id)
        BzrError.__init__(self, msg)


class InstallFailed(BzrError):
    def __init__(self, revisions):
        msg = "Could not install revisions:\n%s" % " ,".join(revisions)
        BzrError.__init__(self, msg)
        self.revisions = revisions


class AmbiguousBase(BzrError):
    def __init__(self, bases):
        msg = "The correct base is unclear, becase %s are all equally close" %\
            ", ".join(bases)
        BzrError.__init__(self, msg)
        self.bases = bases

class NoCommits(BzrError):
    def __init__(self, branch):
        msg = "Branch %s has no commits." % branch
        BzrError.__init__(self, msg)

class UnlistableStore(BzrError):
    def __init__(self, store):
        BzrError.__init__(self, "Store %s is not listable" % store)

class UnlistableBranch(BzrError):
    def __init__(self, br):
        BzrError.__init__(self, "Stores for branch %s are not listable" % br)


from bzrlib.weave import WeaveError, WeaveParentMismatch

class TransportError(BzrError):
    """All errors thrown by Transport implementations should derive
    from this class.
    """
    def __init__(self, msg=None, orig_error=None):
        if msg is None and orig_error is not None:
            msg = str(orig_error)
        BzrError.__init__(self, msg)
        self.msg = msg
        self.orig_error = orig_error

# A set of semi-meaningful errors which can be thrown
class TransportNotPossible(TransportError):
    """This is for transports where a specific function is explicitly not
    possible. Such as pushing files to an HTTP server.
    """
    pass

class NonRelativePath(TransportError):
    """An absolute path was supplied, that could not be decoded into
    a relative path.
    """
    pass

class NoSuchFile(TransportError, IOError):
    """A get() was issued for a file that doesn't exist."""

    # XXX: Is multiple inheritance for exceptions really needed?

    def __str__(self):
        return 'no such file: ' + self.msg

    def __init__(self, msg=None, orig_error=None):
        import errno
        TransportError.__init__(self, msg=msg, orig_error=orig_error)
        IOError.__init__(self, errno.ENOENT, self.msg)

class FileExists(TransportError, OSError):
    """An operation was attempted, which would overwrite an entry,
    but overwritting is not supported.

    mkdir() can throw this, but put() just overwites existing files.
    """
    # XXX: Is multiple inheritance for exceptions really needed?
    def __init__(self, msg=None, orig_error=None):
        import errno
        TransportError.__init__(self, msg=msg, orig_error=orig_error)
        OSError.__init__(self, errno.EEXIST, self.msg)

class PermissionDenied(TransportError):
    """An operation cannot succeed because of a lack of permissions."""
    pass

class ConnectionReset(TransportError):
    """The connection has been closed."""
    pass

class ConflictsInTree(BzrError):
    def __init__(self):
        BzrError.__init__(self, "Working tree has conflicts.")

class ParseConfigError(BzrError):
    def __init__(self, errors, filename):
        if filename is None:
            filename = ""
        message = "Error(s) parsing config file %s:\n%s" % \
            (filename, ('\n'.join(e.message for e in errors)))
        BzrError.__init__(self, message)

class SigningFailed(BzrError):
    def __init__(self, command_line):
        BzrError.__init__(self, "Failed to gpg sign data with command '%s'"
                               % command_line)
