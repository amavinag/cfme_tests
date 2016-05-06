"""Runs smartstate analysis benchmarks."""
from collections import OrderedDict
from cfme.configure.configuration import server_name, server_id
from cfme.infrastructure.virtual_machines import Vm
from utils.appliance import IPAppliance
from utils.conf import cfme_data, env, perf_tests
from utils.hosts import setup_providers_hosts_credentials
from utils.log import logger
from utils.perf import generate_benchmark_code
from utils.perf import get_smartstate_benchmark_providers
from utils.perf import log_benchmark
from utils.perf import parse_benchmark_output
from utils.perf import pbench_start, pbench_stop
from utils.perf import refresh_provider_via_rails
from utils.perf import set_server_roles_benchmark_smartstate
from utils.version import current_version
from utils import providers
from urlparse import urlparse
import datetime
import pytest

pytestmark = [
    pytest.mark.parametrize('provider', get_smartstate_benchmark_providers()),
    pytest.mark.usefixtures('end_log_benchmark_timings', 'end_pbench_move_results')
]

benchmark_values = OrderedDict()
test_run_ts = '{}-SmartState'.format(str(datetime.datetime.now()).replace(" ", "_"))


@pytest.yield_fixture(scope='module')
def end_log_benchmark_timings():
    """Fixture that ensures benchmark timings are written/appended to benchmark-statistics.csv."""
    yield
    log_benchmark(benchmark_values)


def setup_test_smartstate(provider, ssh_client):
    """Setups up benchmark tests for smartstate analysis."""
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    ip_a.install_vddk(reboot=False)
    set_server_roles_benchmark_smartstate()
    providers.setup_provider(provider, validate=False)
    refresh_provider_via_rails(ssh_client, cfme_data['management_systems'][provider]['name'])
    setup_providers_hosts_credentials(provider, ignore_errors=True)
    if 'rhevm' in cfme_data['management_systems'][provider]['tags']:
        vm = Vm(env['appliance_vm_name'], providers.get_crud(provider))
        cfme_rel = Vm.CfmeRelationship(vm)
        if cfme_rel.is_relationship_set() is False:
            cfme_rel.set_relationship(str(server_name()), server_id())


def host_smartstate_benchmark(ssh_client, provider):
    provider_name = cfme_data['management_systems'][provider]['name']
    for host_to_scan in cfme_data['management_systems'][provider]['smartstate_scan_hosts']:
        for iteration in range(perf_tests['benchmark']['smartstate']['host']):
            test_iteration = 'Host_analysis-{}-{}'.format(host_to_scan, str(iteration).zfill(4))
            pbench_start(ssh_client, test_run_ts, test_iteration)
            code = generate_benchmark_code(
                'h = Host.where(:name => \'' + host_to_scan + '\');'
                'task = MiqTask.create(:name => \'SmartState Analysis for \\\''
                + host_to_scan + '\\\'\', :userid => \'admin\');',
                'h[0].scan_from_queue(task.id);')
            exit_status, output = ssh_client.run_rails_console(code, timeout=None)
            try:
                float(output.strip().split('\n')[-1])
            except ValueError:
                logger.error('Unexpected Output: {}'.format(output))
            finally:
                pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
            parse_benchmark_output(output, 'SmartState', 'Host-{}'.format(host_to_scan),
                provider_name, iteration, benchmark_values)


