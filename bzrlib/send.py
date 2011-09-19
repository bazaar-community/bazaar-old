# Copyright (C) 2009, 2010 Canonical Ltd
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


import os
import time

from bzrlib import (
    bzrdir,
    errors,
    osutils,
    registry,
    trace,
    )
from bzrlib.i18n import gettext
from bzrlib.branch import (
    Branch,
    )
from bzrlib.revision import (
    NULL_REVISION,
    )


format_registry = registry.Registry()


def send(submit_branch, revision, public_branch, remember, format,
         no_bundle, no_patch, output, from_, mail_to, message, body,
         to_file, strict=None):
    tree, branch = bzrdir.BzrDir.open_containing_tree_or_branch(from_)[:2]
    # we may need to write data into branch's repository to calculate
    # the data to send.
    branch.lock_write()
    try:
        if output is None:
            config = branch.get_config()
            if mail_to is None:
                mail_to = config.get_user_option('submit_to')
            mail_client = config.get_mail_client()
            if (not getattr(mail_client, 'supports_body', False)
                and body is not None):
                raise errors.BzrCommandError(gettext(
                    'Mail client "%s" does not support specifying body') %
                    mail_client.__class__.__name__)
        if remember and submit_branch is None:
            raise errors.BzrCommandError(gettext(
                '--remember requires a branch to be specified.'))
        stored_submit_branch = branch.get_submit_branch()
        remembered_submit_branch = None
        if submit_branch is None:
            submit_branch = stored_submit_branch
            remembered_submit_branch = "submit"
        else:
            # Remembers if asked explicitly or no previous location is set
            if remember or (remember is None and stored_submit_branch is None):
                branch.set_submit_branch(submit_branch)
        if submit_branch is None:
            submit_branch = branch.get_parent()
            remembered_submit_branch = "parent"
        if submit_branch is None:
            raise errors.BzrCommandError(gettext('No submit branch known or'
                                         ' specified'))
        if remembered_submit_branch is not None:
            trace.note(gettext('Using saved %s location "%s" to determine what '
                       'changes to submit.'), remembered_submit_branch,
                       submit_branch)

        if mail_to is None or format is None:
            # TODO: jam 20090716 we open the submit_branch here, but we *don't*
            #       pass it down into the format creation, so it will have to
            #       open it again
            submit_br = Branch.open(submit_branch)
            submit_config = submit_br.get_config()
            if mail_to is None:
                mail_to = submit_config.get_user_option("child_submit_to")
            if format is None:
                formatname = submit_br.get_child_submit_format()
                try:
                    format = format_registry.get(formatname)
                except KeyError:
                    raise errors.BzrCommandError(gettext("No such send format '%s'.") % 
                                                 formatname)

        stored_public_branch = branch.get_public_branch()
        if public_branch is None:
            public_branch = stored_public_branch
        # Remembers if asked explicitly or no previous location is set
        elif (remember
              or (remember is None and stored_public_branch is None)):
            branch.set_public_branch(public_branch)
        if no_bundle and public_branch is None:
            raise errors.BzrCommandError(gettext('No public branch specified or'
                                         ' known'))
        base_revision_id = None
        revision_id = None
        if revision is not None:
            if len(revision) > 2:
                raise errors.BzrCommandError(gettext('bzr send takes '
                    'at most two one revision identifiers'))
            revision_id = revision[-1].as_revision_id(branch)
            if len(revision) == 2:
                base_revision_id = revision[0].as_revision_id(branch)
        if revision_id is None:
            if tree is not None:
                tree.check_changed_or_out_of_date(
                    strict, 'send_strict',
                    more_error='Use --no-strict to force the send.',
                    more_warning='Uncommitted changes will not be sent.')
            revision_id = branch.last_revision()
        if revision_id == NULL_REVISION:
            raise errors.BzrCommandError(gettext('No revisions to submit.'))
        if format is None:
            format = format_registry.get()
        directive = format(branch, revision_id, submit_branch,
            public_branch, no_patch, no_bundle, message, base_revision_id)
        if output is None:
            directive.compose_merge_request(mail_client, mail_to, body,
                                            branch, tree)
        else:
            if directive.multiple_output_files:
                if output == '-':
                    raise errors.BzrCommandError(gettext('- not supported for '
                        'merge directives that use more than one output file.'))
                if not os.path.exists(output):
                    os.mkdir(output, 0755)
                for (filename, lines) in directive.to_files():
                    path = os.path.join(output, filename)
                    outfile = open(path, 'wb')
                    try:
                        outfile.writelines(lines)
                    finally:
                        outfile.close()
            else:
                if output == '-':
                    outfile = to_file
                else:
                    outfile = open(output, 'wb')
                try:
                    outfile.writelines(directive.to_lines())
                finally:
                    if outfile is not to_file:
                        outfile.close()
    finally:
        branch.unlock()


def _send_4(branch, revision_id, submit_branch, public_branch,
            no_patch, no_bundle, message, base_revision_id):
    from bzrlib import merge_directive
    return merge_directive.MergeDirective2.from_objects(
        branch.repository, revision_id, time.time(),
        osutils.local_time_offset(), submit_branch,
        public_branch=public_branch, include_patch=not no_patch,
        include_bundle=not no_bundle, message=message,
        base_revision_id=base_revision_id)


def _send_0_9(branch, revision_id, submit_branch, public_branch,
              no_patch, no_bundle, message, base_revision_id):
    if not no_bundle:
        if not no_patch:
            patch_type = 'bundle'
        else:
            raise errors.BzrCommandError(gettext('Format 0.9 does not'
                ' permit bundle with no patch'))
    else:
        if not no_patch:
            patch_type = 'diff'
        else:
            patch_type = None
    from bzrlib import merge_directive
    return merge_directive.MergeDirective.from_objects(
        branch.repository, revision_id, time.time(),
        osutils.local_time_offset(), submit_branch,
        public_branch=public_branch, patch_type=patch_type,
        message=message)


format_registry.register('4', 
    _send_4, 'Bundle format 4, Merge Directive 2 (default)')
format_registry.register('0.9',
    _send_0_9, 'Bundle format 0.9, Merge Directive 1')
format_registry.default_key = '4'
