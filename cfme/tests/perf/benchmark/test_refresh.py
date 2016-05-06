"""Runs refresh benchmarks."""
from collections import OrderedDict
from utils.conf import cfme_data
from utils.conf import perf_tests
from utils.log import logger
from utils.perf import append_value
from utils.perf import generate_benchmark_code
from utils.perf import get_benchmark_nobroker_providers
from utils.perf import log_benchmark
from utils.perf import parse_benchmark_array
from utils.perf import parse_benchmark_output
from utils.perf import pbench_start, pbench_stop
from utils.perf import refresh_provider_via_rails
from utils.perf import set_full_refresh_threshold
from utils.perf import set_server_roles_benchmark
from utils import providers
import datetime
import pytest

pytestmark = [
    pytest.mark.usefixtures('end_log_benchmark', 'end_pbench_move_results')
]

benchmark_values = OrderedDict()
test_run_ts = '{}-Refresh'.format(str(datetime.datetime.now()).replace(" ", "_"))


@pytest.yield_fixture(scope='module')
def end_log_benchmark():
    """Fixture that ensures benchmark measurements are written/appended to csv files."""
    yield
    log_benchmark(benchmark_values)


def setup_test_refresh(provider, initial_refresh=False, ssh_client=None):
    set_server_roles_benchmark()
    providers.setup_provider(provider, validate=False)
    if initial_refresh:
        refresh_provider_via_rails(ssh_client, cfme_data['management_systems'][provider]['name'])


@pytest.mark.parametrize('iteration', range(0, perf_tests['benchmark']['refresh']['provider_init']))
@pytest.mark.parametrize('provider', get_benchmark_nobroker_providers())
def test_refresh_provider_init(ssh_client, clean_appliance, iteration, provider):
    """Measures time required to complete an initial EmsRefresh.refresh on specific provider."""
    setup_test_refresh(provider)
    provider_name = cfme_data['management_systems'][provider]['name']
    test_iteration = 'Provider-Init-{}-{}'.format(provider_name, str(iteration).zfill(4))
    code = generate_benchmark_code(
        'e = ExtManagementSystem.find_by_name(\'{}\');'.format(provider_name),
        'EmsRefresh.refresh e;')
    pbench_start(ssh_client, test_run_ts, test_iteration)
    exit_status, output = ssh_client.run_rails_console(code, timeout=None)
    try:
        float(output.strip().split('\n')[-1])
    except ValueError:
        logger.error('Unexpected Output: {}'.format(output))
    finally:
        pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
    parse_benchmark_output(output, 'Refresh', 'Provider-Init', provider_name, iteration,
        benchmark_values)


@pytest.mark.perf_profile
@pytest.mark.parametrize('iteration', range(0, perf_tests['benchmark']['refresh']['provider_init']))
@pytest.mark.parametrize('provider', get_benchmark_nobroker_providers())
def test_profile_refresh_provider_init_perftools(ssh_client, clean_appliance, iteration, provider):
    """Measures time required to complete an initial EmsRefresh.refresh on specific provider and
    profile using perftools.rb.  Appliance must be setup with perftools in advance.  Profile file
    is saved to appliance /root directory.  The file is unique between iterations but not runs of
    the automation currently.
    Tested with appliances running Ruby 1.9.3/2.0.0
    """
    setup_test_refresh(provider)
    provider_name = cfme_data['management_systems'][provider]['name']
    command = ('require \'perftools\';'
               'e = ExtManagementSystem.find_by_name(\'' + provider_name + '\');'
               'GC.start;'
               'PerfTools::CpuProfiler.start(\'/root/perftools-provider-init-'
               + provider_name + '-' + str(iteration) + '\');'
               'value = Benchmark.realtime {EmsRefresh.refresh e};'
               'PerfTools::CpuProfiler.stop;'
               'value')
    exit_status, output = ssh_client.run_rails_console(command, timeout=None)
    try:
        float(output.strip().split('\n')[-1])
    except ValueError:
        logger.error('Unexpected Output: {}'.format(output))
    append_value(benchmark_values, 'Refresh', 'Provider-Init-Perftools', provider_name, 'timing',
        float(output.strip().split('\n')[-1]))
    logger.info('Iteration: {}, Value: {}'.format(iteration, output.strip().split('\n')[-1]))


