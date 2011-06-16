# Copyright (C) 2006, 2007, 2009, 2010, 2011 Canonical Ltd
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

"""Command which looks for unsigned commits by the current user, and signs them.
"""

from bzrlib.lazy_import import lazy_import
lazy_import(globals(), """
from bzrlib import (
    bzrdir as _mod_bzrdir,
    gpg,
    revision as _mod_revision,
    )
""")
from bzrlib.commands import Command
from bzrlib.option import Option


class cmd_sign_my_commits(Command):
    __doc__ = """Sign all commits by a given committer.

    If location is not specified the local tree is used.
    If committer is not specified the default committer is used.

    This does not sign commits that already have signatures.
    """
    # Note that this signs everything on the branch's ancestry
    # (both mainline and merged), but not other revisions that may be in the
    # repository

    takes_options = [
            Option('dry-run',
                   help='Don\'t actually sign anything, just print'
                        ' the revisions that would be signed.'),
            ]
    takes_args = ['location?', 'committer?']

    def run(self, location=None, committer=None, dry_run=False):
        if location is None:
            bzrdir = _mod_bzrdir.BzrDir.open_containing('.')[0]
        else:
            # Passed in locations should be exact
            bzrdir = _mod_bzrdir.BzrDir.open(location)
        branch = bzrdir.open_branch()
        repo = branch.repository
        branch_config = branch.get_config()

        if committer is None:
            committer = branch_config.username()
        gpg_strategy = gpg.GPGStrategy(branch_config)

        count = 0
        repo.lock_write()
        try:
            graph = repo.get_graph()
            repo.start_write_group()
            try:
                for rev_id, parents in graph.iter_ancestry(
                        [branch.last_revision()]):
                    if _mod_revision.is_null(rev_id):
                        continue
                    if repo.has_signature_for_revision_id(rev_id):
                        continue
                    rev = repo.get_revision(rev_id)
                    if rev.committer != committer:
                        continue
                    # We have a revision without a signature who has a
                    # matching committer, start signing
                    print rev_id
                    count += 1
                    if not dry_run:
                        repo.sign_revision(rev_id, gpg_strategy)
            except:
                repo.abort_write_group()
                raise
            else:
                repo.commit_write_group()
        finally:
            repo.unlock()
        print 'Signed %d revisions' % (count,)


