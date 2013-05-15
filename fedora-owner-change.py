#!/usr/bin/python -tt
#-*- coding: utf-8 -*-

#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

"""
This program checks and reports the packages owner change in pkgdb using
its messages catched by datanommer and available via datagrepper.

Dependencies:
* python-requests
"""

import json
import logging
import requests
import sys


DATAGREPPER_URL = 'https://apps.fedoraproject.org/datagrepper/raw/'
DELTA = '86400'  # time in seconds: 24 * 60 * 60 = 24h
TOPIC = 'org.fedoraproject.prod.pkgdb.owner.update'

# Initial simple logging stuff
logging.basicConfig()
LOG = logging.getLogger("owner-change")

if '--debug' in sys.argv:
    LOG.setLevel(logging.DEBUG)


class PkgChange(object):

    def __init__(self, name, summary, branch, new_owner, user):
        """ Constructor, fills in the basic information.
        """
        self.name = name
        self.summary = summary
        self.branch = [branch]
        self.new_owner = new_owner
        self.user = user

    def add_branch(self, branch):
        """ Add a branch to the current ones. """
        self.branch.append(branch)

    def __repr__(self):
        """ String representation of the object. """
        return u'%s [%s] was changed to "%s" by %s' % (
            self.name, ','.join(sorted(self.branch)),
            self.new_owner, self.user)


def retrieve_pkgdb_change():
    """ Query datagrepper to retrieve the list of change in ownership
    on packages of pkgdb over the DELTA period of time.
    """
    messages = []
    page = 1
    pages = 2
    while page <= pages:
        LOG.debug('Retrieving page %s of %s' %(page, pages))
        data = {'delta': DELTA,
                'topic': TOPIC,
                'rows_per_page': 100,
                'page': page,
                }
        output = requests.get(DATAGREPPER_URL, params=data)
        json_output = json.loads(output.text)
        pages = json_output['pages']
        page += 1
        messages.extend(json_output['raw_messages'])

    LOG.debug('Should have retrieved %s' % json_output['total'])
    return messages


def main():
    """ Retrieve all the change in ownership from pkgdb via datagrepper
    and report the changes either as packages have been orphaned or
    packages changed owner.
    """
    hours = int(DELTA) / 3600
    print 'Change in ownership over the last %s hours' % hours
    print '=' * (40 + len(str(hours))), '\n'

    changes = retrieve_pkgdb_change()
    LOG.debug('%s changes retrieved' % len(changes))
    orphaned = {}
    changed = {}
    for change in changes:
        pkg_name = change['msg']['package_listing']['package']['name']
        owner = change['msg']['package_listing']['owner']
        branch = change['msg']['package_listing']['collection']['branchname']
        LOG.debug('%s changed to %s by %s on %s' % (
                  pkg_name, owner, change['msg']['agent'], branch))
        pkg = PkgChange(
                name=pkg_name,
                summary=change['msg']['package_listing']['package']['summary'],
                branch=branch,
                new_owner=owner,
                user=change['msg']['agent'],
                )

        if owner == 'orphan':
            if pkg_name in orphaned:
                orphaned[pkg_name].add_branch(branch)
            else:
                orphaned[pkg_name] = pkg
        else:
            if pkg_name in orphaned:
                del(orphaned[pkg_name])

            if pkg_name in changed:
                changed[pkg_name].add_branch(branch)
            else:
                changed[pkg_name] = pkg

    print '%s packages were orphaned' % len(orphaned)
    print '-' * (len(str(len(orphaned))) + 23)
    for pkg in orphaned:
        print orphaned[pkg]
        print ' ' * 5, orphaned[pkg].summary
        print ' ' * 5, 'https://admin.fedoraproject.org/pkgdb/'\
                       'acls/name/%s\n' % orphaned[pkg].name
    
    print '\n%s packages changed owner' % len(changed)
    print '-' * (len(str(len(changed))) + 23)
    for pkg in changed:
        print changed[pkg], '\n'


if __name__ == '__main__':
    import sys
    sys.exit(main())
