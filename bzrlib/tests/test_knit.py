# Copyright (C) 2005, 2006 by Canonical Ltd
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

"""Tests for Knit data structure"""


import difflib


from bzrlib.errors import KnitError, RevisionAlreadyPresent
from bzrlib.knit import KnitVersionedFile, KnitPlainFactory, KnitAnnotateFactory
from bzrlib.osutils import split_lines
from bzrlib.tests import TestCaseInTempDir
from bzrlib.transport import TransportLogger, get_transport
from bzrlib.transport.memory import MemoryTransport


class KnitTests(TestCaseInTempDir):

    def add_stock_one_and_one_a(self, k):
        k.add_lines('text-1', [], split_lines(TEXT_1))
        k.add_lines('text-1a', ['text-1'], split_lines(TEXT_1A))

    def test_knit_constructor(self):
        """Construct empty k"""
        self.make_test_knit()

    def make_test_knit(self, annotate=False):
        if not annotate:
            factory = KnitPlainFactory()
        else:
            factory = None
        return KnitVersionedFile('test', get_transport('.'), access_mode='w', factory=factory, create=True)

    def test_knit_add(self):
        """Store one text in knit and retrieve"""
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        self.assertTrue(k.has_version('text-1'))
        self.assertEqualDiff(''.join(k.get_lines('text-1')), TEXT_1)

    def test_knit_reload(self):
        # test that the content in a reloaded knit is correct
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        del k
        k2 = KnitVersionedFile('test', get_transport('.'), access_mode='r', factory=KnitPlainFactory(), create=True)
        self.assertTrue(k2.has_version('text-1'))
        self.assertEqualDiff(''.join(k2.get_lines('text-1')), TEXT_1)

    def test_knit_several(self):
        """Store several texts in a knit"""
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        k.add_lines('text-2', [], split_lines(TEXT_2))
        self.assertEqualDiff(''.join(k.get_lines('text-1')), TEXT_1)
        self.assertEqualDiff(''.join(k.get_lines('text-2')), TEXT_2)
        
    def test_repeated_add(self):
        """Knit traps attempt to replace existing version"""
        k = self.make_test_knit()
        k.add_lines('text-1', [], split_lines(TEXT_1))
        self.assertRaises(RevisionAlreadyPresent, 
                k.add_lines,
                'text-1', [], split_lines(TEXT_1))

    def test_empty(self):
        k = self.make_test_knit(True)
        k.add_lines('text-1', [], [])
        self.assertEquals(k.get_lines('text-1'), [])

    def test_incomplete(self):
        """Test if texts without a ending line-end can be inserted and
        extracted."""
        k = KnitVersionedFile('test', get_transport('.'), delta=False, create=True)
        k.add_lines('text-1', [], ['a\n',    'b'  ])
        k.add_lines('text-2', ['text-1'], ['a\rb\n', 'b\n'])
        # reopening ensures maximum room for confusion
        k = KnitVersionedFile('test', get_transport('.'), delta=False, create=True)
        self.assertEquals(k.get_lines('text-1'), ['a\n',    'b'  ])
        self.assertEquals(k.get_lines('text-2'), ['a\rb\n', 'b\n'])

    def test_delta(self):
        """Expression of knit delta as lines"""
        k = self.make_test_knit()
        td = list(line_delta(TEXT_1.splitlines(True),
                             TEXT_1A.splitlines(True)))
        self.assertEqualDiff(''.join(td), delta_1_1a)
        out = apply_line_delta(TEXT_1.splitlines(True), td)
        self.assertEqualDiff(''.join(out), TEXT_1A)

    def test_add_with_parents(self):
        """Store in knit with parents"""
        k = self.make_test_knit()
        self.add_stock_one_and_one_a(k)
        self.assertEquals(k.get_parents('text-1'), [])
        self.assertEquals(k.get_parents('text-1a'), ['text-1'])

    def test_ancestry(self):
        """Store in knit with parents"""
        k = self.make_test_knit()
        self.add_stock_one_and_one_a(k)
        self.assertEquals(set(k.get_ancestry(['text-1a'])), set(['text-1a', 'text-1']))

    def test_add_delta(self):
        """Store in knit with parents"""
        k = KnitVersionedFile('test', get_transport('.'), factory=KnitPlainFactory(),
            delta=True, create=True)
        self.add_stock_one_and_one_a(k)
        k.clear_cache()
        self.assertEqualDiff(''.join(k.get_lines('text-1a')), TEXT_1A)

    def test_annotate(self):
        """Annotations"""
        k = KnitVersionedFile('knit', get_transport('.'), factory=KnitAnnotateFactory(),
            delta=True, create=True)
        self.insert_and_test_small_annotate(k)

    def insert_and_test_small_annotate(self, k):
        """test annotation with k works correctly."""
        k.add_lines('text-1', [], ['a\n', 'b\n'])
        k.add_lines('text-2', ['text-1'], ['a\n', 'c\n'])

        origins = k.annotate('text-2')
        self.assertEquals(origins[0], ('text-1', 'a\n'))
        self.assertEquals(origins[1], ('text-2', 'c\n'))

    def test_annotate_fulltext(self):
        """Annotations"""
        k = KnitVersionedFile('knit', get_transport('.'), factory=KnitAnnotateFactory(),
            delta=False, create=True)
        self.insert_and_test_small_annotate(k)

    def test_annotate_merge_1(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n'])
        k.add_lines('text-a2', [], ['d\n', 'c\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['d\n', 'b\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a2', 'd\n'))
        self.assertEquals(origins[1], ('text-a1', 'b\n'))

    def test_annotate_merge_2(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['a\n', 'y\n', 'c\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a1', 'a\n'))
        self.assertEquals(origins[1], ('text-a2', 'y\n'))
        self.assertEquals(origins[2], ('text-a1', 'c\n'))

    def test_annotate_merge_9(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['k\n', 'y\n', 'c\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-am', 'k\n'))
        self.assertEquals(origins[1], ('text-a2', 'y\n'))
        self.assertEquals(origins[2], ('text-a1', 'c\n'))

    def test_annotate_merge_3(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [] ,['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am', ['text-a1', 'text-a2'], ['k\n', 'y\n', 'z\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-am', 'k\n'))
        self.assertEquals(origins[1], ('text-a2', 'y\n'))
        self.assertEquals(origins[2], ('text-a2', 'z\n'))

    def test_annotate_merge_4(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-a3', ['text-a1'], ['a\n', 'b\n', 'p\n'])
        k.add_lines('text-am', ['text-a2', 'text-a3'], ['a\n', 'b\n', 'z\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a1', 'a\n'))
        self.assertEquals(origins[1], ('text-a1', 'b\n'))
        self.assertEquals(origins[2], ('text-a2', 'z\n'))

    def test_annotate_merge_5(self):
        k = self.make_test_knit(True)
        k.add_lines('text-a1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-a2', [], ['d\n', 'e\n', 'f\n'])
        k.add_lines('text-a3', [], ['x\n', 'y\n', 'z\n'])
        k.add_lines('text-am',
                    ['text-a1', 'text-a2', 'text-a3'],
                    ['a\n', 'e\n', 'z\n'])
        origins = k.annotate('text-am')
        self.assertEquals(origins[0], ('text-a1', 'a\n'))
        self.assertEquals(origins[1], ('text-a2', 'e\n'))
        self.assertEquals(origins[2], ('text-a3', 'z\n'))

    def test_annotate_file_cherry_pick(self):
        k = self.make_test_knit(True)
        k.add_lines('text-1', [], ['a\n', 'b\n', 'c\n'])
        k.add_lines('text-2', ['text-1'], ['d\n', 'e\n', 'f\n'])
        k.add_lines('text-3', ['text-2', 'text-1'], ['a\n', 'b\n', 'c\n'])
        origins = k.annotate('text-3')
        self.assertEquals(origins[0], ('text-1', 'a\n'))
        self.assertEquals(origins[1], ('text-1', 'b\n'))
        self.assertEquals(origins[2], ('text-1', 'c\n'))

    def test_knit_join(self):
        """Store in knit with parents"""
        k1 = KnitVersionedFile('test1', get_transport('.'), factory=KnitPlainFactory(), create=True)
        k1.add_lines('text-a', [], split_lines(TEXT_1))
        k1.add_lines('text-b', ['text-a'], split_lines(TEXT_1))

        k1.add_lines('text-c', [], split_lines(TEXT_1))
        k1.add_lines('text-d', ['text-c'], split_lines(TEXT_1))

        k1.add_lines('text-m', ['text-b', 'text-d'], split_lines(TEXT_1))

        k2 = KnitVersionedFile('test2', get_transport('.'), factory=KnitPlainFactory(), create=True)
        count = k2.join(k1, version_ids=['text-m'])
        self.assertEquals(count, 5)
        self.assertTrue(k2.has_version('text-a'))
        self.assertTrue(k2.has_version('text-c'))

    def test_reannotate(self):
        k1 = KnitVersionedFile('knit1', get_transport('.'),
                               factory=KnitAnnotateFactory(), create=True)
        # 0
        k1.add_lines('text-a', [], ['a\n', 'b\n'])
        # 1
        k1.add_lines('text-b', ['text-a'], ['a\n', 'c\n'])

        k2 = KnitVersionedFile('test2', get_transport('.'),
                               factory=KnitAnnotateFactory(), create=True)
        k2.join(k1, version_ids=['text-b'])

        # 2
        k1.add_lines('text-X', ['text-b'], ['a\n', 'b\n'])
        # 2
        k2.add_lines('text-c', ['text-b'], ['z\n', 'c\n'])
        # 3
        k2.add_lines('text-Y', ['text-b'], ['b\n', 'c\n'])

        # test-c will have index 3
        k1.join(k2, version_ids=['text-c'])

        lines = k1.get_lines('text-c')
        self.assertEquals(lines, ['z\n', 'c\n'])

        origins = k1.annotate('text-c')
        self.assertEquals(origins[0], ('text-c', 'z\n'))
        self.assertEquals(origins[1], ('text-b', 'c\n'))

    def test_extraction_reads_components_once(self):
        t = MemoryTransport()
        instrumented_t = TransportLogger(t)
        k1 = KnitVersionedFile('id', instrumented_t, create=True, delta=True)
        # should read the index
        self.assertEqual([('id.kndx',)], instrumented_t._calls)
        instrumented_t._calls = []
        # add a text       
        k1.add_lines('base', [], ['text\n'])
        # should not have read at all
        self.assertEqual([], instrumented_t._calls)

        # add a text
        k1.add_lines('sub', ['base'], ['text\n', 'text2\n'])
        # should not have read at all
        self.assertEqual([], instrumented_t._calls)
        
        # read a text
        k1.get_lines('sub')
        # should not have read at all
        self.assertEqual([], instrumented_t._calls)

        # clear the cache
        k1.clear_cache()

        # read a text
        k1.get_lines('base')
        # should have read a component
        # should not have read the first component only
        self.assertEqual([('id.knit', [(0, 87)])], instrumented_t._calls)
        instrumented_t._calls = []
        # read again
        k1.get_lines('base')
        # should not have read at all
        self.assertEqual([], instrumented_t._calls)
        # and now read the other component
        k1.get_lines('sub')
        # should have read the second component
        self.assertEqual([('id.knit', [(87, 93)])], instrumented_t._calls)
        instrumented_t._calls = []

        # clear the cache
        k1.clear_cache()
        # add a text cold 
        k1.add_lines('sub2', ['base'], ['text\n', 'text3\n'])
        # should read the first component only
        self.assertEqual([('id.knit', [(0, 87)])], instrumented_t._calls)
        
    def test_iter_lines_reads_in_order(self):
        t = MemoryTransport()
        instrumented_t = TransportLogger(t)
        k1 = KnitVersionedFile('id', instrumented_t, create=True, delta=True)
        self.assertEqual([('id.kndx',)], instrumented_t._calls)
        # add texts with no required ordering
        k1.add_lines('base', [], ['text\n'])
        k1.add_lines('base2', [], ['text2\n'])
        k1.clear_cache()
        instrumented_t._calls = []
        # request a last-first iteration
        results = list(k1.iter_lines_added_or_present_in_versions(['base2', 'base']))
        self.assertEqual([('id.knit', [(0, 87), (87, 89)])], instrumented_t._calls)
        self.assertEqual(['text\n', 'text2\n'], results)

    def test_create_empty_annotated(self):
        k1 = self.make_test_knit(True)
        # 0
        k1.add_lines('text-a', [], ['a\n', 'b\n'])
        k2 = k1.create_empty('t', MemoryTransport())
        self.assertTrue(isinstance(k2.factory, KnitAnnotateFactory))
        self.assertEqual(k1.delta, k2.delta)
        # the generic test checks for empty content and file class

    def test_knit_format(self):
        # this tests that a new knit index file has the expected content
        # and that is writes the data we expect as records are added.
        knit = self.make_test_knit(True)
        self.assertFileEqual("# bzr knit index 8\n", 'test.kndx')
        knit.add_lines_with_ghosts('revid', ['a_ghost'], ['a\n'])
        self.assertFileEqual(
            "# bzr knit index 8\n"
            "\n"
            "revid fulltext 0 84 .a_ghost :",
            'test.kndx')
        knit.add_lines_with_ghosts('revid2', ['revid'], ['a\n'])
        self.assertFileEqual(
            "# bzr knit index 8\n"
            "\nrevid fulltext 0 84 .a_ghost :"
            "\nrevid2 line-delta 84 82 0 :",
            'test.kndx')
        # we should be able to load this file again
        knit = KnitVersionedFile('test', get_transport('.'), access_mode='r')
        self.assertEqual(['revid', 'revid2'], knit.versions())
        # write a short write to the file and ensure that its ignored
        indexfile = file('test.kndx', 'at')
        indexfile.write('\nrevid3 line-delta 166 82 1 2 3 4 5 .phwoar:demo ')
        indexfile.close()
        # we should be able to load this file again
        knit = KnitVersionedFile('test', get_transport('.'), access_mode='w')
        self.assertEqual(['revid', 'revid2'], knit.versions())
        # and add a revision with the same id the failed write had
        knit.add_lines('revid3', ['revid2'], ['a\n'])
        # and when reading it revid3 should now appear.
        knit = KnitVersionedFile('test', get_transport('.'), access_mode='r')
        self.assertEqual(['revid', 'revid2', 'revid3'], knit.versions())
        self.assertEqual(['revid2'], knit.get_parents('revid3'))

    def test_plan_merge(self):
        my_knit = self.make_test_knit(annotate=True)
        my_knit.add_lines('text1', [], split_lines(TEXT_1))
        my_knit.add_lines('text1a', ['text1'], split_lines(TEXT_1A))
        my_knit.add_lines('text1b', ['text1'], split_lines(TEXT_1B))
        plan = list(my_knit.plan_merge('text1a', 'text1b'))
        for plan_line, expected_line in zip(plan, AB_MERGE):
            self.assertEqual(plan_line, expected_line)


TEXT_1 = """\
Banana cup cakes:

- bananas
- eggs
- broken tea cups
"""

TEXT_1A = """\
Banana cup cake recipe
(serves 6)

- bananas
- eggs
- broken tea cups
- self-raising flour
"""

TEXT_1B = """\
Banana cup cake recipe

- bananas (do not use plantains!!!)
- broken tea cups
- flour
"""

delta_1_1a = """\
0,1,2
Banana cup cake recipe
(serves 6)
5,5,1
- self-raising flour
"""

TEXT_2 = """\
Boeuf bourguignon

- beef
- red wine
- small onions
- carrot
- mushrooms
"""

AB_MERGE_TEXT="""unchanged|Banana cup cake recipe
new-a|(serves 6)
unchanged|
killed-b|- bananas
killed-b|- eggs
new-b|- bananas (do not use plantains!!!)
unchanged|- broken tea cups
new-a|- self-raising flour
new-b|- flour
"""
AB_MERGE=[tuple(l.split('|')) for l in AB_MERGE_TEXT.splitlines(True)]


def line_delta(from_lines, to_lines):
    """Generate line-based delta from one text to another"""
    s = difflib.SequenceMatcher(None, from_lines, to_lines)
    for op in s.get_opcodes():
        if op[0] == 'equal':
            continue
        yield '%d,%d,%d\n' % (op[1], op[2], op[4]-op[3])
        for i in range(op[3], op[4]):
            yield to_lines[i]


def apply_line_delta(basis_lines, delta_lines):
    """Apply a line-based perfect diff
    
    basis_lines -- text to apply the patch to
    delta_lines -- diff instructions and content
    """
    out = basis_lines[:]
    i = 0
    offset = 0
    while i < len(delta_lines):
        l = delta_lines[i]
        a, b, c = map(long, l.split(','))
        i = i + 1
        out[offset+a:offset+b] = delta_lines[i:i+c]
        i = i + c
        offset = offset + (b - a) + c
    return out
