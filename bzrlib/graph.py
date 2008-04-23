# Copyright (C) 2007 Canonical Ltd
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

from bzrlib import (
    errors,
    revision,
    symbol_versioning,
    trace,
    tsort,
    )
from bzrlib.deprecated_graph import (node_distances, select_farthest)

# DIAGRAM of terminology
#       A
#       /\
#      B  C
#      |  |\
#      D  E F
#      |\/| |
#      |/\|/
#      G  H
#
# In this diagram, relative to G and H:
# A, B, C, D, E are common ancestors.
# C, D and E are border ancestors, because each has a non-common descendant.
# D and E are least common ancestors because none of their descendants are
# common ancestors.
# C is not a least common ancestor because its descendant, E, is a common
# ancestor.
#
# The find_unique_lca algorithm will pick A in two steps:
# 1. find_lca('G', 'H') => ['D', 'E']
# 2. Since len(['D', 'E']) > 1, find_lca('D', 'E') => ['A']


class DictParentsProvider(object):
    """A parents provider for Graph objects."""

    def __init__(self, ancestry):
        self.ancestry = ancestry

    def __repr__(self):
        return 'DictParentsProvider(%r)' % self.ancestry

    def get_parent_map(self, keys):
        """See _StackedParentsProvider.get_parent_map"""
        ancestry = self.ancestry
        return dict((k, ancestry[k]) for k in keys if k in ancestry)


class _StackedParentsProvider(object):

    def __init__(self, parent_providers):
        self._parent_providers = parent_providers

    def __repr__(self):
        return "_StackedParentsProvider(%r)" % self._parent_providers

    def get_parent_map(self, keys):
        """Get a mapping of keys => parents

        A dictionary is returned with an entry for each key present in this
        source. If this source doesn't have information about a key, it should
        not include an entry.

        [NULL_REVISION] is used as the parent of the first user-committed
        revision.  Its parent list is empty.

        :param keys: An iterable returning keys to check (eg revision_ids)
        :return: A dictionary mapping each key to its parents
        """
        found = {}
        remaining = set(keys)
        for parents_provider in self._parent_providers:
            new_found = parents_provider.get_parent_map(remaining)
            found.update(new_found)
            remaining.difference_update(new_found)
            if not remaining:
                break
        return found


class CachingParentsProvider(object):
    """A parents provider which will cache the revision => parents in a dict.

    This is useful for providers that have an expensive lookup.
    """

    def __init__(self, parent_provider):
        self._real_provider = parent_provider
        # Theoretically we could use an LRUCache here
        self._cache = {}

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self._real_provider)

    def get_parent_map(self, keys):
        """See _StackedParentsProvider.get_parent_map"""
        needed = set()
        # If the _real_provider doesn't have a key, we cache a value of None,
        # which we then later use to realize we cannot provide a value for that
        # key.
        parent_map = {}
        cache = self._cache
        for key in keys:
            if key in cache:
                value = cache[key]
                if value is not None:
                    parent_map[key] = value
            else:
                needed.add(key)

        if needed:
            new_parents = self._real_provider.get_parent_map(needed)
            cache.update(new_parents)
            parent_map.update(new_parents)
            needed.difference_update(new_parents)
            cache.update(dict.fromkeys(needed, None))
        return parent_map


