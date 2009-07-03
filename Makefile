# Copyright (C) 2005, 2006, 2007, 2008 Canonical Ltd
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

# A relatively simple Makefile to assist in building parts of bzr. Mostly for
# building documentation, etc.


### Core Stuff ###

PYTHON=python
PYTHON_BUILDFLAGS=

.PHONY: all clean extensions pyflakes api-docs check-nodocs check

all: extensions

extensions:
	@echo "building extension modules."
	$(PYTHON) setup.py build_ext -i $(PYTHON_BUILDFLAGS)

check: docs check-nodocs

check-nodocs: extensions
	$(PYTHON) -Werror -O ./bzr selftest -1v $(tests)
	@echo "Running all tests with no locale."
	LC_CTYPE= LANG=C LC_ALL= ./bzr selftest -1v $(tests) 2>&1 | sed -e 's/^/[ascii] /'

# Run Python style checker (apt-get install pyflakes)
#
# Note that at present this gives many false warnings, because it doesn't
# know about identifiers loaded through lazy_import.
pyflakes:
	pyflakes bzrlib

pyflakes-nounused:
	# There are many of these warnings at the moment and they're not a
	# high priority to fix
	pyflakes bzrlib | grep -v ' imported but unused'

clean:
	$(PYTHON) setup.py clean
	-find . -name "*.pyc" -o -name "*.pyo" -o -name "*.so" | xargs rm -f

# Build API documentation
docfiles = bzr bzrlib
api-docs:
	mkdir -p api/html
	PYTHONPATH=$(PWD) $(PYTHON) tools/bzr_epydoc --html -o api/html --docformat 'restructuredtext en' $(docfiles)
check-api-docs:
	PYTHONPATH=$(PWD) $(PYTHON) tools/bzr_epydoc --check --docformat 'restructuredtext en' $(docfiles)

# build tags for emacs and vim
TAGS:
	ctags -R -e bzrlib

tags:
	ctags -R bzrlib

# these are treated as phony so they'll always be rebuilt - it's pretty quick
.PHONY: TAGS tags

### Documentation ###

# set PRETTY to get docs that look like the Bazaar web site
ifdef PRETTY
rst2html := $(PYTHON) tools/rst2prettyhtml.py doc/bazaar-vcs.org.kid 
else
rst2html := $(PYTHON) tools/rst2html.py --link-stylesheet --footnote-references=superscript --halt=warning
endif

# translate txt docs to html
derived_txt_files := \
	doc/en/user-reference/bzr_man.txt \
	doc/en/release-notes/NEWS.txt
