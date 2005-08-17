#!/usr/bin/env python
"""\
Just some work for generating a changeset.
"""

import bzrlib, bzrlib.errors

import common

from bzrlib.inventory import ROOT_ID

try:
    set
except NameError:
    from sets import Set as set

def _canonicalize_revision(branch, revno):
    """Turn some sort of revision information into a single
    set of from-to revision ids.

    A revision id can be None if there is no associated revison.

    :return: (old, new)
    """
    # This is a little clumsy because revision parsing may return
    # a single entry, or a list
    if revno is None:
        new = branch.last_patch()
    else:
        new = branch.lookup_revision(revno)

    if new is None:
        raise BzrCommandError('Cannot generate a changset with no commits in tree.')

    old = branch.get_revision(new).precursor

    return old, new

def _get_trees(branch, revisions):
    """Get the old and new trees based on revision.
    """
    from bzrlib.tree import EmptyTree
    if revisions[0] is None:
        if hasattr(branch, 'get_root_id'): # Watch out for trees with labeled ROOT ids
            old_tree = EmptyTree(branch.get_root_id) 
        else:
            old_tree = EmptyTree()
    else:
        old_tree = branch.revision_tree(revisions[0])

    if revisions[1] is None:
        # This is for the future, once we support rollup revisions
        # Or working tree revisions
        new_tree = branch.working_tree()
    else:
        new_tree = branch.revision_tree(revisions[1])
    return old_tree, new_tree

def _fake_working_revision(branch):
    """Fake a Revision object for the working tree.
    
    This is for the future, to support changesets against the working tree.
    """
    from bzrlib.revision import Revision
    import time
    from bzrlib.osutils import local_time_offset, \
            username

    precursor = branch.last_patch()
    precursor_sha1 = branch.get_revision_sha1(precursor)

    return Revision(timestamp=time.time(),
            timezone=local_time_offset(),
            committer=username(),
            precursor=precursor,
            precursor_sha1=precursor_sha1)


