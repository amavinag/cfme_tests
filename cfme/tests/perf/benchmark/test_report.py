"""Runs report/widget generation benchmarks."""
from collections import OrderedDict
from utils.conf import cfme_data
from utils.conf import perf_tests
from utils.log import logger
from utils.perf import generate_benchmark_code
from utils.perf import get_benchmark_providers
from utils.perf import log_benchmark
from utils.perf import parse_benchmark_output
from utils.perf import pbench_start, pbench_stop
from utils.perf import refresh_provider_via_rails
from utils.perf import set_server_roles_benchmark
from utils.perf import set_vim_broker_memory_threshold
from utils import providers
import datetime
import pytest

pytestmark = [
    pytest.mark.usefixtures('end_log_benchmark_timings', 'end_pbench_move_results')
]

benchmark_values = OrderedDict()
test_run_ts = '{}-Report'.format(str(datetime.datetime.now()).replace(" ", "_"))


@pytest.yield_fixture(scope='module')
def end_log_benchmark_timings():
    """Fixture that ensures benchmark timings are written/appended to benchmark-statistics.csv."""
    yield
    log_benchmark(benchmark_values)


def setup_test_report(provider, ssh_client):
    """Setups up benchmark tests for report/widget generation."""
    set_server_roles_benchmark()
    if 'broker_large_memory' in cfme_data['management_systems'][provider]['tags']:
        set_vim_broker_memory_threshold('6 GB')
    providers.setup_provider(provider, validate=False)
    refresh_provider_via_rails(ssh_client, cfme_data['management_systems'][provider]['name'])


def report_generate_benchmark(ssh_client, provider):
    provider_name = cfme_data['management_systems'][provider]['name']
    for report_name in perf_tests['benchmark']['report']['reports']:
        logger.info('Benchmarking Report: {}'.format(report_name))
        code = generate_benchmark_code('',
            'mr = MiqReport.where(\'name = \\\'' + report_name + '\\\'\');'
            'task = MiqTask.create(:name => \'Generate Report: \\\'' + report_name + '\\\'\');'
            'mr[0]._async_generate_table(task.id, '
            '{:userid=>\'admin\', :mode=>\'async\', :report_source=>\'Requested by user\'});')
        for iteration in range(perf_tests['benchmark']['report']['iterations']):
            test_iteration = 'Report-{}-{}-{}'.format(report_name, provider_name,
                str(iteration).zfill(4))
            pbench_start(ssh_client, test_run_ts, test_iteration)
            exit_status, output = ssh_client.run_rails_console(code, timeout=None)
            try:
                float(output.strip().split('\n')[-1])
            except ValueError:
                logger.error('Unexpected Output: {}'.format(output))
            finally:
                pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
            parse_benchmark_output(output, 'Report', 'Report:{}'.format(report_name), provider_name,
                iteration, benchmark_values)


def widget_generate_benchmark(ssh_client, provider):
    provider_name = cfme_data['management_systems'][provider]['name']
    for widget_name in perf_tests['benchmark']['report']['dashboard_widgets']:
        logger.info('Benchmarking Dashboard Widget: {}'.format(widget_name))
        code = generate_benchmark_code('',
            'mw = MiqWidget.where(\'title = \\\'' + widget_name + '\\\'\');'
            'mw[0].create_task(1);'
            'result = mw[0].generate_content(\'MiqGroup\', \'EvmGroup-super_administrator\', nil,'
            ' [\'UTC\']);'
            'mw[0].generate_content_complete_callback(\'ok\', \'Message delivered '
            'successfully\', result);')
        for iteration in range(perf_tests['benchmark']['report']['iterations']):
            test_iteration = 'Widget-{}-{}-{}'.format(widget_name, provider_name,
                str(iteration).zfill(4))
            pbench_start(ssh_client, test_run_ts, test_iteration)
            exit_status, output = ssh_client.run_rails_console(code, timeout=None)
            try:
                float(output.strip().split('\n')[-1])
            except ValueError:
                logger.error('Unexpected Output: {}'.format(output))
            finally:
                pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
            parse_benchmark_output(output, 'Report', 'Widget:{}'.format(widget_name), provider_name,
                iteration, benchmark_values)


@pytest.mark.parametrize('provider', get_benchmark_providers())
def test_report_and_widget_generate(ssh_client, clean_appliance, provider):
    """Saves time by combining report/widget benchmarks on cleaned appliance."""
    setup_test_report(provider, ssh_client)
    report_generate_benchmark(ssh_client, provider)
    widget_generate_benchmark(ssh_client, provider)


@pytest.mark.parametrize('provider', get_benchmark_providers())
def test_report_generate(ssh_client, clean_appliance, provider):
    """Measures time required to complete specific reports per provider."""
    setup_test_report(provider, ssh_client)
    report_generate_benchmark(ssh_client, provider)


@pytest.mark.parametrize('provider', get_benchmark_providers())
def test_widget_generate(ssh_client, clean_appliance, provider):
    """Measures time required to complete specific widgets per provider."""
    setup_test_report(provider, ssh_client)
    widget_generate_benchmark(ssh_client, provider)
