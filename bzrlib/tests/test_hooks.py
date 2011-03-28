# Copyright (C) 2007-2010 Canonical Ltd
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

"""Tests for the core Hooks logic."""

from bzrlib import (
    branch,
    errors,
    pyutils,
    tests,
    )
from bzrlib.hooks import (
    HookPoint,
    Hooks,
    install_lazy_named_hook,
    known_hooks,
    known_hooks_key_to_object,
    known_hooks_key_to_parent_and_attribute,
    _lazy_hooks,
    )
from bzrlib.symbol_versioning import (
    deprecated_in,
    )


class TestHooks(tests.TestCase):

    def test_create_hook_first(self):
        hooks = Hooks()
        doc = ("Invoked after changing the tip of a branch object. Called with"
            "a bzrlib.branch.PostChangeBranchTipParams object")
        hook = HookPoint("post_tip_change", doc, (0, 15), None)
        hooks.create_hook(hook)
        self.assertEqual(hook, hooks['post_tip_change'])

    def test_create_hook_name_collision_errors(self):
        hooks = Hooks()
        doc = ("Invoked after changing the tip of a branch object. Called with"
            "a bzrlib.branch.PostChangeBranchTipParams object")
        hook = HookPoint("post_tip_change", doc, (0, 15), None)
        hook2 = HookPoint("post_tip_change", None, None, None)
        hooks.create_hook(hook)
        self.assertRaises(errors.DuplicateKey, hooks.create_hook, hook2)
        self.assertEqual(hook, hooks['post_tip_change'])

    def test_docs(self):
        """docs() should return something reasonable about the Hooks."""
        class MyHooks(Hooks):
            pass
        hooks = MyHooks()
        hooks['legacy'] = []
        hook1 = HookPoint('post_tip_change',
            "Invoked after the tip of a branch changes. Called with "
            "a ChangeBranchTipParams object.", (1, 4), None)
        hook2 = HookPoint('pre_tip_change',
            "Invoked before the tip of a branch changes. Called with "
            "a ChangeBranchTipParams object. Hooks should raise "
            "TipChangeRejected to signal that a tip change is not permitted.",
            (1, 6), None)
        hooks.create_hook(hook1)
        hooks.create_hook(hook2)
        self.assertEqualDiff(
            "MyHooks\n"
            "-------\n"
            "\n"
            "legacy\n"
            "~~~~~~\n"
            "\n"
            "An old-style hook. For documentation see the __init__ method of 'MyHooks'\n"
            "\n"
            "post_tip_change\n"
            "~~~~~~~~~~~~~~~\n"
            "\n"
            "Introduced in: 1.4\n"
            "\n"
            "Invoked after the tip of a branch changes. Called with a\n"
            "ChangeBranchTipParams object.\n"
            "\n"
            "pre_tip_change\n"
            "~~~~~~~~~~~~~~\n"
            "\n"
            "Introduced in: 1.6\n"
            "\n"
            "Invoked before the tip of a branch changes. Called with a\n"
            "ChangeBranchTipParams object. Hooks should raise TipChangeRejected to\n"
            "signal that a tip change is not permitted.\n", hooks.docs())

    def test_install_named_hook_raises_unknown_hook(self):
        hooks = Hooks()
        self.assertRaises(errors.UnknownHook, hooks.install_named_hook, 'silly',
                          None, "")

    def test_install_named_hook_appends_known_hook(self):
        hooks = Hooks()
        hooks['set_rh'] = []
        hooks.install_named_hook('set_rh', None, "demo")
        self.assertEqual(hooks['set_rh'], [None])

    def test_install_named_hook_and_retrieve_name(self):
        hooks = Hooks()
        hooks['set_rh'] = []
        hooks.install_named_hook('set_rh', None, "demo")
        self.assertEqual("demo", hooks.get_hook_name(None))

    hooks = Hooks("bzrlib.tests.test_hooks", "TestHooks.hooks")

    def test_install_lazy_named_hook(self):
        # When the hook points are not yet registered the hook is
        # added to the _lazy_hooks dictionary in bzrlib.hooks.
        self.hooks.add_hook('set_rh', "doc", (0, 15))
        set_rh = lambda: None
        install_lazy_named_hook('bzrlib.tests.test_hooks',
            'TestHooks.hooks', 'set_rh', set_rh, "demo")
        set_rh_lazy_hooks = _lazy_hooks[
            ('bzrlib.tests.test_hooks', 'TestHooks.hooks', 'set_rh')]
        self.assertEquals(1, len(set_rh_lazy_hooks))
        self.assertEquals(set_rh, set_rh_lazy_hooks[0][0].get_obj())
        self.assertEquals("demo", set_rh_lazy_hooks[0][1])
        self.assertEqual(list(TestHooks.hooks['set_rh']), [set_rh])

    set_rh = lambda: None

    def test_install_named_hook_lazy(self):
        hooks = Hooks()
        hooks['set_rh'] = HookPoint("set_rh", "doc", (0, 15), None)
        hooks.install_named_hook_lazy('set_rh', 'bzrlib.tests.test_hooks',
            'TestHooks.set_rh', "demo")
        self.assertEqual(list(hooks['set_rh']), [TestHooks.set_rh])

    def test_install_named_hook_lazy_old(self):
        # An exception is raised if a lazy hook is raised for
        # an old style hook point.
        hooks = Hooks()
        hooks['set_rh'] = []
        self.assertRaises(errors.UnsupportedOperation,
            hooks.install_named_hook_lazy,
            'set_rh', 'bzrlib.tests.test_hooks', 'TestHooks.set_rh',
            "demo")

    def test_valid_lazy_hooks(self):
        # Make sure that all the registered lazy hooks are referring to existing
        # hook points which allow lazy registration.
        for key, callbacks in _lazy_hooks.iteritems():
            (module_name, member_name, hook_name) = key
            obj = pyutils.get_named_object(module_name, member_name)
            self.assertEquals(obj._module, module_name)
            self.assertEquals(obj._member_name, member_name)
            self.assertTrue(hook_name in obj)
            self.assertIs(callbacks, obj[hook_name]._callbacks)


