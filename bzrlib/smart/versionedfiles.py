# Copyright (C) 2008 Canonical Ltd
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

"""Server-side versioned files related request implmentations."""

import bz2
from cStringIO import StringIO

from bzrlib import (
    errors,
    graph,
    versionedfile,
    )
from bzrlib.bzrdir import BzrDir
from bzrlib.smart.request import (
    FailedSmartServerResponse,
    SmartServerRequest,
    SuccessfulSmartServerResponse,
    )
from bzrlib.smart.repository import SmartServerRepositoryRequest
from bzrlib.repository import _strip_NULL_ghosts
from bzrlib.util import bencode
from bzrlib import revision as _mod_revision


class SmartServerVersionedFilesRequest(SmartServerRepositoryRequest):
    """Common base class for Repository requests."""

    def do(self, path, *args):
        """Execute a repository request.
        
        All Repository requests take a path to the repository as their first
        argument.  The repository must be at the exact path given by the
        client - no searching is done.

        The actual logic is delegated to self.do_repository_request.

        :param client_path: The path for the repository as received from the
            client.
        :return: A SmartServerResponse from self.do_repository_request().
        """
        transport = self.transport_from_client_path(path)
        bzrdir = BzrDir.open_from_transport(transport)
        # Save the repository for use with do_body.
        self._repository = bzrdir.open_repository()
        return self.do_repository_request(self._repository, *args)

    def do_repository_request(self, repository, vf_name, *args):
        if vf_name not in ['texts', 'inventories', 'signatures', 'revisions']:
            return FailedSmartServerResponse(('NoSuchVersionedFile', vf_name))
        versioned_files = getattr(repository, vf_name)
        return self.do_versioned_files_request(versioned_files, *args)

    def do_versioned_files_request(self, versioned_files, *args):
        """Override to provide an implementation for a verb."""


