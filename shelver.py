# Copyright (C) 2008 Aaron Bentley <aaron@aaronbentley.com>
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


import copy
from cStringIO import StringIO
import os.path
import shutil
import sys
import tempfile

from bzrlib import (diff, osutils, patches, workingtree)
from bzrlib.plugins.bzrtools import hunk_selector, patch
from bzrlib.plugins.shelf2 import prepare_shelf


class Shelver(object):

    def __init__(self, work_tree, target_tree, path):
        self.work_tree = work_tree
        self.target_tree = target_tree
        self.path = path
        self.diff_file = StringIO()
        self.text_differ = diff.DiffText(self.target_tree, self.work_tree,
                                         self.diff_file)

    @classmethod
    def from_args(klass):
        tree, path = workingtree.WorkingTree.open_containing('.')
        return klass(tree, tree.basis_tree(), path)

    def run(self):
        creator = prepare_shelf.ShelfCreator(self.work_tree, self.target_tree)
        self.tempdir = tempfile.mkdtemp()
        try:
            for change in creator:
                if change[0] == 'modify text':
                    self.handle_modify_text(creator, change[1])
            choice = self.prompt('Shelve changes? [y/n]')
            if choice == 'y':
                creator.write_shelf()
                creator.transform()
        finally:
            shutil.rmtree(self.tempdir)
            creator.finalize()

    def get_parsed_patch(self, file_id):
        old_path = self.work_tree.id2path(file_id)
        new_path = self.target_tree.id2path(file_id)
        try:
            patch = self.text_differ.diff(file_id, old_path, new_path, 'file',
                                          'file')
            self.diff_file.seek(0)
            return patches.parse_patch(self.diff_file)
        finally:
            self.diff_file.truncate(0)

    def __getchar(self):
        import tty
        import termios
        fd = sys.stdin.fileno()
        settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, settings)
        return ch

    def prompt(self, question):
        print question,
        char = self.__getchar()
        print ""
        return char

    def handle_modify_text(self, creator, file_id):
        parsed = self.get_parsed_patch(file_id)
        selected_hunks = []
        final_patch = copy.copy(parsed)
        final_patch.hunks = []
        for hunk in parsed.hunks:
            print hunk
            char = self.prompt('Shelve? [y/n]')
            if char == 'n':
                final_patch.hunks.append(hunk)
        target_file = self.target_tree.get_file(file_id)
        try:
            if len(final_patch.hunks) == 0:
                creator.shelve_text(file_id, target_file.read())
                return
            filename = os.path.join(self.tempdir, 'patch-target')
            outfile = open(filename, 'w+b')
            try:
                osutils.pumpfile(target_file, outfile)
            finally:
                outfile.close()
        finally:
            target_file.close()
        patch.run_patch('.',
            [str(final_patch)], target_file=filename)
        outfile = open(filename, 'rb')
        try:
            creator.shelve_text(file_id, outfile.read())
        finally:
            outfile.close()
