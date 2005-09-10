# (C) 2005 Canonical

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

def max_distance(node, ancestors, distances):
    """Calculate the max distance to an ancestor.  
    Return None if not all possible ancestors have known distances"""
    best = None
    if node in distances:
        best = distances[node]
    for ancestor in ancestors[node]:
        # An ancestor which is not listed in ancestors will never be in
        # distances, so we pretend it never existed.
        if ancestor not in ancestors:
            continue
        if ancestor not in distances:
            return None
        if best is None or distances[ancestor] > best:
            best = distances[ancestor] + 1
    return best

    
def farthest_nodes(graph, ancestors, start):
    """Produce a list of nodes, sorted by distance from a start node.
    This is an algorithm devised by Aaron Bentley, because applying Dijkstra
    backwards seemed too complicated.

    For each node, we walk its descendants.  If all the descendant's ancestors
    have a max-distance-to-start, (excluding ones that can never reach start),
    we calculate their max-distance-to-start, and schedule their descendants.

    So when a node's last parent acquires a distance, it will acquire a
    distance on the next iteration.

    Once we know the max distances for all nodes, we can return a list sorted
    by distance, farthest first.
    """
    distances = {start: 0}
    lines = set([start])
    while len(lines) > 0:
        new_lines = set()
        for line in lines:
            assert line not in graph[line], "%s refers to itself" % line
            for descendant in graph[line]:
                distance = max_distance(descendant, ancestors, distances)
                if distance is None:
                    continue
                distances[descendant] = distance
                new_lines.add(descendant)
        lines = new_lines

    def by_distance(n):
        return distances[n],n
    node_list = distances.keys()
    node_list.sort(key=by_distance, reverse=True)
    return node_list
