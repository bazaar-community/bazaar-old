from bzrlib.revision import NULL_REVISION
from bzrlib.tests import TestCaseWithMemoryTransport

ancestry_1 = {'rev1': [NULL_REVISION], 'rev2a': ['rev1'], 'rev2b': ['rev1'],
              'rev3': ['rev2a'], 'rev4': ['rev3', 'rev2b']}

class TestGraphWalker(TestCaseWithMemoryTransport):

    def test_distance_from_origin(self):
        tree = self.build_ancestry(ancestry_1)
        graph_walker = tree.branch.repository.get_graph_walker()
        self.assertEqual([1, 0, 2, 4],
                         graph_walker.distance_from_origin(['rev1', 'null:',
                         'rev2b', 'rev4']))

    def build_ancestry(self, ancestors):
        tree = self.make_branch_and_memory_tree('.')
        tree.lock_write()
        tree.add('.')
        pending = [NULL_REVISION]
        descendants = {}
        for descendant, parents in ancestors.iteritems():
            for parent in parents:
                descendants.setdefault(parent, []).append(descendant)
        while len(pending) > 0:
            cur_node = pending.pop()
            for descendant in descendants.get(cur_node, []):
                parents = [p for p in ancestors[descendant] if p is not
                           NULL_REVISION]
                if len([p for p in parents if not
                    tree.branch.repository.has_revision(p)]) > 0:
                    continue
                tree.set_parent_ids(parents)
                tree.branch.set_last_revision_info(
                    len(tree.branch._lefthand_history(cur_node)),
                    cur_node)
                tree.commit(descendant, rev_id=descendant)
                pending.append(descendant)
        tree.unlock()
        return tree

    def test_mca(self):
        tree = self.build_ancestry(ancestry_1)
        graph_walker = tree.branch.repository.get_graph_walker()
        self.assertEqual(set([NULL_REVISION]),
                         graph_walker.minimal_common(NULL_REVISION,
                                                     NULL_REVISION))
        self.assertEqual(set([NULL_REVISION]),
                         graph_walker.minimal_common(NULL_REVISION,
                                                     'rev1'))