class TestHook(tests.TestCase):

    def test___init__(self):
        doc = ("Invoked after changing the tip of a branch object. Called with"
            "a bzrlib.branch.PostChangeBranchTipParams object")
        hook = HookPoint("post_tip_change", doc, (0, 15), None)
        self.assertEqual(doc, hook.__doc__)
        self.assertEqual("post_tip_change", hook.name)
        self.assertEqual((0, 15), hook.introduced)
        self.assertEqual(None, hook.deprecated)
        self.assertEqual([], list(hook))

    def test_docs(self):
        doc = ("Invoked after changing the tip of a branch object. Called with"
            " a bzrlib.branch.PostChangeBranchTipParams object")
        hook = HookPoint("post_tip_change", doc, (0, 15), None)
        self.assertEqual("post_tip_change\n"
            "~~~~~~~~~~~~~~~\n"
            "\n"
            "Introduced in: 0.15\n"
            "\n"
            "Invoked after changing the tip of a branch object. Called with a\n"
            "bzrlib.branch.PostChangeBranchTipParams object\n", hook.docs())

    def test_hook(self):
        hook = HookPoint("foo", "no docs", None, None)
        def callback():
            pass
        hook.hook(callback, "my callback")
        self.assertEqual([callback], list(hook))

    def lazy_callback():
        pass

    def test_lazy_hook(self):
        hook = HookPoint("foo", "no docs", None, None)
        hook.hook_lazy(
            "bzrlib.tests.test_hooks", "TestHook.lazy_callback",
            "my callback")
        self.assertEqual([TestHook.lazy_callback], list(hook))

    def test___repr(self):
        # The repr should list all the callbacks, with names.
        hook = HookPoint("foo", "no docs", None, None)
        def callback():
            pass
        hook.hook(callback, "my callback")
        callback_repr = repr(callback)
        self.assertEqual(
            '<HookPoint(foo), callbacks=[%s(my callback)]>' %
            callback_repr, repr(hook))


class TestHookRegistry(tests.TestCase):

    def test_items_are_reasonable_keys(self):
        # All the items in the known_hooks registry need to map from
        # (module_name, member_name) tuples to the callable used to get an
        # empty Hooks for that attribute. This is used to support the test
        # suite which needs to generate empty hooks (and HookPoints) to ensure
        # isolation and prevent tests failing spuriously.
        for key, factory in known_hooks.items():
            self.assertTrue(callable(factory),
                "The factory(%r) for %r is not callable" % (factory, key))
            obj = known_hooks_key_to_object(key)
            self.assertIsInstance(obj, Hooks)
            new_hooks = factory()
            self.assertIsInstance(obj, Hooks)
            self.assertEqual(type(obj), type(new_hooks))
            self.assertEqual("No hook name", new_hooks.get_hook_name(None))

    def test_known_hooks_key_to_object(self):
        self.assertIs(branch.Branch.hooks,
            known_hooks_key_to_object(('bzrlib.branch', 'Branch.hooks')))

    def test_known_hooks_key_to_parent_and_attribute_deprecated(self):
        self.assertEqual((branch.Branch, 'hooks'),
            self.applyDeprecated(deprecated_in((2,3)),
                known_hooks_key_to_parent_and_attribute,
                ('bzrlib.branch', 'Branch.hooks')))
        self.assertEqual((branch, 'Branch'),
            self.applyDeprecated(deprecated_in((2,3)),
                known_hooks_key_to_parent_and_attribute,
                ('bzrlib.branch', 'Branch')))

    def test_known_hooks_key_to_parent_and_attribute(self):
        self.assertEqual((branch.Branch, 'hooks'),
            known_hooks.key_to_parent_and_attribute(
            ('bzrlib.branch', 'Branch.hooks')))
        self.assertEqual((branch, 'Branch'),
            known_hooks.key_to_parent_and_attribute(
            ('bzrlib.branch', 'Branch')))