def vm_smartstate_benchmark(ssh_client, provider):
    provider_name = cfme_data['management_systems'][provider]['name']
    for vm_to_scan in cfme_data['management_systems'][provider]['smartstate_scan_vms']:
        for iteration in range(perf_tests['benchmark']['smartstate']['vm']):
            if current_version().is_in_series('5.5'):
                logger.error('')
                assert 0
            elif current_version().is_in_series('5.4'):
                code = generate_benchmark_code(
                    'v = VmOrTemplate.where(:name => \'' + vm_to_scan + '\');'
                    'ems_list = v[0].ems_host_list;'
                    'ems_list[\'connect_to\'] = v[0].scan_via_ems? ? \'ems\' : \'host\';'
                    'ems_list[\'connect\'] = false if v[0].vendor.to_s == \'RedHat\';'
                    'config = VMDB::Config.new(\'vmdb\').config;'
                    'snapshot = {\'use_existing\' => false, \'description\'  => \'benchmark\'};'
                    'snapshot[\'create_free_percent\'] = config.fetch_path(:snapshots, :create_free_percent) || 100;'
                    'snapshot[\'remove_free_percent\'] = config.fetch_path(:snapshots, :remove_free_percent) || 100;'
                    'scan_args = {\'ems\' => ems_list};'
                    'scan_args[\'snapshot\'] = snapshot;'
                    'scan_args[\'vmScanProfiles\'] = v[0].scan_profile_list;'
                    'scan_args[\'permissions\'] = {\'group\' => 36} if v[0].vendor.to_s == \'RedHat\';'
                    'options = {:target_id => v[0].id};'
                    'options[:target_class] = \'VmOrTemplate\';'
                    'options[:name] = \'Scan from Vm \' + v[0].name;'
                    'options[:userid] = \'admin\';'
                    'options[:sync_key] = v[0].guid;'
                    'options[:zone] = \'default\';'
                    'j = Job.create_job(\'VmScan\', options);'
                    'j.started_on = Time.now;'
                    'j.state = \'scanning\';'
                    'j.agent_name = \'EVM\';'
                    'j.agent_class = \'MiqServer\';'
                    'j.agent_id = 1;'
                    'j.dispatch_status = \'active\';'
                    'options = {\'category\' => \'vmconfig,accounts,software,services,system\', \'vm_id\' => v[0].id, \'sync_key\' => v[0].guid, \'taskid\' => j.guid, \'method_name\' => \'ScanMetadata\', \'args\' => [YAML.dump(scan_args)]};'
                    'miqhost_args = Array(options.delete(\'args\'));'
                    'options = {\'args\' => [v[0].path] + miqhost_args, \'method_name\' => \'ScanMetadata\', \'vm_guid\' => v[0].guid, :target_id => v[0].id, :categories => [\'vmconfig\',\'accounts\',\'software\',\'services\',\'system\']}.merge(options);'
                    'j.options = options;'
                    'j.save;'
                    'ost = OpenStruct.new(options);'
                    'm = MiqServer.first;',
                    'm.scan_sync_vm(ost);')
            test_iteration = 'VM_analysis-{}-{}-{}'.format(provider_name, vm_to_scan,
                str(iteration).zfill(4))
            pbench_start(ssh_client, test_run_ts, test_iteration)
            exit_status, output = ssh_client.run_rails_console(code, timeout=None)
            try:
                float(output.strip().split('\n')[-1])
            except ValueError:
                logger.error('Unexpected Output: {}'.format(output))
            finally:
                pbench_stop(ssh_client, test_run_ts, test_iteration, results=output)
            parse_benchmark_output(output, 'SmartState', 'VM-{}'.format(vm_to_scan), provider_name,
                iteration, benchmark_values)


def test_host_and_vm_smartstate(ssh_client, clean_appliance, provider):
    """Saves time by benchmarking both Host/VM from same provider at same time."""
    setup_test_smartstate(provider, ssh_client)
    host_smartstate_benchmark(ssh_client, provider)
    vm_smartstate_benchmark(ssh_client, provider)


def test_host_smartstate(ssh_client, clean_appliance, provider):
    """Benchmark host smartstate analysis."""
    setup_test_smartstate(provider, ssh_client)
    host_smartstate_benchmark(ssh_client, provider)


def test_vm_smartstate(ssh_client, clean_appliance, provider):
    """Benchmark vm smartstate analysis.  This test benchmarks a component of vm smartstate
    analysis that is representative of scaning the filesystem.  There are other components and work
    that must be completed to complete a smart state analysis however measuring all components
    working correctly is difficult and involves measuring less precisely with queueing but
    could provide a more accurate customer feeling to the benchmark."""
    setup_test_smartstate(provider, ssh_client)
    vm_smartstate_benchmark(ssh_client, provider)
