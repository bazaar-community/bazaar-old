# Copyright (C) 2004, 2005, 2006 Canonical Ltd.
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

import os
import re
import sys

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
import errno
import subprocess
import tempfile
import time

from bzrlib import (
    errors,
    osutils,
    patiencediff,
    textfile,
    timestamp,
    )
""")

# compatability - plugins import compare_trees from diff!!!
# deprecated as of 0.10
from bzrlib.delta import compare_trees
from bzrlib.symbol_versioning import (
        deprecated_function,
        zero_eight,
        )
from bzrlib.trace import mutter, warning


# TODO: Rather than building a changeset object, we should probably
# invoke callbacks on an object.  That object can either accumulate a
# list, write them out directly, etc etc.

def internal_diff(old_filename, oldlines, new_filename, newlines, to_file,
                  allow_binary=False, sequence_matcher=None,
                  path_encoding='utf8'):
    # FIXME: difflib is wrong if there is no trailing newline.
    # The syntax used by patch seems to be "\ No newline at
    # end of file" following the last diff line from that
    # file.  This is not trivial to insert into the
    # unified_diff output and it might be better to just fix
    # or replace that function.

    # In the meantime we at least make sure the patch isn't
    # mangled.


    # Special workaround for Python2.3, where difflib fails if
    # both sequences are empty.
    if not oldlines and not newlines:
        return
    
    if allow_binary is False:
        textfile.check_text_lines(oldlines)
        textfile.check_text_lines(newlines)

    if sequence_matcher is None:
        sequence_matcher = patiencediff.PatienceSequenceMatcher
    ud = patiencediff.unified_diff(oldlines, newlines,
                      fromfile=old_filename.encode(path_encoding),
                      tofile=new_filename.encode(path_encoding),
                      sequencematcher=sequence_matcher)

    ud = list(ud)
    # work-around for difflib being too smart for its own good
    # if /dev/null is "1,0", patch won't recognize it as /dev/null
    if not oldlines:
        ud[2] = ud[2].replace('-1,0', '-0,0')
    elif not newlines:
        ud[2] = ud[2].replace('+1,0', '+0,0')
    # work around for difflib emitting random spaces after the label
    ud[0] = ud[0][:-2] + '\n'
    ud[1] = ud[1][:-2] + '\n'

    for line in ud:
        to_file.write(line)
        if not line.endswith('\n'):
            to_file.write("\n\\ No newline at end of file\n")
    print >>to_file


def _spawn_external_diff(diffcmd, capture_errors=True):
    """Spawn the externall diff process, and return the child handle.

    :param diffcmd: The command list to spawn
    :param capture_errors: Capture stderr as well as setting LANG=C
        and LC_ALL=C. This lets us read and understand the output of diff,
        and respond to any errors.
    :return: A Popen object.
    """
    if capture_errors:
        # construct minimal environment
        env = {}
        path = os.environ.get('PATH')
        if path is not None:
            env['PATH'] = path
        env['LANGUAGE'] = 'C'   # on win32 only LANGUAGE has effect
        env['LANG'] = 'C'
        env['LC_ALL'] = 'C'
        stderr = subprocess.PIPE
    else:
        env = None
        stderr = None

    try:
        pipe = subprocess.Popen(diffcmd,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=stderr,
                                env=env)
    except OSError, e:
        if e.errno == errno.ENOENT:
            raise errors.NoDiff(str(e))
        raise

    return pipe


def external_diff(old_filename, oldlines, new_filename, newlines, to_file,
                  diff_opts):
    """Display a diff by calling out to the external diff program."""
    # make sure our own output is properly ordered before the diff
    to_file.flush()

    oldtmp_fd, old_abspath = tempfile.mkstemp(prefix='bzr-diff-old-')
    newtmp_fd, new_abspath = tempfile.mkstemp(prefix='bzr-diff-new-')
    oldtmpf = os.fdopen(oldtmp_fd, 'wb')
    newtmpf = os.fdopen(newtmp_fd, 'wb')

    try:
        # TODO: perhaps a special case for comparing to or from the empty
        # sequence; can just use /dev/null on Unix

        # TODO: if either of the files being compared already exists as a
        # regular named file (e.g. in the working directory) then we can
        # compare directly to that, rather than copying it.

        oldtmpf.writelines(oldlines)
        newtmpf.writelines(newlines)

        oldtmpf.close()
        newtmpf.close()

        if not diff_opts:
            diff_opts = []
        diffcmd = ['diff',
                   '--label', old_filename,
                   old_abspath,
                   '--label', new_filename,
                   new_abspath,
                   '--binary',
                  ]

        # diff only allows one style to be specified; they don't override.
        # note that some of these take optargs, and the optargs can be
        # directly appended to the options.
        # this is only an approximate parser; it doesn't properly understand
        # the grammar.
        for s in ['-c', '-u', '-C', '-U',
                  '-e', '--ed',
                  '-q', '--brief',
                  '--normal',
                  '-n', '--rcs',
                  '-y', '--side-by-side',
                  '-D', '--ifdef']:
            for j in diff_opts:
                if j.startswith(s):
                    break
            else:
                continue
            break
        else:
            diffcmd.append('-u')
                  
        if diff_opts:
            diffcmd.extend(diff_opts)

        pipe = _spawn_external_diff(diffcmd, capture_errors=True)
        out,err = pipe.communicate()
        rc = pipe.returncode
        
        # internal_diff() adds a trailing newline, add one here for consistency
        out += '\n'
        if rc == 2:
            # 'diff' gives retcode == 2 for all sorts of errors
            # one of those is 'Binary files differ'.
            # Bad options could also be the problem.
            # 'Binary files' is not a real error, so we suppress that error.
            lang_c_out = out

            # Since we got here, we want to make sure to give an i18n error
            pipe = _spawn_external_diff(diffcmd, capture_errors=False)
            out, err = pipe.communicate()

            # Write out the new i18n diff response
            to_file.write(out+'\n')
            if pipe.returncode != 2:
                raise errors.BzrError(
                               'external diff failed with exit code 2'
                               ' when run with LANG=C and LC_ALL=C,'
                               ' but not when run natively: %r' % (diffcmd,))

            first_line = lang_c_out.split('\n', 1)[0]
            # Starting with diffutils 2.8.4 the word "binary" was dropped.
            m = re.match('^(binary )?files.*differ$', first_line, re.I)
            if m is None:
                raise errors.BzrError('external diff failed with exit code 2;'
                                      ' command: %r' % (diffcmd,))
            else:
                # Binary files differ, just return
                return

        # If we got to here, we haven't written out the output of diff
        # do so now
        to_file.write(out)
        if rc not in (0, 1):
            # returns 1 if files differ; that's OK
            if rc < 0:
                msg = 'signal %d' % (-rc)
            else:
                msg = 'exit code %d' % rc
                
            raise errors.BzrError('external diff failed with %s; command: %r' 
                                  % (rc, diffcmd))


    finally:
        oldtmpf.close()                 # and delete
        newtmpf.close()
        # Clean up. Warn in case the files couldn't be deleted
        # (in case windows still holds the file open, but not
        # if the files have already been deleted)
        try:
            os.remove(old_abspath)
        except OSError, e:
            if e.errno not in (errno.ENOENT,):
                warning('Failed to delete temporary file: %s %s',
                        old_abspath, e)
        try:
            os.remove(new_abspath)
        except OSError:
            if e.errno not in (errno.ENOENT,):
                warning('Failed to delete temporary file: %s %s',
                        new_abspath, e)


@deprecated_function(zero_eight)
def show_diff(b, from_spec, specific_files, external_diff_options=None,
              revision2=None, output=None, b2=None):
    """Shortcut for showing the diff to the working tree.

    Please use show_diff_trees instead.

    b
        Branch.

    revision
        None for 'basis tree', or otherwise the old revision to compare against.
    
    The more general form is show_diff_trees(), where the caller
    supplies any two trees.
    """
    if output is None:
        output = sys.stdout

    if from_spec is None:
        old_tree = b.bzrdir.open_workingtree()
        if b2 is None:
            old_tree = old_tree = old_tree.basis_tree()
    else:
        old_tree = b.repository.revision_tree(from_spec.in_history(b).rev_id)

    if revision2 is None:
        if b2 is None:
            new_tree = b.bzrdir.open_workingtree()
        else:
            new_tree = b2.bzrdir.open_workingtree()
    else:
        new_tree = b.repository.revision_tree(revision2.in_history(b).rev_id)

    return show_diff_trees(old_tree, new_tree, output, specific_files,
                           external_diff_options)


def diff_cmd_helper(tree, specific_files, external_diff_options, 
                    old_revision_spec=None, new_revision_spec=None,
                    revision_specs=None,
                    old_label='a/', new_label='b/'):
    """Helper for cmd_diff.

    :param tree:
        A WorkingTree

    :param specific_files:
        The specific files to compare, or None

    :param external_diff_options:
        If non-None, run an external diff, and pass it these options

    :param old_revision_spec:
        If None, use basis tree as old revision, otherwise use the tree for
        the specified revision. 

    :param new_revision_spec:
        If None, use working tree as new revision, otherwise use the tree for
        the specified revision.
    
    :param revision_specs: 
        Zero, one or two RevisionSpecs from the command line, saying what revisions 
        to compare.  This can be passed as an alternative to the old_revision_spec 
        and new_revision_spec parameters.

    The more general form is show_diff_trees(), where the caller
    supplies any two trees.
    """

    # TODO: perhaps remove the old parameters old_revision_spec and
    # new_revision_spec, since this is only really for use from cmd_diff and
    # it now always passes through a sequence of revision_specs -- mbp
    # 20061221

    def spec_tree(spec):
        if tree:
            revision = spec.in_store(tree.branch)
        else:
            revision = spec.in_store(None)
        revision_id = revision.rev_id
        branch = revision.branch
        return branch.repository.revision_tree(revision_id)

    if revision_specs is not None:
        assert (old_revision_spec is None
                and new_revision_spec is None)
        if len(revision_specs) > 0:
            old_revision_spec = revision_specs[0]
        if len(revision_specs) > 1:
            new_revision_spec = revision_specs[1]

    if old_revision_spec is None:
        old_tree = tree.basis_tree()
    else:
        old_tree = spec_tree(old_revision_spec)

    if (new_revision_spec is None
        or new_revision_spec.spec is None):
        new_tree = tree
    else:
        new_tree = spec_tree(new_revision_spec)

    if new_tree is not tree:
        extra_trees = (tree,)
    else:
        extra_trees = None

    return show_diff_trees(old_tree, new_tree, sys.stdout, specific_files,
                           external_diff_options,
                           old_label=old_label, new_label=new_label,
                           extra_trees=extra_trees)


def show_diff_trees(old_tree, new_tree, to_file, specific_files=None,
                    external_diff_options=None,
                    old_label='a/', new_label='b/',
                    extra_trees=None,
                    path_encoding=None):
    """Show in text form the changes from one tree to another.

    to_files
        If set, include only changes to these files.

    external_diff_options
        If set, use an external GNU diff and pass these options.

    extra_trees
        If set, more Trees to use for looking up file ids

    path_encoding
        If set, the path will be encoded as specified
    """
    if path_encoding is None:
        path_encoding = 'utf8'
    old_tree.lock_read()
    try:
        if extra_trees is not None:
            for tree in extra_trees:
                tree.lock_read()
        new_tree.lock_read()
        try:
            return _show_diff_trees(old_tree, new_tree, to_file,
                                    specific_files, external_diff_options,
                                    old_label=old_label, new_label=new_label,
                                    extra_trees=extra_trees,
                                    path_encoding=path_encoding)
        finally:
            new_tree.unlock()
            if extra_trees is not None:
                for tree in extra_trees:
                    tree.unlock()
    finally:
        old_tree.unlock()


def _show_diff_trees(old_tree, new_tree, to_file,
                     specific_files, external_diff_options, path_encoding,
                     old_label='a/', new_label='b/', extra_trees=None):

    # GNU Patch uses the epoch date to detect files that are being added
    # or removed in a diff.
    EPOCH_DATE = '1970-01-01 00:00:00 +0000'

    # TODO: Generation of pseudo-diffs for added/deleted files could
    # be usefully made into a much faster special case.

    if external_diff_options:
        assert isinstance(external_diff_options, basestring)
        opts = external_diff_options.split()
        def diff_file(olab, olines, nlab, nlines, to_file):
            external_diff(olab, olines, nlab, nlines, to_file, opts)
    else:
        diff_file = internal_diff
    
    delta = new_tree.changes_from(old_tree,
        specific_files=specific_files,
        extra_trees=extra_trees, require_versioned=True)

    has_changes = 0
    for path, file_id, kind in delta.removed:
        has_changes = 1
        print >>to_file, '=== removed %s %r' % (kind,
                                                path.encode(path_encoding))
        old_name = '%s%s\t%s' % (old_label, path,
                                 _patch_header_date(old_tree, file_id, path))
        new_name = '%s%s\t%s' % (new_label, path, EPOCH_DATE)
        old_tree.inventory[file_id].diff(diff_file, old_name, old_tree,
                                         new_name, None, None, to_file)
    for path, file_id, kind in delta.added:
        has_changes = 1
        print >>to_file, '=== added %s %r' % (kind, path.encode(path_encoding))
        old_name = '%s%s\t%s' % (old_label, path, EPOCH_DATE)
        new_name = '%s%s\t%s' % (new_label, path,
                                 _patch_header_date(new_tree, file_id, path))
        new_tree.inventory[file_id].diff(diff_file, new_name, new_tree,
                                         old_name, None, None, to_file, 
                                         reverse=True)
    for (old_path, new_path, file_id, kind,
         text_modified, meta_modified) in delta.renamed:
        has_changes = 1
        prop_str = get_prop_change(meta_modified)
        print >>to_file, '=== renamed %s %r => %r%s' % (
                    kind, old_path.encode(path_encoding),
                    new_path.encode(path_encoding), prop_str)
        old_name = '%s%s\t%s' % (old_label, old_path,
                                 _patch_header_date(old_tree, file_id,
                                                    old_path))
        new_name = '%s%s\t%s' % (new_label, new_path,
                                 _patch_header_date(new_tree, file_id,
                                                    new_path))
        _maybe_diff_file_or_symlink(old_name, old_tree, file_id,
                                    new_name, new_tree,
                                    text_modified, kind, to_file, diff_file)
    for path, file_id, kind, text_modified, meta_modified in delta.modified:
        has_changes = 1
        prop_str = get_prop_change(meta_modified)
        print >>to_file, '=== modified %s %r%s' % (kind,
                                                   path.encode(path_encoding),
                                                   prop_str)
        # The file may be in a different location in the old tree (because
        # the containing dir was renamed, but the file itself was not)
        old_path = old_tree.id2path(file_id)
        old_name = '%s%s\t%s' % (old_label, old_path,
                                 _patch_header_date(old_tree, file_id, old_path))
        new_name = '%s%s\t%s' % (new_label, path,
                                 _patch_header_date(new_tree, file_id, path))
        if text_modified:
            _maybe_diff_file_or_symlink(old_name, old_tree, file_id,
                                        new_name, new_tree,
                                        True, kind, to_file, diff_file)

    return has_changes


def _patch_header_date(tree, file_id, path):
    """Returns a timestamp suitable for use in a patch header."""
    mtime = tree.get_file_mtime(file_id, path)
    assert mtime is not None, \
        "got an mtime of None for file-id %s, path %s in tree %s" % (
                file_id, path, tree)
    return timestamp.format_patch_date(mtime)


def _raise_if_nonexistent(paths, old_tree, new_tree):
    """Complain if paths are not in either inventory or tree.

    It's OK with the files exist in either tree's inventory, or 
    if they exist in the tree but are not versioned.
    
    This can be used by operations such as bzr status that can accept
    unknown or ignored files.
    """
    mutter("check paths: %r", paths)
    if not paths:
        return
    s = old_tree.filter_unversioned_files(paths)
    s = new_tree.filter_unversioned_files(s)
    s = [path for path in s if not new_tree.has_filename(path)]
    if s:
        raise errors.PathsDoNotExist(sorted(s))


def get_prop_change(meta_modified):
    if meta_modified:
        return " (properties changed)"
    else:
        return  ""


def _maybe_diff_file_or_symlink(old_path, old_tree, file_id,
                                new_path, new_tree, text_modified,
                                kind, to_file, diff_file):
    if text_modified:
        new_entry = new_tree.inventory[file_id]
        old_tree.inventory[file_id].diff(diff_file,
                                         old_path, old_tree,
                                         new_path, new_entry, 
                                         new_tree, to_file)
