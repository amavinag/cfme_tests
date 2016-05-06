"""Runs C&U/SSA/Provisioning Workloads on various combinations of providers."""
from cfme.common.vm import VM
from cfme.configure import configuration as conf
from cfme.exceptions import FlashMessageException
from cfme.fixtures import pytest_selenium as sel
from cfme.infrastructure import datastore, host
from cfme.services.catalogs.service_catalogs import ServiceCatalogs
from cfme.web_ui import flash, toolbar as tb
from utils.appliance import IPAppliance
from utils.conf import cfme_data, env, perf_tests
from utils.log import logger
from utils.perf_monitor_memory import MonitorMemory
from utils.perf import add_host_credentials
from utils.perf import add_providers
from utils.perf import clean_appliance_evmserverd_off
from utils.perf import clean_replication_master_appliance
from utils.perf import create_service_catalog_bundles
from utils.perf import generate_providers_test
from utils.perf import generate_test_name
from utils.perf import get_all_workload_memory_scenarios
from utils.perf import idle_time
from utils.perf import log_grafana_url
from utils.perf import set_cap_and_util_all_via_rails
from utils.perf import set_server_roles_workload_all
from utils.perf import start_evm_wait_for_ui
from utils.providers import get_mgmt_by_name
from utils import providers
from selenium.common.exceptions import WebDriverException
from urlparse import urlparse
import time
import pytest


@pytest.mark.parametrize('the_providers', get_all_workload_memory_scenarios())
def test_workload_all(request, ssh_client, the_providers):
    """Runs through provider based scenarios running c&u/ssa/provisioning and replication over a set
    period of time. The scenarios consist of starting up the appliance, run idle for 2 minutes, add
    one or more provisioning providers and C&U providers, allow refresh to consume 800s, then begin
    navigating the UI to continously order a catalog item and provision a VM, continously smartstate
    analyses, all for set period of time defined in perf_test.yaml.  Memory Monitor creates graphs
    and summary at the end of each scenario."""
    from_ts = int(time.time() * 1000)
    logger.debug('Providers: {}'.format(the_providers))
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    ip_a.install_vddk(reboot=False)
    clean_appliance_evmserverd_off()
    ordered_vms = []
    providers_tested = generate_providers_test(the_providers)
    test_name = generate_test_name(providers_tested, the_providers)

    monitor_thread = MonitorMemory(ssh_client, 'workload-all', test_name, providers_tested)

    def cleanup_workload(vms_to_cleanup, from_ts):
        logger.info('Starting test clean up.')
        starttime = time.time()
        logger.info('Disabling replication and provisioning')
        conf.set_server_roles(database_synchronization=False, automate=False)
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
    set_server_roles_workload_all()
    idle_time(120, 'Post set roles.')  # 2 minutes of idle appliance
    add_providers(the_providers)
    idle_time(800, 'Allow refresh to run')  # Allow refresh to run

    set_cap_and_util_all_via_rails(ssh_client)

    # Provisioning workload, create bundles for ordering
    bundles = create_service_catalog_bundles(the_providers, 'wkld-all')

    # Smart State Analysis workload, credentialize the hosts, set cfme relationship
    add_host_credentials(the_providers)

    # Replication Workload, setup replication host:
    cfme_master_ip = perf_tests['workload']['all_in_one']['replication_ip']
    clean_replication_master_appliance(cfme_master_ip)
    conf.set_replication_worker_host(cfme_master_ip)
    flash.assert_message_contain("Configuration settings saved for CFME Server")
    try:
        sel.force_navigate("cfg_settings_currentserver_server")
    except WebDriverException:
        sel.handle_alert()
        sel.force_navigate("cfg_settings_currentserver_server")
    # Force uninstall rubyrep for this region from master
    ssh_client.run_rake_command('evm:dbsync:uninstall')
    idle_time(30, 'Post evm:dbsync:uninstall')
    conf.set_server_roles(database_synchronization=True)

    # Start provisioning and smart state workloads:
    time_between = perf_tests['workload']['all_in_one']['time_between']
    total_time = perf_tests['workload']['all_in_one']['total_time']
    starttime = time.time()
    total_waited = 0
    total_vms = 0
    vm_num = 0
    while (total_waited < total_time):
        vm_num += 1
        start_workload_time = time.time()
        for bundle in bundles:
            service_catalogs = ServiceCatalogs('service_name')
            service_catalogs.order(bundles[bundle]['catalog'], bundles[bundle]['catalog_bundle'])
            flash.assert_no_errors()
            total_vms += 1
            ordered_vm_name = '{}_{}'.format(bundles[bundle]['vm_name'], str(vm_num).zfill(4))
            ordered_vms.append((bundle, ordered_vm_name))
        for provider in the_providers:
            if 'benchmark_smartstate' in cfme_data['management_systems'][provider]['tags']:
                # Start smart state analysis on vms:
                for vm_to_scan in cfme_data['management_systems'][provider]['smartstate_scan_vms']:
                    sel.force_navigate('infrastructure_virtual_machines')
                    vm = VM.factory(vm_to_scan, providers.get_crud(provider))
                    try:
                        vm.smartstate_scan(cancel=False, from_details=False)
                    except Exception as e:
                        logger.error('Could not smart state scan vm: {}'.format(vm_to_scan))
                        logger.error('Exception: {}'.format(e))
                # Start smart state analysis of host(s):
                hosts_to_scan = cfme_data['management_systems'][provider]['smartstate_scan_hosts']
                for host_to_scan in hosts_to_scan:
                    scan_host = host.Host(name=host_to_scan)
                    try:
                        scan_host.run_smartstate_analysis()
                    except FlashMessageException as fme:
                        logger.error('Issue with: {}'.format(scan_host))
                        logger.error('Exception: {}'.format(fme))
                        logger.error('flash.get_messages(): {}'.format(flash.get_messages()))
                        flash.dismiss()
                # Smartstate analysis of Datastore(s):
                ds_to_scan = cfme_data['management_systems'][provider]['smartstate_scan_storage']
                for ds_to_scan in ds_to_scan:
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
        queued_time = time.time() - start_workload_time
        logger.debug('Time to queue provisioning/scans via UI: {}'.format(queued_time))
        logger.info('Time waited: {}/{}'.format(round(total_waited, 2), total_time))
        # Start cleaning up vms once above 3 vms provisioned per provisioning provider
        if total_vms > (3 * len(bundles)):
            for i in range(len(bundles)):
                pro_name, vm_name = ordered_vms.pop(0)
                provider = get_mgmt_by_name(pro_name)
                try:
                    provider.delete_vm(vm_name)
                    total_vms -= 1
                except Exception as e:
                    logger.error('Could not delete VM: {} Exception: {}'.format(vm_name, e))
                    ordered_vms.insert(0, (pro_name, vm_name))
        if queued_time < time_between:
            wait_diff = abs(time_between - queued_time)
            time.sleep(wait_diff)

    logger.info('Test Ending...')
