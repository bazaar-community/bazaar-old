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

"""Exceptions for bzr, and reporting of them.
"""


from bzrlib import (
    osutils,
    symbol_versioning,
    )
from bzrlib.patches import (
    MalformedHunkHeader,
    MalformedLine,
    MalformedPatchHeader,
    PatchConflict,
    PatchSyntax,
    )


# TODO: is there any value in providing the .args field used by standard
# python exceptions?   A list of values with no names seems less useful 
# to me.

# TODO: Perhaps convert the exception to a string at the moment it's 
# constructed to make sure it will succeed.  But that says nothing about
# exceptions that are never raised.

# TODO: selftest assertRaises should probably also check that every error
# raised can be formatted as a string successfully, and without giving
# 'unprintable'.


# return codes from the bzr program
EXIT_OK = 0
EXIT_ERROR = 3
EXIT_INTERNAL_ERROR = 4


class BzrError(StandardError):
    """
    Base class for errors raised by bzrlib.

    :cvar internal_error: if True this was probably caused by a bzr bug and
    should be displayed with a traceback; if False (or absent) this was
    probably a user or environment error and they don't need the gory details.
    (That can be overridden by -Derror on the command line.)

    :cvar _fmt: Format string to display the error; this is expanded
    by the instance's dict.
    """
    
    internal_error = False

    def __init__(self, msg=None, **kwds):
        """Construct a new BzrError.

        There are two alternative forms for constructing these objects.
        Either a preformatted string may be passed, or a set of named
        arguments can be given.  The first is for generic "user" errors which
        are not intended to be caught and so do not need a specific subclass.
        The second case is for use with subclasses that provide a _fmt format
        string to print the arguments.  

        Keyword arguments are taken as parameters to the error, which can 
        be inserted into the format string template.  It's recommended 
        that subclasses override the __init__ method to require specific 
        parameters.

        :param msg: If given, this is the literal complete text for the error,
        not subject to expansion.
        """
        StandardError.__init__(self)
        if msg is not None:
            # I was going to deprecate this, but it actually turns out to be
            # quite handy - mbp 20061103.
            self._preformatted_string = msg
        else:
            self._preformatted_string = None
            for key, value in kwds.items():
                setattr(self, key, value)

    def __str__(self):
        s = getattr(self, '_preformatted_string', None)
        if s is not None:
            # contains a preformatted message; must be cast to plain str
            return str(s)
        try:
            fmt = self._get_format_string()
            if fmt:
                d = dict(self.__dict__)
                # special case: python2.5 puts the 'message' attribute in a
                # slot, so it isn't seen in __dict__
                d['message'] = getattr(self, 'message', 'no message')
                s = fmt % d
                # __str__() should always return a 'str' object
                # never a 'unicode' object.
                if isinstance(s, unicode):
                    return s.encode('utf8')
                return s
        except (AttributeError, TypeError, NameError, ValueError, KeyError), e:
            return 'Unprintable exception %s: dict=%r, fmt=%r, error=%r' \
                % (self.__class__.__name__,
                   self.__dict__,
                   getattr(self, '_fmt', None),
                   e)

    def _get_format_string(self):
        """Return format string for this exception or None"""
        fmt = getattr(self, '_fmt', None)
        if fmt is not None:
            return fmt
        fmt = getattr(self, '__doc__', None)
        if fmt is not None:
            symbol_versioning.warn("%s uses its docstring as a format, "
                    "it should use _fmt instead" % self.__class__.__name__,
                    DeprecationWarning)
            return fmt
        return 'Unprintable exception %s: dict=%r, fmt=%r' \
            % (self.__class__.__name__,
               self.__dict__,
               getattr(self, '_fmt', None),
               )


class InternalBzrError(BzrError):
    """Base class for errors that are internal in nature.

    This is a convenience class for errors that are internal. The
    internal_error attribute can still be altered in subclasses, if needed.
    Using this class is simply an easy way to get internal errors.
    """

    internal_error = True


class BzrNewError(BzrError):
    """Deprecated error base class."""
    # base classes should override the docstring with their human-
    # readable explanation

    def __init__(self, *args, **kwds):
        # XXX: Use the underlying BzrError to always generate the args
        # attribute if it doesn't exist.  We can't use super here, because
        # exceptions are old-style classes in python2.4 (but new in 2.5).
        # --bmc, 20060426
        symbol_versioning.warn('BzrNewError was deprecated in bzr 0.13; '
             'please convert %s to use BzrError instead'
             % self.__class__.__name__,
             DeprecationWarning,
             stacklevel=2)
        BzrError.__init__(self, *args)
        for key, value in kwds.items():
            setattr(self, key, value)

    def __str__(self):
        try:
            # __str__() should always return a 'str' object
            # never a 'unicode' object.
            s = self.__doc__ % self.__dict__
            if isinstance(s, unicode):
                return s.encode('utf8')
            return s
        except (TypeError, NameError, ValueError, KeyError), e:
            return 'Unprintable exception %s(%r): %r' \
                % (self.__class__.__name__,
                   self.__dict__, e)


class AlreadyBuilding(BzrError):
    
    _fmt = "The tree builder is already building a tree."


class BzrCheckError(InternalBzrError):
    
    _fmt = "Internal check failed: %(message)s"

    def __init__(self, message):
        BzrError.__init__(self)
        self.message = message


class DisabledMethod(InternalBzrError):

    _fmt = "The smart server method '%(class_name)s' is disabled."

    def __init__(self, class_name):
        BzrError.__init__(self)
        self.class_name = class_name


class IncompatibleAPI(BzrError):

    _fmt = 'The API for "%(api)s" is not compatible with "%(wanted)s". '\
        'It supports versions "%(minimum)s" to "%(current)s".'

    def __init__(self, api, wanted, minimum, current):
        self.api = api
        self.wanted = wanted
        self.minimum = minimum
        self.current = current


class InProcessTransport(BzrError):

    _fmt = "The transport '%(transport)s' is only accessible within this " \
        "process."

    def __init__(self, transport):
        self.transport = transport


class InvalidEntryName(InternalBzrError):
    
    _fmt = "Invalid entry name: %(name)s"

    def __init__(self, name):
        BzrError.__init__(self)
        self.name = name


class InvalidRevisionNumber(BzrError):
    
    _fmt = "Invalid revision number %(revno)s"

    def __init__(self, revno):
        BzrError.__init__(self)
        self.revno = revno


class InvalidRevisionId(BzrError):

    _fmt = "Invalid revision-id {%(revision_id)s} in %(branch)s"

    def __init__(self, revision_id, branch):
        # branch can be any string or object with __str__ defined
        BzrError.__init__(self)
        self.revision_id = revision_id
        self.branch = branch

class ReservedId(BzrError):

    _fmt = "Reserved revision-id {%(revision_id)s}"

    def __init__(self, revision_id):
        self.revision_id = revision_id


class RootMissing(InternalBzrError):

    _fmt = ("The root entry of a tree must be the first entry supplied to "
        "record_entry_contents.")


class NoHelpTopic(BzrError):

    _fmt = ("No help could be found for '%(topic)s'. "
        "Please use 'bzr help topics' to obtain a list of topics.")

    def __init__(self, topic):
        self.topic = topic


class NoSuchId(BzrError):

    _fmt = 'The file id "%(file_id)s" is not present in the tree %(tree)s.'
    
    def __init__(self, tree, file_id):
        BzrError.__init__(self)
        self.file_id = file_id
        self.tree = tree


class NoSuchIdInRepository(NoSuchId):

    _fmt = ('The file id "%(file_id)s" is not present in the repository'
            ' %(repository)r')

    def __init__(self, repository, file_id):
        BzrError.__init__(self, repository=repository, file_id=file_id)


