#! /usr/bin/env python

"""Installation script for bzr.
Run it with
 './setup.py install', or
 './setup.py --help' for more options
"""

import os
import sys

# NOTE: This assumes we're being run from the setup.py directory, so it can be
# loaded from the cwd.
import bzrlib

##
# META INFORMATION FOR SETUP
# see http://docs.python.org/dist/meta-data.html
META_INFO = {
    'name':         'bzr',
    'version':      bzrlib.__version__,
    'author':       'Canonical Ltd',
    'author_email': 'bazaar@lists.canonical.com',
    'url':          'http://www.bazaar-vcs.org/',
    'description':  'Friendly distributed version control system',
    'license':      'GNU GPL v2',
    'download_url': 'http://bazaar-vcs.org/Download',
    'long_description': file("README").read(),
    'classifiers': [
        'Development Status :: 6 - Mature',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: OS Independent',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Programming Language :: C',
        'Topic :: Software Development :: Version Control',
        ],
    }

# The list of packages is automatically generated later. Add other things
# that are part of BZRLIB here.
BZRLIB = {}

PKG_DATA = {# install files from selftest suite
            'package_data': {'bzrlib': ['doc/api/*.txt',
                                        'tests/test_patches_data/*',
                                        'help_topics/en/*.txt',
                                       ]},
           }

######################################################################
# Reinvocation stolen from bzr, we need python2.4 by virtue of bzr_man
# including bzrlib.help

try:
    version_info = sys.version_info
except AttributeError:
    version_info = 1, 5 # 1.5 or older

REINVOKE = "__BZR_REINVOKE"
NEED_VERS = (2, 4)
KNOWN_PYTHONS = ('python2.4',)

if version_info < NEED_VERS:
    if not os.environ.has_key(REINVOKE):
        # mutating os.environ doesn't work in old Pythons
        os.putenv(REINVOKE, "1")
        for python in KNOWN_PYTHONS:
            try:
                os.execvp(python, [python] + sys.argv)
            except OSError:
                pass
    sys.stderr.write("bzr: error: cannot find a suitable python interpreter\n")
    sys.stderr.write("  (need %d.%d or later)" % NEED_VERS)
    sys.stderr.write('\n')
    sys.exit(1)
if getattr(os, "unsetenv", None) is not None:
    os.unsetenv(REINVOKE)


def get_bzrlib_packages():
    """Recurse through the bzrlib directory, and extract the package names"""

    packages = []
    base_path = os.path.dirname(os.path.abspath(bzrlib.__file__))
    for root, dirs, files in os.walk(base_path):
        if '__init__.py' in files:
            assert root.startswith(base_path)
            # Get just the path below bzrlib
            package_path = root[len(base_path):]
            # Remove leading and trailing slashes
            package_path = package_path.strip('\\/')
            if not package_path:
                package_name = 'bzrlib'
            else:
                package_name = ('bzrlib.' +
                            package_path.replace('/', '.').replace('\\', '.'))
            packages.append(package_name)
    return sorted(packages)


BZRLIB['packages'] = get_bzrlib_packages()


from distutils.core import setup
from distutils.command.install_scripts import install_scripts
from distutils.command.build import build

###############################
# Overridden distutils actions
###############################

class my_install_scripts(install_scripts):
    """ Customized install_scripts distutils action.
    Create bzr.bat for win32.
    """
    def run(self):
        install_scripts.run(self)   # standard action

        if sys.platform == "win32":
            try:
                scripts_dir = os.path.join(sys.prefix, 'Scripts')
                script_path = self._quoted_path(os.path.join(scripts_dir,
                                                             "bzr"))
                python_exe = self._quoted_path(sys.executable)
                args = self._win_batch_args()
                batch_str = "@%s %s %s" % (python_exe, script_path, args)
                batch_path = os.path.join(self.install_dir, "bzr.bat")
                f = file(batch_path, "w")
                f.write(batch_str)
                f.close()
                print "Created:", batch_path
            except Exception, e:
                print "ERROR: Unable to create %s: %s" % (batch_path, e)

    def _quoted_path(self, path):
        if ' ' in path:
            return '"' + path + '"'
        else:
            return path

    def _win_batch_args(self):
        from bzrlib.win32utils import winver
        if winver == 'Windows NT':
            return '%*'
        else:
            return '%1 %2 %3 %4 %5 %6 %7 %8 %9'
#/class my_install_scripts


class bzr_build(build):
    """Customized build distutils action.
    Generate bzr.1.
    """
    def run(self):
        build.run(self)

        import generate_docs
        generate_docs.main(argv=["bzr", "man"])


########################
## Setup
########################

command_classes = {'install_scripts': my_install_scripts,
                   'build': bzr_build}
from distutils import log
from distutils.errors import CCompilerError, DistutilsPlatformError
from distutils.extension import Extension
ext_modules = []
try:
    from Pyrex.Distutils import build_ext
except ImportError:
    have_pyrex = False
    # try to build the extension from the prior generated source.
    print
    print ("The python package 'Pyrex' is not available."
           " If the .c files are available,")
    print ("they will be built,"
           " but modifying the .pyx files will not rebuild them.")
    print
    from distutils.command.build_ext import build_ext