@pytest.mark.perf_profile
@pytest.mark.parametrize('iteration', range(0, perf_tests['benchmark']['refresh']['provider_init']))
@pytest.mark.parametrize('provider', get_benchmark_nobroker_providers())
def test_profile_refresh_provider_init_stackprof(ssh_client, clean_appliance, iteration, provider):
    """Measures time required to complete an initial EmsRefresh.refresh on specific provider and
    profile using stackprof.  Appliance must be setup with stackprof in advance.  Profile file
    is saved to appliance /root directory.  The file is unique between iterations but not runs of
    the automation currently.
    Tested with appliances running Ruby 2.1.x/2.2.2
    """
    setup_test_refresh(provider)
    provider_name = cfme_data['management_systems'][provider]['name']
    command = ('e = ExtManagementSystem.find_by_name(\'' + provider_name + '\');'
               'GC.start;'
               'value = 0;'
               'StackProf.run(mode: :cpu, out: \'/root/stackprof-provider-init-'
               + provider_name + '-' + str(iteration) + '\') do;'
               'value = Benchmark.realtime {EmsRefresh.refresh e};'
               'end;'
               'value')
    exit_status, output = ssh_client.run_rails_console(command, timeout=None)
    try:
        float(output.strip().split('\n')[-1])
    except ValueError:
        logger.error('Unexpected Output: {}'.format(output))
    append_value(benchmark_values, 'Refresh', 'Provider-Init-Stackprof', provider_name, 'timing',
        float(output.strip().split('\n')[-1]))
    logger.info('Iteration: {}, Value: {}'.format(iteration, output.strip().split('\n')[-1]))


@pytest.mark.parametrize('provider', get_benchmark_nobroker_providers())
def test_refresh_provider_delta(ssh_client, clean_appliance, provider):
    """Measures time required to complete an EmsRefresh.refresh on specific provider after initial
    refresh."""
    setup_test_refresh(provider, True, ssh_client)
    provider_name = cfme_data['management_systems'][provider]['name']
    for iteration in range(perf_tests['benchmark']['refresh']['provider_delta']):
        test_iteration = 'Provider-Delta-{}-{}'.format(provider_name, str(iteration).zfill(4))
        code = generate_benchmark_code(
            'e = ExtManagementSystem.find_by_name(\'{}\');'.format(provider_name),
            'EmsRefresh.refresh e;')
        pbench_start(ssh_client, test_run_ts, test_iteration)
        exit_status, output = ssh_client.run_rails_console(code, timeout=None)
        try:
            float(output.strip().split('\n')[-1])
        except ValueError:
            logger.error('Unexpected Output: {}'.format(output))
        finally:
            pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
        parse_benchmark_output(output, 'Refresh', 'Provider-Delta', provider_name, iteration,
            benchmark_values)


@pytest.mark.perf_profile
@pytest.mark.parametrize('provider', get_benchmark_nobroker_providers())
def test_profile_refresh_provider_delta_perftools(ssh_client, clean_appliance, provider):
    """Measures time required to complete an EmsRefresh.refresh on specific provider after initial
    refresh and profiles using perftools.rb.  Appliance must be setup with perftools in advance.
    Profile file is saved to appliance /root directory.  The file is unique between iterations but
    not runs of the automation currently.
    Tested with appliances running Ruby 1.9.3/2.0.0
    """
    setup_test_refresh(provider, True, ssh_client)
    iterations = perf_tests['benchmark']['refresh']['provider_delta']
    provider_name = cfme_data['management_systems'][provider]['name']
    command = ('e = ExtManagementSystem.find_by_name(\'' + provider_name + '\');'
               'require \'perftools\';'
               'r = Array.new;'
               '' + str(iterations) + '.times {|i| '
               'GC.start;'
               'PerfTools::CpuProfiler.start(\'/root/perftools-provider-delta-'
               + provider_name + '-\' + i.to_s);'
               'r.push(Benchmark.realtime {EmsRefresh.refresh e});'
               'PerfTools::CpuProfiler.stop;'
               '};'
               'r')
    exit_status, output = ssh_client.run_rails_console(command, timeout=None)
    try:
        parse_benchmark_array(output, 'Refresh', 'Provider-Delta-Perftools', provider_name)
    except ValueError:
        logger.error('Unexpected Output: {}'.format(output))
        assert 0