class InventoryModified(InternalBzrError):

    _fmt = ("The current inventory for the tree %(tree)r has been modified,"
            " so a clean inventory cannot be read without data loss.")

    def __init__(self, tree):
        self.tree = tree


class NoWorkingTree(BzrError):

    _fmt = 'No WorkingTree exists for "%(base)s".'
    
    def __init__(self, base):
        BzrError.__init__(self)
        self.base = base


class NotBuilding(BzrError):

    _fmt = "Not currently building a tree."


class NotLocalUrl(BzrError):

    _fmt = "%(url)s is not a local path."

    def __init__(self, url):
        self.url = url


class WorkingTreeAlreadyPopulated(InternalBzrError):

    _fmt = 'Working tree already populated in "%(base)s"'

    def __init__(self, base):
        self.base = base


class BzrCommandError(BzrError):
    """Error from user command"""

    # Error from malformed user command; please avoid raising this as a
    # generic exception not caused by user input.
    #
    # I think it's a waste of effort to differentiate between errors that
    # are not intended to be caught anyway.  UI code need not subclass
    # BzrCommandError, and non-UI code should not throw a subclass of
    # BzrCommandError.  ADHB 20051211
    def __init__(self, msg):
        # Object.__str__() must return a real string
        # returning a Unicode string is a python error.
        if isinstance(msg, unicode):
            self.msg = msg.encode('utf8')
        else:
            self.msg = msg

    def __str__(self):
        return self.msg


class NotWriteLocked(BzrError):

    _fmt = """%(not_locked)r is not write locked but needs to be."""

    def __init__(self, not_locked):
        self.not_locked = not_locked


class BzrOptionError(BzrCommandError):

    _fmt = "Error in command line options"


class BadIndexFormatSignature(BzrError):

    _fmt = "%(value)s is not an index of type %(_type)s."

    def __init__(self, value, _type):
        BzrError.__init__(self)
        self.value = value
        self._type = _type


class BadIndexData(BzrError):

    _fmt = "Error in data for index %(value)s."

    def __init__(self, value):
        BzrError.__init__(self)
        self.value = value


class BadIndexDuplicateKey(BzrError):

    _fmt = "The key '%(key)s' is already in index '%(index)s'."

    def __init__(self, key, index):
        BzrError.__init__(self)
        self.key = key
        self.index = index


class BadIndexKey(BzrError):

    _fmt = "The key '%(key)s' is not a valid key."

    def __init__(self, key):
        BzrError.__init__(self)
        self.key = key


class BadIndexOptions(BzrError):

    _fmt = "Could not parse options for index %(value)s."

    def __init__(self, value):
        BzrError.__init__(self)
        self.value = value


class BadIndexValue(BzrError):

    _fmt = "The value '%(value)s' is not a valid value."

    def __init__(self, value):
        BzrError.__init__(self)
        self.value = value


class BadOptionValue(BzrError):

    _fmt = """Bad value "%(value)s" for option "%(name)s"."""

    def __init__(self, name, value):
        BzrError.__init__(self, name=name, value=value)

    
class StrictCommitFailed(BzrError):

    _fmt = "Commit refused because there are unknown files in the tree"


# XXX: Should be unified with TransportError; they seem to represent the
# same thing
# RBC 20060929: I think that unifiying with TransportError would be a mistake
# - this is finer than a TransportError - and more useful as such. It 
# differentiates between 'transport has failed' and 'operation on a transport
# has failed.'
class PathError(BzrError):
    
    _fmt = "Generic path error: %(path)r%(extra)s)"

    def __init__(self, path, extra=None):
        BzrError.__init__(self)
        self.path = path
        if extra:
            self.extra = ': ' + str(extra)
        else:
            self.extra = ''


class NoSuchFile(PathError):

    _fmt = "No such file: %(path)r%(extra)s"


class FileExists(PathError):

    _fmt = "File exists: %(path)r%(extra)s"


class RenameFailedFilesExist(BzrError):
    """Used when renaming and both source and dest exist."""

    _fmt = ("Could not rename %(source)s => %(dest)s because both files exist."
            "%(extra)s")

    def __init__(self, source, dest, extra=None):
        BzrError.__init__(self)
        self.source = str(source)
        self.dest = str(dest)
        if extra:
            self.extra = ' ' + str(extra)
        else:
            self.extra = ''


class NotADirectory(PathError):

    _fmt = '"%(path)s" is not a directory %(extra)s'


class NotInWorkingDirectory(PathError):

    _fmt = '"%(path)s" is not in the working directory %(extra)s'


class DirectoryNotEmpty(PathError):

    _fmt = 'Directory not empty: "%(path)s"%(extra)s'


class ReadingCompleted(InternalBzrError):
    
    _fmt = ("The MediumRequest '%(request)s' has already had finish_reading "
            "called upon it - the request has been completed and no more "
            "data may be read.")

    def __init__(self, request):
        self.request = request


class ResourceBusy(PathError):

    _fmt = 'Device or resource busy: "%(path)s"%(extra)s'


class PermissionDenied(PathError):

    _fmt = 'Permission denied: "%(path)s"%(extra)s'


class InvalidURL(PathError):

    _fmt = 'Invalid url supplied to transport: "%(path)s"%(extra)s'


class InvalidURLJoin(PathError):

    _fmt = 'Invalid URL join request: "%(args)s"%(extra)s'

    def __init__(self, msg, base, args):
        PathError.__init__(self, base, msg)
        self.args = [base] + list(args)


class UnknownHook(BzrError):

    _fmt = "The %(type)s hook '%(hook)s' is unknown in this version of bzrlib."

    def __init__(self, hook_type, hook_name):
        BzrError.__init__(self)
        self.type = hook_type
        self.hook = hook_name


class UnsupportedProtocol(PathError):

    _fmt = 'Unsupported protocol for url "%(path)s"%(extra)s'

    def __init__(self, url, extra):
        PathError.__init__(self, url, extra=extra)


class ReadError(PathError):
    
    _fmt = """Error reading from %(path)r."""


class ShortReadvError(PathError):

    _fmt = ('readv() read %(actual)s bytes rather than %(length)s bytes'
            ' at %(offset)s for "%(path)s"%(extra)s')

    internal_error = True

    def __init__(self, path, offset, length, actual, extra=None):
        PathError.__init__(self, path, extra=extra)
        self.offset = offset
        self.length = length
        self.actual = actual


class PathNotChild(PathError):

    _fmt = 'Path "%(path)s" is not a child of path "%(base)s"%(extra)s'

    internal_error = True

    def __init__(self, path, base, extra=None):
        BzrError.__init__(self)
        self.path = path
        self.base = base
        if extra:
            self.extra = ': ' + str(extra)
        else:
            self.extra = ''


class InvalidNormalization(PathError):

    _fmt = 'Path "%(path)s" is not unicode normalized'


# TODO: This is given a URL; we try to unescape it but doing that from inside
# the exception object is a bit undesirable.
# TODO: Probably this behavior of should be a common superclass 
class NotBranchError(PathError):

    _fmt = 'Not a branch: "%(path)s".'

    def __init__(self, path):
       import bzrlib.urlutils as urlutils
       self.path = urlutils.unescape_for_display(path, 'ascii')


class NoSubmitBranch(PathError):

    _fmt = 'No submit branch available for branch "%(path)s"'

    def __init__(self, branch):
       import bzrlib.urlutils as urlutils
       self.path = urlutils.unescape_for_display(branch.base, 'ascii')


class AlreadyBranchError(PathError):

    _fmt = 'Already a branch: "%(path)s".'


