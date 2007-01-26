# Copyright (C) 2006, 2007 Canonical Ltd
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

"""Launchpad.net branch registration plugin for bzr

This adds commands that tell launchpad about newly-created branches, etc.

To install this file, put the 'bzr_lp' directory, or a symlink to it,
in your ~/.bazaar/plugins/ directory.
"""

# The XMLRPC server address can be overridden by setting the environment
# variable $BZR_LP_XMLRPL_URL

# see http://bazaar-vcs.org/Specs/BranchRegistrationTool

from bzrlib.commands import Command, Option, register_command



class cmd_register_branch(Command):
    """Register a branch with launchpad.net.

    This command lists a bzr branch in the directory of branches on
    launchpad.net.  Registration allows the bug to be associated with
    bugs or specifications.
    
    Before using this command you must register the product to which the
    branch belongs, and create an account for yourself on launchpad.net.

    arguments:
        branch_url: The publicly visible url for the branch.
                    This must be an http or https url, not a local file
                    path.

    example:
        bzr register-branch http://foo.com/bzr/fooproduct.mine \\
                --product fooproduct
    """
    takes_args = ['branch_url']
    takes_options = \
        [Option('product', 
                'launchpad product short name to associate with the branch',
                unicode),
         Option('branch-name',
                'short name for the branch; '
                'by default taken from the last component of the url',
                unicode),
         Option('branch-title',
                'one-sentence description of the branch',
                unicode),
         Option('branch-description',
                'longer description of the purpose or contents of the branch',
                unicode),
         Option('author', 
                'email of the branch\'s author, if not yourself',
                unicode),
         Option('link-bug',
                'the bug this branch fixes',
                int),
         Option('dry-run',
                'prepare the request but don\'t actually send it')
        ]


    def run(self, 
            branch_url, 
            product='',
            branch_name='',
            branch_title='',
            branch_description='',
            author='',
            link_bug=None,
            dry_run=False):
        from lp_registration import (
            LaunchpadService, BranchRegistrationRequest, BranchBugLinkRequest,
            DryRunLaunchpadService)
        rego = BranchRegistrationRequest(branch_url=branch_url,
                                         branch_name=branch_name,
                                         branch_title=branch_title,
                                         branch_description=branch_description,
                                         product_name=product,
                                         author_email=author,
                                         )
        linko = BranchBugLinkRequest(branch_url=branch_url,
                                     bug_id=link_bug)
        if not dry_run:
            service = LaunchpadService()
            # This gives back the xmlrpc url that can be used for future
            # operations on the branch.  It's not so useful to print to the
            # user since they can't do anything with it from a web browser; it
            # might be nice for the server to tell us about an html url as
            # well.
        else:
            # Run on service entirely in memory
            service = DryRunLaunchpadService()
        service.gather_user_credentials()
        branch_object_url = rego.submit(service)
        if link_bug:
            link_bug_url = linko.submit(service)
        print 'Branch registered.'

register_command(cmd_register_branch)

def test_suite():
    """Called by bzrlib to fetch tests for this plugin"""
    from unittest import TestSuite, TestLoader
    import test_register
    import test_lp_indirect

    loader = TestLoader()
    suite = TestSuite()
    for m in [test_register, test_lp_indirect]:
        suite.addTests(loader.loadTestsFromModule(m))
    return suite
