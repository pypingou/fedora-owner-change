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
                'topic': [
                    'org.fedoraproject.prod.pkgdb.owner.update',
                    'org.fedoraproject.prod.pkgdb.package.retire',
                ],
                'rows_per_page': 100,
                'page': page,
                'order': 'asc',
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


def __format_dict(dic):
    keys = dic.keys()
    pkgs = [it[0] for it in keys]
    tmp = {}
    for pkg in pkgs:
        lcl_keys = [key for key in keys if pkg in key]
        for key in lcl_keys:
            lcl = json.dumps(dic[key])
            if lcl in tmp:
                tmp[lcl].append(key)
            else:
                tmp[lcl] = [key]

    output = {}
    for key in tmp:
        pkg_name = tmp[key][0][0]
        branches = set([val[1] for val in tmp[key]])
        data = json.loads(key)
        data['pkg_name'] = pkg_name
        data['branches'] = ','.join(sorted(branches, key=unicode.lower))
        output[pkg_name] = data

    return output


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
    retired = {}
    unorphaned = {}
    unretired = {}
    changed = {}
    for change in changes:
        pkg_name = change['msg']['package_listing']['package']['name']
        owner = change['msg']['package_listing']['owner']
        branch = change['msg']['package_listing']['collection']['branchname']
        user = change['msg']['agent']
        LOG.debug('"%s" changed to %s by %s on %s - topic: %s' % (
                  pkg_name, owner, user, branch, change['topic']))

        key = (pkg_name, branch)

        if 'retirement' in change['msg'] \
                and change['msg']['retirement'] == 'retired':
            LOG.debug('package retired')

            if key in orphaned:
                del orphaned[key]

            value = {
                'user': user,
                'owner': owner,
                'summary': change['msg']['package_listing']['package']['summary']}

            retired[key] = value

        elif 'retirement' in change['msg'] \
                and change['msg']['retirement'] == 'unretired':
            LOG.debug('package unretired')

            if key in orphaned:
                del orphaned[key]

            value = {
                'user': user,
                'owner': owner,
                'summary': change['msg']['package_listing']['package']['summary']}

            unretired[key] = value

        elif not 'retirement' in change['msg'] and owner == 'orphan':
            LOG.debug('package orphaned')

            value = {
                'user': user,
                'owner': owner,
                'summary': change['msg']['package_listing']['package']['summary']}

            orphaned[key] = value

        elif not 'retirement' in change['msg'] and owner == user:
            LOG.debug('package unorphaned')

            self_change = False
            if key in orphaned:
                if 'by %s' % user in orphaned[key]:
                    self_change = True
                del orphaned[key]

            value = {
                'user': user,
                'owner': owner,
                'summary': change['msg']['package_listing']['package']['summary']}

            if not self_change:
                unorphaned[key] = value

        else:
            LOG.debug('package changed')

            value = {
                'user': user,
                'owner': owner,
                'summary': change['msg']['package_listing']['package']['summary']}

            changed[key] = value

    hours = int(DELTA) / 3600
    report = 'Change in ownership over the last %s hours\n' % hours
    report += '=' * (40 + len(str(hours))) + '\n'
    orphaned = __format_dict(orphaned)
    report += '\n%s packages were orphaned\n' % len(orphaned)
    report += '-' * (len(str(len(orphaned))) + 23) + '\n'

    for pkg in sorted(orphaned, key=unicode.lower):
        value = u'%(pkg_name)s [%(branches)s] was orphaned by %(user)s' % (
                orphaned[pkg])
        report += value + '\n'
        report += ' ' * 5 + orphaned[pkg]['summary'] + '\n'
        report += ' ' * 5 + 'https://admin.fedoraproject.org/pkgdb/'\
            'acls/name/%s\n' % pkg

    unorphaned = __format_dict(unorphaned)
    report += '\n%s packages unorphaned\n' % len(unorphaned)
    report += '-' * (len(str(len(unorphaned))) + 20) + '\n'
    for pkg in sorted(unorphaned, key=unicode.lower):
        value = u'%s unorphaned : %s [%s]' % (
            unorphaned[pkg]['user'].ljust(15), unorphaned[pkg]['pkg_name'],
            unorphaned[pkg]['branches'])
        report += value + '\n'

    retired = __format_dict(retired)
    report += '\n%s packages were retired\n' % len(retired)
    report += '-' * (len(str(len(retired))) + 23) + '\n'
    for pkg in sorted(retired, key=unicode.lower):
        value = u'%(pkg_name)s [%(branches)s] was retired by %(user)s' % (
                retired[pkg])
        report += value + '\n'
        report += ' ' * 5 + retired[pkg]['summary'] + '\n'
        report += ' ' * 5 + 'https://admin.fedoraproject.org/pkgdb/'\
            'acls/name/%s\n' % pkg[0]

    unretired = __format_dict(unretired)
    report += '\n%s packages were unretired\n' % len(unretired)
    report += '-' * (len(str(len(unretired))) + 23) + '\n'
    for pkg in sorted(unretired, key=unicode.lower):
        value = u'%(pkg_name)s [%(branches)s] was unretired by %(user)s' % (
                unretired[pkg])
        report += value + '\n'
        report += ' ' * 5 + unretired[pkg]['summary'] + '\n'
        report += ' ' * 5 + 'https://admin.fedoraproject.org/pkgdb/'\
            'acls/name/%s\n' % pkg[0]

    changed = __format_dict(changed)
    report += '\n%s packages changed owner\n' % len(changed)
    report += '-' * (len(str(len(changed))) + 23) + '\n'
    for pkg in sorted(changed, key=unicode.lower):
        value = u'%s gave to %s    : %s [%s]' % (
            changed[pkg]['user'].ljust(15), changed[pkg]['owner'].ljust(15),
            changed[pkg]['pkg_name'], changed[pkg]['branches'])
        report += value + '\n'

    report += '\n\nSources: https://github.com/pypingou/fedora-owner-change'

    if args.nomail:
        print report
    else:
        send_report(report)


if __name__ == '__main__':
    import sys
    sys.exit(main())