class BranchExistsWithoutWorkingTree(PathError):

    _fmt = 'Directory contains a branch, but no working tree \
(use bzr checkout if you wish to build a working tree): "%(path)s"'


class AtomicFileAlreadyClosed(PathError):

    _fmt = ('"%(function)s" called on an AtomicFile after it was closed:'
            ' "%(path)s"')

    def __init__(self, path, function):
        PathError.__init__(self, path=path, extra=None)
        self.function = function


class InaccessibleParent(PathError):

    _fmt = ('Parent not accessible given base "%(base)s" and'
            ' relative path "%(path)s"')

    def __init__(self, path, base):
        PathError.__init__(self, path)
        self.base = base


class NoRepositoryPresent(BzrError):

    _fmt = 'No repository present: "%(path)s"'
    def __init__(self, bzrdir):
        BzrError.__init__(self)
        self.path = bzrdir.transport.clone('..').base


class FileInWrongBranch(BzrError):

    _fmt = 'File "%(path)s" in not in branch %(branch_base)s.'

    def __init__(self, branch, path):
        BzrError.__init__(self)
        self.branch = branch
        self.branch_base = branch.base
        self.path = path


class UnsupportedFormatError(BzrError):

    _fmt = "Unsupported branch format: %(format)s\nPlease run 'bzr upgrade'"


class UnknownFormatError(BzrError):
    
    _fmt = "Unknown branch format: %(format)r"


class IncompatibleFormat(BzrError):
    
    _fmt = "Format %(format)s is not compatible with .bzr version %(bzrdir)s."

    def __init__(self, format, bzrdir_format):
        BzrError.__init__(self)
        self.format = format
        self.bzrdir = bzrdir_format


class IncompatibleRepositories(BzrError):

    _fmt = "Repository %(target)s is not compatible with repository"\
        " %(source)s"

    def __init__(self, source, target):
        BzrError.__init__(self, target=target, source=source)


class IncompatibleRevision(BzrError):
    
    _fmt = "Revision is not compatible with %(repo_format)s"

    def __init__(self, repo_format):
        BzrError.__init__(self)
        self.repo_format = repo_format


class AlreadyVersionedError(BzrError):
    """Used when a path is expected not to be versioned, but it is."""

    _fmt = "%(context_info)s%(path)s is already versioned."

    def __init__(self, path, context_info=None):
        """Construct a new AlreadyVersionedError.

        :param path: This is the path which is versioned,
        which should be in a user friendly form.
        :param context_info: If given, this is information about the context,
        which could explain why this is expected to not be versioned.
        """
        BzrError.__init__(self)
        self.path = path
        if context_info is None:
            self.context_info = ''
        else:
            self.context_info = context_info + ". "


class NotVersionedError(BzrError):
    """Used when a path is expected to be versioned, but it is not."""

    _fmt = "%(context_info)s%(path)s is not versioned."

    def __init__(self, path, context_info=None):
        """Construct a new NotVersionedError.

        :param path: This is the path which is not versioned,
        which should be in a user friendly form.
        :param context_info: If given, this is information about the context,
        which could explain why this is expected to be versioned.
        """
        BzrError.__init__(self)
        self.path = path
        if context_info is None:
            self.context_info = ''
        else:
            self.context_info = context_info + ". "


class PathsNotVersionedError(BzrError):
    """Used when reporting several paths which are not versioned"""

    _fmt = "Path(s) are not versioned: %(paths_as_string)s"

    def __init__(self, paths):
        from bzrlib.osutils import quotefn
        BzrError.__init__(self)
        self.paths = paths
        self.paths_as_string = ' '.join([quotefn(p) for p in paths])


class PathsDoNotExist(BzrError):

    _fmt = "Path(s) do not exist: %(paths_as_string)s%(extra)s"

    # used when reporting that paths are neither versioned nor in the working
    # tree

    def __init__(self, paths, extra=None):
        # circular import
        from bzrlib.osutils import quotefn
        BzrError.__init__(self)
        self.paths = paths
        self.paths_as_string = ' '.join([quotefn(p) for p in paths])
        if extra:
            self.extra = ': ' + str(extra)
        else:
            self.extra = ''


class BadFileKindError(BzrError):

    _fmt = 'Cannot operate on "%(filename)s" of unsupported kind "%(kind)s"'

    def __init__(self, filename, kind):
        BzrError.__init__(self, filename=filename, kind=kind)


class ForbiddenControlFileError(BzrError):

    _fmt = 'Cannot operate on "%(filename)s" because it is a control file'


class LockError(InternalBzrError):

    _fmt = "Lock error: %(msg)s"

    # All exceptions from the lock/unlock functions should be from
    # this exception class.  They will be translated as necessary. The
    # original exception is available as e.original_error
    #
    # New code should prefer to raise specific subclasses
    def __init__(self, message):
        # Python 2.5 uses a slot for StandardError.message,
        # so use a different variable name.  We now work around this in
        # BzrError.__str__, but this member name is kept for compatability.
        self.msg = message


class LockActive(LockError):

    _fmt = "The lock for '%(lock_description)s' is in use and cannot be broken."

    internal_error = False

    def __init__(self, lock_description):
        self.lock_description = lock_description


class CommitNotPossible(LockError):

    _fmt = "A commit was attempted but we do not have a write lock open."

    def __init__(self):
        pass


class AlreadyCommitted(LockError):

    _fmt = "A rollback was requested, but is not able to be accomplished."

    def __init__(self):
        pass


class ReadOnlyError(LockError):

    _fmt = "A write attempt was made in a read only transaction on %(obj)s"

    # TODO: There should also be an error indicating that you need a write
    # lock and don't have any lock at all... mbp 20070226

    def __init__(self, obj):
        self.obj = obj


class ReadOnlyLockError(LockError):

    _fmt = "Cannot acquire write lock on %(fname)s. %(msg)s"

    @symbol_versioning.deprecated_method(symbol_versioning.zero_ninetytwo)
    def __init__(self, fname, msg):
        LockError.__init__(self, '')
        self.fname = fname
        self.msg = msg


class LockFailed(LockError):

    internal_error = False

    _fmt = "Cannot lock %(lock)s: %(why)s"

    def __init__(self, lock, why):
        LockError.__init__(self, '')
        self.lock = lock
        self.why = why


class OutSideTransaction(BzrError):

    _fmt = ("A transaction related operation was attempted after"
            " the transaction finished.")


class ObjectNotLocked(LockError):

    _fmt = "%(obj)r is not locked"

    # this can indicate that any particular object is not locked; see also
    # LockNotHeld which means that a particular *lock* object is not held by
    # the caller -- perhaps they should be unified.
    def __init__(self, obj):
        self.obj = obj


class ReadOnlyObjectDirtiedError(ReadOnlyError):

    _fmt = "Cannot change object %(obj)r in read only transaction"

    def __init__(self, obj):
        self.obj = obj


class UnlockableTransport(LockError):

    internal_error = False

    _fmt = "Cannot lock: transport is read only: %(transport)s"

    def __init__(self, transport):
        self.transport = transport


class LockContention(LockError):

    _fmt = 'Could not acquire lock "%(lock)s"'
    # TODO: show full url for lock, combining the transport and relative
    # bits?

    internal_error = False

    def __init__(self, lock):
        self.lock = lock


class LockBroken(LockError):

    _fmt = ("Lock was broken while still open: %(lock)s"
            " - check storage consistency!")

    internal_error = False

    def __init__(self, lock):
        self.lock = lock


class LockBreakMismatch(LockError):

    _fmt = ("Lock was released and re-acquired before being broken:"
            " %(lock)s: held by %(holder)r, wanted to break %(target)r")

    internal_error = False

    def __init__(self, lock, holder, target):
        self.lock = lock
        self.holder = holder
        self.target = target


