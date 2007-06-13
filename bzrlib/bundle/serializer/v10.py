from bzrlib import (
    multiparent,
    pack,
    timestamp,
    )
from bzrlib.bundle import bundle_data, serializer


class ContainerWriter(pack.ContainerWriter):

    def add_multiparent_record(self, names, mp_bytes):
        self.add_bytes_record(names, mp_bytes)


class BundleSerializerV10(serializer.BundleSerializer):

    def write(self, repository, revision_ids, forced_bases, fileobj):
        fileobj.write(serializer._get_bundle_header('1.0'))
        fileobj.write('#\n')
        container = ContainerWriter(fileobj.write)
        container.begin()
        transaction = repository.get_transaction()
        altered = repository.fileids_altered_by_revision_ids(revision_ids)
        for file_id, file_revision_ids in altered.iteritems():
            vf = repository.weave_store.get_weave(file_id, transaction)
            file_revision_ids = [r for r in revision_ids if r in
                                 file_revision_ids]
            for file_revision_id in file_revision_ids:
                parents = vf.get_parents(file_revision_id)
                text = ''.join(vf.make_mpdiff(file_revision_id).to_patch())
                container_name = self.encode_name('file', file_revision_id,
                                                  file_id)
                self.add_record(container.add_multiparent_record,
                                container_name, parents, text)
        for revision_id in revision_ids:
            parents = repository.revision_parents(revision_id)
            container_name = self.encode_name('inventory', revision_id)
            inventory_text = repository.get_inventory_xml(revision_id)
            self.add_record(container.add_bytes_record, container_name,
                            parents, inventory_text)
        for revision_id in revision_ids:
            parents = repository.revision_parents(revision_id)
            container_name = self.encode_name('revision', revision_id)
            revision_text = repository.get_revision_xml(revision_id)
            self.add_record(container.add_bytes_record, container_name,
                            parents, revision_text)
        container.end()

    def add_record(self, add_method, name, parents, text):
        parents = self.encode_parents(parents)
        text = parents + text
        add_method(text, [name])

    def encode_parents(self, parents):
        return ' '.join(parents) + '\n'

    def decode_parents(self, parents_line):
        parents = parents_line.rstrip('\n').split(' ')
        if parents == ['']:
            parents = []
        return parents

    def read(self, file):
        container = BundleInfoV10(file, self)
        return container

    @staticmethod
    def encode_name(name_kind, revision_id, file_id=None):
        assert name_kind in ('revision', 'file', 'inventory')
        if name_kind in ('revision', 'inventory'):
            assert file_id is None
        else:
            assert file_id is not None
        if file_id is not None:
            file_tail = '/' + file_id
        else:
            file_tail = ''
        return name_kind + ':' + revision_id + file_tail

    @staticmethod
    def decode_name(name):
        kind, revisionfile_id = name.split(':', 1)
        revisionfile_id = revisionfile_id.split('/')
        if len(revisionfile_id) == 1:
            revision_id = revisionfile_id[0]
            file_id = None
        else:
            revision_id, file_id = revisionfile_id
        return kind, revision_id, file_id


class BundleInfoV10(object):

    def __init__(self, fileobj, serializer):
        self._fileobj = fileobj
        self._serializer = serializer
        self.__real_revisions = None
        self.__revisions = None

    def install(self, repository):
        return self.install_revisions(repository)

    def install_revisions(self, repository):
        ri = RevisionInstaller(self._fileobj, self._serializer, repository)
        return ri.install()

    def _get_real_revisions(self):
        from bzrlib import xml7
        self._fileobj.seek(0)
        if self.__real_revisions is None:
            self.__real_revisions = []
            line = self._fileobj.readline()
            if line != '\n':
                line = self._fileobj.readline()
            container = pack.ContainerReader(self._fileobj.read)
            for (name,), bytes in container.iter_records():
                kind, revision_id, file_id = self._serializer.decode_name(name)
                if kind == 'revision':
                    rev = xml7.serializer_v7.read_revision_from_string(bytes)
                    self.__real_revisions.append(rev)
        return self.__real_revisions
    real_revisions = property(_get_real_revisions)

    def _get_revisions(self):
        if self.__revisions is None:
            self.__revisions = []
            for revision in self.real_revisions:
                self.__revisions.append(bundle_data.RevisionInfo(
                    revision.revision_id))
                date = timestamp.format_highres_date(revision.timestamp,
                                                     revision.timezone)
                self.__revisions[-1].date = date
                self.__revisions[-1].timezone = revision.timezone
                self.__revisions[-1].timestamp = revision.timestamp
        return self.__revisions

    revisions = property(_get_revisions)


class RevisionInstaller(object):

    def __init__(self, fileobj, serializer, repository):
        fileobj.seek(0)
        line = fileobj.readline()
        if line != '\n':
            fileobj.readline()
        self._container = pack.ContainerReader(fileobj.read)
        self._serializer = serializer
        self._repository = repository

    def install(self):
        current_file = None
        current_versionedfile = None
        pending_file_records = []
        added_inv = set()
        target_revision = None
        for names, bytes in self._container.iter_records():
            assert len(names) == 1, repr(names)
            (name,) = names
            kind, revision_id, file_id = self._serializer.decode_name(name)
            if  kind != 'file':
                self._install_file_records(current_versionedfile,
                    pending_file_records)
                current_file = None
                current_versionedfile = None
                pending_file_records = []
                if kind == 'inventory':
                    self._install_inventory(revision_id, bytes, added_inv)
                    added_inv.add(revision_id)
                if kind == 'revision':
                    if target_revision is None:
                        target_revision = revision_id
                    self._install_revision(revision_id, bytes)
            if kind == 'file':
                if file_id != current_file:
                    self._install_file_records(current_versionedfile,
                        pending_file_records)
                    current_file = file_id
                    current_versionedfile = \
                        self._repository.weave_store.get_weave_or_empty(
                        file_id, self._repository.get_transaction())
                    pending_file_records = []
                if revision_id in current_versionedfile:
                    continue
                pending_file_records.append((revision_id, bytes))
        self._install_file_records(current_versionedfile, pending_file_records)
        return target_revision

    def _install_file_records(self, current_versionedfile,
                              pending_file_records):
        for revision, text in pending_file_records:
            mpdiff_text = text.splitlines(True)
            parents, mpdiff_text = mpdiff_text[0], mpdiff_text[1:]
            parents = self._serializer.decode_parents(parents)
            mpdiff = multiparent.MultiParent.from_patch(mpdiff_text)
            current_versionedfile.add_mpdiff(revision, parents, mpdiff)

    def _install_inventory(self, revision_id, text, added):
        if self._repository.has_revision(revision_id):
            return
        lines = text.splitlines(True)
        parents = self._serializer.decode_parents(lines[0])
        present_parents = [p for p in parents if
            (p in added or self._repository.has_revision(p))]
        text = ''.join(lines[1:])
        inv = self._repository.deserialise_inventory(revision_id, text)
        self._repository.add_inventory(revision_id, inv, present_parents)

    def _install_revision(self, revision_id, text):
        if self._repository.has_revision(revision_id):
            return
        lines = text.splitlines(True)
        parents = self._serializer.decode_parents(lines[0])
        text = ''.join(lines[1:])
        self._repository._add_revision_text(revision_id, text)
