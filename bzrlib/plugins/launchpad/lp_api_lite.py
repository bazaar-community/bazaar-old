# Copyright (C) 2011 Canonical Ltd
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

"""Tools for dealing with the Launchpad API without using launchpadlib.

The api itself is a RESTful interface, so we can make HTTP queries directly.
loading launchpadlib itself has a fairly high overhead (just calling
Launchpad.login_anonymously() takes a 500ms once the WADL is cached, and 5+s to
get the WADL.
"""

try:
    # Use simplejson if available, much faster, and can be easily installed in
    # older versions of python
    import simplejson as json
except ImportError:
    # Is present since python 2.6
    try:
        import json
    except ImportError:
        json = None

import urllib
import urllib2

from bzrlib import trace


DEFAULT_SERIES = 'oneiric'

class LatestPublication(object):
    """Encapsulate how to find the latest publication for a given project."""

    LP_API_ROOT = 'https://api.launchpad.net/1.0'

    def __init__(self, archive, series, project):
        self._archive = archive
        self._project = project
        self._setup_series_and_pocket(series)

    def _archive_URL(self):
        return '%s/%s/+archive/primary' % (self.LP_API_ROOT, self._archive)

    def _publication_status(self):
        if self._archive == 'debian':
            # Launchpad only tracks debian packages as "Pending", it doesn't mark
            # them Published
            return 'Pending'
        return 'Published'

    def _setup_series_and_pocket(self, series):
        self._series = series
        self._pocket = None
        if self._series is not None and '-' in self._series:
            self._series, self._pocket = self._series.split('-', 1)
            self._pocket = self._pocket.title()

    def _query_params(self):
        params = {'ws.op': 'getPublishedSources',
                  'exact_match': 'true',
                  # If we need to use "" shouldn't we quote the project somehow?
                  'source_name': '"%s"' % (self._project,),
                  'status': self._publication_status(),
                  # We only need the latest one, the results seem to be properly
                  # most-recent-debian-version sorted
                  'ws.size': '1',
        }
        if self._series is not None:
            params['distro_series'] = '/%s/%s' % (self._archive, self._series)
        if self._pocket is not None:
            params['pocket'] = self._pocket
        return params

    def _query_URL(self):
        params = self._query_params()
        # We sort to give deterministic results for testing
        encoded = urllib.urlencode(sorted(params.items()))
        return '%s?%s' % (self._archive_URL(), encoded)

    def _get_lp_info(self):
        query_URL = self._query_URL()
        try:
            req = urllib2.Request(query_URL)
            response = urllib2.urlopen(req)
            json_txt = response.read()
        except (urllib2.URLError,), e:
            trace.mutter('failed to place query to %r' % (query_URL,))
            trace.log_exception_quietly()
            return None
        return json_txt


def get_latest_publication(archive, series, project):
    """Get the most recent publication for a given project.

    :param archive: Either 'ubuntu' or 'debian'
    :param series: Something like 'natty', 'sid', etc. Can be set as None. Can
        also include a pocket such as 'natty-proposed'.
    :param project: Something like 'bzr'
    :return: A version string indicating the most-recent version published in
        Launchpad. Might return None if there is an error.
    """
    if json is None:
        return None
    archive_url = '%s/%s/+archive/primary?' % (LP_API_ROOT, archive)
    pocket = None
    # TODO: If series is None, we probably need to hard-code it. I don't have
    #       proof yet, but otherwise we just get the most-recent version in any
    #       series, rather than getting the one for eg 'oneiric'. The problem I
    #       envision is that natty-proposed might have a newer version than
    #       'oneiric'. Is this a useful distinction in practice?
    if series is not None and '-' in series:
        # The lp: URL 'lp:ubuntu/natty-proposed/...' is translated into series
        # 'natty' pocket 'proposed'
        try:
            series, pocket = series.split('-')
        except ValueError, e:
            trace.mutter('failed to find series,pocket from %s' % (series,))
            return None
        # pocket must be in 'Title' case, so Proposed, not 'proposed'.
        pocket = pocket.title()
    params = {'ws.op': 'getPublishedSources',
              'exact_match': 'true',
              # If we need to use "" shouldn't we quote the project somehow?
              'source_name': '"%s"' % (project,),
              'status': status,
              # We only need the latest one, the results seem to be properly
              # most-recent-debian-version sorted
              'ws.size': '1',
    }
    if series is not None:
        params['distro_series'] = '/%s/%s' % (archive, series)
    if pocket is not None:
        params['pocket'] = pocket
    query_url = archive_url + urllib.urlencode(params)
    try:
        req = urllib2.Request(query_url)
        response = urllib2.urlopen(req)
        json_txt = response.read()
    except urllib2.HTTPError, e:
        trace.mutter('failed to place query to %r' % (query_url,))
        trace.log_exception_quietly()
        return None
    try:
        o = json.loads(json_txt)
    except Exception:
        # simplejson raises simplejson.decoder.JSONDecodeError,
        # but json raises ValueError, so we just catch a generic error and move
        # on
        trace.log_exception_quietly()
        return None
    try:
        for e in o['entries']:
            this_name = e['source_package_name']
            this_ver = e['source_package_version']
            # this_comp seems to always be 'main', are we supposed to do
            # something with it?
            # this_comp = e['component_name']
            # pocket = e['pocket'].lower()
            # series = e['distro_series_link'].split('/')[-1]
            # if pocket != 'release':
            #     series += '-' + pocket
            return this_ver
    except KeyError:
        # Some expected attribute was missing
        trace.log_exception_quietly()
        return None
    trace.mutter('No versions found for: %r', query_url)
    return None