class LockNotHeld(LockError):

    _fmt = "Lock not held: %(lock)s"

    internal_error = False

    def __init__(self, lock):
        self.lock = lock


class TokenLockingNotSupported(LockError):

    _fmt = "The object %(obj)s does not support token specifying a token when locking."

    def __init__(self, obj):
        self.obj = obj


class TokenMismatch(LockBroken):

    _fmt = "The lock token %(given_token)r does not match lock token %(lock_token)r."

    internal_error = True

    def __init__(self, given_token, lock_token):
        self.given_token = given_token
        self.lock_token = lock_token


class PointlessCommit(BzrError):

    _fmt = "No changes to commit"


class CannotCommitSelectedFileMerge(BzrError):

    _fmt = 'Selected-file commit of merges is not supported yet:'\
        ' files %(files_str)s'

    def __init__(self, files):
        files_str = ', '.join(files)
        BzrError.__init__(self, files=files, files_str=files_str)


class BadCommitMessageEncoding(BzrError):

    _fmt = 'The specified commit message contains characters unsupported by '\
        'the current encoding.'


class UpgradeReadonly(BzrError):

    _fmt = "Upgrade URL cannot work with readonly URLs."


class UpToDateFormat(BzrError):

    _fmt = "The branch format %(format)s is already at the most recent format."

    def __init__(self, format):
        BzrError.__init__(self)
        self.format = format


class StrictCommitFailed(Exception):

    _fmt = "Commit refused because there are unknowns in the tree."


class NoSuchRevision(InternalBzrError):

    _fmt = "%(branch)s has no revision %(revision)s"

    def __init__(self, branch, revision):
        # 'branch' may sometimes be an internal object like a KnitRevisionStore
        BzrError.__init__(self, branch=branch, revision=revision)


# zero_ninetyone: this exception is no longer raised and should be removed
class NotLeftParentDescendant(InternalBzrError):

    _fmt = ("Revision %(old_revision)s is not the left parent of"
            " %(new_revision)s, but branch %(branch_location)s expects this")

    def __init__(self, branch, old_revision, new_revision):
        BzrError.__init__(self, branch_location=branch.base,
                          old_revision=old_revision,
                          new_revision=new_revision)


class RangeInChangeOption(BzrError):

    _fmt = "Option --change does not accept revision ranges"


class NoSuchRevisionSpec(BzrError):

    _fmt = "No namespace registered for string: %(spec)r"

    def __init__(self, spec):
        BzrError.__init__(self, spec=spec)


class NoSuchRevisionInTree(NoSuchRevision):
    """When using Tree.revision_tree, and the revision is not accessible."""
    
    _fmt = "The revision id {%(revision_id)s} is not present in the tree %(tree)s."

    def __init__(self, tree, revision_id):
        BzrError.__init__(self)
        self.tree = tree
        self.revision_id = revision_id


class InvalidRevisionSpec(BzrError):

    _fmt = ("Requested revision: %(spec)r does not exist in branch:"
            " %(branch)s%(extra)s")

    def __init__(self, spec, branch, extra=None):
        BzrError.__init__(self, branch=branch, spec=spec)
        if extra:
            self.extra = '\n' + str(extra)
        else:
            self.extra = ''


class HistoryMissing(BzrError):

    _fmt = "%(branch)s is missing %(object_type)s {%(object_id)s}"


class AppendRevisionsOnlyViolation(BzrError):

    _fmt = ('Operation denied because it would change the main history,'
           ' which is not permitted by the append_revisions_only setting on'
           ' branch "%(location)s".')

    def __init__(self, location):
       import bzrlib.urlutils as urlutils
       location = urlutils.unescape_for_display(location, 'ascii')
       BzrError.__init__(self, location=location)


class DivergedBranches(BzrError):

    _fmt = ("These branches have diverged."
            " Use the merge command to reconcile them.")

    def __init__(self, branch1, branch2):
        self.branch1 = branch1
        self.branch2 = branch2


class NotLefthandHistory(InternalBzrError):

    _fmt = "Supplied history does not follow left-hand parents"

    def __init__(self, history):
        BzrError.__init__(self, history=history)


class UnrelatedBranches(BzrError):

    _fmt = ("Branches have no common ancestor, and"
            " no merge base revision was specified.")


class NoCommonAncestor(BzrError):
    
    _fmt = "Revisions have no common ancestor: %(revision_a)s %(revision_b)s"

    def __init__(self, revision_a, revision_b):
        self.revision_a = revision_a
        self.revision_b = revision_b


class NoCommonRoot(BzrError):

    _fmt = ("Revisions are not derived from the same root: "
           "%(revision_a)s %(revision_b)s.")

    def __init__(self, revision_a, revision_b):
        BzrError.__init__(self, revision_a=revision_a, revision_b=revision_b)


class NotAncestor(BzrError):

    _fmt = "Revision %(rev_id)s is not an ancestor of %(not_ancestor_id)s"

    def __init__(self, rev_id, not_ancestor_id):
        BzrError.__init__(self, rev_id=rev_id,
            not_ancestor_id=not_ancestor_id)


class InstallFailed(BzrError):

    def __init__(self, revisions):
        revision_str = ", ".join(str(r) for r in revisions)
        msg = "Could not install revisions:\n%s" % revision_str
        BzrError.__init__(self, msg)
        self.revisions = revisions


class AmbiguousBase(BzrError):

    def __init__(self, bases):
        warn("BzrError AmbiguousBase has been deprecated as of bzrlib 0.8.",
                DeprecationWarning)
        msg = ("The correct base is unclear, because %s are all equally close"
                % ", ".join(bases))
        BzrError.__init__(self, msg)
        self.bases = bases


class NoCommits(BzrError):

    _fmt = "Branch %(branch)s has no commits."

    def __init__(self, branch):
        BzrError.__init__(self, branch=branch)


class UnlistableStore(BzrError):

    def __init__(self, store):
        BzrError.__init__(self, "Store %s is not listable" % store)



class UnlistableBranch(BzrError):

    def __init__(self, br):
        BzrError.__init__(self, "Stores for branch %s are not listable" % br)


class BoundBranchOutOfDate(BzrError):

    _fmt = ("Bound branch %(branch)s is out of date with master branch"
            " %(master)s.")

    def __init__(self, branch, master):
        BzrError.__init__(self)
        self.branch = branch
        self.master = master

        
class CommitToDoubleBoundBranch(BzrError):

    _fmt = ("Cannot commit to branch %(branch)s."
            " It is bound to %(master)s, which is bound to %(remote)s.")

    def __init__(self, branch, master, remote):
        BzrError.__init__(self)
        self.branch = branch
        self.master = master
        self.remote = remote


class OverwriteBoundBranch(BzrError):

    _fmt = "Cannot pull --overwrite to a branch which is bound %(branch)s"

    def __init__(self, branch):
        BzrError.__init__(self)
        self.branch = branch


class BoundBranchConnectionFailure(BzrError):

    _fmt = ("Unable to connect to target of bound branch %(branch)s"
            " => %(target)s: %(error)s")

    def __init__(self, branch, target, error):
        BzrError.__init__(self)
        self.branch = branch
        self.target = target
        self.error = error


class WeaveError(BzrError):

    _fmt = "Error in processing weave: %(message)s"

    def __init__(self, message=None):
        BzrError.__init__(self)
        self.message = message


class WeaveRevisionAlreadyPresent(WeaveError):

    _fmt = "Revision {%(revision_id)s} already present in %(weave)s"

    def __init__(self, revision_id, weave):

        WeaveError.__init__(self)
        self.revision_id = revision_id
        self.weave = weave