class Graph(object):
    """Provide incremental access to revision graphs.

    This is the generic implementation; it is intended to be subclassed to
    specialize it for other repository types.
    """

    def __init__(self, parents_provider):
        """Construct a Graph that uses several graphs as its input

        This should not normally be invoked directly, because there may be
        specialized implementations for particular repository types.  See
        Repository.get_graph().

        :param parents_provider: An object providing a get_parent_map call
            conforming to the behavior of
            StackedParentsProvider.get_parent_map.
        """
        if getattr(parents_provider, 'get_parents', None) is not None:
            self.get_parents = parents_provider.get_parents
        if getattr(parents_provider, 'get_parent_map', None) is not None:
            self.get_parent_map = parents_provider.get_parent_map
        self._parents_provider = parents_provider

    def __repr__(self):
        return 'Graph(%r)' % self._parents_provider

    def find_lca(self, *revisions):
        """Determine the lowest common ancestors of the provided revisions

        A lowest common ancestor is a common ancestor none of whose
        descendants are common ancestors.  In graphs, unlike trees, there may
        be multiple lowest common ancestors.

        This algorithm has two phases.  Phase 1 identifies border ancestors,
        and phase 2 filters border ancestors to determine lowest common
        ancestors.

        In phase 1, border ancestors are identified, using a breadth-first
        search starting at the bottom of the graph.  Searches are stopped
        whenever a node or one of its descendants is determined to be common

        In phase 2, the border ancestors are filtered to find the least
        common ancestors.  This is done by searching the ancestries of each
        border ancestor.

        Phase 2 is perfomed on the principle that a border ancestor that is
        not an ancestor of any other border ancestor is a least common
        ancestor.

        Searches are stopped when they find a node that is determined to be a
        common ancestor of all border ancestors, because this shows that it
        cannot be a descendant of any border ancestor.

        The scaling of this operation should be proportional to
        1. The number of uncommon ancestors
        2. The number of border ancestors
        3. The length of the shortest path between a border ancestor and an
           ancestor of all border ancestors.
        """
        border_common, common, sides = self._find_border_ancestors(revisions)
        # We may have common ancestors that can be reached from each other.
        # - ask for the heads of them to filter it down to only ones that
        # cannot be reached from each other - phase 2.
        return self.heads(border_common)

    def find_difference(self, left_revision, right_revision):
        """Determine the graph difference between two revisions"""
        border, common, searchers = self._find_border_ancestors(
            [left_revision, right_revision])
        self._search_for_extra_common(common, searchers)
        left = searchers[0].seen
        right = searchers[1].seen
        return (left.difference(right), right.difference(left))

    @symbol_versioning.deprecated_method(symbol_versioning.one_one)
    def get_parents(self, revisions):
        """Find revision ids of the parents of a list of revisions

        A list is returned of the same length as the input.  Each entry
        is a list of parent ids for the corresponding input revision.

        [NULL_REVISION] is used as the parent of the first user-committed
        revision.  Its parent list is empty.

        If the revision is not present (i.e. a ghost), None is used in place
        of the list of parents.

        Deprecated in bzr 1.2 - please see get_parent_map.
        """
        parents = self.get_parent_map(revisions)
        return [parents.get(r, None) for r in revisions]

    def get_parent_map(self, revisions):
        """Get a map of key:parent_list for revisions.

        This implementation delegates to get_parents, for old parent_providers
        that do not supply get_parent_map.
        """
        result = {}
        for rev, parents in self.get_parents(revisions):
            if parents is not None:
                result[rev] = parents
        return result

    def _make_breadth_first_searcher(self, revisions):
        return _BreadthFirstSearcher(revisions, self)

    def _find_border_ancestors(self, revisions):
        """Find common ancestors with at least one uncommon descendant.

        Border ancestors are identified using a breadth-first
        search starting at the bottom of the graph.  Searches are stopped
        whenever a node or one of its descendants is determined to be common.

        This will scale with the number of uncommon ancestors.

        As well as the border ancestors, a set of seen common ancestors and a
        list of sets of seen ancestors for each input revision is returned.
        This allows calculation of graph difference from the results of this
        operation.
        """
        if None in revisions:
            raise errors.InvalidRevisionId(None, self)
        common_ancestors = set()
        searchers = [self._make_breadth_first_searcher([r])
                     for r in revisions]
        active_searchers = searchers[:]
        border_ancestors = set()

        while True:
            newly_seen = set()
            for searcher in searchers:
                new_ancestors = searcher.step()
                if new_ancestors:
                    newly_seen.update(new_ancestors)
            new_common = set()
            for revision in newly_seen:
                if revision in common_ancestors:
                    # Not a border ancestor because it was seen as common
                    # already
                    new_common.add(revision)
                    continue
                for searcher in searchers:
                    if revision not in searcher.seen:
                        break
                else:
                    # This is a border because it is a first common that we see
                    # after walking for a while.
                    border_ancestors.add(revision)
                    new_common.add(revision)
            if new_common:
                for searcher in searchers:
                    new_common.update(searcher.find_seen_ancestors(new_common))
                for searcher in searchers:
                    searcher.start_searching(new_common)
                common_ancestors.update(new_common)

            # Figure out what the searchers will be searching next, and if
            # there is only 1 set being searched, then we are done searching,
            # since all searchers would have to be searching the same data,
            # thus it *must* be in common.
            unique_search_sets = set()
            for searcher in searchers:
                will_search_set = frozenset(searcher._next_query)
                if will_search_set not in unique_search_sets:
                    # This searcher is searching a unique set of nodes, let it
                    unique_search_sets.add(will_search_set)

            if len(unique_search_sets) == 1:
                nodes = unique_search_sets.pop()
                uncommon_nodes = nodes.difference(common_ancestors)
                assert not uncommon_nodes, ("Somehow we ended up converging"
                                            " without actually marking them as"
                                            " in common."
                                            "\nStart_nodes: %s"
                                            "\nuncommon_nodes: %s"
                                            % (revisions, uncommon_nodes))
                break
        return border_ancestors, common_ancestors, searchers

    def heads(self, keys):
        """Return the heads from amongst keys.

        This is done by searching the ancestries of each key.  Any key that is
        reachable from another key is not returned; all the others are.

        This operation scales with the relative depth between any two keys. If
        any two keys are completely disconnected all ancestry of both sides
        will be retrieved.

        :param keys: An iterable of keys.
        :return: A set of the heads. Note that as a set there is no ordering
            information. Callers will need to filter their input to create
            order if they need it.
        """
        candidate_heads = set(keys)
        if revision.NULL_REVISION in candidate_heads:
            # NULL_REVISION is only a head if it is the only entry
            candidate_heads.remove(revision.NULL_REVISION)
            if not candidate_heads:
                return set([revision.NULL_REVISION])
        if len(candidate_heads) < 2:
            return candidate_heads
        searchers = dict((c, self._make_breadth_first_searcher([c]))
                          for c in candidate_heads)
        active_searchers = dict(searchers)
        # skip over the actual candidate for each searcher
        for searcher in active_searchers.itervalues():
            searcher.next()
        # The common walker finds nodes that are common to two or more of the
        # input keys, so that we don't access all history when a currently
        # uncommon search point actually meets up with something behind a
        # common search point. Common search points do not keep searches
        # active; they just allow us to make searches inactive without
        # accessing all history.
        common_walker = self._make_breadth_first_searcher([])
        while len(active_searchers) > 0:
            ancestors = set()
            # advance searches
            try:
                common_walker.next()
            except StopIteration:
                # No common points being searched at this time.
                pass
            for candidate in active_searchers.keys():
                try:
                    searcher = active_searchers[candidate]
                except KeyError:
                    # rare case: we deleted candidate in a previous iteration
                    # through this for loop, because it was determined to be
                    # a descendant of another candidate.
                    continue
                try:
                    ancestors.update(searcher.next())
                except StopIteration:
                    del active_searchers[candidate]
                    continue
            # process found nodes
            new_common = set()
            for ancestor in ancestors:
                if ancestor in candidate_heads:
                    candidate_heads.remove(ancestor)
                    del searchers[ancestor]
                    if ancestor in active_searchers:
                        del active_searchers[ancestor]
                # it may meet up with a known common node
                if ancestor in common_walker.seen:
                    # some searcher has encountered our known common nodes:
                    # just stop it
                    ancestor_set = set([ancestor])
                    for searcher in searchers.itervalues():
                        searcher.stop_searching_any(ancestor_set)
                else:
                    # or it may have been just reached by all the searchers:
                    for searcher in searchers.itervalues():
                        if ancestor not in searcher.seen:
                            break
                    else:
                        # The final active searcher has just reached this node,
                        # making it be known as a descendant of all candidates,
                        # so we can stop searching it, and any seen ancestors
                        new_common.add(ancestor)
                        for searcher in searchers.itervalues():
                            seen_ancestors =\
                                searcher.find_seen_ancestors([ancestor])
                            searcher.stop_searching_any(seen_ancestors)
            common_walker.start_searching(new_common)
        return candidate_heads

    def find_unique_lca(self, left_revision, right_revision,
                        count_steps=False):
        """Find a unique LCA.

        Find lowest common ancestors.  If there is no unique  common
        ancestor, find the lowest common ancestors of those ancestors.

        Iteration stops when a unique lowest common ancestor is found.
        The graph origin is necessarily a unique lowest common ancestor.

        Note that None is not an acceptable substitute for NULL_REVISION.
        in the input for this method.

        :param count_steps: If True, the return value will be a tuple of
            (unique_lca, steps) where steps is the number of times that
            find_lca was run.  If False, only unique_lca is returned.
        """
        revisions = [left_revision, right_revision]
        steps = 0
        while True:
            steps += 1
            lca = self.find_lca(*revisions)
            if len(lca) == 1:
                result = lca.pop()
                if count_steps:
                    return result, steps
                else:
                    return result
            if len(lca) == 0:
                raise errors.NoCommonAncestor(left_revision, right_revision)
            revisions = lca

    def iter_ancestry(self, revision_ids):
        """Iterate the ancestry of this revision.

        :param revision_ids: Nodes to start the search
        :return: Yield tuples mapping a revision_id to its parents for the
            ancestry of revision_id.
            Ghosts will be returned with None as their parents, and nodes
            with no parents will have NULL_REVISION as their only parent. (As
            defined by get_parent_map.)
            There will also be a node for (NULL_REVISION, ())
        """
        pending = set(revision_ids)
        processed = set()
        while pending:
            processed.update(pending)
            next_map = self.get_parent_map(pending)
            next_pending = set()
            for item in next_map.iteritems():
                yield item
                next_pending.update(p for p in item[1] if p not in processed)
            ghosts = pending.difference(next_map)
            for ghost in ghosts:
                yield (ghost, None)
            pending = next_pending

    def iter_topo_order(self, revisions):
        """Iterate through the input revisions in topological order.

        This sorting only ensures that parents come before their children.
        An ancestor may sort after a descendant if the relationship is not
        visible in the supplied list of revisions.
        """
        sorter = tsort.TopoSorter(self.get_parent_map(revisions))
        return sorter.iter_topo_order()

    def is_ancestor(self, candidate_ancestor, candidate_descendant):
        """Determine whether a revision is an ancestor of another.

        We answer this using heads() as heads() has the logic to perform the
        smallest number of parent lookups to determine the ancestral
        relationship between N revisions.
        """
        return set([candidate_descendant]) == self.heads(
            [candidate_ancestor, candidate_descendant])

    def _search_for_extra_common(self, common, searchers):
        """Make sure that unique nodes are genuinely unique.

        After _find_border_ancestors, all nodes marked "common" are indeed
        common. Some of the nodes considered unique are not, due to history
        shortcuts stopping the searches early.

        We know that we have searched enough when all common search tips are
        descended from all unique (uncommon) nodes because we know that a node
        cannot be an ancestor of its own ancestor.

        :param common: A set of common nodes
        :param searchers: The searchers returned from _find_border_ancestors
        :return: None
        """
        # Basic algorithm...
        #   A) The passed in searchers should all be on the same tips, thus
        #      they should be considered the "common" searchers.
        #   B) We find the difference between the searchers, these are the
        #      "unique" nodes for each side.
        #   C) We do a quick culling so that we only start searching from the
        #      more interesting unique nodes. (A unique ancestor is more
        #      interesting than any of its children.)
        #   D) We start searching for ancestors common to all unique nodes.
        #   E) We have the common searchers stop searching any ancestors of
        #      nodes found by (D)
        #   F) When there are no more common search tips, we stop

        # TODO: We need a way to remove unique_searchers when they overlap with
        #       other unique searchers.
        assert len(searchers) == 2, (
            "Algorithm not yet implemented for > 2 searchers")
        common_searchers = searchers
        left_searcher = searchers[0]
        right_searcher = searchers[1]
        unique = left_searcher.seen.symmetric_difference(right_searcher.seen)
        total_unique = len(unique)
        unique = self._remove_simple_descendants(unique,
                    self.get_parent_map(unique))
        simple_unique = len(unique)
        trace.mutter('Starting %s unique searchers for %s unique revisions',
                     simple_unique, total_unique)

        unique_searchers = []
        for revision_id in unique:
            if revision_id in left_searcher.seen:
                parent_searcher = left_searcher
            else:
                parent_searcher = right_searcher
            revs_to_search = parent_searcher.find_seen_ancestors([revision_id])
            if not revs_to_search: # XXX: This shouldn't be possible
                revs_to_search = [revision_id]
            searcher = self._make_breadth_first_searcher(revs_to_search)
            # We don't care about the starting nodes.
            searcher.step()
            unique_searchers.append(searcher)

        # Aggregate all of the searchers into a single common searcher, would
        # it be okay to do this?
        # okay to do this?
        # common_searcher = self._make_breadth_first_searcher([])
        # for searcher in searchers:
        #     common_searcher.start_searching(searcher.will_search())
        #     common_searcher.seen.update(searcher.seen)
        common_ancestors_unique = set()

        while True: # If we have no more nodes we have nothing to do
            # XXX: Any nodes here which don't match between searchers indicate
            #      that we have found a genuinely unique node, which would not
            #      have been found by the other searching techniques
            newly_seen_common = set()
            for searcher in common_searchers:
                newly_seen_common.update(searcher.step())
            newly_seen_unique = set()
            for searcher in unique_searchers:
                newly_seen_unique.update(searcher.step())
            new_common_unique = set()
            for revision in newly_seen_unique:
                if revision in common_ancestors_unique:
                    # It is already in common_ancestors_unique, so we don't
                    # need to search it again.
                    continue
                for searcher in unique_searchers:
                    if revision not in searcher.seen:
                        break
                else:
                    # This is a border because it is a first common that we see
                    # after walking for a while.
                    new_common_unique.add(revision)
            if newly_seen_common:
                # These are nodes descended from one of the 'common' searchers.
                # Make sure all searchers are on the same page
                for searcher in common_searchers:
                    newly_seen_common.update(searcher.find_seen_ancestors(newly_seen_common))
                # We start searching the whole ancestry. It is a bit wasteful,
                # though. We really just want to mark all of these nodes as
                # 'seen' and then start just the tips. However, it requires a
                # get_parent_map() call to figure out the tips anyway, and all
                # redundant requests should be fairly fast.
                for searcher in common_searchers:
                    searcher.start_searching(newly_seen_common)

                # If a 'common' node has been found by a unique searcher, we
                # can stop searching it.
                stop_searching_common = None
                for searcher in unique_searchers:
                    if stop_searching_common is None:
                        stop_searching_common = searcher.find_seen_ancestors(newly_seen_common)
                    else:
                        stop_searching_common = stop_searching_common.intersection(searcher.find_seen_ancestors(newly_seen_common))
                if stop_searching_common:
                    for searcher in common_searchers:
                        searcher.stop_searching_any(stop_searching_common)
            if new_common_unique:
                # We found some ancestors that are common, jump all the way to
                # their most ancestral node that we have already seen.
                for searcher in unique_searchers:
                    new_common_unique.update(searcher.find_seen_ancestors(new_common_unique))
                # Since these are common, we can grab another set of ancestors
                # that we have seen
                for searcher in common_searchers:
                    new_common_unique.update(searcher.find_seen_ancestors(new_common_unique))

                # Now we have a complete set of common nodes which are
                # ancestors of the unique nodes.
                # We can tell all of the unique searchers to start at these
                # nodes, and tell all of the common searchers to *stop*
                # searching these nodes
                for searcher in unique_searchers:
                    searcher.start_searching(new_common_unique)
                for searcher in common_searchers:
                    searcher.stop_searching_any(new_common_unique)
                common_ancestors_unique.update(new_common_unique)
            for searcher in common_searchers:
                if searcher._next_query:
                    break
            else:
                # All common searcher have stopped searching
                break


    def _remove_simple_descendants(self, revisions, parent_map):
        """remove revisions which are children of other ones in the set

        This doesn't do any graph searching, it just checks the immediate
        parent_map to find if there are any children which can be removed.

        :param revisions: A set of revision_ids
        :return: A set of revision_ids with the children removed
        """
        simple_ancestors = revisions.copy()
        # TODO: jam 20071214 we *could* restrict it to searching only the
        #       parent_map of revisions already present in 'revisions', but
        #       considering the general use case, I think this is actually
        #       better.

        # This is the same as the following loop. I don't know that it is any
        # faster.
        ## simple_ancestors.difference_update(r for r, p_ids in parent_map.iteritems()
        ##     if p_ids is not None and revisions.intersection(p_ids))
        ## return simple_ancestors

        # Yet Another Way, invert the parent map (which can be cached)
        ## descendants = {}
        ## for revision_id, parent_ids in parent_map.iteritems():
        ##   for p_id in parent_ids:
        ##       descendants.setdefault(p_id, []).append(revision_id)
        ## for revision in revisions.intersection(descendants):
        ##   simple_ancestors.difference_update(descendants[revision])
        ## return simple_ancestors
        for revision, parent_ids in parent_map.iteritems():
            if parent_ids is None:
                continue
            for parent_id in parent_ids:
                if parent_id in revisions:
                    # This node has a parent present in the set, so we can
                    # remove it
                    simple_ancestors.discard(revision)
                    break
        return simple_ancestors


