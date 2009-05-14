# Copyright (C) 2009 Canonical Ltd
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

"""Tests for _rio_*."""

from bzrlib import (
    rio,
    tests,
    )


def load_tests(standard_tests, module, loader):
    # parameterize all tests in this module
    suite = loader.suiteClass()
    import bzrlib._rio_py as py_module
    scenarios = [('python', {'module': py_module})]
    if CompiledRioFeature.available():
        import bzrlib._rio_pyx as c_module
        scenarios.append(('C', {'module': c_module}))
    else:
        # the compiled module isn't available, so we add a failing test
        class FailWithoutFeature(tests.TestCase):
            def test_fail(self):
                self.requireFeature(CompiledRioFeature)
        suite.addTest(loader.loadTestsFromTestCase(FailWithoutFeature))
    tests.multiply_tests(standard_tests, scenarios, suite)
    return suite


class _CompiledRioFeature(tests.Feature):

    def _probe(self):
        try:
            import bzrlib._rio_pyx
        except ImportError:
            return False
        return True

    def feature_name(self):
        return 'bzrlib._rio_pyx'

CompiledRioFeature = _CompiledRioFeature()


class TestValidTag(tests.TestCase):

    module = None # Filled in by test parameterization

    def test_ok(self):
        self.assertTrue(self.module._valid_tag("foo"))

    def test_no_spaces(self):
        self.assertFalse(self.module._valid_tag("foo bla"))

    def test_numeric(self):
        self.assertTrue(self.module._valid_tag("3foo423"))

    def test_no_colon(self):
        self.assertFalse(self.module._valid_tag("foo:bla"))
    
    def test_type_error(self):
        self.assertRaises(TypeError, self.module._valid_tag, 423)

    def test_empty(self):
        self.assertFalse(self.module._valid_tag(""))


class TestReadUTF8Stanza(tests.TestCase):

    module = None # Filled in by test parameterization

    def assertReadStanza(self, result, line_iter):
        self.assertEquals(result, self.module._read_stanza_utf8(line_iter))

    def assertReadStanzaRaises(self, exception, line_iter):
        self.assertRaises(exception, self.module._read_stanza_utf8, line_iter)

    def test_no_string(self):
        self.assertReadStanzaRaises(TypeError, [21323])

    def test_empty(self):
        self.assertReadStanza(None, [])

    def test_none(self):
        self.assertReadStanza(None, [""])

    def test_simple(self):
        self.assertReadStanza(rio.Stanza(foo="bar"), ["foo: bar\n", ""])

    def test_multi_line(self):
        self.assertReadStanza(rio.Stanza(foo="bar\nbla"), 
                ["foo: bar\n", "\tbla\n"])

    def test_repeated(self):
        s = rio.Stanza()
        s.add("foo", "bar")
        s.add("foo", "foo")
        self.assertReadStanza(s, ["foo: bar\n", "foo: foo\n"])

    def test_invalid_early_colon(self):
        self.assertReadStanzaRaises(ValueError, ["f:oo: bar\n"])

    def test_invalid_tag(self):
        self.assertReadStanzaRaises(ValueError, ["f%oo: bar\n"])

    def test_continuation_too_early(self):
        self.assertReadStanzaRaises(ValueError, ["\tbar\n"])

    def test_large(self):
        value = "bla" * 9000
        self.assertReadStanza(rio.Stanza(foo=value),
            ["foo: %s\n" % value])

    def test_non_ascii_char(self):
        self.assertReadStanza(rio.Stanza(foo=u"n\xe5me"),
            [u"foo: n\xe5me\n".encode("utf-8")])


class TestReadUnicodeStanza(tests.TestCase):

    module = None # Filled in by test parameterization

    def assertReadStanza(self, result, line_iter):
        self.assertEquals(result, self.module._read_stanza_unicode(line_iter))

    def assertReadStanzaRaises(self, exception, line_iter):
        self.assertRaises(exception, self.module._read_stanza_unicode,
                          line_iter)

    def test_no_string(self):
        self.assertReadStanzaRaises(TypeError, [21323])

    def test_empty(self):
        self.assertReadStanza(None, [])

    def test_none(self):
        self.assertReadStanza(None, [u""])

    def test_simple(self):
        self.assertReadStanza(rio.Stanza(foo="bar"), [u"foo: bar\n", u""])

    def test_multi_line(self):
        self.assertReadStanza(rio.Stanza(foo="bar\nbla"), 
                [u"foo: bar\n", u"\tbla\n"])

    def test_repeated(self):
        s = rio.Stanza()
        s.add("foo", "bar")
        s.add("foo", "foo")
        self.assertReadStanza(s, [u"foo: bar\n", u"foo: foo\n"])

    def test_invalid_early_colon(self):
        self.assertReadStanzaRaises(ValueError, [u"f:oo: bar\n"])

    def test_invalid_tag(self):
        self.assertReadStanzaRaises(ValueError, [u"f%oo: bar\n"])

    def test_continuation_too_early(self):
        self.assertReadStanzaRaises(ValueError, [u"\tbar\n"])

    def test_large(self):
        value = u"bla" * 9000
        self.assertReadStanza(rio.Stanza(foo=value),
            [u"foo: %s\n" % value])

    def test_non_ascii_char(self):
        self.assertReadStanza(rio.Stanza(foo=u"n\xe5me"), [u"foo: n\xe5me\n"])
