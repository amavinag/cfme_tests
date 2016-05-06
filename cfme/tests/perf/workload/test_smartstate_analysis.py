"""Runs SmartState Analysis Workload on various providers."""
from cfme.common.vm import VM
from cfme.exceptions import FlashMessageException
from cfme.fixtures import pytest_selenium as sel
from cfme.infrastructure import datastore, host
from cfme.web_ui import flash, toolbar as tb
from utils.appliance import IPAppliance
from utils.conf import cfme_data, env, perf_tests
from utils.log import logger
from utils.perf_monitor_memory import MonitorMemory
from utils.perf import add_host_credentials
from utils.perf import add_providers
from utils.perf import clean_appliance_evmserverd_off
from utils.perf import generate_providers_test
from utils.perf import generate_test_name
from utils.perf import get_smartstate_memory_scenarios
from utils.perf import idle_time
from utils.perf import log_grafana_url
from utils.perf import set_server_roles_workload_smartstate
from utils.perf import start_evm_wait_for_ui
from utils import providers
from urlparse import urlparse
import time
import pytest


@pytest.mark.parametrize('the_providers', get_smartstate_memory_scenarios())
def test_workload_smartstate_analysis(request, ssh_client, the_providers):
    """Runs through provider based scenarios running smart state analyses over a set period of time.
    The scenarios consist of starting up the appliance, run idle for 2 minutes, add one or more SSA
    providers, allow refresh to consume 5 minutes, then begin navigating the UI to perform SSA on
    VMs/Hosts/Datastores for set period of time defined in perf_test.yaml.  Memory Monitor creates
    graphs and summary at the end of each scenario."""
    from_ts = int(time.time() * 1000)
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    ip_a.install_vddk(reboot=False)
    clean_appliance_evmserverd_off()

    providers_tested = generate_providers_test(the_providers)
    test_name = generate_test_name(providers_tested, the_providers)

    monitor_thread = MonitorMemory(ssh_client, 'workload-smartstate-analysis', test_name,
        providers_tested)

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
    set_server_roles_workload_smartstate()
    idle_time(120, 'Post set roles.')  # 2 minutes of idle appliance
    add_providers(the_providers)
    idle_time(300, 'Allow refresh to run')  # Allow refresh to run

    add_host_credentials(the_providers)

    time_between_analyses = perf_tests['workload']['smartstate']['time_between_analysis']
    total_time = perf_tests['workload']['smartstate']['total_time']
    starttime = time.time()
    total_waited = 0
    while (total_waited < total_time):
        for provider in the_providers:
            # Start smart state analysis on vms:
            start_scan_time = time.time()
            for vm_to_scan in cfme_data['management_systems'][provider]['smartstate_scan_vms']:
                sel.force_navigate('infrastructure_virtual_machines')
                vm = VM.factory(vm_to_scan, providers.get_crud(provider))
                try:
                    vm.smartstate_scan(cancel=False, from_details=False)
                except Exception as e:
                    logger.error('Could not smart state scan vm: {}'.format(vm_to_scan))
                    logger.error('Exception: {}'.format(e))
            # Start smart state analysis of host(s):
            for host_to_scan in cfme_data['management_systems'][provider]['smartstate_scan_hosts']:
                scan_host = host.Host(name=host_to_scan)
                try:
                    scan_host.run_smartstate_analysis()
                except FlashMessageException as fme:
                    logger.error('Issue with: {}'.format(scan_host))
                    logger.error('Exception: {}'.format(fme))
                    logger.error('flash.get_messages(): {}'.format(flash.get_messages()))
                    flash.dismiss()
            # Smartstate analysis of Datastore(s):
            for ds_to_scan in cfme_data['management_systems'][provider]['smartstate_scan_storage']:
                test_datastore = datastore.Datastore(ds_to_scan, provider)
                sel.force_navigate('infrastructure_datastore', context={
                    'datastore': test_datastore,
                    'provider': test_datastore.provider
                })
                tb.select('Configuration', 'Perform SmartState Analysis', invokes_alert=True)
                sel.handle_alert()
                try:
                    flash.assert_message_contain(
                        '"{}": scan successfully initiated'.format(ds_to_scan))
                except FlashMessageException as fme:
                    logger.error('Issue with: {}'.format(ds_to_scan))
                    logger.error('Exception: {}'.format(fme))
                    logger.error('flash.get_messages(): {}'.format(flash.get_messages()))
                    flash.dismiss()
        total_waited = time.time() - starttime
        queued_scans_time = time.time() - start_scan_time
        logger.debug('Time to queue scans via UI: {}'.format(queued_scans_time))
        logger.info('Time waited: {}/{}'.format(round(total_waited, 2), total_time))
        if queued_scans_time < time_between_analyses:
            wait_diff = abs(time_between_analyses - queued_scans_time)
            time.sleep(wait_diff)

    logger.info('Test Ending...')
