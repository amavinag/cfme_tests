"""Runs Capacity and Utilization Benchmark."""
from cfme.configure.configuration import candu
from collections import OrderedDict
from utils.conf import cfme_data
from utils.conf import perf_tests
from utils.log import logger
from utils.perf import delete_all_method_from_queue_via_rails
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
    pytest.mark.usefixtures('end_log_benchmark', 'end_pbench_move_results')
]

benchmark_values = OrderedDict()
test_run_ts = '{}-Capacity-And-Utilization'.format(str(datetime.datetime.now()).replace(" ", "_"))


@pytest.yield_fixture(scope='module')
def end_log_benchmark():
    """Fixture that ensures benchmark measurements are written/appended to csv files."""
    yield
    log_benchmark(benchmark_values)


def setup_test_capacity_and_utilization(provider, ssh_client):
    set_server_roles_benchmark()
    if 'broker_large_memory' in cfme_data['management_systems'][provider]['tags']:
        set_vim_broker_memory_threshold('6 GB')
    providers.setup_provider(provider, validate=False)
    refresh_provider_via_rails(ssh_client, cfme_data['management_systems'][provider]['name'])


@pytest.mark.parametrize('provider', get_benchmark_providers())
def test_vm_perf_capture_infra(ssh_client, clean_appliance, provider):
    """Measures time required to perform realtime performance capture on a virtual machine."""
    setup_test_capacity_and_utilization(provider, ssh_client)
    provider_name = cfme_data['management_systems'][provider]['name']
    for iteration in range(perf_tests['benchmark']['capacity_and_utilization']['perf_capture']):
        test_iteration = 'vm-perf-capture-{}-{}'.format(provider_name, str(iteration).zfill(4))
        code = generate_benchmark_code(
            'v = VmInfra.find(:all, :conditions => \'raw_power_state = \\\'poweredOn\\\' Or '
            'raw_power_state = \\\'up\\\'\');',
            'v[' + str(iteration) + '].perf_capture(\'realtime\');')
        pbench_start(ssh_client, test_run_ts, test_iteration)
        exit_status, output = ssh_client.run_rails_console(code, timeout=None)
        try:
            float(output.strip().split('\n')[-1])
        except ValueError:
            logger.error('Unexpected Output: {}'.format(output))
        finally:
            pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
        parse_benchmark_output(output, 'Capacity And Utilization', 'vm-perf_capture',
            provider_name, iteration, benchmark_values)


@pytest.mark.parametrize('provider', get_benchmark_providers())
def test_host_perf_capture(ssh_client, clean_appliance, provider):
    """Measures time required to perform a realtime performance capture on a Host."""
    setup_test_capacity_and_utilization(provider, ssh_client)
    provider_name = cfme_data['management_systems'][provider]['name']
    for iteration in range(perf_tests['benchmark']['capacity_and_utilization']['perf_capture']):
        test_iteration = 'host-perf-capture-{}-{}'.format(provider_name, str(iteration).zfill(4))
        code = generate_benchmark_code('h = Host.find(:all);',
            'h[' + str(iteration) + '].perf_capture(\'realtime\');')
        pbench_start(ssh_client, test_run_ts, test_iteration)
        exit_status, output = ssh_client.run_rails_console(code, timeout=None)
        try:
            float(output.strip().split('\n')[-1])
        except ValueError:
            logger.error('Unexpected Output: {}'.format(output))
        finally:
            pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
        parse_benchmark_output(output, 'Capacity And Utilization', 'host-perf_capture',
            provider_name, iteration, benchmark_values)


@pytest.mark.parametrize('provider', get_benchmark_providers())
def test_perf_capture_timer(ssh_client, clean_appliance, provider):
    """Measures time required to schedule all targets if no other perf_captures are on the queue."""
    setup_test_capacity_and_utilization(provider, ssh_client)
    candu.enable_all()
    provider_name = cfme_data['management_systems'][provider]['name']
    code = generate_benchmark_code('the_zone = Zone.find_by_name(\'default\');',
        'Metric::Capture.perf_capture_timer(the_zone);')
    for iteration in range(
            perf_tests['benchmark']['capacity_and_utilization']['perf_capture_timer']):
        test_iteration = 'perf_capture_timer-{}-{}'.format(provider_name, str(iteration).zfill(4))
        pbench_start(ssh_client, test_run_ts, test_iteration)
        exit_status, output = ssh_client.run_rails_console(code, timeout=None)
        try:
            float(output.strip().split('\n')[-1])
        except ValueError:
            logger.error('Unexpected Output: {}'.format(output))
        finally:
            pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
        parse_benchmark_output(output, 'Capacity And Utilization', 'perf_capture_timer',
            provider_name, iteration, benchmark_values)
        # Clears all perf_captures off queue, thus workload can be repeated without cleaning db
        delete_all_method_from_queue_via_rails(ssh_client, 'perf_capture')
