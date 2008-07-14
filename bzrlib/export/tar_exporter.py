# Copyright (C) 2005, 2006, 2008 Canonical Ltd
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

"""Export a Tree to a non-versioned directory.
"""

import os
import tarfile
import time
import sys

from bzrlib import errors, export
from bzrlib.trace import mutter


def tar_exporter(tree, dest, root, compression=None):
    """Export this tree to a new tar file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be clobbered, like with "tar -c".
    """
    now = time.time()
    compression = str(compression or '')
    if dest == '-':
        # XXX: If no root is given, the output tarball will contain files
        # named '-/foo'; perhaps this is the most reasonable thing.
        ball = tarfile.open(None, 'w|' + compression, sys.stdout)
    else:
        if root is None:
            root = export.get_root_name(dest)
        ball = tarfile.open(dest, 'w:' + compression)
    mutter('export version %r', tree)
    inv = tree.inventory
    entries = inv.iter_entries()
    entries.next() # skip root
    for dp, ie in entries:
        # .bzrignore has no meaning outside of a working tree
        # so do not export it
        if dp == ".bzrignore":
            continue
        item, fileobj = ie.get_tar_item(root, dp, now, tree)
        ball.addfile(item, fileobj)
    ball.close()


def tgz_exporter(tree, dest, root):
    tar_exporter(tree, dest, root, compression='gz')


def tbz_exporter(tree, dest, root):
    tar_exporter(tree, dest, root, compression='bz2')

