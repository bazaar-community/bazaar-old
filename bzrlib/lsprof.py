# this is copied from the lsprof distro because somehow
# it is not installed by distutils
# I made one modification to profile so that it returns a pair
# instead of just the Stats object

import sys
import thread
import threading
from _lsprof import Profiler, profiler_entry

__all__ = ['profile', 'Stats']

_g_threadmap = {}


def _thread_profile(f, *args, **kwds):
    # we lose the first profile point for a new thread in order to trampoline
    # a new Profile object into place
    global _g_threadmap
    thr = thread.get_ident()
    _g_threadmap[thr] = p = Profiler()
    # this overrides our sys.setprofile hook:
    p.enable(subcalls=True, builtins=True)


def profile(f, *args, **kwds):
    """XXX docstring"""
    global _g_threadmap
    p = Profiler()
    p.enable(subcalls=True)
    threading.setprofile(_thread_profile)
    try:
        ret = f(*args, **kwds)
    finally:
        p.disable()
        for pp in _g_threadmap.values():
            pp.disable()
        threading.setprofile(None)
    
    threads = {}
    for tid, pp in _g_threadmap.items():
        threads[tid] = Stats(pp.getstats(), {})
    _g_threadmap = {}
    return ret, Stats(p.getstats(), threads)


class Stats(object):
    """XXX docstring"""

    def __init__(self, data, threads):
        self.data = data
        self.threads = threads

    def sort(self, crit="inlinetime"):
        """XXX docstring"""
        if crit not in profiler_entry.__dict__:
            raise ValueError, "Can't sort by %s" % crit
        self.data.sort(lambda b, a: cmp(getattr(a, crit),
                                        getattr(b, crit)))
        for e in self.data:
            if e.calls:
                e.calls.sort(lambda b, a: cmp(getattr(a, crit),
                                              getattr(b, crit)))

    def pprint(self, top=None, file=None):
        """XXX docstring"""
        if file is None:
            file = sys.stdout
        d = self.data
        if top is not None:
            d = d[:top]
        cols = "% 12s %12s %11.4f %11.4f   %s\n"
        hcols = "% 12s %12s %12s %12s %s\n"
        cols2 = "+%12s %12s %11.4f %11.4f +  %s\n"
        file.write(hcols % ("CallCount", "Recursive", "Total(ms)",
                            "Inline(ms)", "module:lineno(function)"))
        for e in d:
            file.write(cols % (e.callcount, e.reccallcount, e.totaltime,
                               e.inlinetime, label(e.code)))
            if e.calls:
                for se in e.calls:
                    file.write(cols % ("+%s" % se.callcount, se.reccallcount,
                                       se.totaltime, se.inlinetime,
                                       "+%s" % label(se.code)))

    def freeze(self):
        """Replace all references to code objects with string
        descriptions; this makes it possible to pickle the instance."""

        # this code is probably rather ickier than it needs to be!
        for i in range(len(self.data)):
            e = self.data[i]
            if not isinstance(e.code, str):
                self.data[i] = type(e)((label(e.code),) + e[1:])
            if e.calls:
                for j in range(len(e.calls)):
                    se = e.calls[j]
                    if not isinstance(se.code, str):
                        e.calls[j] = type(se)((label(se.code),) + se[1:])
        for s in self.threads.values():
            s.freeze()

    def calltree(self, file):
        """Output profiling data in calltree format (for KCacheGrind)."""
        _CallTreeFilter(self.data).output(file)


class _CallTreeFilter(object):
    """Converter of a Stats object to input suitable for KCacheGrind.

    This code is taken from http://ddaa.net/blog/python/lsprof-calltree
    with the changes made by J.P. Calderone and Itamar applied. Note that
    isinstance(code, str) needs to be used at times to determine if the code 
    object is actually an external code object (with a filename, etc.) or
    a Python built-in.
    """

    def __init__(self, data):
        self.data = data
        self.out_file = None

    def output(self, out_file):
        self.out_file = out_file        
        print >> out_file, 'events: Ticks'
        self._print_summary()
        for entry in self.data:
            self._entry(entry)

    def _print_summary(self):
        max_cost = 0
        for entry in self.data:
            totaltime = int(entry.totaltime * 1000)
            max_cost = max(max_cost, totaltime)
        print >> self.out_file, 'summary: %d' % (max_cost,)

    def _entry(self, entry):
        out_file = self.out_file
        code = entry.code
        inlinetime = int(entry.inlinetime * 1000)
        #print >> out_file, 'ob=%s' % (code.co_filename,)
        if isinstance(code, str):
            print >> out_file, 'fi=~'
        else:
            print >> out_file, 'fi=%s' % (code.co_filename,)
        print >> out_file, 'fn=%s' % (label(code, True),)
        if isinstance(code, str):
            print >> out_file, '0 ', inlinetime
        else:
            print >> out_file, '%d %d' % (code.co_firstlineno, inlinetime)
        # recursive calls are counted in entry.calls
        if entry.calls:
            calls = entry.calls
        else:
            calls = []
        if isinstance(code, str):
            lineno = 0
        else:
            lineno = code.co_firstlineno
        for subentry in calls:
            self._subentry(lineno, subentry)
        print >> out_file

    def _subentry(self, lineno, subentry):
        out_file = self.out_file
        code = subentry.code
        totaltime = int(subentry.totaltime * 1000)
        #print >> out_file, 'cob=%s' % (code.co_filename,)
        print >> out_file, 'cfn=%s' % (label(code, True),)
        if isinstance(code, str):
            print >> out_file, 'cfi=~'
            print >> out_file, 'calls=%d 0' % (subentry.callcount,)
        else:
            print >> out_file, 'cfi=%s' % (code.co_filename,)
            print >> out_file, 'calls=%d %d' % (
                subentry.callcount, code.co_firstlineno)
        print >> out_file, '%d %d' % (lineno, totaltime)

_fn2mod = {}

def label(code, calltree=False):
    if isinstance(code, str):
        return code
    try:
        mname = _fn2mod[code.co_filename]
    except KeyError:
        for k, v in sys.modules.items():
            if v is None:
                continue
            if getattr(v, '__file__', None) is None:
                continue
            if not isinstance(v.__file__, str):
                continue
            if v.__file__.startswith(code.co_filename):
                mname = _fn2mod[code.co_filename] = k
                break
        else:
            mname = _fn2mod[code.co_filename] = '<%s>'%code.co_filename
    if calltree:
        return '%s %s:%d' % (code.co_name, mname, code.co_firstlineno)
    else:
        return '%s:%d(%s)' % (mname, code.co_firstlineno, code.co_name)


if __name__ == '__main__':
    import os
    sys.argv = sys.argv[1:]
    if not sys.argv:
        print >> sys.stderr, "usage: lsprof.py <script> <arguments...>"
        sys.exit(2)
    sys.path.insert(0, os.path.abspath(os.path.dirname(sys.argv[0])))
    stats = profile(execfile, sys.argv[0], globals(), locals())
    stats.sort()
    stats.pprint()