class HeadsCache(object):
    """A cache of results for graph heads calls."""

    def __init__(self, graph):
        self.graph = graph
        self._heads = {}

    def heads(self, keys):
        """Return the heads of keys.

        This matches the API of Graph.heads(), specifically the return value is
        a set which can be mutated, and ordering of the input is not preserved
        in the output.

        :see also: Graph.heads.
        :param keys: The keys to calculate heads for.
        :return: A set containing the heads, which may be mutated without
            affecting future lookups.
        """
        keys = frozenset(keys)
        try:
            return set(self._heads[keys])
        except KeyError:
            heads = self.graph.heads(keys)
            self._heads[keys] = heads
            return set(heads)


class FrozenHeadsCache(object):
    """Cache heads() calls, assuming the caller won't modify them."""

    def __init__(self, graph):
        self.graph = graph
        self._heads = {}

    def heads(self, keys):
        """Return the heads of keys.

        Similar to Graph.heads(). The main difference is that the return value
        is a frozen set which cannot be mutated.

        :see also: Graph.heads.
        :param keys: The keys to calculate heads for.
        :return: A frozenset containing the heads.
        """
        keys = frozenset(keys)
        try:
            return self._heads[keys]
        except KeyError:
            heads = frozenset(self.graph.heads(keys))
            self._heads[keys] = heads
            return heads

    def cache(self, keys, heads):
        """Store a known value."""
        self._heads[frozenset(keys)] = frozenset(heads)


