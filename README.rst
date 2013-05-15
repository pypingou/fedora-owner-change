Fedora Owner Changes
====================

Small application to retrieve and report the ownership changed that occured in
the `Fedora package database <https://admin.fedoraproject.org/pkgdb>`_.

Since not all ownership changes are announced on the list, running this script
in a cron job on a daily/bi-daily/weekly basis would allow to inform Fedora
contributor about ownership changes eventually allowing anyone to pick up
orphaned packages earlier than at the release orphan clean-up.



To debug, run fedora-owner-change.py with a ``--debug`` argument.