else:
    have_pyrex = True


class build_ext_if_possible(build_ext):

    def run(self):
        try:
            build_ext.run(self)
        except DistutilsPlatformError, e:
            log.warn(str(e))
            log.warn('Extensions cannot be built, '
                     'will use the Python versions instead')

    def build_extension(self, ext):
        try:
            build_ext.build_extension(self, ext)
        except CCompilerError:
            log.warn('Building of "%s" extension failed, '
                     'will use the Python version instead' % (ext.name,))


# Override the build_ext if we have Pyrex available
command_classes['build_ext'] = build_ext_if_possible
unavailable_files = []


def add_pyrex_extension(module_name, **kwargs):
    """Add a pyrex module to build.

    This will use Pyrex to auto-generate the .c file if it is available.
    Otherwise it will fall back on the .c file. If the .c file is not
    available, it will warn, and not add anything.

    You can pass any extra options to Extension through kwargs. One example is
    'libraries = []'.

    :param module_name: The python path to the module. This will be used to
        determine the .pyx and .c files to use.
    """
    path = module_name.replace('.', '/')
    pyrex_name = path + '.pyx'
    c_name = path + '.c'
    if have_pyrex:
        ext_modules.append(Extension(module_name, [pyrex_name]))
    else:
        if not os.path.isfile(c_name):
            unavailable_files.append(c_name)
        else:
            ext_modules.append(Extension(module_name, [c_name]))


add_pyrex_extension('bzrlib._dirstate_helpers_c')
add_pyrex_extension('bzrlib._knit_load_data_c')
ext_modules.append(Extension('bzrlib._patiencediff_c', ['bzrlib/_patiencediff_c.c']))


if unavailable_files:
    print 'C extension(s) not found:'
    print '   %s' % ('\n  '.join(unavailable_files),)
    print 'The python versions will be used instead.'
    print


if 'bdist_wininst' in sys.argv:
    def find_docs():
        docs = []
        for root, dirs, files in os.walk('doc'):
            r = []
            for f in files:
                if os.path.splitext(f)[1] in ('.html','.css','.png','.pdf'):
                    r.append(os.path.join(root, f))
            if r:
                relative = root[4:]
                if relative:
                    target = os.path.join('Doc\\Bazaar', relative)
                else:
                    target = 'Doc\\Bazaar'
                docs.append((target, r))
        return docs

    # python's distutils-based win32 installer
    ARGS = {'scripts': ['bzr', 'tools/win32/bzr-win32-bdist-postinstall.py'],
            'ext_modules': ext_modules,
            # help pages
            'data_files': find_docs(),
            # for building pyrex extensions
            'cmdclass': {'build_ext': build_ext_if_possible},
           }

    ARGS.update(META_INFO)
    ARGS.update(BZRLIB)
    ARGS.update(PKG_DATA)
    
    setup(**ARGS)

elif 'py2exe' in sys.argv:
    # py2exe setup
    import py2exe

    # pick real bzr version
    import bzrlib

    version_number = []
    for i in bzrlib.version_info[:4]:
        try:
            i = int(i)
        except ValueError:
            i = 0
        version_number.append(str(i))
    version_str = '.'.join(version_number)

    target = py2exe.build_exe.Target(script = "bzr",
                                     dest_base = "bzr",
                                     icon_resources = [(0,'bzr.ico')],
                                     name = META_INFO['name'],
                                     version = version_str,
                                     description = META_INFO['description'],
                                     author = META_INFO['author'],
                                     copyright = "(c) Canonical Ltd, 2005-2007",
                                     company_name = "Canonical Ltd.",
                                     comments = META_INFO['description'],
                                    )

    additional_packages =  []
    if sys.version.startswith('2.4'):
        # adding elementtree package
        additional_packages.append('elementtree')
    elif sys.version.startswith('2.5'):
        additional_packages.append('xml.etree')
    else:
        import warnings
        warnings.warn('Unknown Python version.\n'
                      'Please check setup.py script for compatibility.')
    # email package from std python library use lazy import,
    # so we need to explicitly add all package
    additional_packages.append('email')

    # text files for help topis
    import glob
    text_topics = glob.glob('bzrlib/help_topics/en/*.txt')

    options_list = {"py2exe": {"packages": BZRLIB['packages'] +
                                           additional_packages,
                               "excludes": ["Tkinter", "medusa", "tools"],
                               "dist_dir": "win32_bzr.exe",
                              },
                   }
    setup(options=options_list,
          console=[target,
                   'tools/win32/bzr_postinstall.py',
                  ],
          zipfile='lib/library.zip',
          data_files=[('lib/help_topics/en', text_topics)],
          )

else:
    # ad-hoc for easy_install
    DATA_FILES = []
    if not 'bdist_egg' in sys.argv:
        # generate and install bzr.1 only with plain install, not easy_install one
        DATA_FILES = [('man/man1', ['bzr.1'])]

    # std setup
    ARGS = {'scripts': ['bzr'],
            'data_files': DATA_FILES,
            'cmdclass': command_classes,
            'ext_modules': ext_modules,
           }

    ARGS.update(META_INFO)
    ARGS.update(BZRLIB)
    ARGS.update(PKG_DATA)

    setup(**ARGS)