class SmartServerVersionedFilesGetParentMap(SmartServerVersionedFilesRequest):
    """Bzr 1.2+ - get parent data for revisions during a graph search."""
    
    def do_versioned_files_request(self, versioned_files, *keys):
        """Get parent details for some revisions.
        
        All the parents for revision_ids are returned. Additionally up to 64KB
        of additional parent data found by performing a breadth first search
        from revision_ids is returned. The verb takes a body containing the
        current search state, see do_body for details.

        :param repository: The repository to query in.
        :param revision_ids: The utf8 encoded revision_id to answer for.
        """
        self._keys = keys
        self._versioned_files = versioned_files
        return None # Signal that we want a body.

    def do_body(self, body_bytes):
        """Process the current search state and perform the parent lookup.

        :return: A smart server response where the body contains an utf8
            encoded flattened list of the parents of the keys which has been
            bz2 compressed.
        """
        repository = self._repository
        repository.lock_read()
        try:
            vf_graph = graph.Graph(self._versioned_files)
            return self._do_repository_request(body_bytes, vf_graph)
        finally:
            repository.unlock()

    def _deserialise_search_tuple_key_recipe(self, bytes):
        start_keys_bytes, stop_keys_bytes, count_bytes = bytes.split('\n')
        start_keys = [tuple(k.split(' ')) for k in start_keys_bytes.split('\0')]
        stop_keys = [tuple(k.split(' ')) for k in stop_keys_bytes.split('\0')]
        count = int(count_bytes)
        return tuple(start_keys), set(stop_keys), count

    def recreate_vf_search(self, vf_graph, recipe_bytes):
        recipe = self._deserialise_search_tuple_key_recipe(recipe_bytes)
        start_keys, exclude_keys, key_count = recipe
        # lock_read
        try:
            search = vf_graph._make_breadth_first_searcher(start_keys)
            while True:
                try:
                    next_revs = search.next()
                except StopIteration:
                    break
                search.stop_searching_any(exclude_keys.intersection(next_revs))
            search_result = search.get_result()
            if search_result.get_recipe()[2] != key_count:
                # we got back a different amount of data than expected, this
                # gets reported as NoSuchRevision, because less revisions
                # indicates missing revisions, and more should never happen as
                # the excludes list considers ghosts and ensures that ghost
                # filling races are not a problem.
                return (None, FailedSmartServerResponse(('NoSuchRevision',)))
            return (search, None)
        finally:
            pass
            # unlock
            
    def _do_repository_request(self, body_bytes, vf_graph):
        repository = self._repository
        keys = set(self._keys)
        search, error = self.recreate_vf_search(vf_graph, body_bytes)
        if error is not None:
            return error
        # TODO might be nice to start up the search again; but thats not
        # written or tested yet.
        client_seen_keys = set(search.get_result().get_keys())
        # Always include the requested ids.
        client_seen_keys.difference_update(keys)
        lines = []
        result = {}
        queried_keys = set()
        size_so_far = 0
        next_keys = keys
        first_loop_done = False
        while next_keys:
            queried_keys.update(next_keys)
            parent_map = vf_graph.get_parent_map(next_keys)
            next_keys = set()
            for key, parents in parent_map.iteritems():
                # prepare the next query
                next_keys.update(parents)
                if key not in client_seen_keys:
                    # Client does not have this revision, give it to it.
                    # add parents to the result
                    result[key] = parents
                    # Approximate the serialized cost of this key.
                    # XXX: this approximation is out of date
                    size_so_far += 2 + len(key) + sum(map(len, parents))
            # get all the directly asked for parents, and then flesh out to
            # 64K (compressed) or so. We do one level of depth at a time to
            # stay in sync with the client. The 250000 magic number is
            # estimated compression ratio taken from bzr.dev itself.
            if first_loop_done and size_so_far > 250000:
                next_keys = set()
                break
            # don't query things we've already queried
            next_keys.difference_update(queried_keys)
            first_loop_done = True

        # sorting trivially puts lexographically similar revision ids together.
        # Compression FTW.
        result = sorted(result.items())

        return SuccessfulSmartServerResponse(
            ('ok', ), bz2.compress(_serialise_search_result(result)))


def _serialise_search_result(result_items):
    buf = StringIO()
    first = True
    for key, parents in result_items:
        if first:
            first = False
        else:
            buf.write('\n')
        buf.write(' '.join(key))
        buf.write('\0')
        parents_iter = (' '.join(parent) for parent in parents)
        buf.write('\0'.join(parents_iter))
    return buf.getvalue()


class SmartServerVersionedFilesInsertRecordStream(SmartServerVersionedFilesRequest):

    def do_versioned_files_request(self, versioned_files, *args):
        self._repository.lock_write()
        self._repository.start_write_group()
        self.versioned_files = versioned_files

    def do_chunk(self, stream_chunk):
        record = deserialise_record(stream_chunk)
        self.versioned_files.insert_record_stream([record])
    
    def do_end(self):
        self._repository.commit_write_group()
        self._repository.unlock()
        return SuccessfulSmartServerResponse(('ok',))


from bzrlib.knit import KnitContentFactory

def deserialise_record(stream_chunk):
    struct = bencode.bdecode(stream_chunk)

    (sha1, storage_kind, key, parents, build_details, bytes) = struct
    if parents == 'nil':
        parents = None
    if sha1 == '':
        sha1 = None
    if storage_kind.startswith('knit-'):
        annotated = bool(storage_kind.startswith('knit-annotated-'))
        record = KnitContentFactory(key, parents, build_details, sha1, bytes,
            annotated)
        if record.storage_kind != storage_kind:
            raise AssertionError(
                'Reconstructed record kind %r does not match expected kind %r'
                % (record.storage_kind, storage_kind))
    elif storage_kind == 'fulltext':
        record = versionedfile.FulltextContentFactory(
            key, parents, sha1, bytes)
    return record

