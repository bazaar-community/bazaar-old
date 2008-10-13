#! /usr/bin/env python

"""Installation script for bzr.
Run it with
 './setup.py install', or
 './setup.py --help' for more options
"""

import os
import os.path
import sys

if sys.version_info < (2, 4):
    sys.stderr.write("[ERROR] Not a supported Python version. Need 2.4+\n")
    sys.exit(1)

# NOTE: The directory containing setup.py, whether run by 'python setup.py' or
# './setup.py' or the equivalent with another path, should always be at the
# start of the path, so this should find the right one...
import bzrlib

def get_long_description():
    dirname = os.path.dirname(__file__)
    readme = os.path.join(dirname, 'README')
    f = open(readme, 'rb')
    try:
        return f.read()
    finally:
        f.close()


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
    'long_description': get_long_description(),
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
from distutils.command.install_data import install_data
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
    from Pyrex.Compiler.Version import version as pyrex_version


class build_ext_if_possible(build_ext):

    user_options = build_ext.user_options + [
        ('allow-python-fallback', None,
         "When an extension cannot be built, allow falling"
         " back to the pure-python implementation.")
        ]

    def initialize_options(self):
        build_ext.initialize_options(self)
        self.allow_python_fallback = False

    def run(self):
        try:
            build_ext.run(self)
        except DistutilsPlatformError, e:
            if not self.allow_python_fallback:
                log.warn('\n  Cannot build extensions.\n'
                         '  Use --allow-python-fallback to use slower'
                         ' python implementations instead.\n')
                raise
            log.warn(str(e))
            log.warn('\n  Extensions cannot be built.\n'
                     '  Using the slower Python implementations instead.\n')

    def build_extension(self, ext):
        try:
            build_ext.build_extension(self, ext)
        except CCompilerError:
            if not self.allow_python_fallback:
                log.warn('\n  Failed to build "%s".\n'
                         '  Use --allow-python-fallback to use slower'
                         ' python implementations instead.\n'
                         % (ext.name,))
                raise
            log.warn('\n  Building of "%s" extension failed.\n'
                     '  Using the slower Python implementation instead.'
                     % (ext.name,))


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
        ext_modules.append(Extension(module_name, [pyrex_name], **kwargs))
    else:
        if not os.path.isfile(c_name):
            unavailable_files.append(c_name)
        else:
            ext_modules.append(Extension(module_name, [c_name], **kwargs))


add_pyrex_extension('bzrlib._btree_serializer_c')
add_pyrex_extension('bzrlib._knit_load_data_c')
if sys.platform == 'win32':
    add_pyrex_extension('bzrlib._dirstate_helpers_c',
                         libraries=['Ws2_32']
                       )
    # pyrex uses the macro WIN32 to detect the platform, even though it should
    # be using something like _WIN32 or MS_WINDOWS, oh well, we can give it the
    # right value.
    add_pyrex_extension('bzrlib._walkdirs_win32',
                        define_macros=[('WIN32', None)])
else:
    if have_pyrex and pyrex_version == '0.9.4.1':
        # Pyrex 0.9.4.1 fails to compile this extension correctly
        # The code it generates re-uses a "local" pointer and
        # calls "PY_DECREF" after having set it to NULL. (It mixes PY_XDECREF
        # which is NULL safe with PY_DECREF which is not.)
        print 'Cannot build extension "bzrlib._dirstate_helpers_c" using'
        print 'your version of pyrex "%s". Please upgrade your pyrex' % (
            pyrex_version,)
        print 'install. For now, the non-compiled (python) version will'
        print 'be used instead.'
    else:
        add_pyrex_extension('bzrlib._dirstate_helpers_c')
    add_pyrex_extension('bzrlib._readdir_pyx')
ext_modules.append(Extension('bzrlib._patiencediff_c', ['bzrlib/_patiencediff_c.c']))


if unavailable_files:
    print 'C extension(s) not found:'
    print '   %s' % ('\n  '.join(unavailable_files),)
    print 'The python versions will be used instead.'
    print


