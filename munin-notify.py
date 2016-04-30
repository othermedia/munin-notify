#!/usr/bin/python
# pylint: disable=C0103

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

class ConfigurationError(Exception):
    '''
    ConfigurationError is raised during startup if there is a configuration problem
    '''
    pass

class ParseException(Exception):
    '''
    ParseException is raised if Munin sends something that couldn't be parsed
    Usually the cause will be a misconfigured Munin
    '''
    pass

def log_output(output):
    '''
    Helper to output diagnostics to stdout
    '''
    out, err = output
    if out is not None:
        logging.info('Output: [%s]', out)
    if err is not None:
        logging.info('Error:  [%s]', err)

def quit_with_usage(error=None):
    '''
    Quit the program and report Usage information
    '''
    if error != None:
        print(error)
        print()
    print('Usage: munin-notify [--log-file=<filename>]')
    print('  --log-file=<filename>')
    print('    Specified a path to a file to send log messages to. If no')
    print('    path is specified, logs are printed to STDOUT.')
    sys.exit(1)

class MuninTarget(object):
    '''
    MuninTarget provides helper methods for target handlers
    '''
    def __init__(self):
        self.levels = [
            'FIXED',
            'UNKNOWN',
            'WARNING',
            'CRITICAL',
        ]

    def worst_level(self, status):
        '''
        Calculate the worst alert level in the set of alerts we're processing
        '''
        level = 0
        for entry in status:
            if entry['level'] == 'CRITICAL':
                level = 3
                break
            elif entry['level'] == 'WARNING' and level < 2:
                level = 2
            elif entry['level'] != 'FIXED' and level < 1:
                level = 1

        return self.levels[level]

    def config_validator(self, config, definition):
        '''
        Validate the configuration
        '''
        name = string.replace(self.__class__.__name__, 'MuninTarget', '')

        for key, value in config.iteritems():
            if key not in definition and key != 'type':
                raise ConfigurationError('Unknown %s setting: %s' % (name, key))

        for key, value in definition.iteritems():
            if key not in config:
                raise ConfigurationError('hipchat setting %s is required' % key)
            if not isinstance(config[key], value):
                raise ConfigurationError(
                    'hipchat setting %s must be a %s (%s given)' %
                    (key, value, config[key].__class__))

    def check_config(self, config):
        '''
        Abstract method for configuration check for a target
        '''
        raise NotImplementedError('check_config must be implemented')

    def send(self, config, what, status):
        '''
        Abstract method for target send
        '''
        raise NotImplementedError('send must be implemented')

