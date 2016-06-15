"""Runs Capacity and Utilization Workload with replication."""
from cfme.configure import configuration
from cfme.fixtures import pytest_selenium as sel
from cfme.web_ui import flash
from utils.conf import perf_tests
from utils.log import logger
from utils.perf_monitor_memory import MonitorMemory
from utils.perf import add_providers
from utils.perf import clean_appliance_evmserverd_off
from utils.perf import clean_replication_master_appliance
from utils.perf import generate_providers_test
from utils.perf import generate_test_name
from utils.perf import get_cap_and_util_memory_scenarios
from utils.perf import idle_time
from utils.perf import log_grafana_url
from utils.perf import set_cap_and_util_all_via_rails
from utils.perf import set_server_roles_benchmark_memory_cap_and_util
from utils.perf import start_evm_wait_for_ui
from selenium.common.exceptions import WebDriverException
from utils import version
import time
import pytest


@pytest.mark.parametrize('the_providers', get_cap_and_util_memory_scenarios())
def test_workload_cap_and_util_with_replication(request, ssh_client, the_providers):
    """Runs through provider based scenarios enabling C&U and running for a set period of time. The
    scenarios consist of starting up the appliance, run idle for 2 minutes, add one or more C&U
    providers, allow refresh to consume 10 minutes, then enable C&U and monitor for set period of
    time defined in perf_test.yaml. Additionally, replication is enabled and pointed at a host
    defined in perf_test.yaml. Memory Monitor creates graphs and summary at the end of each
    scenario."""
    from_ts = int(time.time() * 1000)
    clean_appliance_evmserverd_off()
    providers_tested = generate_providers_test(the_providers)
    test_name = generate_test_name(providers_tested, the_providers)

    monitor_thread = MonitorMemory(ssh_client, 'workload-cap-and-util-replication', test_name,
        providers_tested)

    def cleanup_workload(from_ts):
        logger.info('Starting test clean up.')
        starttime = time.time()
        logger.info('Disabling replication')
        configuration.set_server_roles(database_synchronization=False)
        monitor_thread.signal = False
        monitor_thread.join()
        timediff = time.time() - starttime
        logger.info('Finished cleaning up in {}'.format(timediff))
        log_grafana_url(from_ts)
    request.addfinalizer(lambda: cleanup_workload(from_ts))

    monitor_thread.start()

    start_evm_wait_for_ui(ssh_client)
    if version.current_stream() == 'downstream-56z':
        set_server_roles_benchmark_memory_cap_and_util(True)
    else:
        set_server_roles_benchmark_memory_cap_and_util()
    idle_time(120, 'Post set roles.')  # 2 minutes of idle appliance
    add_providers(the_providers)
    idle_time(600, 'Allow refresh to run')  # Allow refresh to run

    set_cap_and_util_all_via_rails(ssh_client)

    # Replication Workload, setup replication host:
    cfme_master_ip = perf_tests['workload']['cap_and_util_rep']['replication_ip']
    clean_replication_master_appliance(cfme_master_ip)
    configuration.set_replication_worker_host(cfme_master_ip)
    flash.assert_message_contain("Configuration settings saved for CFME Server")
    try:
        sel.force_navigate("cfg_settings_currentserver_server")
    except WebDriverException:
        sel.handle_alert()
        sel.force_navigate("cfg_settings_currentserver_server")
    # Force uninstall rubyrep for this region from master
    ssh_client.run_rake_command('evm:dbsync:uninstall')
    idle_time(30, 'Post evm:dbsync:uninstall')
    configuration.set_server_roles(database_synchronization=True)

    # Variable amount of C&U collections
    total_time = perf_tests['workload']['cap_and_util_rep']['total_time']
    starttime = time.time()
    total_waited = 0
    while (total_waited < total_time):
        total_waited = time.time() - starttime
        time_left = abs(total_time - total_waited)
        logger.info('Time waited: {}/{}'.format(round(total_waited, 2), total_time))
        if time_left < 300:
            time.sleep(time_left)
        else:
            time.sleep(300)

    logger.info('Test Ending...')
