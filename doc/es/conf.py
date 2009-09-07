# -*- coding: utf-8 -*-
#
# Bazaar documentation build configuration file, created by
# sphinx-quickstart on Tue Jul 21 17:04:52 2009.
#
# This file is execfile()d with the current directory set to its containing dir.
#
# Note that not all possible configuration values are present in this
# autogenerated file.
#
# All configuration values have a default; values that are commented out
# serve to show the default.

import sys, os

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#sys.path.append(os.path.abspath('.'))


# -- Bazaar-specific configuration ---------------------------------------------

# NOTE: Editing this section is generally all that is required ...

# We *could* get this from bzrlib but there's no certainly that the bzr on
# the Python path is indeed the one we're building the documentation for ...
bzr_version = (2, 0, 0, 'rc', 2)

# The locale code for this documentation set
bzr_locale = 'es'

# Authors of the documents
bzr_team = u'Bazaar Developers'

# Translations
bzr_titles = {
        u'Table of Contents (%s)': None,
        u'Bazaar User Guide': None,
        u'Bazaar User Reference': None,
        u'Bazaar Release Notes': None,
        u'Bazaar Upgrade Guide': None,
        u'Bazaar in five minutes': None,
        u'Bazaar Tutorial': None,
        u'Using Bazaar With Launchpad': None,
        u'Centralized Workflow Tutorial': None,
    }

# Helper function for looking up translations
def bzr_title(s):
    return bzr_titles.get(s) or s


# -- General configuration -----------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be extensions
# coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
extensions = ['sphinx.ext.ifconfig']

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# The suffix of source filenames.
source_suffix = '.txt'

# The encoding of source files.
#source_encoding = 'utf-8'

# The master toctree document.
master_doc = 'index'

# General information about the project.
project = u'Bazaar'
copyright = u'2009, Canonical Ltd'

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
#
# The short X.Y version.
version = '.'.join(str(p) for p in bzr_version[:3])
# The full version, including alpha/beta/rc tags.
release = version + ''.join(str(p) for p in bzr_version[3:])

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
language = bzr_locale

# There are two options for replacing |today|: either, you set today to some
# non-false value, then it is used:
#today = ''
# Else, today_fmt is used as the format for a strftime call.
#today_fmt = '%B %d, %Y'

# List of documents that shouldn't be included in the build.
#unused_docs = []

# List of directories, relative to source directory, that shouldn't be searched
# for source files.
exclude_trees = ['_build']

# The reST default role (used for this markup: `text`) to use for all documents.
#default_role = None

# If true, '()' will be appended to :func: etc. cross-reference text.
#add_function_parentheses = True

# If true, the current module name will be prepended to all description
# unit titles (such as .. function::).
#add_module_names = True

# If true, sectionauthor and moduleauthor directives will be shown in the
# output. They are ignored by default.
#show_authors = False

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

# A list of ignored prefixes for module index sorting.
#modindex_common_prefix = []


# -- Options for HTML output ---------------------------------------------------

# The theme to use for HTML and HTML Help pages.  Major themes that come with
# Sphinx are currently 'default' and 'sphinxdoc'.
html_theme = 'default'

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
html_theme_options = {
    'rightsidebar': True,

    # Non-document areas: header (relbar), footer, sidebar, etc.
    # Some useful colours here:
    # * blue: darkblue, mediumblue, darkslateblue, cornflowerblue, royalblue,
    #   midnightblue
    # * gray: dimgray, slategray, lightslategray
    'sidebarbgcolor':   "cornflowerblue",
    'sidebarlinkcolor': "midnightblue",
    'relbarbgcolor':    "darkblue",
    'footerbgcolor':    "lightslategray",

    # Text, heading and code colouring
    'codebgcolor':      "lightyellow",
    'codetextcolor':    "firebrick",
    'linkcolor':        "mediumblue",
    }

# Add any paths that contain custom themes here, relative to this directory.
#html_theme_path = []

# The name for this set of Sphinx documents.  If None, it defaults to
# "<project> v<release> documentation".
#html_title = None