class MetaInfoHeader(object):
    """Maintain all of the header information about this
    changeset.
    """

    def __init__(self, branch, revisions, delta,
            full_remove=True, full_rename=False,
            external_diff_options = None,
            new_tree=None, old_tree=None,
            old_label = '', new_label = ''):
        """
        :param full_remove: Include the full-text for a delete
        :param full_rename: Include an add+delete patch for a rename
        """
        self.branch = branch
        self.delta = delta
        self.full_remove=full_remove
        self.full_rename=full_rename
        self.external_diff_options = external_diff_options
        self.old_label = old_label
        self.new_label = new_label
        self.old_tree = old_tree
        self.new_tree = new_tree
        self.to_file = None
        self.revno = None
        self.precursor_revno = None

        self._get_revision_list(revisions)

    def _get_revision_list(self, revisions):
        """This generates the list of all revisions from->to.

        This is for the future, when we support having a rollup changeset.
        For now, the list should only be one long.
        """
        old_revno = None
        new_revno = None
        rh = self.branch.revision_history()
        for revno, rev in enumerate(rh):
            if rev == revisions[0]:
                old_revno = revno
            if rev == revisions[1]:
                new_revno = revno

        self.revision_list = []
        if old_revno is None:
            self.base_revision = None # Effectively the EmptyTree()
            old_revno = -1
        else:
            self.base_revision = self.branch.get_revision(rh[old_revno])
        if new_revno is None:
            # For the future, when we support working tree changesets.
            for rev_id in rh[old_revno+1:]:
                self.revision_list.append(self.branch.get_revision(rev_id))
            self.revision_list.append(_fake_working_revision(self.branch))
        else:
            for rev_id in rh[old_revno+1:new_revno+1]:
                self.revision_list.append(self.branch.get_revision(rev_id))
        self.precursor_revno = old_revno
        self.revno = new_revno

    def _write(self, txt, key=None):
        if key:
            self.to_file.write('# %s: %s\n' % (key, txt))
        else:
            self.to_file.write('# %s\n' % (txt,))

    def write_meta_info(self, to_file):
        """Write out the meta-info portion to the supplied file.

        :param to_file: Write out the meta information to the supplied
                        file
        """
        self.to_file = to_file

        self._write_header()
        self._write_diffs()
        self._write_footer()

    def _write_header(self):
        """Write the stuff that comes before the patches."""
        from bzrlib.osutils import username, format_date
        write = self._write

        for line in common.get_header():
            write(line)

        # This grabs the current username, what we really want is the
        # username from the actual patches.
        #write(username(), key='committer')
        assert len(self.revision_list) == 1
        rev = self.revision_list[0]
        write(rev.committer, key='committer')
        write(format_date(rev.timestamp, offset=rev.timezone), key='date')
        write(str(self.revno), key='revno')
        if rev.message:
            self.to_file.write('# message:\n')
            for line in rev.message.split('\n'):
                self.to_file.write('#    %s\n' % line)
        write(rev.revision_id, key='revision')

        if self.base_revision:
            write(self.base_revision.revision_id, key='precursor')
            write(str(self.precursor_revno), key='precursor revno')


        write('')
        self.to_file.write('\n')

    def _write_footer(self):
        """Write the stuff that comes after the patches.

        This is meant to be more meta-information, which people probably don't want
        to read, but which is required for proper bzr operation.
        """
        write = self._write

        write('BEGIN BZR FOOTER')

        assert len(self.revision_list) == 1 # We only handle single revision entries
        rev = self.revision_list[0]
        write(self.branch.get_revision_sha1(rev.revision_id),
                key='revision sha1')
        if self.base_revision:
            rev_id = self.base_revision.revision_id
            write(self.branch.get_revision_sha1(rev_id),
                    key='precursor sha1')

        write('%.9f' % rev.timestamp, key='timestamp')
        write(str(rev.timezone), key='timezone')

        self._write_ids()

        write('END BZR FOOTER')

    def _write_revisions(self):
        """Not used. Used for writing multiple revisions."""
        first = True
        for rev in self.revision_list:
            if rev.revision_id is not None:
                if first:
                    self._write('revisions:')
                    first = False
                self._write(' '*4 + rev.revision_id + '\t' + self.branch.get_revision_sha1(rev.revision_id))


    def _write_ids(self):
        if hasattr(self.branch, 'get_root_id'):
            root_id = self.branch.get_root_id()
        else:
            root_id = ROOT_ID

        old_ids = set()
        new_ids = set()

        for path, file_id, kind in self.delta.removed:
            old_ids.add(file_id)
        for path, file_id, kind in self.delta.added:
            new_ids.add(file_id)
        for old_path, new_path, file_id, kind, text_modified in self.delta.renamed:
            old_ids.add(file_id)
            new_ids.add(file_id)
        for path, file_id, kind in self.delta.modified:
            new_ids.add(file_id)

        self._write(root_id, key='tree root id')

        def write_ids(tree, id_set, name):
            if len(id_set) > 0:
                self.to_file.write('# %s ids:\n' % name)
            seen_ids = set([root_id])
            while len(id_set) > 0:
                file_id = id_set.pop()
                if file_id in seen_ids:
                    continue
                seen_ids.add(file_id)
                ie = tree.inventory[file_id]
                if ie.parent_id not in seen_ids:
                    id_set.add(ie.parent_id)
                path = tree.inventory.id2path(file_id)
                self.to_file.write('#    %s\t%s\t%s\n'
                        % (path.encode('utf8'), file_id.encode('utf8'),
                            ie.parent_id.encode('utf8')))
        write_ids(self.new_tree, new_ids, 'file')
        write_ids(self.old_tree, old_ids, 'old file')

    def _write_diffs(self):
        """Write out the specific diffs"""
        from bzrlib.diff import internal_diff, external_diff
        DEVNULL = '/dev/null'

        if self.external_diff_options:
            assert isinstance(self.external_diff_options, basestring)
            opts = self.external_diff_options.split()
            def diff_file(olab, olines, nlab, nlines, to_file):
                external_diff(olab, olines, nlab, nlines, to_file, opts)
        else:
            diff_file = internal_diff

        for path, file_id, kind in self.delta.removed:
            print >>self.to_file, '*** removed %s %r' % (kind, path)
            if kind == 'file' and self.full_remove:
                diff_file(self.old_label + path,
                          self.old_tree.get_file(file_id).readlines(),
                          DEVNULL, 
                          [],
                          self.to_file)
    
        for path, file_id, kind in self.delta.added:
            print >>self.to_file, '*** added %s %r' % (kind, path)
            if kind == 'file':
                diff_file(DEVNULL,
                          [],
                          self.new_label + path,
                          self.new_tree.get_file(file_id).readlines(),
                          self.to_file)
    
        for old_path, new_path, file_id, kind, text_modified in self.delta.renamed:
            print >>self.to_file, '*** renamed %s %r => %r' % (kind, old_path, new_path)
            if self.full_rename and kind == 'file':
                diff_file(self.old_label + old_path,
                          self.old_tree.get_file(file_id).readlines(),
                          DEVNULL, 
                          [],
                          self.to_file)
                diff_file(DEVNULL,
                          [],
                          self.new_label + new_path,
                          self.new_tree.get_file(file_id).readlines(),
                          self.to_file)
            elif text_modified:
                    diff_file(self.old_label + old_path,
                              self.old_tree.get_file(file_id).readlines(),
                              self.new_label + new_path,
                              self.new_tree.get_file(file_id).readlines(),
                              self.to_file)
    
        for path, file_id, kind in self.delta.modified:
            print >>self.to_file, '*** modified %s %r' % (kind, path)
            if kind == 'file':
                diff_file(self.old_label + path,
                          self.old_tree.get_file(file_id).readlines(),
                          self.new_label + path,
                          self.new_tree.get_file(file_id).readlines(),
                          self.to_file)

def show_changeset(branch, revision=None, specific_files=None,
        external_diff_options=None, to_file=None,
        include_full_diff=False):
    from bzrlib.diff import compare_trees

    if to_file is None:
        import sys
        to_file = sys.stdout
    revisions = _canonicalize_revision(branch, revision)

    old_tree, new_tree = _get_trees(branch, revisions)

    delta = compare_trees(old_tree, new_tree, want_unchanged=False,
                          specific_files=specific_files)

    meta = MetaInfoHeader(branch, revisions, delta,
            external_diff_options=external_diff_options,
            old_tree=old_tree, new_tree=new_tree)
    meta.write_meta_info(to_file)