class WeaveRevisionNotPresent(WeaveError):

    _fmt = "Revision {%(revision_id)s} not present in %(weave)s"

    def __init__(self, revision_id, weave):
        WeaveError.__init__(self)
        self.revision_id = revision_id
        self.weave = weave


class WeaveFormatError(WeaveError):

    _fmt = "Weave invariant violated: %(what)s"

    def __init__(self, what):
        WeaveError.__init__(self)
        self.what = what


class WeaveParentMismatch(WeaveError):

    _fmt = "Parents are mismatched between two revisions."
    

class WeaveInvalidChecksum(WeaveError):

    _fmt = "Text did not match it's checksum: %(message)s"


class WeaveTextDiffers(WeaveError):

    _fmt = ("Weaves differ on text content. Revision:"
            " {%(revision_id)s}, %(weave_a)s, %(weave_b)s")

    def __init__(self, revision_id, weave_a, weave_b):
        WeaveError.__init__(self)
        self.revision_id = revision_id
        self.weave_a = weave_a
        self.weave_b = weave_b


class WeaveTextDiffers(WeaveError):

    _fmt = ("Weaves differ on text content. Revision:"
            " {%(revision_id)s}, %(weave_a)s, %(weave_b)s")

    def __init__(self, revision_id, weave_a, weave_b):
        WeaveError.__init__(self)
        self.revision_id = revision_id
        self.weave_a = weave_a
        self.weave_b = weave_b


class VersionedFileError(BzrError):
    
    _fmt = "Versioned file error"


class RevisionNotPresent(VersionedFileError):
    
    _fmt = 'Revision {%(revision_id)s} not present in "%(file_id)s".'

    def __init__(self, revision_id, file_id):
        VersionedFileError.__init__(self)
        self.revision_id = revision_id
        self.file_id = file_id


class RevisionAlreadyPresent(VersionedFileError):
    
    _fmt = 'Revision {%(revision_id)s} already present in "%(file_id)s".'

    def __init__(self, revision_id, file_id):
        VersionedFileError.__init__(self)
        self.revision_id = revision_id
        self.file_id = file_id


class VersionedFileInvalidChecksum(VersionedFileError):

    _fmt = "Text did not match its checksum: %(message)s"


class KnitError(InternalBzrError):
    
    _fmt = "Knit error"


class KnitCorrupt(KnitError):

    _fmt = "Knit %(filename)s corrupt: %(how)s"

    def __init__(self, filename, how):
        KnitError.__init__(self)
        self.filename = filename
        self.how = how


class KnitDataStreamIncompatible(KnitError):

    _fmt = "Cannot insert knit data stream of format \"%(stream_format)s\" into knit of format \"%(target_format)s\"."

    def __init__(self, stream_format, target_format):
        self.stream_format = stream_format
        self.target_format = target_format
        

class KnitHeaderError(KnitError):

    _fmt = 'Knit header error: %(badline)r unexpected for file "%(filename)s".'

    def __init__(self, badline, filename):
        KnitError.__init__(self)
        self.badline = badline
        self.filename = filename

class KnitIndexUnknownMethod(KnitError):
    """Raised when we don't understand the storage method.

    Currently only 'fulltext' and 'line-delta' are supported.
    """
    
    _fmt = ("Knit index %(filename)s does not have a known method"
            " in options: %(options)r")

    def __init__(self, filename, options):
        KnitError.__init__(self)
        self.filename = filename
        self.options = options


class NoSuchExportFormat(BzrError):
    
    _fmt = "Export format %(format)r not supported"

    def __init__(self, format):
        BzrError.__init__(self)
        self.format = format


class TransportError(BzrError):
    
    _fmt = "Transport error: %(msg)s %(orig_error)s"

    def __init__(self, msg=None, orig_error=None):
        if msg is None and orig_error is not None:
            msg = str(orig_error)
        if orig_error is None:
            orig_error = ''
        if msg is None:
            msg =  ''
        self.msg = msg
        self.orig_error = orig_error
        BzrError.__init__(self)


class TooManyConcurrentRequests(InternalBzrError):

    _fmt = ("The medium '%(medium)s' has reached its concurrent request limit."
            " Be sure to finish_writing and finish_reading on the"
            " currently open request.")

    def __init__(self, medium):
        self.medium = medium


class SmartProtocolError(TransportError):

    _fmt = "Generic bzr smart protocol error: %(details)s"

    def __init__(self, details):
        self.details = details


# A set of semi-meaningful errors which can be thrown
class TransportNotPossible(TransportError):

    _fmt = "Transport operation not possible: %(msg)s %(orig_error)s"


class ConnectionError(TransportError):

    _fmt = "Connection error: %(msg)s %(orig_error)s"


class SocketConnectionError(ConnectionError):

    _fmt = "%(msg)s %(host)s%(port)s%(orig_error)s"

    def __init__(self, host, port=None, msg=None, orig_error=None):
        if msg is None:
            msg = 'Failed to connect to'
        if orig_error is None:
            orig_error = ''
        else:
            orig_error = '; ' + str(orig_error)
        ConnectionError.__init__(self, msg=msg, orig_error=orig_error)
        self.host = host
        if port is None:
            self.port = ''
        else:
            self.port = ':%s' % port


class ConnectionReset(TransportError):

    _fmt = "Connection closed: %(msg)s %(orig_error)s"


class InvalidRange(TransportError):

    _fmt = "Invalid range access in %(path)s at %(offset)s."
    
    def __init__(self, path, offset):
        TransportError.__init__(self, ("Invalid range access in %s at %d"
                                       % (path, offset)))
        self.path = path
        self.offset = offset


class InvalidHttpResponse(TransportError):

    _fmt = "Invalid http response for %(path)s: %(msg)s"

    def __init__(self, path, msg, orig_error=None):
        self.path = path
        TransportError.__init__(self, msg, orig_error=orig_error)


class InvalidHttpRange(InvalidHttpResponse):

    _fmt = "Invalid http range %(range)r for %(path)s: %(msg)s"
    
    def __init__(self, path, range, msg):
        self.range = range
        InvalidHttpResponse.__init__(self, path, msg)


class InvalidHttpContentType(InvalidHttpResponse):

    _fmt = 'Invalid http Content-type "%(ctype)s" for %(path)s: %(msg)s'
    
    def __init__(self, path, ctype, msg):
        self.ctype = ctype
        InvalidHttpResponse.__init__(self, path, msg)


class RedirectRequested(TransportError):

    _fmt = '%(source)s is%(permanently)s redirected to %(target)s'

    def __init__(self, source, target, is_permanent=False, qual_proto=None):
        self.source = source
        self.target = target
        if is_permanent:
            self.permanently = ' permanently'
        else:
            self.permanently = ''
        self._qualified_proto = qual_proto
        TransportError.__init__(self)

    def _requalify_url(self, url):
        """Restore the qualified proto in front of the url"""
        # When this exception is raised, source and target are in
        # user readable format. But some transports may use a
        # different proto (http+urllib:// will present http:// to
        # the user. If a qualified proto is specified, the code
        # trapping the exception can get the qualified urls to
        # properly handle the redirection themself (creating a
        # new transport object from the target url for example).
        # But checking that the scheme of the original and
        # redirected urls are the same can be tricky. (see the
        # FIXME in BzrDir.open_from_transport for the unique use
        # case so far).
        if self._qualified_proto is None:
            return url

        # The TODO related to NotBranchError mention that doing
        # that kind of manipulation on the urls may not be the
        # exception object job. On the other hand, this object is
        # the interface between the code and the user so
        # presenting the urls in different ways is indeed its
        # job...
        import urlparse
        proto, netloc, path, query, fragment = urlparse.urlsplit(url)
        return urlparse.urlunsplit((self._qualified_proto, netloc, path,
                                   query, fragment))

    def get_source_url(self):
        return self._requalify_url(self.source)

    def get_target_url(self):
        return self._requalify_url(self.target)


