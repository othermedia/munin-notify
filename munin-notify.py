#!/usr/bin/python

'''
Munin-Notify v1.0
by Other Media
http://www.othermedia.com/

Copyright 2015 Other Media

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Author: Jason Woods (devel@jasonwoods.me.uk)
'''

from __future__ import print_function

import datetime
import getopt
import logging
import string
import sys
import time
import yaml

# MuninTargetemail
import socket
import subprocess

# MuninTargethipchat
import json
import requests

# ConfigurationError is raised during startup if there is a configuration problem
class ConfigurationError(Exception):
    pass

# ParseException is raised if Munin sends something that couldn't be parsed
# Usually the cause will be a misconfigured Munin
class ParseException(Exception):
    pass

# MuninTarget provides helper methods for target handlers
class MuninTarget(object):
    def __init__(self):
        self.levels = [
            'FIXED',
            'UNKNOWN',
            'WARNING',
            'CRITICAL',
        ]

    def worst_level(self, status):
        level = 0
        for e in status:
            if e['level'] == 'CRITICAL':
                level = 3
                break
            elif e['level'] == 'WARNING' and level < 2:
                level = 2
            elif e['level'] != 'FIXED' and level < 1:
                level = 1

        return self.levels[level]

    def config_validator(self, config, definition):
        name = string.replace(self.__class__.__name__, 'MuninTarget', '')

        for k, v in config.iteritems():
            if k not in definition and k != 'type':
                raise ConfigurationError('Unknown %s setting: %s' % (name, k))

        for k, v in definition.iteritems():
            if k not in config:
                raise ConfigurationError('hipchat setting %s is required' % k)
            if not isinstance(config[k], v):
                raise ConfigurationError('hipchat setting %s must be a %s (%s given)' % (k, v, config[k].__class__))

    def check_config(self, config):
        raise NotImplementedError('check_config must be implemented')

    def send(self, config, what, status):
        raise NotImplementedError('send must be implemented')

