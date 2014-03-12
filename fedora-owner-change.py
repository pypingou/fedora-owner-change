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
* python-argparse
"""

import argparse
import json
import logging
import requests
import smtplib
import sys

from email.mime.text import MIMEText


DATAGREPPER_URL = 'https://apps.fedoraproject.org/datagrepper/raw/'
DELTA = 7 * 24 * 60 * 60  # 7 days
TOPIC = 'org.fedoraproject.prod.pkgdb.owner.update'
EMAIL_TO = ''
EMAIL_FROM = ''
SMTP_SERVER = 'localhost'

# Initial simple logging stuff
logging.basicConfig()
LOG = logging.getLogger("owner-change")


class PkgChange(object):

    def __init__(self, name, summary, branch, new_owner, user):
        """ Constructor, fills in the basic information.
        """
        self.name = name
        self.summary = summary
        self.branch = [branch]
        self.new_owner = new_owner
        self.user = user

    def __repr__(self):
        return '<PkgChange(Name:{0}, branch:[{1}], new_owner:{2}, '\
            'user:{3})>'.format(self.name, ','.join(self.branch),
                                self.new_owner, self.user)

    def add_branch(self, branch):
        """ Add a branch to the current ones. """
        self.branch.append(branch)

    def unorphaned(self):
        """ Returns a boolean specifying if the package has been
        unorphaned or not.
        """
        return self.new_owner == self.user

    def to_string(self):
        """ String representation of the object adjusted for the
        ownership change.
        """
        if self.new_owner == self.user:
            output = u'%s unorphaned : %s [%s]' % (
                self.user.ljust(15), self.name, ','.join(sorted(self.branch)))
        elif self.new_owner == 'orphan':
            output = u'%s [%s] was orphaned by %s' % (
                self.name, ','.join(sorted(self.branch)), self.user)
        elif self.new_owner == 'retired':
            output = u'%s [%s] was retired by %s' % (
                self.name, ','.join(sorted(self.branch)), self.user)
        else:
            output = u'%s gave to %s    : %s [%s]' % (
                self.user.ljust(15), self.new_owner.ljust(15),
                self.name, ','.join(sorted(self.branch)))
        return output


def send_report(report):
    """ This function sends the actual report.
    :arg report: the content to send by email
    """
    report = report.encode('utf-8', 'replace')
    msg = MIMEText(report)
    msg['Subject'] = '[Owner-change] Fedora packages ownership change'
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO

    # Send the message via our own SMTP server, but don't include the
    # envelope header.
    s = smtplib.SMTP(SMTP_SERVER)
    s.sendmail(EMAIL_FROM,
               EMAIL_TO,
               msg.as_string())
    s.quit()


def retrieve_pkgdb_change():
    """ Query datagrepper to retrieve the list of change in ownership
    on packages of pkgdb over the DELTA period of time.
    """
    messages = []
    page = 1
    pages = 2
    while page <= pages:
        LOG.debug('Retrieving page %s of %s' % (page, pages))
        data = {'delta': DELTA,
                'topic': TOPIC,
                'rows_per_page': 100,
                'page': page,
                'order': 'desc',
                }
        output = requests.get(DATAGREPPER_URL, params=data)
        json_output = json.loads(output.text)
        pages = json_output['pages']
        page += 1
        messages.extend(json_output['raw_messages'])

    LOG.debug('Should have retrieved %s' % json_output['total'])
    return messages


def retrieve_pkgdb_retired():
    """ Query datagrepper to retrieve the list of package retired
    in pkgdb over the DELTA period of time.
    """
    messages = []
    page = 1
    pages = 2
    while page <= pages:
        LOG.debug('Retrieving page %s of %s' % (page, pages))
        data = {'delta': DELTA,
                'topic': 'org.fedoraproject.prod.pkgdb.package.retire',
                'rows_per_page': 100,
                'page': page,
                'order': 'desc',
                }
        output = requests.get(DATAGREPPER_URL, params=data)
        json_output = json.loads(output.text)
        pages = json_output['pages']
        page += 1
        messages.extend(json_output['raw_messages'])

    LOG.debug('Should have retrieved %s' % json_output['total'])
    return messages


def setup_parser():
    """
    Set the command line arguments.
    """
    parser = argparse.ArgumentParser(
        prog="fedora-owner-change")
    parser.add_argument(
        '--nomail', action='store_true',
        help="Prints the report instead of sending it by email")
    parser.add_argument(
        '--debug', action='store_true',
        help="Outputs debugging info")
    return parser


def main():
    """ Retrieve all the change in ownership from pkgdb via datagrepper
    and report the changes either as packages have been orphaned or
    packages changed owner.
    """
    parser = setup_parser()
    args = parser.parse_args()

    global LOG
    if args.debug:
        LOG.setLevel(logging.DEBUG)

    changes = retrieve_pkgdb_change()
    LOG.debug('%s changes retrieved' % len(changes))
    orphaned = {}
    unorphaned = {}
    changed = {}
    for change in changes:
        pkg_name = change['msg']['package_listing']['package']['name']
        owner = change['msg']['package_listing']['owner']
        branch = change['msg']['package_listing']['collection']['branchname']
        user = change['msg']['agent']
        LOG.debug('%s changed to %s by %s on %s' % (
                  pkg_name, owner, user, branch))
        pkg = PkgChange(
            name=pkg_name,
            summary=change['msg']['package_listing']['package']['summary'],
            branch=branch,
            new_owner=owner,
            user=user,
        )

        if owner == 'orphan':
            LOG.debug('package orphaned')
            if pkg_name in orphaned:
                orphaned[pkg_name].add_branch(branch)
            else:
                orphaned[pkg_name] = pkg
        elif owner == user:
            LOG.debug('package unorphaned')
            if pkg_name in orphaned:
                del(orphaned[pkg_name])

            if pkg_name in unorphaned:
                unorphaned[pkg_name].add_branch(branch)
            else:
                unorphaned[pkg_name] = pkg
        else:
            LOG.debug('package changed')
            if pkg_name in orphaned:
                del(orphaned[pkg_name])

            if pkg_name in changed:
                changed[pkg_name].add_branch(branch)
            else:
                changed[pkg_name] = pkg

    # Orphaned packages might have been deprecated:
    retired_info = retrieve_pkgdb_retired()
    retired = {}
    for pkg in retired_info:
        pkg_name = pkg['msg']['package_listing']['package']['name']
        LOG.debug('Retired: %s' % (pkg_name))
        if pkg_name in orphaned:
            pkg = orphaned[pkg_name]
            del(orphaned[pkg_name])
            pkg.new_owner = 'retired'
            retired[pkg_name] = pkg

    hours = int(DELTA) / 3600
    report = 'Change in ownership over the last %s hours\n' % hours
    report += '=' * (40 + len(str(hours))) + '\n'

    report += '\n%s packages were orphaned\n' % len(orphaned)
    report += '-' * (len(str(len(orphaned))) + 23) + '\n'
    for pkg in orphaned:
        report += orphaned[pkg].to_string() + '\n'
        report += ' ' * 5 + orphaned[pkg].summary + '\n'
        report += ' ' * 5 + 'https://admin.fedoraproject.org/pkgdb/'\
            'acls/name/%s\n' % orphaned[pkg].name

    report += '\n%s packages unorphaned\n' % len(unorphaned)
    report += '-' * (len(str(len(unorphaned))) + 20) + '\n'
    for pkg in unorphaned:
        if unorphaned[pkg].unorphaned():
            report += unorphaned[pkg].to_string() + '\n'

    report += '\n%s packages were retired\n' % len(retired)
    report += '-' * (len(str(len(retired))) + 23) + '\n'
    for pkg in retired:
        report += retired[pkg].to_string() + '\n'
        report += ' ' * 5 + retired[pkg].summary + '\n'
        report += ' ' * 5 + 'https://admin.fedoraproject.org/pkgdb/'\
            'acls/name/%s\n' % retired[pkg].name

    report += '\n%s packages changed owner\n' % len(changed)
    report += '-' * (len(str(len(changed))) + 23) + '\n'
    for pkg in changed:
        if not changed[pkg].unorphaned():
            report += changed[pkg].to_string() + '\n'

    report += '\n\nSources: https://github.com/pypingou/fedora-owner-change'

    if args.nomail:
        print report
    else:
        send_report(report)


if __name__ == '__main__':
    import sys
    sys.exit(main())
