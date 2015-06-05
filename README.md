# munin-notify

## Overview

Send Munin notifications to email or HipChat!

Pull requests welcome for additional targets.

## Usage

1. Install PyYAML (`yum install PyYAML` / `pip install pyyaml`)
1. Install mutt (`yum install mutt`)
1. Save munin-notify.py to /etc/munin
1. Chmod munin-notify.py to 0755
1. Add the following to /etc/munin/munin.conf:

        contact.alerts.text ${var:group} / ${var:host} / ${var:graph_category} / ${var:graph_title}\n\
        ${loop<\n>:wfields  WARNING / ${var:label} / ${var:value} / ${var:wrange} / ${var:extinfo}}\n\
        ${loop<\n>:cfields  CRITICAL / ${var:label} / ${var:value} / ${var:crange} / ${var:extinfo}}\n\
        ${loop<\n>:ufields  UNKNOWN / ${var:label} / ${var:value} / - / ${var:extinfo}}\n\
        ${loop<\n>:fofields  FIXED / ${var:label} / ${var:value} / - / ${var:extinfo}}\n

        contact.alerts.command /etc/munin/munin-notify.py --log-file /var/log/munin/munin-notify.log

1. Configure your alert targets in /etc/munin/munin-notify.yml

        targets:
          - type: email
            recipients: [ user@example.com ]
          - type: hipchat
            room: 123456
            token: abcdef0123456789abcdef0123456789

## Known Munin Issues

There are several known issues with Munin's alerting.

1. FIXED alerts do not work correctly (fixed in Munin 2.0.26 - patch available at https://github.com/munin-monitoring/munin/pull/334)
2. Inherited alert values do not produce alerts (not yet merged - patch available at https://github.com/munin-monitoring/munin/pull/362)
