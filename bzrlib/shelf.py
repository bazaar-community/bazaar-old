# Copyright (C) 2008 Canonical Ltd
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


import errno

from bzrlib import (
    errors,
    merge,
    merge3,
    osutils,
    pack,
    transform,
    ui,
    workingtree
)
from bzrlib.util import bencode


class ShelfCreator(object):

    def __init__(self, work_tree, target_tree, file_list=None):
        self.work_tree = work_tree
        self.work_transform = transform.TreeTransform(work_tree)
        self.target_tree = target_tree
        self.shelf_transform = transform.TransformPreview(self.target_tree)
        self.renames = {}
        self.creation = {}
        self.deletion = {}
        self.iter_changes = work_tree.iter_changes(self.target_tree,
                                                   specific_files=file_list)

    def __iter__(self):
        for (file_id, paths, changed, versioned, parents, names, kind,
             executable) in self.iter_changes:
            if kind[0] is None or versioned[0] == False:
                self.creation[file_id] = (kind[1], names[1], parents[1],
                                          versioned)
                yield ('add file', file_id, kind[1], paths[1])
            elif kind[1] is None or versioned[0] == False:
                self.deletion[file_id] = (kind[0], names[0], parents[0],
                                          versioned)
                yield ('delete file', file_id, kind[0], paths[0])
            else:
                if names[0] != names[1] or parents[0] != parents[1]:
                    self.renames[file_id] = (names, parents)
                    yield ('rename', file_id) + paths

                if kind[0] != kind [1]:
                    yield ('change kind', file_id, kind[0], kind[1], paths[0])
                elif changed:
                    yield ('modify text', file_id)

    def shelve_rename(self, file_id):
        names, parents = self.renames[file_id]
        w_trans_id = self.work_transform.trans_id_file_id(file_id)
        work_parent = self.work_transform.trans_id_file_id(parents[0])
        self.work_transform.adjust_path(names[0], work_parent, w_trans_id)

        s_trans_id = self.shelf_transform.trans_id_file_id(file_id)
        shelf_parent = self.shelf_transform.trans_id_file_id(parents[1])
        self.shelf_transform.adjust_path(names[1], shelf_parent, s_trans_id)

    def shelve_lines(self, file_id, new_lines):
        w_trans_id = self.work_transform.trans_id_file_id(file_id)
        self.work_transform.delete_contents(w_trans_id)
        self.work_transform.create_file(new_lines, w_trans_id)

        s_trans_id = self.shelf_transform.trans_id_file_id(file_id)
        self.shelf_transform.delete_contents(s_trans_id)
        inverse_lines = self._inverse_lines(new_lines, file_id)
        self.shelf_transform.create_file(inverse_lines, s_trans_id)

    @staticmethod
    def _content_from_tree(tt, tree, file_id):
        trans_id = tt.trans_id_file_id(file_id)
        tt.delete_contents(trans_id)
        transform.create_from_tree(tt, trans_id, tree, file_id)

    def shelve_content_change(self, file_id):
        self._content_from_tree(self.work_transform, self.target_tree, file_id)
        self._content_from_tree(self.shelf_transform, self.work_tree, file_id)

    def shelve_creation(self, file_id):
        kind, name, parent, versioned = self.creation[file_id]
        version = not versioned[0]
        self._shelve_creation(self.work_tree, file_id, self.work_transform,
                              self.shelf_transform, kind, name, parent,
                              version)

    def shelve_deletion(self, file_id):
        kind, name, parent, versioned = self.deletion[file_id]
        existing_path = self.target_tree.id2path(file_id)
        if not self.work_tree.has_filename(existing_path):
            existing_path = None
        version = not versioned[1]
        self._shelve_creation(self.target_tree, file_id, self.shelf_transform,
                              self.work_transform, kind, name, parent,
                              version, existing_path=existing_path)

    def _shelve_creation(self, tree, file_id, from_transform, to_transform,
                         kind, name, parent, version, existing_path=None):
        w_trans_id = from_transform.trans_id_file_id(file_id)
        if parent is not None and kind is not None:
            from_transform.delete_contents(w_trans_id)
        from_transform.unversion_file(w_trans_id)

        if existing_path is not None:
            s_trans_id = to_transform.trans_id_tree_path(existing_path)
        else:
            s_trans_id = to_transform.trans_id_file_id(file_id)
        if parent is not None:
            s_parent_id = to_transform.trans_id_file_id(parent)
            to_transform.adjust_path(name, s_parent_id, s_trans_id)
            if existing_path is None:
                if kind is None:
                    to_transform.create_file('', s_trans_id)
                else:
                    transform.create_from_tree(to_transform, s_trans_id,
                                               tree, file_id)
        if version:
            to_transform.version_file(file_id, s_trans_id)

    def read_tree_lines(self, tree, file_id):
        return osutils.split_lines(tree.get_file_text(file_id))

    def _inverse_lines(self, new_lines, file_id):
        """Produce a version with only those changes removed from new_lines."""
        target_lines = self.target_tree.get_file_lines(file_id)
        work_lines = self.read_tree_lines(self.work_tree, file_id)
        return merge3.Merge3(new_lines, target_lines, work_lines).merge_lines()

    def finalize(self):
        self.work_transform.finalize()
        self.shelf_transform.finalize()

    def transform(self):
        self.work_transform.apply()

    def write_shelf(self, shelf_file, message=None):
        transform.resolve_conflicts(self.shelf_transform)
        serializer = pack.ContainerSerialiser()
        shelf_file.write(serializer.begin())
        metadata = {
            'revision_id': self.target_tree.get_revision_id(),
        }
        if message is not None:
            metadata['message'] = message.encode('utf-8')
        shelf_file.write(serializer.bytes_record(
            bencode.bencode(metadata), (('metadata',),)))
        for bytes in self.shelf_transform.serialize(serializer):
            shelf_file.write(bytes)
        shelf_file.write(serializer.end())


