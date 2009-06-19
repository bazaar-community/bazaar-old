#!/usr/bin/env python
import random
import os
import time
import sys
import optparse
from bzrlib import (
    branch,
    commands,
    graph,
    ui,
    trace,
    _known_graph_py,
    _known_graph_pyx,
    )
from bzrlib.ui import text

p = optparse.OptionParser()
p.add_option('--quick', default=False, action='store_true')
p.add_option('--max-combinations', default=500, type=int)
p.add_option('--lsprof', default=None, type=str)
opts, args = p.parse_args(sys.argv[1:])

trace.enable_default_logging()
ui.ui_factory = text.TextUIFactory()

begin = time.clock()
if len(args) >= 1:
    b = branch.Branch.open(args[0])
else:
    b = branch.Branch.open('.')
b.lock_read()
try:
    g = b.repository.get_graph()
    parent_map = dict(p for p in g.iter_ancestry([b.last_revision()])
                         if p[1] is not None)
finally:
    b.unlock()
end = time.clock()

print 'Found %d nodes, loaded in %.3fs' % (len(parent_map), end - begin)

def all_heads_comp(g, combinations):
    h = []
    pb = ui.ui_factory.nested_progress_bar()
    try:
        for idx, combo in enumerate(combinations):
            if idx & 0x1f == 0:
                pb.update('proc', idx, len(combinations))
            h.append(g.heads(combo))
    finally:
        pb.finished()
    return h

combinations = []
# parents = parent_map.keys()
# for p1 in parents:
#     for p2 in random.sample(parents, 10):
#         combinations.append((p1, p2))
# Times for random sampling of 10x1150 of bzrtools
#   Graph        KnownGraph
#   96.1s   vs   25.7s  :)
# Times for 500 'merge parents' from bzr.dev
#   25.6s   vs   45.0s  :(

for revision_id, parent_ids in parent_map.iteritems():
    if parent_ids is not None and len(parent_ids) > 1:
        combinations.append(parent_ids)
if opts.max_combinations > 0 and len(combinations) > opts.max_combinations:
    combinations = random.sample(combinations, opts.max_combinations)

print '      %d combinations' % (len(combinations),)

def combi_graph(graph_klass, comb):
    # DEBUG
    graph._counters[1] = 0
    graph._counters[2] = 0

    begin = time.clock()
    g = graph_klass(parent_map)
    if opts.lsprof is not None:
        heads = commands.apply_lsprofiled(opts.lsprof, all_heads_comp, g, comb)
    else:
        heads = all_heads_comp(g, comb)
    end = time.clock()
    return dict(elapsed=(end - begin), graph=g, heads=heads)

def report(name, g):
    print '%s: %.3fs' % (name, g['elapsed'])
    counters_used = False
    for c in graph._counters:
        if c:
            counters_used = True
    if counters_used:
        print '  %s' % (graph._counters,)

known_python = combi_graph(_known_graph_py.KnownGraph, combinations)
report('Known', known_python)

known_pyrex = combi_graph(_known_graph_pyx.KnownGraph, combinations)
report('Known (pyx)', known_pyrex)

def _simple_graph(parent_map):
    return graph.Graph(graph.DictParentsProvider(parent_map))

if opts.quick:
    if known_python['heads'] != known_pyrex['heads']:
        import pdb; pdb.set_trace()
    print 'ratio: %.1f:1 faster' % (
        known_python['elapsed'] / known_pyrex['elapsed'],)
else:
    orig = combi_graph(_simple_graph, combinations)
    report('Orig', orig)

    if orig['heads'] != known_pyrex['heads']:
        import pdb; pdb.set_trace()

    print 'ratio: %.1f:1 faster' % (
        orig['elapsed'] / known_pyrex['elapsed'],)