@pytest.mark.perf_profile
@pytest.mark.parametrize('provider', get_benchmark_nobroker_providers())
def test_profile_refresh_provider_delta_stackprof(ssh_client, clean_appliance, provider):
    """Measures time required to complete an EmsRefresh.refresh on specific provider after initial
    refresh and profiles using stackprof.  Appliance must be setup with stackprof in advance.
    Profile file is saved to appliance /root directory.  The file is unique between iterations but
    not runs of the automation currently.
    Tested with appliances running Ruby 2.1.x/2.2.2
    """
    setup_test_refresh(provider, True, ssh_client)
    iterations = perf_tests['benchmark']['refresh']['provider_delta']
    provider_name = cfme_data['management_systems'][provider]['name']
    command = ('e = ExtManagementSystem.find_by_name(\'' + provider_name + '\');'
               'r = Array.new;'
               '' + str(iterations) + '.times {|i| '
               'GC.start;'
               'StackProf.run(mode: :cpu, out: \'/root/stackprof-provider-delta-'
               + provider_name + '-\' + i.to_s) do;'
               'r.push(Benchmark.realtime {EmsRefresh.refresh e});'
               'end;'
               '};'
               'r')
    exit_status, output = ssh_client.run_rails_console(command, timeout=None)
    try:
        parse_benchmark_array(output, 'Refresh', 'Provider-Delta-Stackprof', provider_name)
    except ValueError:
        logger.error('Unexpected Output: {}'.format(output))
        assert 0


@pytest.mark.parametrize('provider', get_benchmark_nobroker_providers())
def test_refresh_host(ssh_client, clean_appliance, provider):
    """Measures time required to complete an EmsRefresh.refresh on specific host after initial
    refresh."""
    setup_test_refresh(provider, True, ssh_client)
    provider_name = cfme_data['management_systems'][provider]['name']
    code = generate_benchmark_code('h = Host.first();', 'EmsRefresh.refresh h;')
    for iteration in range(perf_tests['benchmark']['refresh']['host']):
        test_iteration = 'Host-{}-{}'.format(provider_name, str(iteration).zfill(4))
        pbench_start(ssh_client, test_run_ts, test_iteration)
        exit_status, output = ssh_client.run_rails_console(code, timeout=None)
        try:
            float(output.strip().split('\n')[-1])
        except ValueError:
            logger.error('Unexpected Output: {}'.format(output))
        finally:
            pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
        parse_benchmark_output(output, 'Refresh', 'Host', provider_name, iteration,
            benchmark_values)


@pytest.mark.parametrize('provider', get_benchmark_nobroker_providers())
def test_refresh_vm(ssh_client, clean_appliance, provider):
    """Measures time required to complete an EmsRefresh.refresh on a specific numnber of VM(s) after
    initial refresh."""
    setup_test_refresh(provider, True, ssh_client)
    provider_name = cfme_data['management_systems'][provider]['name']
    num_vms = perf_tests['benchmark']['refresh']['vm_targets']
    for vms in num_vms:
        refresh_target = 'EmsRefresh.refresh v[0..{}];'.format(vms - 1)
        if vms >= 100:
            set_full_refresh_threshold(vms + 1)
        code = generate_benchmark_code('v = VmInfra.find(:all);', refresh_target)
        for iteration in range(perf_tests['benchmark']['refresh']['vm']):
            test_iteration = 'VM-{}-{}-{}'.format(vms, provider_name, str(iteration).zfill(4))
            pbench_start(ssh_client, test_run_ts, test_iteration)
            exit_status, output = ssh_client.run_rails_console(code, timeout=None)
            try:
                float(output.strip().split('\n')[-1])
            except ValueError:
                logger.error('Unexpected Output: {}'.format(output))
            finally:
                pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
            parse_benchmark_output(output, 'Refresh', 'VM-{}'.format(vms), provider_name, iteration,
                benchmark_values)
        if vms >= 100:
            set_full_refresh_threshold()