# MuninTargetemail sends notifications to email
class MuninTargetemail(MuninTarget):
    def log_output(self, output):
        out, err = output
        if out is not None:
            logging.info('Output: [%s]', out)
        if err is not None:
            logging.info('Error:  [%s]', err)

    def send_email(self, recipients, subject, content, what):
        d = datetime.date.today()
        cmdline = [
            'mutt', '-s', subject,
            '-e', 'set copy=no',
            '-e', 'set content_type=text/html',
            '-e', 'my_hdr Importance: High',
            '-e', 'my_hdr References: <%(date)s.%(what)s.munin@%(muninserver)s>' % ({
                'date':        d.strftime('%Y%m'),
                'what':        what,
                'muninserver': socket.gethostname(),
            }),
            '--',
        ]
        cmdline += recipients
        logging.info('Running command: %s', ' '.join(cmdline))
        try:
            mutt = subprocess.Popen(cmdline, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.log_output(mutt.communicate(content))
            while mutt.poll() is None:
                time.sleep(1.0)
                self.log_output(mutt.communicate(None))
            logging.info('Email sent successfully')
        except OSError as e:
            logging.error('Email command error: %s', e)

    def create_email(self, what, status):
        level = self.worst_level(status)

        subject = '[%s] [%s] %s' % (level, what['group'], what['host'])
        title = '[%s] %s' % (what['group'], what['host'])
        content = '''
<!DOCTYPE html>
<html><head>
<title>%(title)s</title>
<style type="text/css">
body {
    font-family: Arial, sans-serif;
    color: #000;
    background: transparent;
}
table {
    border-collapse: collapse;
    border: 0;
}
h1, h2, h3, h4, h5, h6, p, table, ul, ol {
    margin: 12px 0;
}
th {
    text-align: left;
    font-weight: normal;
    color: #fff;
    background: #555;
}
th, td {
    padding: 4px;
    border: 1px solid #333;
}
tr.WARNING {
    color: #990;
    font-weight: bold;
}
tr.CRITICAL {
    color: #900;
    font-weight: bold;
}
tr.UNKNOWN {
    color: #999;
    font-weight: bold;
}
tr.FIXED {
    color: #090;
    font-weight: bold;
}
</style>
</head><body>
<h1>%(subject)s</h1>
<p><strong>Date:</strong> %(datetime)s</p>
<p>Munin has triggered the following alerts.</p>
<table cellspacing="0" cellpadding="0" border="0"><tr>
<th>Level</th>
<th>Label</th>
<th>Value</th>
<th>Extra</th>
</tr>'''.lstrip('\n') % ({
            'title':    title,
            'subject':  subject,
            'datetime': datetime.datetime.today().strftime('%d-%m-%Y %H.%M.%S'),
        })

        for e in status:
            content += '''
<tr class="%(level)s">
<td>%(level)s</td>
<td>%(graph_title)s - %(label)s</td>'''.lstrip('\n') % e
            if e['threshold'] == '-':
                content += '''
<td>%(value)s</td>'''.lstrip('\n') % e
            else:
                content += '''
<td>%(value)s [%(threshold)s]</td>'''.lstrip('\n') % e
            content += '''
<td>%(extra)s</td>
</tr>'''.lstrip('\n') % e

        content += '''
</table>
<p style="font-size: 80%%"><i>Sent by <a href="https://github.com/othermedia/munin-notify">Munin-Notify</a> on %s.</i></p>
</body>
</html>'''.lstrip('\n') % socket.gethostname()
        return subject, content

    def check_config(self, config):
        definition = {
            'recipients': list,
        }

        self.config_validator(config, definition)

        if len(config['recipients']) < 1:
            raise ConfigurationError('email setting recipients must contain at least one email address')

    def send(self, config, what, status):
        subject, content = self.create_email(what, status)
        logging.info('Sending email report with subject: %s', subject)
        self.send_email(config['recipients'], subject, content, '%(group)s.%(host)s' % what)


# MuninTargethipchat sends notifications to HipChat
class MuninTargethipchat(MuninTarget):
    def __init__(self):
        super(MuninTargethipchat, self).__init__()

        self.levels_img = {
            'FIXED':    'icon-build-successful.png',
            'UNKNOWN':  'icon-build-disabled.png',
            'WARNING':  'icon-build-failed.png',
            'CRITICAL': 'icon-emoticon-error.png',
        }

        self.levels_colour = {
            'FIXED':    'green',
            'UNKNOWN':  'gray',
            'WARNING':  'yellow',
            'CRITICAL': 'red',
        }

    def hipchat(self, config, message, colour):
        # This access token is a v1 API token for the group. Label is Fabric
        # Cannot use v2 as it needs to be setup as an Add-On, or use a personal token, which forces From=Name of Person
        headers = {
          'Authorization': 'Bearer %s' % (config['token']),
          'Content-Type': 'application/json',
        }

        payload = {
          'message_format': 'html',
          'notify': True,
          'color': colour,
          'message': message,
        }

        logging.info('Posting HipChat notification:\n%s', payload['message'])
        requests.post(url='http://api.hipchat.com/v2/room/%s/notification' % config['room'], headers=headers, data=json.dumps(payload))

    def check_config(self, config):
        definition = {
            'room':  int,
            'token': basestring,
        }

        self.config_validator(config, definition)

    def send(self, config, what, status):
        message = '<b>[%(group)s] %(host)s</b>' % what
        for e in status:
            if e['level'] in self.levels_img:
                e['img'] = self.levels_img[e['level']]
            else:
                e['img'] = self.levels_img['UNKNOWN']
            message += '<br>\n<img src="http://bamboo.othermedia.com/images/iconsv4/%(img)s" alt=""> <b>%(level)s</b>: %(graph_title)s - %(label)s' % e
            if e['threshold'] == '-':
                message += ' = %(value)s' % e
            else:
                message += ' = %(value)s [%(threshold)s]' % e
            if e['extra'] != '':
                message += ' - %(extra)s' % e

        level = self.worst_level(status)
        if level in self.levels_colour:
            colour = self.levels_colour[level]
        else:
            colour = self.levels_colour['UNKNOWN']

        self.hipchat(config, message, colour)

# MuninNotifications is the main class
class MuninNotifications(object):
    def __init__(self):
        self.targets = {}

        self.levels = [
            'FIXED',
            'UNKNOWN',
            'WARNING',
            'CRITICAL',
        ]

        log_config = {
            'level': logging.NOTSET,
        }

        try:
            opts, args = getopt.getopt(sys.argv[1:], 'hl:', ['help', 'log-file='])
        except getopt.GetoptError as e:
            self.quit_with_usage(e)

        if len(args) != 0:
            self.quit_with_usage('Unexpected arguments')

        for o, v in opts:
            if o == '--log-file':
                log_config['filename'] = v
            elif o in ('-h', '--help'):
                self.quit_with_usage()
            else:
                self.quit_with_usage('unhandled option: %s' % o)

        try:
            # pylint: disable=W0142
            logging.basicConfig(**log_config)
        except IOError as e:
            self.quit_with_usage(e)

        logging.info('=====STARTING %s=====', datetime.datetime.today().strftime('%d-%m-%Y %H.%M.%S'))

        try:
            self.config = self.load_config('/etc/munin/munin-notify.yml')

            if 'targets' not in self.config:
                raise ConfigurationError('targets missing')
            elif not isinstance(self.config['targets'], list):
                raise ConfigurationError('targets is not a list')
            elif len(self.config['targets']) < 1:
                raise ConfigurationError('At least one target must be specified')

            i = 0
            for target in self.config['targets']:
                i += 1
                if 'type' not in target:
                    raise ConfigurationError('Target entry %d does not specify type' % i)

                if target['type'] not in self.targets:
                    try:
                        self.targets[target['type']] = globals()['MuninTarget%s' % target['type']]()
                    except NameError:
                        raise ConfigurationError('Target %s could not be found' % target['type'])

                self.targets[target['type']].check_config(target)

        except ConfigurationError as e:
            logging.error('Configuration error: %s', e)
            sys.exit(1)

        self.what = None
        self.meta = None
        self.status = None

        try:
            self.parse()
        except ParseException as e:
            logging.error('Parse error: %s', e)
        except IOError as e:
            logging.error('Failed to read: %s', e)
        except KeyboardInterrupt as e:
            pass

        logging.info('=====FINISHED=====')

    def quit_with_usage(self, error=None):
        if error != None:
            print(error)
            print()
        print('Usage: munin-notify [--log-file=<filename>]')
        print('  --log-file=<filename>')
        print('    Specified a path to a file to send log messages to. If no')
        print('    path is specified, logs are printed to STDOUT.')
        sys.exit(1)

    def load_config(self, fname):
        try:
            with open(fname, 'r') as r:
                return yaml.load(r)
        except IOError as e:
            raise ConfigurationError('Failed to read configuration: %s' % e)
        except yaml.YAMLError as e:
            raise ConfigurationError('YAML error: %s' % e)

    def invoke_targets(self):
        for target in self.config['targets']:
            logging.info('Invoking target: %s', target['type'])
            self.targets[target['type']].send(target, self.what, self.status)

    def parse_what(self, line):
        s = line.split(' / ')
        if len(s) != 4:
            raise ParseException('Host line invalid')
        what = {
            'group':          s[0],
            'host':           s[1],
            'graph_category': s[2],
            'graph_title':    s[3],
        }
        return what

    def parse_status(self, line):
        s = line.split(' / ')
        if len(s) != 5:
            raise ParseException('Status line invalid')
        status = {
            'level':     s[0],
            'label':     s[1],
            'value':     s[2],
            'threshold': s[3],
            'extra':     s[4],
        }
        return status

    def parse(self):
        while True:
            line = sys.stdin.readline()
            if line == '':
                break
            line = line.rstrip('\r\n')
            if line.lstrip(' \t') == '':
                continue
            logging.info("Input: [%s]", line)
            if line[0] != ' ' and line[0] != '\t':
                host_line = self.parse_what(line)
                if self.what is not None and len(self.status) > 0 and (host_line['host'] != self.what['host'] or host_line['group'] != self.what['group']):
                    self.invoke_targets()
                    self.status = None
                self.what = {
                    'host': host_line['host'],
                    'group': host_line['group'],
                }
                meta = {
                    'graph_category': host_line['graph_category'],
                    'graph_title': host_line['graph_title'],
                }
                if self.status is None:
                    self.status = []
            else:
                if self.status is None:
                    raise ParseException('Invalid input encountered')
                new_status = meta.copy()
                new_status.update(self.parse_status(line.lstrip(' \t')))
                self.status.append(new_status)
        if self.what is not None and len(self.status) > 0:
            self.invoke_targets()

MuninNotifications()
