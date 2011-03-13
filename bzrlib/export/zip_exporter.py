# Copyright (C) 2005, 2006, 2008, 2009, 2010 Canonical Ltd
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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

"""Export a Tree to a non-versioned directory.
"""

import os
import stat
import sys
import time
import zipfile

from bzrlib import (
    osutils,
    )
from bzrlib.export import _export_iter_entries
from bzrlib.filters import (
    ContentFilterContext,
    filtered_output_bytes,
    )
from bzrlib.trace import mutter


# Windows expects this bit to be set in the 'external_attr' section
# Or it won't consider the entry a directory
ZIP_DIRECTORY_BIT = (1 << 4)
FILE_PERMISSIONS = (0644 << 16)
DIR_PERMISSIONS = (0755 << 16)

_FILE_ATTR = stat.S_IFREG | FILE_PERMISSIONS
_DIR_ATTR = stat.S_IFDIR | ZIP_DIRECTORY_BIT | DIR_PERMISSIONS


def zip_exporter(tree, dest, root, subdir, filtered=False, force_mtime=None):
    """ Export this tree to a new zip file.

    `dest` will be created holding the contents of this tree; if it
    already exists, it will be overwritten".
    """

    compression = zipfile.ZIP_DEFLATED
    if dest == "-":
        dest = sys.stdout
    zipf = zipfile.ZipFile(dest, "w", compression)

    try:
        for dp, ie in _export_iter_entries(tree, subdir):
            file_id = ie.file_id
            mutter("  export {%s} kind %s to %s", file_id, ie.kind, dest)

            # zipfile.ZipFile switches all paths to forward
            # slashes anyway, so just stick with that.
            if force_mtime is not None:
                mtime = force_mtime
            else:
                mtime = tree.get_file_mtime(ie.file_id, dp)
            date_time = time.localtime(mtime)[:6]
            filename = osutils.pathjoin(root, dp).encode('utf8')
            if ie.kind == "file":
                zinfo = zipfile.ZipInfo(
                            filename=filename,
                            date_time=date_time)
                zinfo.compress_type = compression
                zinfo.external_attr = _FILE_ATTR
                if filtered:
                    chunks = tree.get_file_lines(file_id)
                    filters = tree._content_filter_stack(dp)
                    context = ContentFilterContext(dp, tree, ie)
                    contents = filtered_output_bytes(chunks, filters, context)
                    content = ''.join(contents)
                else:
                    content = tree.get_file_text(file_id)
                zipf.writestr(zinfo, content)
            elif ie.kind == "directory":
                # Directories must contain a trailing slash, to indicate
                # to the zip routine that they are really directories and
                # not just empty files.
                zinfo = zipfile.ZipInfo(
                            filename=filename + '/',
                            date_time=date_time)
                zinfo.compress_type = compression
                zinfo.external_attr = _DIR_ATTR
                zipf.writestr(zinfo,'')
            elif ie.kind == "symlink":
                zinfo = zipfile.ZipInfo(
                            filename=(filename + '.lnk'),
                            date_time=date_time)
                zinfo.compress_type = compression
                zinfo.external_attr = _FILE_ATTR
                zipf.writestr(zinfo, ie.symlink_target)

        zipf.close()

    except UnicodeEncodeError:
        zipf.close()
        os.remove(dest)
        from bzrlib.errors import BzrError
        raise BzrError("Can't export non-ascii filenames to zip")