# A shorter title for the navigation bar.  Default is the same as html_title.
html_short_title = bzr_title(u"Table of Contents (%s)") % (release,)

# The name of an image file (relative to this directory) to place at the top
# of the sidebar.
#html_logo = None

# The name of an image file (within the static path) to use as favicon of the
# docs.  This file should be a Windows icon file (.ico) being 16x16 or 32x32
# pixels large.
html_favicon = "bzr.ico"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

# If not '', a 'Last updated on:' timestamp is inserted at every page bottom,
# using the given strftime format.
#html_last_updated_fmt = '%b %d, %Y'

# If true, SmartyPants will be used to convert quotes and dashes to
# typographically correct entities.
#html_use_smartypants = True

# Custom sidebar templates, maps document names to template names.
#html_sidebars = {}

# Additional templates that should be rendered to pages, maps page names to
# template names.
#html_additional_pages = {'index': 'index.html'}

# If false, no module index is generated.
html_use_modindex = False

# If false, no index is generated.
html_use_index = False

# If true, the index is split into individual pages for each letter.
#html_split_index = False

# If true, links to the reST sources are added to the pages.
html_show_sourcelink = True

# If true, an OpenSearch description file will be output, and all pages will
# contain a <link> tag referring to it.  The value of this option must be the
# base URL from which the finished HTML is served.
#html_use_opensearch = ''

# If nonempty, this is the file name suffix for HTML files (e.g. ".xhtml").
#html_file_suffix = ''

# Output file base name for HTML help builder.
htmlhelp_basename = 'bzr-%s-user-docs' % (bzr_locale,)


# -- Options for LaTeX output --------------------------------------------------

# The paper size ('letter' or 'a4').
#latex_paper_size = 'letter'

# The font size ('10pt', '11pt' or '12pt').
#latex_font_size = '10pt'

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
latex_documents = [
  # Manuals
  ('user-guide/index', 'bzr-%s-user-guide.tex' % (bzr_locale,),
    bzr_title(u'Bazaar User Guide'), bzr_team, 'manual'),
  ('user-reference/bzr_man', 'bzr-%s-user-reference.tex' % (bzr_locale,),
    bzr_title(u'Bazaar User Reference'), bzr_team, 'manual'),
  ('release-notes/NEWS', 'bzr-%s-release-notes.tex' % (bzr_locale,),
    bzr_title(u'Bazaar Release Notes'), bzr_team, 'manual'),
  ('upgrade-guide/index', 'bzr-%s-upgrade-guide.tex' % (bzr_locale,),
    bzr_title(u'Bazaar Upgrade Guide'), bzr_team, 'manual'),
  # Tutorials
  ('mini-tutorial/index', 'bzr-%s-tutorial-mini.tex' % (bzr_locale,),
    bzr_title(u'Bazaar in five minutes'), bzr_team, 'howto'),
  ('tutorials/tutorial', 'bzr-%s-tutorial.tex' % (bzr_locale,),
    bzr_title(u'Bazaar Tutorial'), bzr_team, 'howto'),
  ('tutorials/using_bazaar_with_launchpad',
    'bzr-%s-tutorial-with-launchpad.tex' % (bzr_locale,),
    bzr_title(u'Using Bazaar With Launchpad'), bzr_team, 'howto'),
  ('tutorials/centralized_workflow',
    'bzr-%s-tutorial-centralized.tex' % (bzr_locale,),
    bzr_title(u'Centralized Workflow Tutorial'), bzr_team, 'howto'),
]

# The name of an image file (relative to this directory) to place at the top of
# the title page.
latex_logo = 'Bazaar-Logo-For-Manuals.png'

# For "manual" documents, if this is true, then toplevel headings are parts,
# not chapters.
#latex_use_parts = False

# Additional stuff for the LaTeX preamble.
#latex_preamble = ''

# Documents to append as an appendix to all manuals.
#latex_appendices = []

# If false, no module index is generated.
#latex_use_modindex = True
