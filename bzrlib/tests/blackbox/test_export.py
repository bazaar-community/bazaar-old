# -*- coding: utf-8 -*-
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


"""Black-box tests for bzr export.
"""

import os
import tarfile
import zipfile

from bzrlib.tests import TestSkipped
from bzrlib.tests.blackbox import ExternalBase


class TestExport(ExternalBase):

    def test_tar_export(self):

        os.mkdir('tar')
        os.chdir('tar')

        self.runbzr('init')
        open('a', 'wb').write('foo\n')
        self.runbzr('add a')
        self.runbzr('ignore something')
        self.runbzr('commit -m 1')
        self.runbzr('export test.tar.gz')
        ball = tarfile.open('test.tar.gz')
        for m in ball.getnames():
            #print m
            self.failIf(os.path.basename(m) == '.bzrignore',
                        'tar export contains .bzrignore')

    def test_tar_export_unicode(self):
        tree = self.make_branch_and_tree('tar')
        fname = u'\xe5.txt'
        try:
            self.build_tree(['tar/' + fname])
        except UnicodeError:
            raise TestSkipped('Unable to represent path %r' % (fname,))
        tree.add([fname])
        tree.commit('first')

        os.chdir('tar')
        self.run_bzr('export', 'test.tar')
        ball = tarfile.open('test.tar')
        # all paths are prefixed with the base name of the tarball
        self.assertEqual(['test/' + fname.encode('utf8')],
                         sorted(ball.getnames()))

    def test_zip_export(self):

        os.mkdir('zip')
        os.chdir('zip')

        self.runbzr('init')
        open('a', 'wb').write('foo\n')
        self.runbzr('add a')
        self.runbzr('ignore something')
        self.runbzr('commit -m 1')
        self.runbzr('export test.zip')
        ball = zipfile.ZipFile('test.zip')
        for m in ball.namelist():
            #print m
            self.failIf(os.path.basename(m) == '.bzrignore',
                        'zip export contains .bzrignore')

    def test_zip_export_unicode(self):
        tree = self.make_branch_and_tree('zip')
        fname = u'\xe5.txt'
        try:
            self.build_tree(['zip/' + fname])
        except UnicodeError:
            raise TestSkipped('Unable to represent path %r' % (fname,))
        tree.add([fname])
        tree.commit('first')

        os.chdir('zip')
        self.run_bzr('export', 'test.zip')
        zfile = zipfile.ZipFile('test.zip')
        # all paths are prefixed with the base name of the zipfile
        self.assertEqual(['test/' + fname.encode('utf8')],
                         sorted(zfile.namelist()))

    def test_dir_export(self):

        os.mkdir('dir')
        os.chdir('dir')

        self.runbzr('init')
        open('a', 'wb').write('foo\n')
        self.runbzr('add a')
        self.runbzr('ignore something')
        self.runbzr('commit -m 1')
        self.runbzr('export direxport')

        files = sorted(os.listdir('direxport'))
        self.assertEqual(['a'], files, 'dir contains .bzrignore')