def get_tbzr_py2exe_info(includes, excludes, packages, console_targets,
                         gui_targets):
    packages.append('tbzrcommands')

    # ModuleFinder can't handle runtime changes to __path__, but
    # win32com uses them.  Hook this in so win32com.shell is found.
    import modulefinder
    import win32com
    import cPickle as pickle
    for p in win32com.__path__[1:]:
        modulefinder.AddPackagePath("win32com", p)
    for extra in ["win32com.shell"]:
        __import__(extra)
        m = sys.modules[extra]
        for p in m.__path__[1:]:
            modulefinder.AddPackagePath(extra, p)

    # TBZR points to the TBZR directory
    tbzr_root = os.environ["TBZR"]

    # Ensure tbzrlib itself is on sys.path
    sys.path.append(tbzr_root)

    # Ensure our COM "entry-point" is on sys.path
    sys.path.append(os.path.join(tbzr_root, "shellext", "python"))

    packages.append("tbzrlib")

    # collect up our icons.
    cwd = os.getcwd()
    ico_root = os.path.join(tbzr_root, 'tbzrlib', 'resources')
    icos = [] # list of (path_root, relative_ico_path)
    # First always bzr's icon and its in the root of the bzr tree.
    icos.append(('', 'bzr.ico'))
    for root, dirs, files in os.walk(ico_root):
        icos.extend([(ico_root, os.path.join(root, f)[len(ico_root)+1:])
                     for f in files if f.endswith('.ico')])
    # allocate an icon ID for each file and the full path to the ico
    icon_resources = [(rid, os.path.join(ico_dir, ico_name))
                      for rid, (ico_dir, ico_name) in enumerate(icos)]
    # create a string resource with the mapping.  Might as well save the
    # runtime some effort and write a pickle.
    # Runtime expects unicode objects with forward-slash seps.
    fse = sys.getfilesystemencoding()
    map_items = [(f.replace('\\', '/').decode(fse), rid)
                 for rid, (_, f) in enumerate(icos)]
    ico_map = dict(map_items)
    # Create a new resource type of 'ICON_MAP', and use ID=1
    other_resources = [ ("ICON_MAP", 1, pickle.dumps(ico_map))]

    excludes.extend("""pywin pywin.dialogs pywin.dialogs.list
                       win32ui crawler.Crawler""".split())

    tbzr = dict(
        modules=["tbzr"],
        create_exe = False, # we only want a .dll
    )
    com_targets.append(tbzr)

    # tbzrcache executables - a "console" version for debugging and a
    # GUI version that is generally used.
    tbzrcache = dict(
        script = os.path.join(tbzr_root, "Scripts", "tbzrcache.py"),
        icon_resources = icon_resources,
        other_resources = other_resources,
    )
    console_targets.append(tbzrcache)

    # Make a windows version which is the same except for the base name.
    tbzrcachew = tbzrcache.copy()
    tbzrcachew["dest_base"]="tbzrcachew"
    gui_targets.append(tbzrcachew)

    # ditto for the tbzrcommand tool
    tbzrcommand = dict(
        script = os.path.join(tbzr_root, "Scripts", "tbzrcommand.py"),
        icon_resources = [(0,'bzr.ico')],
    )
    console_targets.append(tbzrcommand)
    tbzrcommandw = tbzrcommand.copy()
    tbzrcommandw["dest_base"]="tbzrcommandw"
    gui_targets.append(tbzrcommandw)
    
    # tbzr tests
    tbzrtest = dict(
        script = os.path.join(tbzr_root, "Scripts", "tbzrtest.py"),
    )
    console_targets.append(tbzrtest)

    # A utility to see python output from the shell extension - this will
    # die when we get a c++ extension
    # any .py file from pywin32's win32 lib will do (other than
    # win32traceutil itself that is)
    import winerror
    win32_lib_dir = os.path.dirname(winerror.__file__)
    tracer = dict(script = os.path.join(win32_lib_dir, "win32traceutil.py"),
                  dest_base="tbzr_tracer")
    console_targets.append(tracer)


def get_qbzr_py2exe_info(includes, excludes, packages):
    # PyQt4 itself still escapes the plugin detection code for some reason...
    packages.append('PyQt4')
    excludes.append('PyQt4.elementtree.ElementTree')
    includes.append('sip') # extension module required for Qt.
    packages.append('pygments') # colorizer for qbzr
    packages.append('docutils') # html formatting
    # but we can avoid many Qt4 Dlls.
    dll_excludes.extend(
        """QtAssistantClient4.dll QtCLucene4.dll QtDesigner4.dll
        QtHelp4.dll QtNetwork4.dll QtOpenGL4.dll QtScript4.dll
        QtSql4.dll QtTest4.dll QtWebKit4.dll QtXml4.dll
        qscintilla2.dll""".split())
    # the qt binaries might not be on PATH...
    qt_dir = os.path.join(sys.prefix, "PyQt4", "bin")
    path = os.environ.get("PATH","")
    if qt_dir.lower() not in [p.lower() for p in path.split(os.pathsep)]:
        os.environ["PATH"] = path + os.pathsep + qt_dir


