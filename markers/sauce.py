"""sauce: Mark a test to run on sauce

Mark a single test to run on sauce.

"""
import base64
import httplib
import json

from utils import browser
from utils import conf


def pytest_addoption(parser):
    group = parser.getgroup('cfme')
    group.addoption('--sauce', dest='sauce', action='store_true', default=False,
                    help="Run tests with the sauce marker on sauce labs.")


def pytest_configure(config):
    config.addinivalue_line('markers', __doc__.splitlines()[0])


def pytest_runtest_setup(item):
    if item.config.option.sauce:
        browser_webdriver = conf.env['browser'].get('webdriver_options', {})
        browser_webdriver.get('desired_capabilities', {})['name'] = item.name
        browser.manager = browser.BrowserManager.from_conf()
        browser.ensure_browser_open()


def pytest_runtest_teardown(item):
    if item.config.option.sauce:
        jobid = browser.manager.browser.session_id
        browser.quit()
        passed = item.rep_call.outcome == 'passed'
        update_sauce_result(jobid, passed)


def update_sauce_result(jobid, passed):
    base64string = base64.encodestring('{user_name}:{access_key}'.format(
        user_name=conf.credentials['saucelabs']['username'],
        access_key=conf.credentials['saucelabs']['access_key']))[:-1]
    body_content = json.dumps({"passed": passed})
    connection = httplib.HTTPConnection("saucelabs.com")
    connection.request('PUT', '/rest/v1/{user_name}/jobs/{job_id}'.format(
        user_name=conf.credentials['saucelabs']['username'], job_id=jobid),
                       body_content,
                       headers={"Authorization": "Basic %s" % base64string})
    result = connection.getresponse()
    return result.status == 200

