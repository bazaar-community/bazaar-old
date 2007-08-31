# Copyright (C) 2004, 2005, 2006, 2007 Canonical Ltd
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

"""File annotate based on weave storage"""

# TODO: Choice of more or less verbose formats:
# 
# interposed: show more details between blocks of modified lines

# TODO: Show which revision caused a line to merge into the parent

# TODO: perhaps abbreviate timescales depending on how recent they are
# e.g. "3:12 Tue", "13 Oct", "Oct 2005", etc.  

import sys
import time

from bzrlib import (
    errors,
    osutils,
    patiencediff,
    tsort,
    )
from bzrlib.config import extract_email_address


def annotate_file(branch, rev_id, file_id, verbose=False, full=False,
                  to_file=None, show_ids=False):
    if to_file is None:
        to_file = sys.stdout

    prevanno=''
    last_rev_id = None
    if show_ids:
        w = branch.repository.weave_store.get_weave(file_id,
            branch.repository.get_transaction())
        annotations = list(w.annotate_iter(rev_id))
        max_origin_len = max(len(origin) for origin, text in annotations)
        for origin, text in annotations:
            if full or last_rev_id != origin:
                this = origin
            else:
                this = ''
            to_file.write('%*s | %s' % (max_origin_len, this, text))
            last_rev_id = origin
        return

    annotation = list(_annotate_file(branch, rev_id, file_id))
    if len(annotation) == 0:
        max_origin_len = max_revno_len = max_revid_len = 0
    else:
        max_origin_len = max(len(x[1]) for x in annotation)
        max_revno_len = max(len(x[0]) for x in annotation)
        max_revid_len = max(len(x[3]) for x in annotation)

    if not verbose:
        max_revno_len = min(max_revno_len, 12)
    max_revno_len = max(max_revno_len, 3)

    for (revno_str, author, date_str, line_rev_id, text) in annotation:
        if verbose:
            anno = '%-*s %-*s %8s ' % (max_revno_len, revno_str,
                                       max_origin_len, author, date_str)
        else:
            if len(revno_str) > max_revno_len:
                revno_str = revno_str[:max_revno_len-1] + '>'
            anno = "%-*s %-7s " % (max_revno_len, revno_str, author[:7])

        if anno.lstrip() == "" and full: anno = prevanno
        try:
            to_file.write(anno)
        except UnicodeEncodeError:
            # cmd_annotate should be passing in an 'exact' object, which means
            # we have a direct handle to sys.stdout or equivalent. It may not
            # be able to handle the exact Unicode characters, but 'annotate' is
            # a user function (non-scripting), so shouldn't die because of
            # unrepresentable annotation characters. So encode using 'replace',
            # and write them again.
            encoding = getattr(to_file, 'encoding', None) or \
                    osutils.get_terminal_encoding()
            to_file.write(anno.encode(encoding, 'replace'))
        print >>to_file, '| %s' % (text,)
        prevanno=anno


def _annotate_file(branch, rev_id, file_id):
    """Yield the origins for each line of a file.

    This includes detailed information, such as the author name, and
    date string for the commit, rather than just the revision id.
    """
    revision_id_to_revno = branch.get_revision_id_to_revno_map()
    w = branch.repository.weave_store.get_weave(file_id,
        branch.repository.get_transaction())
    last_origin = None
    annotations = list(w.annotate_iter(rev_id))
    revision_ids = set(o for o, t in annotations)
    revision_ids = [o for o in revision_ids if 
                    branch.repository.has_revision(o)]
    revisions = dict((r.revision_id, r) for r in 
                     branch.repository.get_revisions(revision_ids))
    for origin, text in annotations:
        text = text.rstrip('\r\n')
        if origin == last_origin:
            (revno_str, author, date_str) = ('','','')
        else:
            last_origin = origin
            if origin not in revisions:
                (revno_str, author, date_str) = ('?','?','?')
            else:
                revno_str = '.'.join(str(i) for i in
                                            revision_id_to_revno[origin])
            rev = revisions[origin]
            tz = rev.timezone or 0
            date_str = time.strftime('%Y%m%d',
                                     time.gmtime(rev.timestamp + tz))
            # a lazy way to get something like the email address
            # TODO: Get real email address
            author = rev.get_apparent_author()
            try:
                author = extract_email_address(author)
            except errors.NoEmailInUsername:
                pass        # use the whole name
        yield (revno_str, author, date_str, origin, text)


def reannotate(parents_lines, new_lines, new_revision_id, blocks=None):
    """Create a new annotated version from new lines and parent annotations.
    
    :param parents_lines: List of annotated lines for all parents
    :param new_lines: The un-annotated new lines
    :param new_revision_id: The revision-id to associate with new lines
        (will often be CURRENT_REVISION)
    """
    if len(parents_lines) == 0:
        for line in new_lines:
            yield new_revision_id, line
    elif len(parents_lines) == 1:
        for data in _reannotate(parents_lines[0], new_lines, new_revision_id,
                                blocks):
            yield data
    else:
        block_list = [blocks] + [None] * len(parents_lines)
        reannotations = [list(_reannotate(p, new_lines, new_revision_id, b))
                         for p, b in zip(parents_lines, block_list)]
        for annos in zip(*reannotations):
            origins = set(a for a, l in annos)
            line = annos[0][1]
            if len(origins) == 1:
                yield iter(origins).next(), line
            elif len(origins) == 2 and new_revision_id in origins:
                yield (x for x in origins if x != new_revision_id).next(), line
            else:
                yield new_revision_id, line


def _reannotate(parent_lines, new_lines, new_revision_id, blocks=None):
    plain_parent_lines = [l for r, l in parent_lines]
    matcher = patiencediff.PatienceSequenceMatcher(None, plain_parent_lines,
                                                   new_lines)
    new_cur = 0
    if blocks is None:
        blocks = matcher.get_matching_blocks()
    for i, j, n in blocks:
        for line in new_lines[new_cur:j]:
            yield new_revision_id, line
        for data in parent_lines[i:i+n]:
            yield data
        new_cur = j + n