class TooManyRedirections(TransportError):

    _fmt = "Too many redirections"


class ConflictsInTree(BzrError):

    _fmt = "Working tree has conflicts."


class ParseConfigError(BzrError):

    def __init__(self, errors, filename):
        if filename is None:
            filename = ""
        message = "Error(s) parsing config file %s:\n%s" % \
            (filename, ('\n'.join(e.message for e in errors)))
        BzrError.__init__(self, message)


class NoEmailInUsername(BzrError):

    _fmt = "%(username)r does not seem to contain a reasonable email address"

    def __init__(self, username):
        BzrError.__init__(self)
        self.username = username


class SigningFailed(BzrError):

    _fmt = 'Failed to gpg sign data with command "%(command_line)s"'

    def __init__(self, command_line):
        BzrError.__init__(self, command_line=command_line)


class WorkingTreeNotRevision(BzrError):

    _fmt = ("The working tree for %(basedir)s has changed since" 
            " the last commit, but weave merge requires that it be"
            " unchanged")

    def __init__(self, tree):
        BzrError.__init__(self, basedir=tree.basedir)


class CantReprocessAndShowBase(BzrError):

    _fmt = ("Can't reprocess and show base, because reprocessing obscures "
           "the relationship of conflicting lines to the base")


class GraphCycleError(BzrError):

    _fmt = "Cycle in graph %(graph)r"

    def __init__(self, graph):
        BzrError.__init__(self)
        self.graph = graph


class WritingCompleted(InternalBzrError):

    _fmt = ("The MediumRequest '%(request)s' has already had finish_writing "
            "called upon it - accept bytes may not be called anymore.")

    def __init__(self, request):
        self.request = request


class WritingNotComplete(InternalBzrError):

    _fmt = ("The MediumRequest '%(request)s' has not has finish_writing "
            "called upon it - until the write phase is complete no "
            "data may be read.")

    def __init__(self, request):
        self.request = request


class NotConflicted(BzrError):

    _fmt = "File %(filename)s is not conflicted."

    def __init__(self, filename):
        BzrError.__init__(self)
        self.filename = filename


class MediumNotConnected(InternalBzrError):

    _fmt = """The medium '%(medium)s' is not connected."""

    def __init__(self, medium):
        self.medium = medium


class MustUseDecorated(Exception):

    _fmt = "A decorating function has requested its original command be used."


class NoBundleFound(BzrError):

    _fmt = 'No bundle was found in "%(filename)s".'

    def __init__(self, filename):
        BzrError.__init__(self)
        self.filename = filename


class BundleNotSupported(BzrError):

    _fmt = "Unable to handle bundle version %(version)s: %(msg)s"

    def __init__(self, version, msg):
        BzrError.__init__(self)
        self.version = version
        self.msg = msg


class MissingText(BzrError):

    _fmt = ("Branch %(base)s is missing revision"
            " %(text_revision)s of %(file_id)s")

    def __init__(self, branch, text_revision, file_id):
        BzrError.__init__(self)
        self.branch = branch
        self.base = branch.base
        self.text_revision = text_revision
        self.file_id = file_id


class DuplicateFileId(BzrError):

    _fmt = "File id {%(file_id)s} already exists in inventory as %(entry)s"

    def __init__(self, file_id, entry):
        BzrError.__init__(self)
        self.file_id = file_id
        self.entry = entry


class DuplicateKey(BzrError):

    _fmt = "Key %(key)s is already present in map"


class DuplicateHelpPrefix(BzrError):

    _fmt = "The prefix %(prefix)s is in the help search path twice."

    def __init__(self, prefix):
        self.prefix = prefix


class MalformedTransform(BzrError):

    _fmt = "Tree transform is malformed %(conflicts)r"


class NoFinalPath(BzrError):

    _fmt = ("No final name for trans_id %(trans_id)r\n"
            "file-id: %(file_id)r\n"
            "root trans-id: %(root_trans_id)r\n")

    def __init__(self, trans_id, transform):
        self.trans_id = trans_id
        self.file_id = transform.final_file_id(trans_id)
        self.root_trans_id = transform.root


class BzrBadParameter(InternalBzrError):

    _fmt = "Bad parameter: %(param)r"

    # This exception should never be thrown, but it is a base class for all
    # parameter-to-function errors.

    def __init__(self, param):
        BzrError.__init__(self)
        self.param = param


class BzrBadParameterNotUnicode(BzrBadParameter):

    _fmt = "Parameter %(param)s is neither unicode nor utf8."


class ReusingTransform(BzrError):

    _fmt = "Attempt to reuse a transform that has already been applied."


class CantMoveRoot(BzrError):

    _fmt = "Moving the root directory is not supported at this time"


class BzrMoveFailedError(BzrError):

    _fmt = "Could not move %(from_path)s%(operator)s %(to_path)s%(extra)s"

    def __init__(self, from_path='', to_path='', extra=None):
        BzrError.__init__(self)
        if extra:
            self.extra = ': ' + str(extra)
        else:
            self.extra = ''

        has_from = len(from_path) > 0
        has_to = len(to_path) > 0
        if has_from:
            self.from_path = osutils.splitpath(from_path)[-1]
        else:
            self.from_path = ''

        if has_to:
            self.to_path = osutils.splitpath(to_path)[-1]
        else:
            self.to_path = ''

        self.operator = ""
        if has_from and has_to:
            self.operator = " =>"
        elif has_from:
            self.from_path = "from " + from_path
        elif has_to:
            self.operator = "to"
        else:
            self.operator = "file"


class BzrRenameFailedError(BzrMoveFailedError):

    _fmt = "Could not rename %(from_path)s%(operator)s %(to_path)s%(extra)s"

    def __init__(self, from_path, to_path, extra=None):
        BzrMoveFailedError.__init__(self, from_path, to_path, extra)

class BzrRemoveChangedFilesError(BzrError):
    """Used when user is trying to remove changed files."""

    _fmt = ("Can't safely remove modified or unknown files:\n"
        "%(changes_as_text)s"
        "Use --keep to not delete them, or --force to delete them regardless.")

    def __init__(self, tree_delta):
        BzrError.__init__(self)
        self.changes_as_text = tree_delta.get_changes_as_text()
        #self.paths_as_string = '\n'.join(changed_files)
        #self.paths_as_string = '\n'.join([quotefn(p) for p in changed_files])


class BzrBadParameterNotString(BzrBadParameter):

    _fmt = "Parameter %(param)s is not a string or unicode string."


class BzrBadParameterMissing(BzrBadParameter):

    _fmt = "Parameter $(param)s is required but not present."


class BzrBadParameterUnicode(BzrBadParameter):

    _fmt = ("Parameter %(param)s is unicode but"
            " only byte-strings are permitted.")


class BzrBadParameterContainsNewline(BzrBadParameter):

    _fmt = "Parameter %(param)s contains a newline."


class DependencyNotPresent(BzrError):

    _fmt = 'Unable to import library "%(library)s": %(error)s'

    def __init__(self, library, error):
        BzrError.__init__(self, library=library, error=error)


class ParamikoNotPresent(DependencyNotPresent):

    _fmt = "Unable to import paramiko (required for sftp support): %(error)s"

    def __init__(self, error):
        DependencyNotPresent.__init__(self, 'paramiko', error)