if 'bdist_wininst' in sys.argv:
    def find_docs():
        docs = []
        for root, dirs, files in os.walk('doc'):
            r = []
            for f in files:
                if (os.path.splitext(f)[1] in ('.html','.css','.png','.pdf')
                    or f == 'quick-start-summary.svg'):
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
    import glob
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

    # An override to install_data used only by py2exe builds, which arranges
    # to byte-compile any .py files in data_files (eg, our plugins)
    # Necessary as we can't rely on the user having the relevant permissions
    # to the "Program Files" directory to generate them on the fly.
    class install_data_with_bytecompile(install_data):
        def run(self):
            from distutils.util import byte_compile

            install_data.run(self)

            py2exe = self.distribution.get_command_obj('py2exe', False)
            optimize = py2exe.optimize
            compile_names = [f for f in self.outfiles if f.endswith('.py')]
            byte_compile(compile_names,
                         optimize=optimize,
                         force=self.force, prefix=self.install_dir,
                         dry_run=self.dry_run)
            if optimize:
                suffix = 'o'
            else:
                suffix = 'c'
            self.outfiles.extend([f + suffix for f in compile_names])
    # end of class install_data_with_bytecompile

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

    packages = BZRLIB['packages']
    packages.remove('bzrlib')
    packages = [i for i in packages if not i.startswith('bzrlib.plugins')]
    includes = []
    for i in glob.glob('bzrlib\\*.py'):
        module = i[:-3].replace('\\', '.')
        if module.endswith('__init__'):
            module = module[:-len('__init__')]
        includes.append(module)

    additional_packages = set()
    if sys.version.startswith('2.4'):
        # adding elementtree package
        additional_packages.add('elementtree')
    elif sys.version.startswith('2.5'):
        additional_packages.add('xml.etree')
    else:
        import warnings
        warnings.warn('Unknown Python version.\n'
                      'Please check setup.py script for compatibility.')

    # Although we currently can't enforce it, we consider it an error for
    # py2exe to report any files are "missing".  Such modules we know aren't
    # used should be listed here.
    excludes = """Tkinter psyco ElementPath r_hmac
                  ImaginaryModule cElementTree elementtree.ElementTree
                  Crypto.PublicKey._fastmath
                  medusa medusa.filesys medusa.ftp_server
                  tools tools.doc_generate
                  resource validate""".split()
    dll_excludes = []

    # email package from std python library use lazy import,
    # so we need to explicitly add all package
    additional_packages.add('email')
    # And it uses funky mappings to conver to 'Oldname' to 'newname'.  As
    # a result, packages like 'email.Parser' show as missing.  Tell py2exe
    # to exclude them.
    import email
    for oldname in getattr(email, '_LOWERNAMES', []):
        excludes.append("email." + oldname)
    for oldname in getattr(email, '_MIMENAMES', []):
        excludes.append("email.MIME" + oldname)

    # text files for help topis
    text_topics = glob.glob('bzrlib/help_topics/en/*.txt')
    topics_files = [('lib/help_topics/en', text_topics)]

    # built-in plugins
    plugins_files = []
    # XXX - should we consider having the concept of an 'official' build,
    # which hard-codes the list of plugins, gets more upset if modules are
    # missing, etc?
    plugins = None # will be a set after plugin sniffing...
    for root, dirs, files in os.walk('bzrlib/plugins'):
        if root == 'bzrlib/plugins':
            plugins = set(dirs)
        x = []
        for i in files:
            if os.path.splitext(i)[1] not in [".py", ".pyd", ".dll", ".mo"]:
                continue
            if i == '__init__.py' and root == 'bzrlib/plugins':
                continue
            x.append(os.path.join(root, i))
        if x:
            target_dir = root[len('bzrlib/'):]  # install to 'plugins/...'
            plugins_files.append((target_dir, x))
    # find modules for built-in plugins
    import tools.package_mf
    mf = tools.package_mf.CustomModuleFinder()
    mf.run_package('bzrlib/plugins')
    packs, mods = mf.get_result()
    additional_packages.update(packs)
    includes.extend(mods)

    console_targets = [target,
                       'tools/win32/bzr_postinstall.py',
                       ]
    gui_targets = []
    com_targets = []

    if 'qbzr' in plugins:
        get_qbzr_py2exe_info(includes, excludes, packages)

    if "TBZR" in os.environ:
        # TORTOISE_OVERLAYS_MSI_WIN32 must be set to the location of the
        # TortoiseOverlays MSI installer file. It is in the TSVN svn repo and
        # can be downloaded from (username=guest, blank password):
        # http://tortoisesvn.tigris.org/svn/tortoisesvn/TortoiseOverlays/version-1.0.4/bin/TortoiseOverlays-1.0.4.11886-win32.msi
        if not os.path.isfile(os.environ.get('TORTOISE_OVERLAYS_MSI_WIN32',
                                             '<nofile>')):
            raise RuntimeError("Please set TORTOISE_OVERLAYS_MSI_WIN32 to the"
                               " location of the Win32 TortoiseOverlays .msi"
                               " installer file")
        get_tbzr_py2exe_info(includes, excludes, packages, console_targets,
                             gui_targets)
    else:
        # print this warning to stderr as output is redirected, so it is seen
        # at build time.  Also to stdout so it appears in the log
        for f in (sys.stderr, sys.stdout):
            print >> f, \
                "Skipping TBZR binaries - please set TBZR to a directory to enable"

    # MSWSOCK.dll is a system-specific library, which py2exe accidentally pulls
    # in on Vista.
    dll_excludes.append("MSWSOCK.dll")
    options_list = {"py2exe": {"packages": packages + list(additional_packages),
                               "includes": includes,
                               "excludes": excludes,
                               "dll_excludes": dll_excludes,
                               "dist_dir": "win32_bzr.exe",
                               "optimize": 1,
                              },
                   }

    setup(options=options_list,
          console=console_targets,
          windows=gui_targets,
          com_server=com_targets,
          zipfile='lib/library.zip',
          data_files=topics_files + plugins_files,
          cmdclass={'install_data': install_data_with_bytecompile},
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
