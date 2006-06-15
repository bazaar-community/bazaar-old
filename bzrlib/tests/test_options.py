# Copyright (C) 2005, 2006 Canonical Ltd

from bzrlib.tests import TestCase
from bzrlib.commands import Command, parse_args
from bzrlib.builtins import cmd_commit, cmd_log, cmd_status

# TODO: might be nice to just parse them into a structured form and test
# against that, rather than running the whole command.

class OptionTests(TestCase):
    """Command-line option tests"""

    def test_parse_args(self):
        """Option parser"""
        eq = self.assertEquals
        eq(parse_args(cmd_commit(), ['--help']),
           ([], {'help': True}))
        eq(parse_args(cmd_status(), ['--all']),
           ([], {'all': True}))
        eq(parse_args(cmd_commit(), ['--message=biter']),
           ([], {'message': 'biter'}))
        ## eq(parse_args(cmd_log(),  '-r 500'.split()),
        ##   ([], {'revision': RevisionSpec_int(500)}))

    def test_no_more_opts(self):
        """Terminated options"""
        self.assertEquals(parse_args(cmd_commit(), ['--', '-file-with-dashes']),
                          (['-file-with-dashes'], {}))

    def test_option_help(self):
        """Options have help strings."""
        out, err = self.run_bzr_captured(['commit', '--help'])
        self.assertContainsRe(out, r'--file.*file containing commit message')
        self.assertContainsRe(out, r'--help.*-h')

    def test_option_help_global(self):
        """Global options have help strings."""
        out, err = self.run_bzr_captured(['help', 'status'])
        self.assertContainsRe(out, r'--show-ids.*show internal object')

    def test_option_arg_help(self):
        """Help message shows option arguments."""
        out, err = self.run_bzr_captured(['help', 'commit'])
        self.assertEquals(err, '')
        self.assertContainsRe(out, r'--file[ =]MSGFILE')

    def test_unknown_short_opt(self):
        out, err = self.run_bzr_captured(['help', '-r'], retcode=3)
        self.assertContainsRe(err, r'unknown option')


#     >>> parse_args('log -r 500'.split())
#     (['log'], {'revision': [<RevisionSpec_int 500>]})
#     >>> parse_args('log -r500..600'.split())
#     (['log'], {'revision': [<RevisionSpec_int 500>, <RevisionSpec_int 600>]})
#     >>> parse_args('log -vr500..600'.split())
#     (['log'], {'verbose': True, 'revision': [<RevisionSpec_int 500>, <RevisionSpec_int 600>]})
#     >>> parse_args('log -rrevno:500..600'.split()) #the r takes an argument
#     (['log'], {'revision': [<RevisionSpec_revno revno:500>, <RevisionSpec_int 600>]})
