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
DELTA = 1 * 24 * 60 * 60  # 1 day
TOPIC = 'org.fedoraproject.prod.pkgdb.owner.update'
EMAIL_TO = 'pingou@pingoured.fr'
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
            output = u'%s [%s] was unorphaned by %s' % (
                self.name, ','.join(sorted(self.branch)),
                self.user)
        elif self.new_owner == 'orphan':
            output = u'%s [%s] was orphaned by %s' % (
                self.name, ','.join(sorted(self.branch)),
                self.user)
        else:
            output = u'%s [%s] was changed to "%s" by %s' % (
                self.name, ','.join(sorted(self.branch)),
                self.new_owner, self.user)
        return output


def send_report(report):
    """ This function sends the actual report.
    :arg report: the content to send by email
    """
    msg = MIMEText(report)
    msg['Subject'] = '[Owner-change] Fedora packages ownership change'
    from_email = 'pingou@pingoured.fr'
    msg['From'] = from_email
    msg['To'] = EMAIL_TO

    # Send the message via our own SMTP server, but don't include the
    # envelope header.
    s = smtplib.SMTP(SMTP_SERVER)
    s.sendmail(from_email,
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
            if pkg_name in orphaned:
                orphaned[pkg_name].add_branch(branch)
            else:
                orphaned[pkg_name] = pkg
        elif owner == user:
            if pkg_name in orphaned:
                del(orphaned[pkg_name])

            if pkg_name in changed:
                unorphaned[pkg_name].add_branch(branch)
            else:
                unorphaned[pkg_name] = pkg
        else:
            if pkg_name in orphaned:
                del(orphaned[pkg_name])

            if pkg_name in changed:
                changed[pkg_name].add_branch(branch)
            else:
                changed[pkg_name] = pkg

    hours = int(DELTA) / 3600
    report = 'Change in ownership over the last %s hours\n' % hours
    report += '=' * (40 + len(str(hours))) + '\n'

    report += '%s packages were orphaned\n' % len(orphaned)
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

    report += '\n%s packages changed owner\n' % len(changed)
    report += '-' * (len(str(len(changed))) + 23) + '\n'
    for pkg in changed:
        if not changed[pkg].unorphaned():
            report += changed[pkg].to_string() + '\n'

    if args.nomail:
        print report
    else:
        send_report(report)


if __name__ == '__main__':
    import sys
    sys.exit(main())
