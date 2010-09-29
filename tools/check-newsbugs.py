#!/usr/bin/python
# Simple script that will check which bugs mentioned in NEWS 
# are not yet marked Fix Released in Launchpad

import getopt, re, sys
try:
    from launchpadlib.launchpad import Launchpad
    from lazr.restfulclient import errors
except ImportError:
    print "Please install launchpadlib from lp:launchpadlib"
    sys.exit(1)
try:
    import hydrazine
except ImportError:
    print "Please install hydrazine from lp:launchpadlib"
    sys.exit(1)


options, args = getopt.gnu_getopt(sys.argv, "l", ["launchpad"])
options = dict(options)

if len(args) == 1:
    print "Usage: check-newsbugs [--launchpad] NEWS"
    print "Options:"
    print "--launchpad     Print out Launchpad mail commands for closing bugs "
    print "                that are already fixed."
    sys.exit(1)


def report_notmarked(bug, task, section):
    print 
    print "Bug %d was mentioned in NEWS but is not marked fix released:" % (bug.id, )
    print "Launchpad title: %s" % bug.title
    print "NEWS summary: "
    print section
    if "--launchpad" in options or "-l" in options:
        print "  bug %d" % bug.id
        print "  affects %s" % task.bug_target_name
        print "  status fixreleased"


def read_news_bugnos(path):
    """Read the bug numbers closed by a particular NEWS file

    :param path: Path to the NEWS file
    :return: list of bug numbers that were closed.
    """
    # Pattern to find bug numbers
    bug_pattern = re.compile("\#([0-9]+)")
    ret = set()
    f = open(path, 'r')
    try:
        section = ""
        for l in f.readlines():
            if l.strip() == "":
                try:
                    parenthesed = section.rsplit("(", 1)[1]
                except IndexError:
                    parenthesed = ""
                # Empty line, next section begins
                for bugno in [int(m) for m in bug_pattern.findall(parenthesed)]:
                    ret.add((bugno, section))
                section = ""
            else:
                section += l
        return ret
    finally:
        f.close()


def print_bug_url(bugno):
    print '<URL:http://pad.lv/%s>' % (bugno,)

launchpad = hydrazine.create_session()
bugnos = read_news_bugnos(args[1])
for bugno, section in bugnos:
    try:
        bug = launchpad.bugs[bugno]
    except errors.HTTPError, e:
        if e.response.status == 401:
            print_bug_url(bugno)
            # Private, we can't access the bug content
            print '%s is private and cannot be accessed' % (bugno,)
            continue
        raise
     
    found_bzr = False
    fix_released = False
    for task in bug.bug_tasks:
        parts = task.bug_target_name.split('/')
        if len(parts) == 1:
            project = parts[0]
            distribution = None
        else:
            project = parts[0]
            distribution = parts[1]
        if project == "bzr":
            found_bzr = True
            if not fix_released and task.status == "Fix Released":
                # We could check that the NEWS section and task_status are in
                # sync, but that would be overkill. (case at hand: bug #416732)
                fix_released = True

    if not found_bzr:
        print_bug_url(bugno)
        print "Bug %d was mentioned in NEWS but is not marked as affecting bzr" % bugno
    elif not fix_released:
        print_bug_url(bugno)
        report_notmarked(bug, task, section)
