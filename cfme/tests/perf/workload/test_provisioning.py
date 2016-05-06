"""Runs Provisioning Workload on various providers."""
from cfme.configure import configuration
from cfme.services.catalogs.service_catalogs import ServiceCatalogs
from cfme.web_ui import flash
from utils.conf import perf_tests
from utils.log import logger
from utils.perf_monitor_memory import MonitorMemory
from utils.perf import add_providers
from utils.perf import clean_appliance_evmserverd_off
from utils.perf import create_service_catalog_bundles
from utils.perf import generate_providers_test
from utils.perf import generate_test_name
from utils.perf import get_provisioning_memory_scenarios
from utils.perf import idle_time
from utils.perf import log_grafana_url
from utils.perf import set_server_roles_workload_provisioning
from utils.perf import start_evm_wait_for_ui
from utils.providers import get_mgmt_by_name
import time
import pytest


@pytest.mark.parametrize('the_providers', get_provisioning_memory_scenarios())
def test_workload_provisioning(request, ssh_client, the_providers):
    """Runs through provider based scenarios running provisioning over a set period of time. The
    scenarios consist of starting up the appliance, run idle for 2 minutes, add one or more
    provisioning providers, allow refresh to consume 5 minutes, then begin navigating the UI to
    continously order a catalog item and provision a VM for set period of time defined in
    perf_test.yaml.  Memory Monitor creates graphs and summary at the end of each scenario."""
    from_ts = int(time.time() * 1000)
    clean_appliance_evmserverd_off()
    ordered_vms = []
    providers_tested = generate_providers_test(the_providers)
    test_name = generate_test_name(providers_tested, the_providers)

    monitor_thread = MonitorMemory(ssh_client, 'workload-provisioning', test_name, providers_tested)

    def cleanup_workload(vms_to_cleanup, from_ts):
        logger.info('Starting test clean up.')
        starttime = time.time()
        logger.info('Disabling provisioning')
        configuration.set_server_roles(automate=False)
        # Create graphs - Consumes some time to allow test to quiesce
        monitor_thread.signal = False
        monitor_thread.join()
        logger.info('{} remaining vms to cleanup'.format(len(vms_to_cleanup)))
        for pro_name, vm_name in vms_to_cleanup:
            logger.debug('Cleaning up: {}'.format(vm_name))
            provider = get_mgmt_by_name(pro_name)
            try:
                provider.delete_vm(vm_name)
            except Exception as e:
                # VM potentially was not yet provisioned
                logger.error('Could not delete VM: {} Exception: {}'.format(vm_name, e))
        timediff = time.time() - starttime
        logger.info('Finished cleaning up in {}'.format(timediff))
        log_grafana_url(from_ts)
    request.addfinalizer(lambda: cleanup_workload(ordered_vms, from_ts))

    monitor_thread.start()

    start_evm_wait_for_ui(ssh_client)
    set_server_roles_workload_provisioning()
    idle_time(120, 'Post set roles.')  # 2 minutes of idle appliance
    add_providers(the_providers)
    idle_time(300, 'Allow refresh to run')  # Allow refresh to run

    bundles = create_service_catalog_bundles(the_providers)

    time_between_provision = perf_tests['workload']['provisioning']['time_between_provisions']
    total_time = perf_tests['workload']['provisioning']['total_time']
    starttime = time.time()
    total_waited = 0
    total_vms = 0
    vm_num = 0
    while (total_waited < total_time):
        vm_num += 1
        start_provision_time = time.time()
        for bundle in bundles:
            service_catalogs = ServiceCatalogs('service_name')
            service_catalogs.order(bundles[bundle]['catalog'], bundles[bundle]['catalog_bundle'])
            flash.assert_no_errors()
            total_vms += 1
            ordered_vm_name = '{}_{}'.format(bundles[bundle]['vm_name'], str(vm_num).zfill(4))
            ordered_vms.append((bundle, ordered_vm_name))
        total_waited = time.time() - starttime
        queued_provisions_time = time.time() - start_provision_time
        logger.debug('Time to queue provisions via UI: {}'.format(queued_provisions_time))
        logger.info('Time waited: {}/{}'.format(round(total_waited, 2), total_time))
        # Start cleaning up vms once above 3 vms provisioned per provisioning provider
        if total_vms > (3 * len(the_providers)):
            for i in range(len(the_providers)):
                pro_name, vm_name = ordered_vms.pop(0)
                provider = get_mgmt_by_name(pro_name)
                try:
                    provider.delete_vm(vm_name)
                    total_vms -= 1
                except Exception as e:
                    logger.error('Could not delete VM: {} Exception: {}'.format(vm_name, e))
                    ordered_vms.insert(0, (pro_name, vm_name))
        if queued_provisions_time < time_between_provision:
            wait_diff = abs(time_between_provision - queued_provisions_time)
            time.sleep(wait_diff)

    logger.info('Test Ending...')
