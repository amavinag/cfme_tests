"""Runs Idle Workload by enabling all roles with no providers."""
from utils.conf import perf_tests
from utils.log import logger
from utils.perf_monitor_memory import MonitorMemory
from utils.perf import clean_appliance_evmserverd_off
from utils.perf import log_grafana_url
from utils.perf import set_server_roles_workload_idle
from utils.perf import start_evm_wait_for_ui
from utils import version
import time


def test_workload_idle(request, ssh_client):
    """Runs an appliance at idle for specific amount of time. Memory Monitor creates graphs and
    summary at the end of the scenario."""
    from_ts = int(time.time() * 1000)
    clean_appliance_evmserverd_off()

    monitor_thread = MonitorMemory(ssh_client, 'workload-idle', 'all-roles', 'No Providers')

    def cleanup_workload(from_ts):
        starttime = time.time()
        logger.debug('Started cleaning up monitoring thread.')
        monitor_thread.signal = False
        monitor_thread.join()
        timediff = time.time() - starttime
        logger.info('Finished cleaning up monitoring thread in {}'.format(timediff))
        log_grafana_url(from_ts)
    request.addfinalizer(lambda: cleanup_workload(from_ts))

    monitor_thread.start()

    start_evm_wait_for_ui(ssh_client)
    set_server_roles_workload_idle()

    s_time = perf_tests['workload']['idle']['total_time']
    logger.info('Idling appliance for {}s'.format(s_time))
    time.sleep(s_time)

    logger.info('Test Ending...')
