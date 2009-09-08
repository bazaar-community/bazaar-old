# -*- coding: utf-8 -*-
#
# Bazaar documentation build configuration file, created by
# sphinx-quickstart on Tue Jul 21 17:04:52 2009.
#
# This file is execfile()d with the current directory set to its containing dir.

import sys, os

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
sys.path = [os.path.abspath('../..')] + sys.path

# Most of the configuration for Bazaar docs is defined here ...
from bzrlib.doc_generate.sphinx_conf import *


## Configuration specific to this site ##

# The locale code for this documentation set
bzr_locale = 'en'

# A shorter title for the navigation bar.  Default is the same as html_title.
html_short_title = u"Developer Document Catalog (%s)" % (release,)

# Additional templates that should be rendered to pages, maps page names to
# template names.
#html_additional_pages = {'index': 'index.html'}

# Output file base name for HTML help builder.
htmlhelp_basename = 'bzr-%s-devel-docs' % (bzr_locale,)

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass [howto/manual]).
latex_documents = [
  ('HACKING', 'bzr-en-developer-guide.tex', u'Bazaar Developer Guide',
   u'Bazaar Developers', 'manual'),
  ('testing', 'bzr-en-testing-guide.tex', u'Bazaar Testing Guide',
   u'Bazaar Developers', 'manual'),
  ('overview', 'bzr-en-architecture-overview.tex', u'Bazaar Architecture Overview',
   u'Bazaar Developers', 'howto'),
  ('integration', 'bzr-en-integration-guide.tex', u'Bazaar Integration Guide',
   u'Bazaar Developers', 'howto'),
]