class MuninTargetemail(MuninTarget):
    '''
    Send Munin email notifications
    '''
    def __init__(self):
        super(MuninTargetemail, self).__init__()
        self.what = None
        self.status = None
        self.subject = None
        self.content = None

    def send_email(self, recipients, what):
        '''
        Send an email using mutt
        '''
        date = datetime.date.today()
        cmdline = [
            'mutt', '-s', self.subject,
            '-e', 'set copy=no',
            '-e', 'set content_type=text/html',
            '-e', 'my_hdr Importance: High',
            '-e', 'my_hdr References: <%(date)s.%(what)s.munin@%(muninserver)s>' % ({
                'date':        date.strftime('%Y%m'),
                'what':        what,
                'muninserver': socket.gethostname(),
            }),
            '--',
        ]
        cmdline += recipients
        logging.info('Running command: %s', ' '.join(cmdline))
        try:
            mutt = subprocess.Popen(
                cmdline,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            log_output(mutt.communicate(self.content))
            while mutt.poll() is None:
                time.sleep(1.0)
                log_output(mutt.communicate(None))
            logging.info('Email sent successfully')
        except OSError as err:
            logging.error('Email command error: %s', err)

    def create_email(self):
        '''
        Create the HTML for a Munin email
        '''
        level = self.worst_level(self.status)

        self.subject = '[%s] [%s] %s' % (level, self.what['group'], self.what['host'])
        title = '[%s] %s' % (self.what['group'], self.what['host'])
        self.content = '''
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
    'subject':  self.subject,
    'datetime': datetime.datetime.today().strftime('%d-%m-%Y %H.%M.%S'),
})

        for entry in self.status:
            self.content += '''
<tr class="%(level)s">
<td>%(level)s</td>
<td>%(graph_title)s - %(label)s</td>'''.lstrip('\n') % entry
            if entry['threshold'] == '-':
                self.content += '''
<td>%(value)s</td>'''.lstrip('\n') % entry
            else:
                self.content += '''
<td>%(value)s [%(threshold)s]</td>'''.lstrip('\n') % entry
            self.content += '''
<td>%(extra)s</td>
</tr>'''.lstrip('\n') % entry

        self.content += '''
</table>
<p style="font-size: 80%%"><i>Sent by <a href="https://github.com/othermedia/munin-notify">Munin-Notify</a> on %s.</i></p>
</body>
</html>'''.lstrip('\n') % socket.gethostname()

    def check_config(self, config):
        '''
        Validate the configuration for this target
        '''
        definition = {
            'recipients': list,
        }

        self.config_validator(config, definition)

        if len(config['recipients']) < 1:
            raise ConfigurationError(
                'email setting recipients must contain at least one email address')

    def send(self, config, what, status):
        '''
        Send to the target
        '''
        self.what = what
        self.status = status
        self.create_email()
        logging.info('Sending email report with subject: %s', self.subject)
        self.send_email(config['recipients'], '%(group)s.%(host)s' % self.what)

class MuninTargethipchat(MuninTarget):
    '''
    MuninTargethipchat sends notifications to HipChat
    '''
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

        self.config = None
        self.colour = None
        self.message = None

    def hipchat(self):
        '''
        Send a message to HipChat
        '''
        # This access token is a v1 API token for the group. Label is Fabric
        # Cannot use v2 as it needs to be setup as an Add-On, or use a personal token,
        # which forces From=Name of Person
        headers = {
            'Authorization': 'Bearer %s' % (self.config['token']),
            'Content-Type': 'application/json',
        }

        payload = {
            'message_format': 'html',
            'notify': True,
            'color': self.colour,
            'message': self.message,
        }

        logging.info('Posting HipChat notification:\n%s', payload['message'])
        requests.post(
            url='http://api.hipchat.com/v2/room/%s/notification' % self.config['room'],
            headers=headers,
            data=json.dumps(payload)
        )

    def check_config(self, config):
        '''
        Validate the configuration for this target
        '''
        definition = {
            'room':  int,
            'token': basestring,
        }

        self.config_validator(config, definition)

    def send(self, config, what, status):
        '''
        Send to this target
        '''
        self.config = config
        self.message = '<b>[%(group)s] %(host)s</b>' % what
        for entry in status:
            if entry['level'] in self.levels_img:
                entry['img'] = self.levels_img[entry['level']]
            else:
                entry['img'] = self.levels_img['UNKNOWN']
            self.message += '<br>\n' \
                '<img src="http://bamboo.othermedia.com/images/iconsv4/%(img)s" alt=""> ' \
                '<b>%(level)s</b>: %(graph_title)s - %(label)s' % entry
            if entry['threshold'] == '-':
                self.message += ' = %(value)s' % entry
            else:
                self.message += ' = %(value)s [%(threshold)s]' % entry
            if entry['extra'] != '':
                self.message += ' - %(extra)s' % entry

        level = self.worst_level(status)
        if level in self.levels_colour:
            self.colour = self.levels_colour[level]
        else:
            self.colour = self.levels_colour['UNKNOWN']

        self.hipchat()

class MuninTargetslack(MuninTarget):
    '''
    MuninTargetslack sends notifications to Slack
    '''
    def __init__(self):
        super(MuninTargetslack, self).__init__()

        self.levels_colour = {
            'FIXED':    'good',
            'UNKNOWN':  '#aaaaaa',
            'WARNING':  'warning',
            'CRITICAL': 'danger',
        }

        self.config = None
        self.colour = None
        self.title = None
        self.message = None

    def slack(self):
        '''
        Send a message to Slack
        '''
        payload = {
            'channel': self.config['channel'],
            'attachments': [{
                'color': self.colour,
                'title': self.title,
                'text': self.message,
                'mrkdwn_in': ['text'],
            }]
        }

        logging.info(
            'Posting Slack notification:\n%s - %s',
            self.title,
            self.message)
        requests.post(
            url=self.config['webhook_url'],
            data=json.dumps(payload)
        )

    def check_config(self, config):
        '''
        Validate the configuration for this target
        '''
        definition = {
            'channel':     basestring,
            'webhook_url': basestring,
        }

        self.config_validator(config, definition)

    def send(self, config, what, status):
        '''
        Send to this target
        '''
        self.config = config
        self.title = '[%(group)s] %(host)s' % what
        self.message = ''
        for entry in status:
            if self.message != '':
                self.message += '\n'
            self.message += '*%(level)s*: %(graph_title)s - %(label)s' % entry
            if entry['threshold'] == '-':
                self.message += ' = %(value)s' % entry
            else:
                self.message += ' = %(value)s [%(threshold)s]' % entry
            if entry['extra'] != '':
                self.message += ' - %(extra)s' % entry

        level = self.worst_level(status)
        if level in self.levels_colour:
            self.colour = self.levels_colour[level]
        else:
            self.colour = self.levels_colour['UNKNOWN']

        self.slack()

class MuninNotifications(object):
    '''
    MuninNotifications is the main class
    '''
    def __init__(self):
        self.targets = {}

        self.levels = [
            'FIXED',
            'UNKNOWN',
            'WARNING',
            'CRITICAL',
        ]

        self.log_config = {
            'level': logging.NOTSET,
        }

        self.config = None

        self.init_logging()
        self.init_config()

        self.what = None
        self.meta = None
        self.status = None

        try:
            self.parse()
        except ParseException as err:
            logging.error('Parse error: %s', err)
        except IOError as err:
            logging.error('Failed to read: %s', err)
        except KeyboardInterrupt as err:
            pass

        logging.info('=====FINISHED=====')

    def read_args(self):
        '''
        Read command line arguments
        '''
        try:
            opts, args = getopt.getopt(sys.argv[1:], 'hl:', ['help', 'log-file='])
        except getopt.GetoptError as err:
            quit_with_usage(err)

        if len(args) != 0:
            quit_with_usage('Unexpected arguments')

        for opt, value in opts:
            if opt == '--log-file':
                self.log_config['filename'] = value
            elif opt in ('-h', '--help'):
                quit_with_usage()
            else:
                quit_with_usage('unhandled option: %s' % opt)

    def init_logging(self):
        '''
        Initialise logging
        '''
        try:
            logging.basicConfig(**self.log_config)
        except IOError as err:
            quit_with_usage(err)

        logging.info(
            '=====STARTING %s=====',
            datetime.datetime.today().strftime('%d-%m-%Y %H.%M.%S')
        )

    def init_config(self):
        '''
        Initialise configuration
        '''
        try:
            self.load_config('/etc/munin/munin-notify.yml')

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

        except ConfigurationError as err:
            logging.error('Configuration error: %s', err)
            sys.exit(1)

    def load_config(self, fname):
        '''
        Load the YAML configuration
        '''
        try:
            with open(fname, 'r') as reader:
                self.config = yaml.load(reader)
        except IOError as err:
            raise ConfigurationError('Failed to read configuration: %s' % err)
        except yaml.YAMLError as err:
            raise ConfigurationError('YAML error: %s' % err)

    def invoke_targets(self):
        '''
        Invoke the targets with the current host and status
        '''
        for target in self.config['targets']:
            logging.info('Invoking target: %s', target['type'])
            self.targets[target['type']].send(target, self.what, self.status)

    @classmethod
    def parse_what(cls, line):
        '''
        Parse a header line from Munin
        '''
        parts = line.split(' / ')
        if len(parts) != 4:
            raise ParseException('Host line invalid')
        what = {
            'group':          parts[0],
            'host':           parts[1],
            'graph_category': parts[2],
            'graph_title':    parts[3],
        }
        return what

    @classmethod
    def parse_status(cls, line):
        '''
        Parse a status line from Munin
        '''
        parts = line.split(' / ')
        if len(parts) != 5:
            raise ParseException('Status line invalid')
        status = {
            'level':     parts[0],
            'label':     parts[1],
            'value':     parts[2],
            'threshold': parts[3],
            'extra':     parts[4],
        }
        return status

    def parse(self):
        '''
        Begin parsing STDIN from Munin and triggering targets
        '''
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
                if self.what is not None and len(self.status) > 0 and (\
                    host_line['host'] != self.what['host'] or \
                    host_line['group'] != self.what['group']):
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
