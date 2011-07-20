# Copyright (C) 2006-2011 Canonical Ltd
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

"""Launchpad.net integration plugin for Bazaar.

This plugin provides facilities for working with Bazaar branches that are
hosted on Launchpad (http://launchpad.net).  It provides a directory service 
for referring to Launchpad branches using the "lp:" prefix.  For example,
lp:bzr refers to the Bazaar's main development branch and
lp:~username/project/branch-name can be used to refer to a specific branch.

This plugin provides a bug tracker so that "bzr commit --fixes lp:1234" will
record that revision as fixing Launchpad's bug 1234.

The plugin also provides the following commands:

    launchpad-login: Show or set the Launchpad user ID
    launchpad-open: Open a Launchpad branch page in your web browser
    lp-propose-merge: Propose merging a branch on Launchpad
    register-branch: Register a branch with launchpad.net
    launchpad-mirror: Ask Launchpad to mirror a branch now

"""

# The XMLRPC server address can be overridden by setting the environment
# variable $BZR_LP_XMLRPC_URL

# see http://wiki.bazaar.canonical.com/Specs/BranchRegistrationTool

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    ui,
    trace,
    )
""")

from bzrlib import (
    branch as _mod_branch,
    bzrdir,
    lazy_regex,
    # Since we are a built-in plugin we share the bzrlib version
    version_info,
    )
from bzrlib.commands import (
    Command,
    register_command,
    )
from bzrlib.directory_service import directories
from bzrlib.errors import (
    BzrCommandError,
    InvalidRevisionSpec,
    InvalidURL,
    NoPublicBranch,
    NotBranchError,
    )
from bzrlib.help_topics import topic_registry
from bzrlib.option import (
        Option,
        ListOption,
)


class cmd_register_branch(Command):
    __doc__ = """Register a branch with launchpad.net.

    This command lists a bzr branch in the directory of branches on
    launchpad.net.  Registration allows the branch to be associated with
    bugs or specifications.

    Before using this command you must register the project to which the
    branch belongs, and create an account for yourself on launchpad.net.

    arguments:
        public_url: The publicly visible url for the branch to register.
                    This must be an http or https url (which Launchpad can read
                    from to access the branch). Local file urls, SFTP urls, and
                    bzr+ssh urls will not work.
                    If no public_url is provided, bzr will use the configured
                    public_url if there is one for the current branch, and
                    otherwise error.

    example:
        bzr register-branch http://foo.com/bzr/fooproject.mine \\
                --project fooproject
    """
    takes_args = ['public_url?']
    takes_options = [
         Option('project',
                'Launchpad project short name to associate with the branch.',
                unicode),
         Option('product',
                'Launchpad product short name to associate with the branch.', 
                unicode,
                hidden=True),
         Option('branch-name',
                'Short name for the branch; '
                'by default taken from the last component of the url.',
                unicode),
         Option('branch-title',
                'One-sentence description of the branch.',
                unicode),
         Option('branch-description',
                'Longer description of the purpose or contents of the branch.',
                unicode),
         Option('author',
                "Branch author's email address, if not yourself.",
                unicode),
         Option('link-bug',
                'The bug this branch fixes.',
                int),
         Option('dry-run',
                'Prepare the request but don\'t actually send it.')
        ]


    def run(self,
            public_url=None,
            project='',
            product=None,
            branch_name='',
            branch_title='',
            branch_description='',
            author='',
            link_bug=None,
            dry_run=False):
        from bzrlib.plugins.launchpad.lp_registration import (
            BranchRegistrationRequest, BranchBugLinkRequest,
            DryRunLaunchpadService, LaunchpadService)
        if public_url is None:
            try:
                b = _mod_branch.Branch.open_containing('.')[0]
            except NotBranchError:
                raise BzrCommandError('register-branch requires a public '
                    'branch url - see bzr help register-branch.')
            public_url = b.get_public_branch()
            if public_url is None:
                raise NoPublicBranch(b)
        if product is not None:
            project = product
            trace.note('--product is deprecated; please use --project.')


        rego = BranchRegistrationRequest(branch_url=public_url,
                                         branch_name=branch_name,
                                         branch_title=branch_title,
                                         branch_description=branch_description,
                                         product_name=project,
                                         author_email=author,
                                         )
        linko = BranchBugLinkRequest(branch_url=public_url,
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
        rego.submit(service)
        if link_bug:
            linko.submit(service)
        print 'Branch registered.'

register_command(cmd_register_branch)


class cmd_launchpad_open(Command):
    __doc__ = """Open a Launchpad branch page in your web browser."""

    aliases = ['lp-open']
    takes_options = [
        Option('dry-run',
               'Do not actually open the browser. Just say the URL we would '
               'use.'),
        ]
    takes_args = ['location?']

    def _possible_locations(self, location):
        """Yield possible external locations for the branch at 'location'."""
        yield location
        try:
            branch = _mod_branch.Branch.open_containing(location)[0]
        except NotBranchError:
            return
        branch_url = branch.get_public_branch()
        if branch_url is not None:
            yield branch_url
        branch_url = branch.get_push_location()
        if branch_url is not None:
            yield branch_url

    def _get_web_url(self, service, location):
        from bzrlib.plugins.launchpad.lp_registration import (
            NotLaunchpadBranch)
        for branch_url in self._possible_locations(location):
            try:
                return service.get_web_url_from_branch_url(branch_url)
            except (NotLaunchpadBranch, InvalidURL):
                pass
        raise NotLaunchpadBranch(branch_url)

    def run(self, location=None, dry_run=False):
        from bzrlib.plugins.launchpad.lp_registration import (
            LaunchpadService)
        if location is None:
            location = u'.'
        web_url = self._get_web_url(LaunchpadService(), location)
        trace.note('Opening %s in web browser' % web_url)
        if not dry_run:
            import webbrowser   # this import should not be lazy
                                # otherwise bzr.exe lacks this module
            webbrowser.open(web_url)

register_command(cmd_launchpad_open)


class cmd_launchpad_login(Command):
    __doc__ = """Show or set the Launchpad user ID.

    When communicating with Launchpad, some commands need to know your
    Launchpad user ID.  This command can be used to set or show the
    user ID that Bazaar will use for such communication.

    :Examples:
      Show the Launchpad ID of the current user::

          bzr launchpad-login

      Set the Launchpad ID of the current user to 'bob'::

          bzr launchpad-login bob
    """
    aliases = ['lp-login']
    takes_args = ['name?']
    takes_options = [
        'verbose',
        Option('no-check',
               "Don't check that the user name is valid."),
        ]

    def run(self, name=None, no_check=False, verbose=False):
        # This is totally separate from any launchpadlib login system.
        from bzrlib.plugins.launchpad import account
        check_account = not no_check

        if name is None:
            username = account.get_lp_login()
            if username:
                if check_account:
                    account.check_lp_login(username)
                    if verbose:
                        self.outf.write(
                            "Launchpad user ID exists and has SSH keys.\n")
                self.outf.write(username + '\n')
            else:
                self.outf.write('No Launchpad user ID configured.\n')
                return 1
        else:
            name = name.lower()
            if check_account:
                account.check_lp_login(name)
                if verbose:
                    self.outf.write(
                        "Launchpad user ID exists and has SSH keys.\n")
            account.set_lp_login(name)
            if verbose:
                self.outf.write("Launchpad user ID set to '%s'.\n" % (name,))

register_command(cmd_launchpad_login)


# XXX: cmd_launchpad_mirror is untested
class cmd_launchpad_mirror(Command):
    __doc__ = """Ask Launchpad to mirror a branch now."""

    aliases = ['lp-mirror']
    takes_args = ['location?']

    def run(self, location='.'):
        from bzrlib.plugins.launchpad import lp_api
        from bzrlib.plugins.launchpad.lp_registration import LaunchpadService
        branch, _ = _mod_branch.Branch.open_containing(location)
        service = LaunchpadService()
        launchpad = lp_api.login(service)
        lp_branch = lp_api.LaunchpadBranch.from_bzr(launchpad, branch,
                create_missing=False)
        lp_branch.lp.requestMirror()


register_command(cmd_launchpad_mirror)


class cmd_lp_propose_merge(Command):
    __doc__ = """Propose merging a branch on Launchpad.

    This will open your usual editor to provide the initial comment.  When it
    has created the proposal, it will open it in your default web browser.

    The branch will be proposed to merge into SUBMIT_BRANCH.  If SUBMIT_BRANCH
    is not supplied, the remembered submit branch will be used.  If no submit
    branch is remembered, the development focus will be used.

    By default, the SUBMIT_BRANCH's review team will be requested to review
    the merge proposal.  This can be overriden by specifying --review (-R).
    The parameter the launchpad account name of the desired reviewer.  This
    may optionally be followed by '=' and the review type.  For example:

      bzr lp-propose-merge --review jrandom --review review-team=qa

    This will propose a merge,  request "jrandom" to perform a review of
    unspecified type, and request "review-team" to perform a "qa" review.
    """

    takes_options = [Option('staging',
                            help='Propose the merge on staging.'),
                     Option('message', short_name='m', type=unicode,
                            help='Commit message.'),
                     Option('approve',
                            help='Mark the proposal as approved immediately.'),
                     ListOption('review', short_name='R', type=unicode,
                            help='Requested reviewer and optional type.')]

    takes_args = ['submit_branch?']

    aliases = ['lp-submit', 'lp-propose']

    def run(self, submit_branch=None, review=None, staging=False,
            message=None, approve=False):
        from bzrlib.plugins.launchpad import lp_propose
        tree, branch, relpath = bzrdir.BzrDir.open_containing_tree_or_branch(
            '.')
        if review is None:
            reviews = None
        else:
            reviews = []
            for review in review:
                if '=' in review:
                    reviews.append(review.split('=', 2))
                else:
                    reviews.append((review, ''))
            if submit_branch is None:
                submit_branch = branch.get_submit_branch()
        if submit_branch is None:
            target = None
        else:
            target = _mod_branch.Branch.open(submit_branch)
        proposer = lp_propose.Proposer(tree, branch, target, message,
                                       reviews, staging, approve=approve)
        proposer.check_proposal()
        proposer.create_proposal()


register_command(cmd_lp_propose_merge)


class cmd_lp_find_proposal(Command):

    __doc__ = """Find the proposal to merge this revision.

    Finds the merge proposal(s) that discussed landing the specified revision.
    This works only if the selected branch was the merge proposal target, and
    if the merged_revno is recorded for the merge proposal.  The proposal(s)
    are opened in a web browser.

    Any revision involved in the merge may be specified-- the revision in
    which the merge was performed, or one of the revisions that was merged.

    So, to find the merge proposal that reviewed line 1 of README::

      bzr lp-find-proposal -r annotate:README:1
    """

    takes_options = ['revision']

    def run(self, revision=None):
        from bzrlib.plugins.launchpad import lp_api
        import webbrowser
        b = _mod_branch.Branch.open_containing('.')[0]
        pb = ui.ui_factory.nested_progress_bar()
        b.lock_read()
        try:
            revno = self._find_merged_revno(revision, b, pb)
            merged = self._find_proposals(revno, b, pb)
            if len(merged) == 0:
                raise BzrCommandError('No review found.')
            trace.note('%d proposals(s) found.' % len(merged))
            for mp in merged:
                webbrowser.open(lp_api.canonical_url(mp))
        finally:
            b.unlock()
            pb.finished()

    def _find_merged_revno(self, revision, b, pb):
        if revision is None:
            return b.revno()
        pb.update('Finding revision-id')
        revision_id = revision[0].as_revision_id(b)
        # a revno spec is necessarily on the mainline.
        if self._is_revno_spec(revision[0]):
            merging_revision = revision_id
        else:
            graph = b.repository.get_graph()
            pb.update('Finding merge')
            merging_revision = graph.find_lefthand_merger(
                revision_id, b.last_revision())
            if merging_revision is None:
                raise InvalidRevisionSpec(revision[0].user_spec, b)
        pb.update('Finding revno')
        return b.revision_id_to_revno(merging_revision)

    def _find_proposals(self, revno, b, pb):
        launchpad = lp_api.login(lp_registration.LaunchpadService())
        pb.update('Finding Launchpad branch')
        lpb = lp_api.LaunchpadBranch.from_bzr(launchpad, b,
                                              create_missing=False)
        pb.update('Finding proposals')
        return list(lpb.lp.getMergeProposals(status=['Merged'],
                                             merged_revnos=[revno]))


    @staticmethod
    def _is_revno_spec(spec):
        try:
            int(spec.user_spec)
        except ValueError:
            return False
        else:
            return True


register_command(cmd_lp_find_proposal)


def _register_directory():
    directories.register_lazy('lp:', 'bzrlib.plugins.launchpad.lp_directory',
                              'LaunchpadDirectory',
                              'Launchpad-based directory service',)
    directories.register_lazy(
        'debianlp:', 'bzrlib.plugins.launchpad.lp_directory',
        'LaunchpadDirectory',
        'debianlp: shortcut')
    directories.register_lazy(
        'ubuntu:', 'bzrlib.plugins.launchpad.lp_directory',
        'LaunchpadDirectory',
        'ubuntu: shortcut')

_register_directory()

# This is kept in __init__ so that we don't load lp_api_lite unless the branch
# actually matches. That way we can avoid importing extra dependencies like
# json.
_package_branch = lazy_regex.lazy_compile(
    r'bazaar.launchpad.net.*?/'
    r'(?P<user>~[^/]+/)?(?P<archive>ubuntu|debian)/(?P<series>[^/]+/)?'
    r'(?P<project>[^/]+)(?P<branch>/[^/]+)?'
    )

def _get_package_branch_info(url):
    """Determine the packaging information for this URL.

    :return: If this isn't a packaging branch, return None. If it is, return
        (archive, series, project)
    """
    m = _package_branch.search(url)
    if m is None:
        return
    archive, series, project, user = m.group('archive', 'series',
                                             'project', 'user')
    if series is not None:
        # series is optional, so the regex includes the extra '/', we don't
        # want to send that on (it causes Internal Server Errors.)
        series = series.strip('/')
    if user is not None:
        user = user.strip('~/')
        if user != 'ubuntu-branches':
            return None
    return archive, series, project


def _check_is_up_to_date(the_branch):
    info = _get_package_branch_info(the_branch.base)
    if info is None:
        return
    c = the_branch.get_config()
    verbosity = c.get_user_option('bzr.plugins.launchpad.packaging_verbosity')
    if verbosity is not None:
        verbosity = verbosity.lower()
    if verbosity == 'off':
        trace.mutter('not checking %s because verbosity is turned off'
                     % (the_branch.base,))
        return
    archive, series, project = info
    from bzrlib.plugins.launchpad import lp_api_lite
    latest_pub = lp_api_lite.LatestPublication(archive, series, project)
    lp_api_lite.report_freshness(the_branch, verbosity, latest_pub)


def _register_hooks():
    _mod_branch.Branch.hooks.install_named_hook('open',
        _check_is_up_to_date, 'package-branch-up-to-date')


_register_hooks()

def load_tests(basic_tests, module, loader):
    testmod_names = [
        'test_account',
        'test_register',
        'test_lp_api',
        'test_lp_api_lite',
        'test_lp_directory',
        'test_lp_login',
        'test_lp_open',
        'test_lp_service',
        ]
    basic_tests.addTest(loader.loadTestsFromModuleNames(
            ["%s.%s" % (__name__, tmn) for tmn in testmod_names]))
    return basic_tests


_launchpad_help = """Integration with Launchpad.net

Launchpad.net provides free Bazaar branch hosting with integrated bug and
specification tracking.

The bzr client (through the plugin called 'launchpad') has special
features to communicate with Launchpad:

    * The launchpad-login command tells Bazaar your Launchpad user name. This
      is then used by the 'lp:' transport to download your branches using
      bzr+ssh://.

    * The 'lp:' transport uses Launchpad as a directory service: for example
      'lp:bzr' and 'lp:python' refer to the main branches of the relevant
      projects and may be branched, logged, etc. You can also use the 'lp:'
      transport to refer to specific branches, e.g. lp:~bzr/bzr/trunk.

    * The 'lp:' bug tracker alias can expand launchpad bug numbers to their
      URLs for use with 'bzr commit --fixes', e.g. 'bzr commit --fixes lp:12345'
      will record a revision property that marks that revision as fixing
      Launchpad bug 12345. When you push that branch to Launchpad it will
      automatically be linked to the bug report.

    * The register-branch command tells Launchpad about the url of a
      public branch.  Launchpad will then mirror the branch, display
      its contents and allow it to be attached to bugs and other
      objects.

For more information see http://help.launchpad.net/
"""
topic_registry.register('launchpad',
    _launchpad_help,
    'Using Bazaar with Launchpad.net')
