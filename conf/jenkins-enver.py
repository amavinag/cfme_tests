#!/usr/bin/env python
"""Writes env.local.yaml based on environment variables

Writes an env.local.yaml using sauce environment variables set by the sauce-ondemand plugin

While it always uses the sauce environment vars, it uses webdriver wharf by default.

Also supports command-line overrides

"""
import argparse
import os
import yaml

parser = argparse.ArgumentParser(epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('-n', '--no-artifactor', help="don't configure the artifactor",
    action='store_false', default=True, dest='use_artifactor')
sauce_opts = parser.add_mutually_exclusive_group()
sauce_opts.add_argument('-s', '--use-sauce', help='force using sauce labs',
    action='store_true', default=True, dest='use_sauce')

args = parser.parse_args()

# These should be set by jenkins, and we're relying on the KeyError to fail if they aren't set
selenium_platform = os.environ.get('SELENIUM_PLATFORM', 'Linux')
selenium_browser = os.environ.get('SELENIUM_BROWSER', 'firefox')
selenium_version = os.environ.get('SELENIUM_VERSION', '31')
enable_sauce = os.environ.get('enable_sauce', False)
workspace = os.environ['WORKSPACE']

# Basic env dict, for settings common to using wharf and sauce
env = {
    'using_sauce': enable_sauce,
    'browser': {
        'webdriver': 'Remote',
        'webdriver_options': {
            'desired_capabilities': {
                'browserName': selenium_browser,
            }
        }
    },
    'smtp': {
        'server': 'smtp.corp.redhat.com',
    },
}

if args.use_artifactor:
    env.update({
        'artifactor': {
            'log_dir': os.path.join(workspace, 'log'),
            'artifact_dir': os.path.join(workspace, 'log', 'artifacts'),
            'per_run': 'None',
            'plugins': {
                'ostriz': {
                    'enabled': True,
                    'plugin': 'ostriz',
                    'url': 'http://10.16.4.32/trackerbot/ostriz/post_result/',
                    'source': 'jenkins'
                },
                'filedump': {
                    'enabled': True,
                    'plugin': 'filedump'
                },
                'logger': {
                    'enabled': True,
                    'level': 'DEBUG',
                    'plugin': 'logger'
                },
                'merkyl': {
                    'enabled': True,
                    'log_files': [
                        '/var/www/miq/vmdb/log/evm.log',
                        '/var/www/miq/vmdb/log/production.log',
                        '/var/www/miq/vmdb/log/automation.log'
                    ],
                    'plugin': 'merkyl',
                    'port': 8192
                },
                'post-result': {
                    'enabled': True,
                    'plugin': 'post-result'
                },
                'reporter': {
                    'enabled': True,
                    'only_failed': True,
                    'plugin': 'reporter'
                },
                'video': {
                    'display': ':99',
                    'enabled': False,
                    'plugin': 'video',
                    'quality': 10
                },
                'softassert': {
                    'enabled': True,
                    'plugin': 'softassert'
                },
                'screenshots': {
                    'enabled': True,
                    'plugin': 'screenshots',
                }
            },
            'reuse_dir': True,
            'server_address': '127.0.0.1',
            'server_enabled': True,
            'squash_exceptions': True,
            'threaded': False
        },
    })

# This is change for test runs
# Enabling sauce by default for test sauce_poc over weekend.
# if enable_sauce:
executor = ('http://%s:%s@ondemand.saucelabs.com:80/wd/hub' %
    (os.environ['SAUCE_USER_NAME'], os.environ['SAUCE_API_KEY'])
)
opts = env['browser']['webdriver_options']
opts['command_executor'] = executor
opts['desired_capabilities']['platform'] = selenium_platform
opts['desired_capabilities']['version'] = selenium_version
opts['desired_capabilities']['version'] = selenium_version
opts['desired_capabilities']['screen-resolution'] = '1280x1024'
opts['desired_capabilities']['maxDuration'] = 10800
opts['desired_capabilities']['commandTimeout'] = 600
opts['desired_capabilities']['idleTimeout'] = 1000
# opts['desired_capabilities']['selenium_version'] = '2.42.2'

# Resolution set only works for windows or osx, easiest check is for ie or safari
if selenium_browser in ('internet explorer', 'safari'):
    opts['desired_capabilities']['screen-resolution'] = '1280x1024'

# if a build tag is set, use for sauce build tag
if 'BUILD_TAG' in os.environ:
    opts['desired_capabilities']['build'] = os.environ['BUILD_TAG']
# else:
#     If we aren't using sauce, use wharf
    # TODO: We need a way to easily configure using multiple wharves
    # env['browser']['webdriver_wharf'] = 'http://ibm-x3530m4-05.cfme.lab.eng.rdu2.redhat.com:4899/'

print "# This file is automatically generated by the jenkins-enver script, found in the cfme-qe-yamls repository"
print yaml.dump(env, default_flow_style=False)