class PointlessMerge(BzrError):

    _fmt = "Nothing to merge."


class UninitializableFormat(BzrError):

    _fmt = "Format %(format)s cannot be initialised by this version of bzr."

    def __init__(self, format):
        BzrError.__init__(self)
        self.format = format


class BadConversionTarget(BzrError):

    _fmt = "Cannot convert to format %(format)s.  %(problem)s"

    def __init__(self, problem, format):
        BzrError.__init__(self)
        self.problem = problem
        self.format = format


class NoDiff(BzrError):

    _fmt = "Diff is not installed on this machine: %(msg)s"

    def __init__(self, msg):
        BzrError.__init__(self, msg=msg)


class NoDiff3(BzrError):

    _fmt = "Diff3 is not installed on this machine."


class ExistingContent(BzrError):
    # Added in bzrlib 0.92, used by VersionedFile.add_lines.

    _fmt = "The content being inserted is already present."


class ExistingLimbo(BzrError):

    _fmt = """This tree contains left-over files from a failed operation.
    Please examine %(limbo_dir)s to see if it contains any files you wish to
    keep, and delete it when you are done."""
    
    def __init__(self, limbo_dir):
       BzrError.__init__(self)
       self.limbo_dir = limbo_dir


class ExistingPendingDeletion(BzrError):

    _fmt = """This tree contains left-over files from a failed operation.
    Please examine %(pending_deletion)s to see if it contains any files you
    wish to keep, and delete it when you are done."""

    def __init__(self, pending_deletion):
       BzrError.__init__(self, pending_deletion=pending_deletion)


class ImmortalLimbo(BzrError):

    _fmt = """Unable to delete transform temporary directory %(limbo_dir)s.
    Please examine %(limbo_dir)s to see if it contains any files you wish to
    keep, and delete it when you are done."""

    def __init__(self, limbo_dir):
       BzrError.__init__(self)
       self.limbo_dir = limbo_dir


class ImmortalPendingDeletion(BzrError):

    _fmt = """Unable to delete transform temporary directory
    %(pending_deletion)s.  Please examine %(pending_deletions)s to see if it
    contains any files you wish to keep, and delete it when you are done."""

    def __init__(self, pending_deletion):
       BzrError.__init__(self, pending_deletion=pending_deletion)


class OutOfDateTree(BzrError):

    _fmt = "Working tree is out of date, please run 'bzr update'."

    def __init__(self, tree):
        BzrError.__init__(self)
        self.tree = tree


class PublicBranchOutOfDate(BzrError):

    _fmt = 'Public branch "%(public_location)s" lacks revision '\
        '"%(revstring)s".'

    def __init__(self, public_location, revstring):
        import bzrlib.urlutils as urlutils
        public_location = urlutils.unescape_for_display(public_location,
                                                        'ascii')
        BzrError.__init__(self, public_location=public_location,
                          revstring=revstring)


class MergeModifiedFormatError(BzrError):

    _fmt = "Error in merge modified format"


class ConflictFormatError(BzrError):

    _fmt = "Format error in conflict listings"


class CorruptRepository(BzrError):

    _fmt = ("An error has been detected in the repository %(repo_path)s.\n"
            "Please run bzr reconcile on this repository.")

    def __init__(self, repo):
        BzrError.__init__(self)
        self.repo_path = repo.bzrdir.root_transport.base


class UpgradeRequired(BzrError):

    _fmt = "To use this feature you must upgrade your branch at %(path)s."

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path


class LocalRequiresBoundBranch(BzrError):

    _fmt = "Cannot perform local-only commits on unbound branches."


class MissingProgressBarFinish(BzrError):

    _fmt = "A nested progress bar was not 'finished' correctly."


class InvalidProgressBarType(BzrError):

    _fmt = ("Environment variable BZR_PROGRESS_BAR='%(bar_type)s"
            " is not a supported type Select one of: %(valid_types)s")

    def __init__(self, bar_type, valid_types):
        BzrError.__init__(self, bar_type=bar_type, valid_types=valid_types)


class UnsupportedOperation(BzrError):

    _fmt = ("The method %(mname)s is not supported on"
            " objects of type %(tname)s.")

    def __init__(self, method, method_self):
        self.method = method
        self.mname = method.__name__
        self.tname = type(method_self).__name__


class CannotSetRevisionId(UnsupportedOperation):
    """Raised when a commit is attempting to set a revision id but cant."""


class NonAsciiRevisionId(UnsupportedOperation):
    """Raised when a commit is attempting to set a non-ascii revision id
       but cant.
    """


class BinaryFile(BzrError):
    
    _fmt = "File is binary but should be text."


class IllegalPath(BzrError):

    _fmt = "The path %(path)s is not permitted on this platform"

    def __init__(self, path):
        BzrError.__init__(self)
        self.path = path


class TestamentMismatch(BzrError):

    _fmt = """Testament did not match expected value.
       For revision_id {%(revision_id)s}, expected {%(expected)s}, measured
       {%(measured)s}"""

    def __init__(self, revision_id, expected, measured):
        self.revision_id = revision_id
        self.expected = expected
        self.measured = measured


class NotABundle(BzrError):
    
    _fmt = "Not a bzr revision-bundle: %(text)r"

    def __init__(self, text):
        BzrError.__init__(self)
        self.text = text


class BadBundle(BzrError): 
    
    _fmt = "Bad bzr revision-bundle: %(text)r"

    def __init__(self, text):
        BzrError.__init__(self)
        self.text = text


class MalformedHeader(BadBundle): 
    
    _fmt = "Malformed bzr revision-bundle header: %(text)r"


class MalformedPatches(BadBundle): 
    
    _fmt = "Malformed patches in bzr revision-bundle: %(text)r"


class MalformedFooter(BadBundle): 
    
    _fmt = "Malformed footer in bzr revision-bundle: %(text)r"


class UnsupportedEOLMarker(BadBundle):
    
    _fmt = "End of line marker was not \\n in bzr revision-bundle"    

    def __init__(self):
        # XXX: BadBundle's constructor assumes there's explanatory text, 
        # but for this there is not
        BzrError.__init__(self)


class IncompatibleBundleFormat(BzrError):
    
    _fmt = "Bundle format %(bundle_format)s is incompatible with %(other)s"

    def __init__(self, bundle_format, other):
        BzrError.__init__(self)
        self.bundle_format = bundle_format
        self.other = other


class BadInventoryFormat(BzrError):
    
    _fmt = "Root class for inventory serialization errors"


class UnexpectedInventoryFormat(BadInventoryFormat):

    _fmt = "The inventory was not in the expected format:\n %(msg)s"

    def __init__(self, msg):
        BadInventoryFormat.__init__(self, msg=msg)


class RootNotRich(BzrError):

    _fmt = """This operation requires rich root data storage"""


class NoSmartMedium(InternalBzrError):

    _fmt = "The transport '%(transport)s' cannot tunnel the smart protocol."

    def __init__(self, transport):
        self.transport = transport


class NoSmartServer(NotBranchError):

    _fmt = "No smart server available at %(url)s"

    def __init__(self, url):
        self.url = url


class UnknownSSH(BzrError):

    _fmt = "Unrecognised value for BZR_SSH environment variable: %(vendor)s"

    def __init__(self, vendor):
        BzrError.__init__(self)
        self.vendor = vendor


class SSHVendorNotFound(BzrError):

    _fmt = ("Don't know how to handle SSH connections."
            " Please set BZR_SSH environment variable.")


class GhostRevisionUnusableHere(BzrError):

    _fmt = "Ghost revision {%(revision_id)s} cannot be used here."

    def __init__(self, revision_id):
        BzrError.__init__(self)
        self.revision_id = revision_id