class _BreadthFirstSearcher(object):
    """Parallel search breadth-first the ancestry of revisions.

    This class implements the iterator protocol, but additionally
    1. provides a set of seen ancestors, and
    2. allows some ancestries to be unsearched, via stop_searching_any
    """

    def __init__(self, revisions, parents_provider):
        self._iterations = 0
        self._next_query = set(revisions)
        self.seen = set()
        self._started_keys = set(self._next_query)
        self._stopped_keys = set()
        self._parents_provider = parents_provider
        self._returning = 'next_with_ghosts'
        self._current_present = set()
        self._current_ghosts = set()
        self._current_parents = {}

    def __repr__(self):
        if self._iterations:
            prefix = "searching"
        else:
            prefix = "starting"
        search = '%s=%r' % (prefix, list(self._next_query))
        return ('_BreadthFirstSearcher(iterations=%d, %s,'
                ' seen=%r)' % (self._iterations, search, list(self.seen)))

    def get_result(self):
        """Get a SearchResult for the current state of this searcher.
        
        :return: A SearchResult for this search so far. The SearchResult is
            static - the search can be advanced and the search result will not
            be invalidated or altered.
        """
        if self._returning == 'next':
            # We have to know the current nodes children to be able to list the
            # exclude keys for them. However, while we could have a second
            # look-ahead result buffer and shuffle things around, this method
            # is typically only called once per search - when memoising the
            # results of the search. 
            found, ghosts, next, parents = self._do_query(self._next_query)
            # pretend we didn't query: perhaps we should tweak _do_query to be
            # entirely stateless?
            self.seen.difference_update(next)
            next_query = next.union(ghosts)
        else:
            next_query = self._next_query
        excludes = self._stopped_keys.union(next_query)
        included_keys = self.seen.difference(excludes)
        return SearchResult(self._started_keys, excludes, len(included_keys),
            included_keys)

    def step(self):
        try:
            return self.next()
        except StopIteration:
            return ()

    def next(self):
        """Return the next ancestors of this revision.

        Ancestors are returned in the order they are seen in a breadth-first
        traversal.  No ancestor will be returned more than once. Ancestors are
        returned before their parentage is queried, so ghosts and missing
        revisions (including the start revisions) are included in the result.
        This can save a round trip in LCA style calculation by allowing
        convergence to be detected without reading the data for the revision
        the convergence occurs on.

        :return: A set of revision_ids.
        """
        if self._returning != 'next':
            # switch to returning the query, not the results.
            self._returning = 'next'
            self._iterations += 1
        else:
            self._advance()
        if len(self._next_query) == 0:
            raise StopIteration()
        # We have seen what we're querying at this point as we are returning
        # the query, not the results.
        self.seen.update(self._next_query)
        return self._next_query

    def next_with_ghosts(self):
        """Return the next found ancestors, with ghosts split out.
        
        Ancestors are returned in the order they are seen in a breadth-first
        traversal.  No ancestor will be returned more than once. Ancestors are
        returned only after asking for their parents, which allows us to detect
        which revisions are ghosts and which are not.

        :return: A tuple with (present ancestors, ghost ancestors) sets.
        """
        if self._returning != 'next_with_ghosts':
            # switch to returning the results, not the current query.
            self._returning = 'next_with_ghosts'
            self._advance()
        if len(self._next_query) == 0:
            raise StopIteration()
        self._advance()
        return self._current_present, self._current_ghosts

    def _advance(self):
        """Advance the search.

        Updates self.seen, self._next_query, self._current_present,
        self._current_ghosts, self._current_parents and self._iterations.
        """
        self._iterations += 1
        found, ghosts, next, parents = self._do_query(self._next_query)
        self._current_present = found
        self._current_ghosts = ghosts
        self._next_query = next
        self._current_parents = parents
        # ghosts are implicit stop points, otherwise the search cannot be
        # repeated when ghosts are filled.
        self._stopped_keys.update(ghosts)

    def _do_query(self, revisions):
        """Query for revisions.

        Adds revisions to the seen set.

        :param revisions: Revisions to query.
        :return: A tuple: (set(found_revisions), set(ghost_revisions),
           set(parents_of_found_revisions), dict(found_revisions:parents)).
        """
        found_revisions = set()
        parents_of_found = set()
        # revisions may contain nodes that point to other nodes in revisions:
        # we want to filter them out.
        self.seen.update(revisions)
        parent_map = self._parents_provider.get_parent_map(revisions)
        found_revisions.update(parent_map)
        for rev_id, parents in parent_map.iteritems():
            new_found_parents = [p for p in parents if p not in self.seen]
            if new_found_parents:
                # Calling set.update() with an empty generator is actually
                # rather expensive.
                parents_of_found.update(new_found_parents)
        ghost_revisions = revisions - found_revisions
        return found_revisions, ghost_revisions, parents_of_found, parent_map

    def __iter__(self):
        return self

    def find_seen_ancestors(self, revisions):
        """Find ancestors of these revisions that have already been seen."""
        all_seen = self.seen
        pending = set(revisions).intersection(all_seen)
        seen_ancestors = set(pending)

        if self._returning == 'next':
            # self.seen contains what nodes have been returned, not what nodes
            # have been queried. We don't want to probe for nodes that haven't
            # been searched yet.
            not_searched_yet = self._next_query
        else:
            not_searched_yet = ()
        pending.difference_update(not_searched_yet)
        get_parent_map = self._parents_provider.get_parent_map
        while pending:
            parent_map = get_parent_map(pending)
            all_parents = []
            # We don't care if it is a ghost, since it can't be seen if it is
            # a ghost
            for parent_ids in parent_map.itervalues():
                all_parents.extend(parent_ids)
            next_pending = all_seen.intersection(all_parents).difference(seen_ancestors)
            seen_ancestors.update(next_pending)
            next_pending.difference_update(not_searched_yet)
            pending = next_pending

        return seen_ancestors

    def stop_searching_any(self, revisions):
        """
        Remove any of the specified revisions from the search list.

        None of the specified revisions are required to be present in the
        search list.  In this case, the call is a no-op.
        """
        revisions = frozenset(revisions)
        if self._returning == 'next':
            stopped = self._next_query.intersection(revisions)
            self._next_query = self._next_query.difference(revisions)
        else:
            stopped_present = self._current_present.intersection(revisions)
            stopped = stopped_present.union(
                self._current_ghosts.intersection(revisions))
            self._current_present.difference_update(stopped)
            self._current_ghosts.difference_update(stopped)
            # stopping 'x' should stop returning parents of 'x', but 
            # not if 'y' always references those same parents
            stop_rev_references = {}
            for rev in stopped_present:
                for parent_id in self._current_parents[rev]:
                    if parent_id not in stop_rev_references:
                        stop_rev_references[parent_id] = 0
                    stop_rev_references[parent_id] += 1
            # if only the stopped revisions reference it, the ref count will be
            # 0 after this loop
            for parents in self._current_parents.itervalues():
                for parent_id in parents:
                    try:
                        stop_rev_references[parent_id] -= 1
                    except KeyError:
                        pass
            stop_parents = set()
            for rev_id, refs in stop_rev_references.iteritems():
                if refs == 0:
                    stop_parents.add(rev_id)
            self._next_query.difference_update(stop_parents)
        self._stopped_keys.update(stopped)
        return stopped

    def start_searching(self, revisions):
        """Add revisions to the search.

        The parents of revisions will be returned from the next call to next()
        or next_with_ghosts(). If next_with_ghosts was the most recently used
        next* call then the return value is the result of looking up the
        ghost/not ghost status of revisions. (A tuple (present, ghosted)).
        """
        revisions = frozenset(revisions)
        self._started_keys.update(revisions)
        new_revisions = revisions.difference(self.seen)
        revs, ghosts, query, parents = self._do_query(revisions)
        self._stopped_keys.update(ghosts)
        if self._returning == 'next':
            self._next_query.update(new_revisions)
        else:
            # perform a query on revisions
            self._current_present.update(revs)
            self._current_ghosts.update(ghosts)
            self._next_query.update(query)
            self._current_parents.update(parents)
            return revs, ghosts


