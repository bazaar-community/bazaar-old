#!/usr/bin/env python
"""\
Just some work for generating a changeset.
"""

import bzrlib, bzrlib.errors

import common

from bzrlib.inventory import ROOT_ID
from bzrlib.errors import BzrCommandError

try:
    set
except NameError:
    from sets import Set as set

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
        raise BzrCommandError('Cannot form a bzr changeset with no committed revisions')
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
        self.old_label = old_label
        self.new_label = new_label
        self.old_tree = old_tree
        self.new_tree = new_tree
        self.to_file = None
        #self.revno = None
        #self.parent_revno = None

        # These are entries in the header.
        # They will be repeated in the footer,
        # only if they have changed
        self.date = None
        self.committer = None
        self.message = None

        self._get_revision_list(revisions)

    def _get_revision_list(self, revisions):
        """This generates the list of all revisions from->to.

        This is for having a rollup changeset.
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
        #self.parent_revno = old_revno+1
        #self.revno = new_revno+1

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
        from bzrlib.osutils import username
        from common import format_highres_date
        write = self._write

        for line in common.get_header():
            write(line)

        # Print out the basic information about the 'target' revision
        rev = self.revision_list[-1]
        write(rev.committer, key='committer')
        self.committer = rev.committer
        self.date = format_highres_date(rev.timestamp, offset=rev.timezone)
        write(self.date, key='date')
        if rev.message:
            self.to_file.write('# message:\n')
            for line in rev.message.split('\n'):
                self.to_file.write('#    %s\n' % line)
            self.message = rev.message

        write('')
        self.to_file.write('\n')

    def _write_footer(self):
        """Write the stuff that comes after the patches.

        This is meant to be more meta-information, which people probably don't want
        to read, but which is required for proper bzr operation.
        """
        write = self._write

        # What should we print out for an Empty base revision?
        if len(self.revision_list[0].parents) == 0:
            assumed_base = None
        else:
            assumed_base = self.revision_list[0].parents[0].revision_id
        if (self.base_revision is not None 
                and self.base_revision.revision_id != assumed_base):
            base = self.base_revision.revision_id
            write(base, key='base')
            write(self.branch.get_revision_sha1(base), key='base sha1')

        self._write_revisions()

        #self._write_ids()
        self._write_text_ids()

    def _write_revisions(self):
        """Not used. Used for writing multiple revisions."""
        from common import format_highres_date

        for rev in self.revision_list:
            rev_id = rev.revision_id
            self.to_file.write('# revision: %s\n' % rev_id)
            self.to_file.write('#    sha1: %s\n' % 
                self.branch.get_revision_sha1(rev_id))
            if rev.committer != self.committer:
                self.to_file.write('#    committer: %s\n' % rev.committer)
            date = format_highres_date(rev.timestamp, rev.timezone)
            if date != self.date:
                self.to_file.write('#    date: %s\n' % date)
            if rev.inventory_id != rev_id:
                self.to_file.write('#    inventory id: %s\n' % rev.inventory_id)
            self.to_file.write('#    inventory sha1: %s\n' % rev.inventory_sha1)
            if len(rev.parents) > 0:
                self.to_file.write('#    parents:\n')
                for parent in rev.parents:
                    self.to_file.write('#       %s\t%s\n' % (
                        parent.revision_id,
                        parent.revision_sha1))
            if rev.message and rev.message != self.message:
                self.to_file.write('#    message:\n')
                for line in rev.message.split('\n'):
                    self.to_file.write('#       %s\n' % line)


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
                        % (path, file_id,
                            ie.parent_id))
        write_ids(self.new_tree, new_ids, 'file')
        write_ids(self.old_tree, old_ids, 'old file')

    def _write_text_ids(self):
        pass

    def _write_diffs(self):
        """Write out the specific diffs"""
        from bzrlib.diff import internal_diff, external_diff
        from common import encode
        DEVNULL = '/dev/null'

        diff_file = internal_diff
        # Get the target tree so that we can check for
        # Appropriate text ids.
        rev_id = self.revision_list[-1].revision_id
        tree = self.branch.revision_tree(rev_id)


        def get_text_id_str(file_id, modified=True):
            """This returns an empty string if guess_text_id == real_text_id.
            Otherwise it returns a string suitable for printing, indicating
            the file's id.
            """
            guess_id = common.guess_text_id(tree, file_id, rev_id,
                    modified=modified)
            real_id = tree.inventory[file_id].text_id
            if guess_id != real_id:
                return '\ttext-id:' + encode(real_id)
            else:
                return ''


        for path, file_id, kind in self.delta.removed:
            # We don't care about text ids for removed files
            print >>self.to_file, '*** removed %s %s' % (kind,
                    encode(path))
            if kind == 'file' and self.full_remove:
                diff_file(self.old_label + path,
                          self.old_tree.get_file(file_id).readlines(),
                          DEVNULL, 
                          [],
                          self.to_file)
    
        for path, file_id, kind in self.delta.added:
            print >>self.to_file, '*** added %s %s\tfile-id:%s%s' % (kind,
                    encode(path),
                    encode(file_id),
                    get_text_id_str(file_id))
            if kind == 'file':
                diff_file(DEVNULL,
                          [],
                          self.new_label + path,
                          self.new_tree.get_file(file_id).readlines(),
                          self.to_file)
    
        for old_path, new_path, file_id, kind, text_modified in self.delta.renamed:
            print >>self.to_file, '*** renamed %s %s\t=> %s%s' % (kind,
                    encode(old_path), encode(new_path),
                    get_text_id_str(file_id, text_modified))
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
            print >>self.to_file, '*** modified %s %s%s' % (kind,
                    encode(path), get_text_id_str(file_id))
            if kind == 'file':
                diff_file(self.old_label + path,
                          self.old_tree.get_file(file_id).readlines(),
                          self.new_label + path,
                          self.new_tree.get_file(file_id).readlines(),
                          self.to_file)

def show_changeset(branch, revisions=None, to_file=None, include_full_diff=False):
    from bzrlib.diff import compare_trees

    if to_file is None:
        import sys
        to_file = sys.stdout
    revisions = common.canonicalize_revision(branch, revisions)

    old_tree, new_tree = _get_trees(branch, revisions)

    delta = compare_trees(old_tree, new_tree, want_unchanged=False)

    meta = MetaInfoHeader(branch, revisions, delta,
            old_tree=old_tree, new_tree=new_tree)
    meta.write_meta_info(to_file)