txt_files := $(wildcard doc/en/tutorials/*.txt) \
	$(derived_txt_files) \
	doc/en/user-guide/index.txt \
	doc/en/mini-tutorial/index.txt \
	doc/en/developer-guide/HACKING.txt \
	doc/en/upgrade-guide/index.txt \
	$(wildcard doc/es/guia-usario/*.txt) \
	doc/es/mini-tutorial/index.txt \
	doc/index.txt \
	doc/index.es.txt \
	doc/index.ru.txt \
	doc/ru/user-guide/index.txt \
	doc/ru/mini-tutorial/index.txt \
	$(wildcard doc/ru/tutorials/*.txt)
non_txt_files := \
       doc/default.css \
       doc/en/quick-reference/quick-start-summary.svg \
       doc/en/quick-reference/quick-start-summary.png \
       doc/en/quick-reference/quick-start-summary.pdf \
       $(wildcard doc/en/user-guide/images/*.png) \
       doc/es/referencia-rapida/referencia-rapida.svg \
       doc/es/referencia-rapida/referencia-rapida.png \
       doc/es/referencia-rapida/referencia-rapida.pdf \
       $(wildcard doc/es/guia-usuario/images/*.png) \
       doc/ru/quick-reference/quick-start-summary.svg \
       doc/ru/quick-reference/quick-start-summary.png \
       doc/ru/quick-reference/quick-start-summary.pdf \
       $(wildcard doc/ru/user-guide/images/*.png)
htm_files := $(patsubst %.txt, %.html, $(txt_files)) 

# doc/developers/*.txt files that should *not* be individually
# converted to HTML
dev_txt_nohtml := \
	doc/developers/add.txt \
	doc/developers/annotate.txt \
	doc/developers/bundle-creation.txt \
	doc/developers/commit.txt \
	doc/developers/diff.txt \
	doc/developers/directory-fingerprints.txt \
	doc/developers/gc.txt \
	doc/developers/incremental-push-pull.txt \
	doc/developers/initial-push-pull.txt \
	doc/developers/merge-scaling.txt \
	doc/developers/missing.txt \
	doc/developers/performance-roadmap-rationale.txt \
	doc/developers/performance-use-case-analysis.txt \
	doc/developers/planned-change-integration.txt \
	doc/developers/planned-performance-changes.txt \
	doc/developers/revert.txt \
	doc/developers/status.txt \
	doc/developers/uncommit.txt

dev_txt_all := $(wildcard $(addsuffix /*.txt, doc/developers))
dev_txt_files := $(filter-out $(dev_txt_nohtml), $(dev_txt_all))
dev_htm_files := $(patsubst %.txt, %.html, $(dev_txt_files)) 

doc/%/user-guide/index.html: $(wildcard $(addsuffix /*.txt, doc/%/user-guide)) 
	$(rst2html) --stylesheet=../../default.css $(dir $@)index.txt $@

# Set the paper size for PDF files.
# Options:  'a4' (ISO A4 size), 'letter' (US Letter size)
PAPERSIZE = a4
# TODO: Add generation for Russian PDF
PDF_DOCS := doc/en/user-guide/user-guide.$(PAPERSIZE).pdf

# Copy and modify the RST sources, and convert SVG images to PDF
# files for use a images in the LaTeX-generated PDF.
# Then generate the PDF output from the modified RST sources.
doc/en/user-guide/user-guide.$(PAPERSIZE).pdf: $(wildcard $(addsuffix /*.txt, doc/en/user-guide))
	mkdir -p doc/en/user-guide/latex_prepared
	$(PYTHON) tools/prepare_for_latex.py \
	    --out-dir=doc/en/user-guide/latex_prepared \
	    --in-dir=doc/en/user-guide
	cd doc/en/user-guide/latex_prepared && \
	    $(PYTHON) ../../../../tools/rst2pdf.py \
	        --documentoptions=10pt,$(PAPERSIZE)paper \
	        --input-encoding=UTF-8:strict --output-encoding=UTF-8:strict \
	        --strict --title="Bazaar User Guide" \
	        index.txt ../user-guide.$(PAPERSIZE).pdf

doc/developers/%.html: doc/developers/%.txt
	$(rst2html) --stylesheet=../default.css $< $@

doc/index.html: doc/index.txt
	$(rst2html) --stylesheet=default.css $< $@

doc/index.%.html: doc/index.%.txt
	$(rst2html) --stylesheet=default.css $< $@

%.html: %.txt
	$(rst2html) --stylesheet=../../default.css $< $@

MAN_DEPENDENCIES = bzrlib/builtins.py \
	$(wildcard bzrlib/*.py) \
	$(wildcard bzrlib/*/*.py) \
	tools/generate_docs.py \
	$(wildcard $(addsuffix /*.txt, bzrlib/help_topics/en)) 

doc/en/user-reference/bzr_man.txt: $(MAN_DEPENDENCIES)
	PYTHONPATH=.:$$PYTHONPATH $(PYTHON) tools/generate_docs.py -o $@ rstx

doc/en/release-notes/NEWS.txt: NEWS
	$(PYTHON) -c "import shutil; shutil.copyfile('$<', '$@')"

MAN_PAGES = man1/bzr.1
man1/bzr.1: $(MAN_DEPENDENCIES)
	PYTHONPATH=.:$$PYTHONPATH $(PYTHON) tools/generate_docs.py -o $@ man

upgrade_guide_dependencies =  $(wildcard $(addsuffix /*.txt, doc/en/upgrade-guide)) 

doc/en/upgrade-guide/index.html: $(upgrade_guide_dependencies)
	$(rst2html) --stylesheet=../../default.css $(dir $@)index.txt $@

# build a png of our performance task list
# 
# this is no longer built by default; you can build it if you want to look at it
doc/developers/performance.png: doc/developers/performance.dot
	@echo Generating $@
	@dot -Tpng $< -o$@ || echo "Dot not installed; skipping generation of $@"

derived_web_docs = $(htm_files) $(dev_htm_files) 
WEB_DOCS = $(derived_web_docs) $(non_txt_files)
ALL_DOCS = $(derived_web_docs) $(MAN_PAGES)

# the main target to build all the docs
docs: $(ALL_DOCS)

# produce a tree containing just the final docs, ready for uploading to the web
HTMLDIR := html_docs
html-docs: docs
	$(PYTHON) tools/win32/ostools.py copytree $(WEB_DOCS) $(HTMLDIR)

# Produce PDF documents.  Requires pdfLaTeX, rubber, and Inkscape.
pdf-docs: $(PDF_DOCS)

# clean produced docs
clean-docs:
	$(PYTHON) tools/win32/ostools.py remove $(ALL_DOCS) \
	    $(HTMLDIR) $(derived_txt_files)
	rm -f doc/*/user-guide/*.pdf
	rm -rf doc/*/user-guide/latex_prepared


### Windows Support ###

# make bzr.exe for win32 with py2exe
exe:
	@echo *** Make bzr.exe
	$(PYTHON) tools/win32/ostools.py remove bzrlib/*.pyd
	$(PYTHON) setup.py build_ext -i -f $(PYTHON_BUILDFLAGS)
	$(PYTHON) setup.py py2exe > py2exe.log
	$(PYTHON) tools/win32/ostools.py copytodir tools/win32/start_bzr.bat win32_bzr.exe
	$(PYTHON) tools/win32/ostools.py copytodir tools/win32/bazaar.url win32_bzr.exe

# win32 installer for bzr.exe
installer: exe copy-docs
	@echo *** Make windows installer
	$(PYTHON) tools/win32/run_script.py cog.py -d -o tools/win32/bzr.iss tools/win32/bzr.iss.cog
	iscc /Q tools/win32/bzr.iss

# win32 Python's distutils-based installer
# require to have Python interpreter installed on win32
py-inst-24: docs
	python24 setup.py bdist_wininst --install-script="bzr-win32-bdist-postinstall.py" -d .

py-inst-25: docs
	python25 setup.py bdist_wininst --install-script="bzr-win32-bdist-postinstall.py" -d .

py-inst-26: docs
	python26 setup.py bdist_wininst --install-script="bzr-win32-bdist-postinstall.py" -d .

python-installer: py-inst-24 py-inst-25 py-inst-26


copy-docs: docs
	$(PYTHON) tools/win32/ostools.py copytodir README win32_bzr.exe/doc
	$(PYTHON) tools/win32/ostools.py copytree $(WEB_DOCS) win32_bzr.exe

# clean on win32 all installer-related files and directories
clean-win32: clean-docs
	$(PYTHON) tools/win32/ostools.py remove build
	$(PYTHON) tools/win32/ostools.py remove win32_bzr.exe
	$(PYTHON) tools/win32/ostools.py remove py2exe.log
	$(PYTHON) tools/win32/ostools.py remove tools/win32/bzr.iss
	$(PYTHON) tools/win32/ostools.py remove bzr-setup*.exe
	$(PYTHON) tools/win32/ostools.py remove bzr-*win32.exe
	$(PYTHON) tools/win32/ostools.py remove dist

.PHONY: dist dist-upload-escudero check-dist-tarball

# build a distribution tarball and zip file.
#
# this method of copying the pyrex generated files is a bit ugly; it would be
# nicer to generate it from distutils.
dist: 
	version=`./bzr version --short` && \
	echo Building distribution of bzr $$version && \
	expbasedir=`mktemp -t -d tmp_bzr_dist.XXXXXXXXXX` && \
	expdir=$$expbasedir/bzr-$$version && \
	tarball=$$PWD/../bzr-$$version.tar.gz && \
	zipball=$$PWD/../bzr-$$version.zip && \
	$(MAKE) clean && \
	$(MAKE) && \
	bzr export $$expdir && \
	cp bzrlib/*.c $$expdir/bzrlib/. && \
	tar cfz $$tarball -C $$expbasedir bzr-$$version && \
	(cd $$expbasedir && zip -r $$zipball bzr-$$version) && \
	gpg --detach-sign $$tarball && \
	gpg --detach-sign $$zipball && \
	rm -rf $$expbasedir

# run all tests in a previously built tarball
check-dist-tarball:
	tmpdir=`mktemp -t -d tmp_bzr_check_dist.XXXXXXXXXX` && \
	version=`./bzr version --short` && \
	tarball=$$PWD/../bzr-$$version.tar.gz && \
	tar Cxz $$tmpdir -f $$tarball && \
	$(MAKE) -C $$tmpdir/bzr-$$version check && \
	rm -rf $$tmpdir


# upload previously built tarball to the download directory on bazaar-vcs.org,
# and verify that it can be downloaded ok.
dist-upload-escudero:
	version=`./bzr version --short` && \
	tarball=../bzr-$$version.tar.gz && \
	zipball=../bzr-$$version.zip && \
	scp $$zipball $$zipball.sig $$tarball $$tarball.sig \
	    escudero.ubuntu.com:/srv/bazaar.canonical.com/www/releases/src \
		&& \
	echo verifying over http... && \
	curl http://bazaar-vcs.org/releases/src/bzr-$$version.zip \
		| diff -s - $$zipball && \
	curl http://bazaar-vcs.org/releases/src/bzr-$$version.zip.sig \
		| diff -s - $$zipball.sig 
	curl http://bazaar-vcs.org/releases/src/bzr-$$version.tar.gz \
		| diff -s - $$tarball && \
	curl http://bazaar-vcs.org/releases/src/bzr-$$version.tar.gz.sig \
		| diff -s - $$tarball.sig 