class Unshelver(object):

    def __init__(self, tree, base_tree, transform, message):
        self.tree = tree
        self.base_tree = base_tree
        self.transform = transform
        self.message = message

    @classmethod
    def from_tree_and_shelf(klass, tree, shelf_file):
        parser = pack.ContainerPushParser()
        parser.accept_bytes(shelf_file.read())
        records = iter(parser.read_pending_records())
        names, metadata_bytes = records.next()
        assert names[0] == ('metadata',)
        metadata = bencode.bdecode(metadata_bytes)
        base_revision_id = metadata['revision_id']
        message = metadata.get('message')
        if message is not None:
            message = message.decode('utf-8')
        try:
            base_tree = tree.revision_tree(base_revision_id)
        except errors.NoSuchRevisionInTree:
            base_tree = tree.branch.repository.revision_tree(base_revision_id)
        tt = transform.TransformPreview(base_tree)
        tt.deserialize(records)
        return klass(tree, base_tree, tt, message)

    def unshelve(self, change_reporter=None):
        pb = ui.ui_factory.nested_progress_bar()
        try:
            merger = self.get_merger()
            merger.change_reporter = change_reporter
            merger.do_merge()
        finally:
            pb.finished()

    def get_merger(self):
        pb = ui.ui_factory.nested_progress_bar()
        try:
            target_tree = self.transform.get_preview_tree()
            merger = merge.Merger.from_uncommitted(self.tree, target_tree, pb,
                                                   self.base_tree)
            merger.merge_type = merge.Merge3Merger
            return merger
        finally:
            pb.finished()

    def finalize(self):
        self.transform.finalize()


class NoSuchShelfId(errors.BzrError):

    _fmt = 'No changes are shelved with id "%(shelf_id)d".'

    def __init__(self, shelf_id):
        errors.BzrError.__init__(self, shelf_id=shelf_id)

class ShelfManager(object):

    def __init__(self, tree, transport):
        self.tree = tree
        self.transport = transport.clone('shelf')
        self.transport.ensure_base()

    def new_shelf(self):
        last_shelf = self.last_shelf()
        if last_shelf is None:
            next_shelf = 1
        else:
            next_shelf = last_shelf + 1
        shelf_file = open(self.transport.local_abspath(str(next_shelf)), 'wb')
        return next_shelf, shelf_file

    def shelve_changes(self, creator, message=None):
        next_shelf, shelf_file = self.new_shelf()
        try:
            creator.write_shelf(shelf_file, message)
        finally:
            shelf_file.close()
        creator.transform()
        return next_shelf

    def read_shelf(self, shelf_id):
        try:
            return open(self.transport.local_abspath(str(shelf_id)), 'rb')
        except IOError, e:
            if e.errno != errno.ENOENT:
                raise
            raise NoSuchShelfId(shelf_id)

    def get_unshelver(self, shelf_id):
        shelf_file = self.read_shelf(shelf_id)
        try:
            return Unshelver.from_tree_and_shelf(self.tree, shelf_file)
        finally:
            shelf_file.close()

    def delete_shelf(self, shelf_id):
        self.transport.delete(str(shelf_id))

    def active_shelves(self):
        return [int(f) for f in self.transport.list_dir('.')]

    def last_shelf(self):
        active = self.active_shelves()
        if len(active) > 0:
            return max(active)
        else:
            return None


def get_shelf_manager(self):
    return ShelfManager(self, self._transport)


workingtree.WorkingTree.get_shelf_manager = get_shelf_manager
