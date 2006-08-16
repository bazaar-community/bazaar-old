# Copyright (C) 2006 by Canonical Ltd
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Tests for bzr xml serialization performance."""

from bzrlib import (
    xml5,
    )
from bzrlib.benchmarks import Benchmark


class BenchXMLSerializer(Benchmark):

    def test_serialize_kernel_like_inventory(self):
        # Really all we want is a real inventory
        tree = self.make_kernel_like_committed_tree('.', link_bzr=True)

        # We want a real tree with lots of file ids and sha strings, etc.
        self.time(xml5.serializer_v5.write_inventory_to_string,
                  tree.basis_tree().inventory)

