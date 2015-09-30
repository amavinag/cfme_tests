"""Runs configuration management refresh benchmarks."""
from cfme.infrastructure.config_management import ConfigManager
from collections import OrderedDict
from utils.conf import cfme_data, credentials
from utils.conf import perf_tests
from utils.log import logger
from utils.perf import append_value
from utils.perf import generate_benchmark_code
from utils.perf import get_benchmark_cfg_mgt_providers
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
test_run_ts = '{}-Refresh-cfg-mgt'.format(str(datetime.datetime.now()).replace(" ", "_"))


@pytest.yield_fixture(scope='module')
def end_log_benchmark():
    """Fixture that ensures benchmark measurements are written/appended to csv files."""
    yield
    log_benchmark(benchmark_values)


def setup_test_refresh(provider, initial_refresh=False, ssh_client=None):
    set_server_roles_benchmark()
    cfg_mgr_name = cfme_data['configuration_managers'][provider]['name']
    cfg_mgr_url = cfme_data['configuration_managers'][provider]['url']
    cred = cfme_data['configuration_managers'][provider]['credentials']
    cfg_mgr_user = credentials[cred]['username']
    cfg_mgr_pass = credentials[cred]['password']
    cfg_mgr = ConfigManager(cfg_mgr_name, cfg_mgr_url, False,
        ConfigManager.Credential(principal=cfg_mgr_user, secret=cfg_mgr_pass))
    cfg_mgr.create(validate=False)
    if initial_refresh:
        refresh_provider_via_rails(ssh_client, cfme_data['configuration_managers'][provider]
            ['name'] + ' Provisioning Manager')
        refresh_provider_via_rails(ssh_client, cfme_data['configuration_managers'][provider]
            ['name'] + ' Configuration Manager')


@pytest.mark.parametrize('iteration', range(0,
    perf_tests['benchmark']['refresh_config_mgt']['provider_init']))
@pytest.mark.parametrize('provider', get_benchmark_cfg_mgt_providers())
def test_refresh_cfg_provider_init(ssh_client, clean_appliance, iteration, provider):
    """Measures time required to complete an initial EmsRefresh.refresh on specific provider."""
    setup_test_refresh(provider)
    provider_name = cfme_data['configuration_managers'][provider]['name']
    test_iteration = 'Provider-provision-Init-{}-{}'.format(provider_name, str(iteration).zfill(4))
    code = generate_benchmark_code(
        'e = ExtManagementSystem.find_by_name(\'{} Provisioning Manager\');'.format(provider_name),
        'EmsRefresh.refresh e;')
    pbench_start(ssh_client, test_run_ts, test_iteration)
    exit_status, output = ssh_client.run_rails_console(code, timeout=None)
    try:
        float(output.strip().split('\n')[-1])
    except ValueError:
        logger.error('Unexpected Output: {}'.format(output))
    finally:
        pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
    parse_benchmark_output(output, 'Refresh-cfg-mgt-provision', 'Provider-Init', provider_name,
        iteration, benchmark_values)

    test_iteration = 'Provider-configuration-Init-{}-{}'.format(provider_name,
        str(iteration).zfill(4))
    code = generate_benchmark_code(
        'e = ExtManagementSystem.find_by_name(\'{} Configuration Manager\');'.format(provider_name),
        'EmsRefresh.refresh e;')
    pbench_start(ssh_client, test_run_ts, test_iteration)
    exit_status, output = ssh_client.run_rails_console(code, timeout=None)
    try:
        float(output.strip().split('\n')[-1])
    except ValueError:
        logger.error('Unexpected Output: {}'.format(output))
    finally:
        pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
    parse_benchmark_output(output, 'Refresh-cfg-mgt-configuration', 'Provider-Init', provider_name,
        iteration, benchmark_values)


@pytest.mark.parametrize('provider', get_benchmark_cfg_mgt_providers())
def test_refresh_cfg_provider_delta(ssh_client, clean_appliance, provider):
    """Measures time required to complete an EmsRefresh.refresh on specific provider after initial
    refresh."""
    setup_test_refresh(provider, True, ssh_client)
    provider_name = cfme_data['configuration_managers'][provider]['name']
    for iteration in range(perf_tests['benchmark']['refresh_config_mgt']['provider_delta']):
        test_iteration = 'Provider-provision-Delta-{}-{}'.format(provider_name,
            str(iteration).zfill(4))

        code = generate_benchmark_code(
            'e = ExtManagementSystem.find_by_name(\'{} Provisioning Manager\');'.format(provider_name),
            'EmsRefresh.refresh e;')
        pbench_start(ssh_client, test_run_ts, test_iteration)
        exit_status, output = ssh_client.run_rails_console(code, timeout=None)
        try:
            float(output.strip().split('\n')[-1])
        except ValueError:
            logger.error('Unexpected Output: {}'.format(output))
        finally:
            pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
        parse_benchmark_output(output, 'Refresh-cfg-mgt-provision', 'Provider-Delta', provider_name,
            iteration, benchmark_values)

        test_iteration = 'Provider-configuration-Delta-{}-{}'.format(provider_name,
            str(iteration).zfill(4))
        code = generate_benchmark_code(
            'e = ExtManagementSystem.find_by_name(\'{} Configuration Manager\');'.format(provider_name),
            'EmsRefresh.refresh e;')
        pbench_start(ssh_client, test_run_ts, test_iteration)
        exit_status, output = ssh_client.run_rails_console(code, timeout=None)
        try:
            float(output.strip().split('\n')[-1])
        except ValueError:
            logger.error('Unexpected Output: {}'.format(output))
        finally:
            pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
        parse_benchmark_output(output, 'Refresh-cfg-mgt-configuration', 'Provider-Delta', provider_name,
            iteration, benchmark_values)