class SearchResult(object):
    """The result of a breadth first search.

    A SearchResult provides the ability to reconstruct the search or access a
    set of the keys the search found.
    """

    def __init__(self, start_keys, exclude_keys, key_count, keys):
        """Create a SearchResult.

        :param start_keys: The keys the search started at.
        :param exclude_keys: The keys the search excludes.
        :param key_count: The total number of keys (from start to but not
            including exclude).
        :param keys: The keys the search found. Note that in future we may get
            a SearchResult from a smart server, in which case the keys list is
            not necessarily immediately available.
        """
        self._recipe = (start_keys, exclude_keys, key_count)
        self._keys = frozenset(keys)

    def get_recipe(self):
        """Return a recipe that can be used to replay this search.
        
        The recipe allows reconstruction of the same results at a later date
        without knowing all the found keys. The essential elements are a list
        of keys to start and and to stop at. In order to give reproducible
        results when ghosts are encountered by a search they are automatically
        added to the exclude list (or else ghost filling may alter the
        results).

        :return: A tuple (start_keys_set, exclude_keys_set, revision_count). To
            recreate the results of this search, create a breadth first
            searcher on the same graph starting at start_keys. Then call next()
            (or next_with_ghosts()) repeatedly, and on every result, call
            stop_searching_any on any keys from the exclude_keys set. The
            revision_count value acts as a trivial cross-check - the found
            revisions of the new search should have as many elements as
            revision_count. If it does not, then additional revisions have been
            ghosted since the search was executed the first time and the second
            time.
        """
        return self._recipe

    def get_keys(self):
        """Return the keys found in this search.

        :return: A set of keys.
        """
        return self._keys

