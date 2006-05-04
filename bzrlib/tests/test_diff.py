from cStringIO import StringIO

from bzrlib.diff import internal_diff, external_diff
from bzrlib.errors import BinaryFile
from bzrlib.tests import TestCase
from tempfile import TemporaryFile


def udiff_lines(old, new, allow_binary=False):
    output = StringIO()
    internal_diff('old', old, 'new', new, output, allow_binary)
    output.seek(0, 0)
    return output.readlines()

def external_udiff_lines(old, new):
    output = TemporaryFile()
    external_diff('old', old, 'new', new, output, diff_opts=['-u'])
    output.seek(0, 0)
    lines = output.readlines()
    output.close()
    return lines


class TestDiff(TestCase):
    def test_add_nl(self):
        """diff generates a valid diff for patches that add a newline"""
        lines = udiff_lines(['boo'], ['boo\n'])
        self.check_patch(lines)
        self.assertEquals(lines[4], '\\ No newline at end of file\n')
            ## "expected no-nl, got %r" % lines[4]

    def test_add_nl_2(self):
        """diff generates a valid diff for patches that change last line and
        add a newline.
        """
        lines = udiff_lines(['boo'], ['goo\n'])
        self.check_patch(lines)
        self.assertEquals(lines[4], '\\ No newline at end of file\n')
            ## "expected no-nl, got %r" % lines[4]

    def test_remove_nl(self):
        """diff generates a valid diff for patches that change last line and
        add a newline.
        """
        lines = udiff_lines(['boo\n'], ['boo'])
        self.check_patch(lines)
        self.assertEquals(lines[5], '\\ No newline at end of file\n')
            ## "expected no-nl, got %r" % lines[5]

    def check_patch(self, lines):
        self.assert_(len(lines) > 1)
            ## "Not enough lines for a file header for patch:\n%s" % "".join(lines)
        self.assert_(lines[0].startswith ('---'))
            ## 'No orig line for patch:\n%s' % "".join(lines)
        self.assert_(lines[1].startswith ('+++'))
            ## 'No mod line for patch:\n%s' % "".join(lines)
        self.assert_(len(lines) > 2)
            ## "No hunks for patch:\n%s" % "".join(lines)
        self.assert_(lines[2].startswith('@@'))
            ## "No hunk header for patch:\n%s" % "".join(lines)
        self.assert_('@@' in lines[2][2:])
            ## "Unterminated hunk header for patch:\n%s" % "".join(lines)

    def test_binary_lines(self):
        self.assertRaises(BinaryFile, udiff_lines, [1023 * 'a' + '\x00'], [])
        self.assertRaises(BinaryFile, udiff_lines, [], [1023 * 'a' + '\x00'])
        udiff_lines([1023 * 'a' + '\x00'], [], allow_binary=True)
        udiff_lines([], [1023 * 'a' + '\x00'], allow_binary=True)

    def test_external_diff(self):
        lines = external_udiff_lines(['boo\n'], ['goo\n'])
        self.check_patch(lines)
        