class IllegalUseOfScopeReplacer(InternalBzrError):

    _fmt = ("ScopeReplacer object %(name)r was used incorrectly:"
            " %(msg)s%(extra)s")

    def __init__(self, name, msg, extra=None):
        BzrError.__init__(self)
        self.name = name
        self.msg = msg
        if extra:
            self.extra = ': ' + str(extra)
        else:
            self.extra = ''


class InvalidImportLine(InternalBzrError):

    _fmt = "Not a valid import statement: %(msg)\n%(text)s"

    def __init__(self, text, msg):
        BzrError.__init__(self)
        self.text = text
        self.msg = msg


class ImportNameCollision(InternalBzrError):

    _fmt = ("Tried to import an object to the same name as"
            " an existing object. %(name)s")

    def __init__(self, name):
        BzrError.__init__(self)
        self.name = name


class NotAMergeDirective(BzrError):
    """File starting with %(firstline)r is not a merge directive"""
    def __init__(self, firstline):
        BzrError.__init__(self, firstline=firstline)


class NoMergeSource(BzrError):
    """Raise if no merge source was specified for a merge directive"""

    _fmt = "A merge directive must provide either a bundle or a public"\
        " branch location."


class IllegalMergeDirectivePayload(BzrError):
    """A merge directive contained something other than a patch or bundle"""

    _fmt = "Bad merge directive payload %(start)r"

    def __init__(self, start):
        BzrError(self)
        self.start = start


class PatchVerificationFailed(BzrError):
    """A patch from a merge directive could not be verified"""

    _fmt = "Preview patch does not match requested changes."


class PatchMissing(BzrError):
    """Raise a patch type was specified but no patch supplied"""

    _fmt = "Patch_type was %(patch_type)s, but no patch was supplied."

    def __init__(self, patch_type):
        BzrError.__init__(self)
        self.patch_type = patch_type


class UnsupportedInventoryKind(BzrError):
    
    _fmt = """Unsupported entry kind %(kind)s"""

    def __init__(self, kind):
        self.kind = kind


class BadSubsumeSource(BzrError):

    _fmt = "Can't subsume %(other_tree)s into %(tree)s. %(reason)s"

    def __init__(self, tree, other_tree, reason):
        self.tree = tree
        self.other_tree = other_tree
        self.reason = reason


class SubsumeTargetNeedsUpgrade(BzrError):
    
    _fmt = """Subsume target %(other_tree)s needs to be upgraded."""

    def __init__(self, other_tree):
        self.other_tree = other_tree


class BadReferenceTarget(InternalBzrError):

    _fmt = "Can't add reference to %(other_tree)s into %(tree)s." \
           "%(reason)s"

    def __init__(self, tree, other_tree, reason):
        self.tree = tree
        self.other_tree = other_tree
        self.reason = reason


class NoSuchTag(BzrError):

    _fmt = "No such tag: %(tag_name)s"

    def __init__(self, tag_name):
        self.tag_name = tag_name


class TagsNotSupported(BzrError):

    _fmt = ("Tags not supported by %(branch)s;"
            " you may be able to use bzr upgrade --dirstate-tags.")

    def __init__(self, branch):
        self.branch = branch

        
class TagAlreadyExists(BzrError):

    _fmt = "Tag %(tag_name)s already exists."

    def __init__(self, tag_name):
        self.tag_name = tag_name


class MalformedBugIdentifier(BzrError):

    _fmt = "Did not understand bug identifier %(bug_id)s: %(reason)s"

    def __init__(self, bug_id, reason):
        self.bug_id = bug_id
        self.reason = reason


class UnknownBugTrackerAbbreviation(BzrError):

    _fmt = ("Cannot find registered bug tracker called %(abbreviation)s "
            "on %(branch)s")

    def __init__(self, abbreviation, branch):
        self.abbreviation = abbreviation
        self.branch = branch


class UnexpectedSmartServerResponse(BzrError):

    _fmt = "Could not understand response from smart server: %(response_tuple)r"

    def __init__(self, response_tuple):
        self.response_tuple = response_tuple


class ContainerError(BzrError):
    """Base class of container errors."""


class UnknownContainerFormatError(ContainerError):

    _fmt = "Unrecognised container format: %(container_format)r"
    
    def __init__(self, container_format):
        self.container_format = container_format


class UnexpectedEndOfContainerError(ContainerError):

    _fmt = "Unexpected end of container stream"


class UnknownRecordTypeError(ContainerError):

    _fmt = "Unknown record type: %(record_type)r"

    def __init__(self, record_type):
        self.record_type = record_type


class InvalidRecordError(ContainerError):

    _fmt = "Invalid record: %(reason)s"

    def __init__(self, reason):
        self.reason = reason


class ContainerHasExcessDataError(ContainerError):

    _fmt = "Container has data after end marker: %(excess)r"

    def __init__(self, excess):
        self.excess = excess


class DuplicateRecordNameError(ContainerError):

    _fmt = "Container has multiple records with the same name: %(name)s"

    def __init__(self, name):
        self.name = name


class NoDestinationAddress(InternalBzrError):

    _fmt = "Message does not have a destination address."


class RepositoryDataStreamError(BzrError):

    _fmt = "Corrupt or incompatible data stream: %(reason)s"

    def __init__(self, reason):
        self.reason = reason


class SMTPError(BzrError):

    _fmt = "SMTP error: %(error)s"

    def __init__(self, error):
        self.error = error


class NoMessageSupplied(BzrError):

    _fmt = "No message supplied."


class UnknownMailClient(BzrError):

    _fmt = "Unknown mail client: %(mail_client)s"

    def __init__(self, mail_client):
        BzrError.__init__(self, mail_client=mail_client)


class MailClientNotFound(BzrError):

    _fmt = "Unable to find mail client with the following names:"\
        " %(mail_command_list_string)s"

    def __init__(self, mail_command_list):
        mail_command_list_string = ', '.join(mail_command_list)
        BzrError.__init__(self, mail_command_list=mail_command_list,
                          mail_command_list_string=mail_command_list_string)

class SMTPConnectionRefused(SMTPError):

    _fmt = "SMTP connection to %(host)s refused"

    def __init__(self, error, host):
        self.error = error
        self.host = host


class DefaultSMTPConnectionRefused(SMTPConnectionRefused):

    _fmt = "Please specify smtp_server.  No server at default %(host)s."


class BzrDirError(BzrError):

    def __init__(self, bzrdir):
        import bzrlib.urlutils as urlutils
        display_url = urlutils.unescape_for_display(bzrdir.root_transport.base,
                                                    'ascii')
        BzrError.__init__(self, bzrdir=bzrdir, display_url=display_url)


class AlreadyBranch(BzrDirError):

    _fmt = "'%(display_url)s' is already a branch."


class AlreadyTree(BzrDirError):

    _fmt = "'%(display_url)s' is already a tree."


class AlreadyCheckout(BzrDirError):

    _fmt = "'%(display_url)s' is already a checkout."


class ReconfigurationNotSupported(BzrDirError):

    _fmt = "Requested reconfiguration of '%(display_url)s' is not supported."


class NoBindLocation(BzrDirError):

    _fmt = "No location could be found to bind to at %(display_url)s."


class UncommittedChanges(BzrError):

    _fmt = 'Working tree "%(display_url)s" has uncommitted changes.'

    def __init__(self, tree):
        import bzrlib.urlutils as urlutils
        display_url = urlutils.unescape_for_display(
            tree.bzrdir.root_transport.base, 'ascii')
        BzrError.__init__(self, tree=tree, display_url=display_url)
