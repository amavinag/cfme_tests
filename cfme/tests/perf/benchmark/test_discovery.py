"""Runs discovery benchmarks."""
from collections import OrderedDict
from utils.conf import cfme_data
from utils.conf import perf_tests
from utils.log import logger
from utils.perf import generate_benchmark_code
from utils.perf import get_benchmark_providers
from utils.perf import log_benchmark
from utils.perf import parse_benchmark_output
from utils.perf import pbench_start, pbench_stop
from utils.perf import set_server_roles_benchmark
import datetime
import pytest

pytestmark = [
    pytest.mark.parametrize('provider', get_benchmark_providers()),
    pytest.mark.usefixtures('end_log_benchmark_timings', 'end_pbench_move_results')
]

benchmark_values = OrderedDict()
test_run_ts = '{}-Discovery'.format(str(datetime.datetime.now()).replace(" ", "_"))


@pytest.yield_fixture(scope='module')
def end_log_benchmark_timings():
    """Fixture that ensures benchmark timings are written/appended to benchmark-statistics.csv."""
    yield
    log_benchmark(benchmark_values)


def test_discovery_provider(ssh_client, clean_appliance, provider):
    """Measures time required to discover a provider."""
    set_server_roles_benchmark()
    provider_name = cfme_data['management_systems'][provider]['name']
    ip_addr = cfme_data['management_systems'][provider]['ipaddress']
    discover_type = ':{}'.format(cfme_data['management_systems'][provider]['type'])
    code = generate_benchmark_code('',
        'Host.discoverHost(Marshal.dump({:ipaddr => '
        '\'' + str(ip_addr) + '\', :discover_types => [' + str(discover_type) + '],'
        ' :timeout => 10 }));')
    for iteration in range(perf_tests['benchmark']['discovery']['provider']):
        test_iteration = 'Discovery-{}-{}'.format(provider_name, str(iteration).zfill(4))
        pbench_start(ssh_client, test_run_ts, test_iteration)
        exit_status, output = ssh_client.run_rails_console(code, timeout=None)
        try:
            float(output.strip().split('\n')[-1])
        except ValueError:
            logger.error('Unexpected Output: {}'.format(output))
        finally:
            pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
        parse_benchmark_output(output, 'Discovery', 'Provider', provider_name, iteration,
            benchmark_values)
