"""Functions that performance tests use."""
from cfme.automate.service_dialogs import ServiceDialog
from cfme.common.vm import VM
from cfme.configure.configuration import server_name, set_server_roles, server_id
from cfme.infrastructure.virtual_machines import Vm
from cfme.services.catalogs.catalog_item import CatalogBundle, CatalogItem
from cfme.services.catalogs.catalog import Catalog
from cfme.web_ui import fill, flash, Form, form_buttons, Select
from collections import OrderedDict
from utils.appliance import IPAppliance
from utils.browser import quit
from utils.conf import cfme_data, credentials, env, perf_tests
from utils.hosts import setup_providers_hosts_credentials
from utils.log import logger
from utils.path import log_path
from utils.ssh import SSHClient, SSHTail
from utils import db, providers, version
from urlparse import urlparse
import cfme.fixtures.pytest_selenium as sel
import csv
import numpy
import os
import pytest
import time

connection_broker = Form(
    fields=[
        ('value', Select("select#vim_broker_worker_threshold"))
    ]
)


def add_host_credentials(the_providers):
    for provider_key in the_providers:
        if 'benchmark_smartstate' in cfme_data['management_systems'][provider_key]['tags']:
            setup_providers_hosts_credentials(provider_key, ignore_errors=True)
            if 'rhevm' in cfme_data['management_systems'][provider_key]['tags']:
                vm = VM.factory(env['appliance_vm_name'], providers.get_crud(provider_key))
                cfme_rel = Vm.CfmeRelationship(vm)
                cfme_rel.set_relationship(str(server_name()), server_id())


def add_providers(the_providers):
    for provider_key in the_providers:
        if 'broker_large_memory' in cfme_data['management_systems'][provider_key]['tags']:
            set_vim_broker_memory_threshold('4 GB')
            # set_refresh_core_worker_memory_threshold('500.megabytes')
        providers.setup_provider(provider_key, validate=False)


def append_value(values, feature, test_name, provider_name, measurement, value):
    """Appends a timing value into a nested dictionary.  This is useful to save timing values for
    benchmarks which run multiple repetitions through pytest rather than in the test function
    itself.
    """
    if feature not in values:
        values[feature] = OrderedDict()
    if test_name not in values[feature]:
        values[feature][test_name] = OrderedDict()
    if provider_name not in values[feature][test_name]:
        values[feature][test_name][provider_name] = OrderedDict()
    if measurement not in values[feature][test_name][provider_name]:
        values[feature][test_name][provider_name][measurement] = []
    values[feature][test_name][provider_name][measurement].append(value)


def clean_appliance_evmserverd_off():
    ssh_client = SSHClient()
    ssh_client.run_command('service evmserverd stop')
    ssh_client.run_command('sync; sync; echo 3 > /proc/sys/vm/drop_caches')
    ssh_client.run_command('service collectd stop')
    ssh_client.run_command('service {}-postgresql restart'.format(db.scl_name()))
    ssh_client.run_rake_command('evm:dbsync:local_uninstall')
    # 5.6 requires DISABLE_DATABASE_ENVIRONMENT_CHECK=1
    ssh_client.run_command(
        'cd /var/www/miq/vmdb;DISABLE_DATABASE_ENVIRONMENT_CHECK=1 bin/rake evm:db:reset')
    ssh_client.run_rake_command('db:seed')
    ssh_client.run_command('service collectd start')
    # Work around for https://bugzilla.redhat.com/show_bug.cgi?id=1337525
    ssh_client.run_command('service httpd stop')
    ssh_client.run_command('rm -rf /run/httpd/*')


def clean_replication_master_appliance(master_ip):
    ssh_kwargs = {
        'username': credentials['ssh']['username'],
        'password': credentials['ssh']['password'],
        'hostname': master_ip
    }
    ssh_client = SSHClient(**ssh_kwargs)
    ssh_client.run_command('service evmserverd stop')
    ssh_client.run_command('sync; sync; echo 3 > /proc/sys/vm/drop_caches')
    ssh_client.run_command('service {}-postgresql restart'.format(db.scl_name()))
    ssh_client.run_rake_command('evm:db:reset')
    ssh_client.run_rake_command('db:seed')
    ssh_client.run_command('service evmserverd start')


def create_service_catalog_bundles(the_providers, vm_name_suffix='wkld-pro'):
    bundles = {}
    # Create Bundle per provider:
    for provider_key in the_providers:
        provider = cfme_data['management_systems'][provider_key]
        if 'benchmark_provisioning' in provider.tags:
            bundles[provider.name] = {}

            dialog = '{}_dialog'.format(provider.name)
            element_data = dict(
                ele_label='Element Label for {}'.format(provider.name),
                ele_name='Element_Name',
                ele_desc='Description for Element for {}'.format(provider.name),
                choose_type='Text Box',
                default_text_box='default value'
            )
            service_dialog = ServiceDialog(label=dialog,
                description='Dialog for {}'.format(provider.name),
                submit=True, cancel=True,
                tab_label='tab_{}'.format(provider.name), tab_desc='Description for Tab',
                box_label='box_{}'.format(provider.name), box_desc='Description for Box')
            service_dialog.create(element_data)
            flash.assert_success_message('Dialog "%s" was added' % dialog)

            catalog = '{}_catalog'.format(provider.name)
            cat = Catalog(name=catalog, description='Catalog for {}'.format(provider.name))
            cat.create()
            vm_name = '{}-{}'.format(time.strftime('%Y%m%d%H%M%S'), vm_name_suffix)
            template = provider.provisioning.template
            host = provider.provisioning.host
            datastore = provider.provisioning.datastore
            catalog_item_type = provider.provisioning.catalog_item_type

            provisioning_data = {
                'vm_name': vm_name,
                'host_name': {'name': [host]},
                'datastore_name': {'name': [datastore]}
            }

            if provider.type == 'rhevm':
                provisioning_data['provision_type'] = 'Native Clone'
                provisioning_data['vlan'] = provider.provisioning.vlan
                catalog_item_type = version.pick({
                    version.LATEST: 'RHEV',
                    '5.3': 'RHEV',
                    '5.2': 'Redhat'
                })
            elif provider.type == 'virtualcenter':
                provisioning_data['provision_type'] = 'VMware'
            item_name = '{}_catalog_item'.format(provider.name)
            catalog_item = CatalogItem(item_type=catalog_item_type, name=item_name,
                description='Catalog Item for {}'.format(provider.name), display_in=True,
                catalog=catalog, dialog=dialog, catalog_name=template, provider=provider.name,
                prov_data=provisioning_data)

            vm_name = catalog_item.provisioning_data['vm_name']
            catalog_item.create()
            bundle_name = '{}_bundle'.format(provider.name)
            catalog_bundle = CatalogBundle(name=bundle_name,
                description='Bundle for {}'.format(provider.name), display_in=True,
                catalog=catalog_item.catalog, dialog=catalog_item.dialog)
            catalog_bundle.create([catalog_item.name])
            bundles[provider.name]['vm_name'] = vm_name
            bundles[provider.name]['catalog'] = catalog_item.catalog
            bundles[provider.name]['catalog_bundle'] = catalog_bundle
    return bundles


def collect_log(ssh_client, log_prefix, local_file_name, strip_whitespace=False):
    """Collects all of the logs associated with a single log prefix (ex. evm or top_output) and
    combines to single gzip log file.  The log file is then scp-ed back to the host.
    """
    log_dir = '/var/www/miq/vmdb/log/'

    log_file = '{}{}.log'.format(log_dir, log_prefix)
    dest_file = '{}{}.perf.log'.format(log_dir, log_prefix)
    dest_file_gz = '{}{}.perf.log.gz'.format(log_dir, log_prefix)

    ssh_client.run_command('rm -f {}'.format(dest_file_gz))

    status, out = ssh_client.run_command('ls -1 {}-*'.format(log_file))
    if status == 0:
        files = out.strip().split('\n')
        for lfile in sorted(files):
            ssh_client.run_command('cp {} {}-2.gz'.format(lfile, lfile))
            ssh_client.run_command('gunzip {}-2.gz'.format(lfile))
            if strip_whitespace:
                ssh_client.run_command('sed -i  \'s/^ *//; s/ *$//; /^$/d; /^\s*$/d\' '
                    '{}-2'.format(lfile))
            ssh_client.run_command('cat {}-2 >> {}'.format(lfile, dest_file))
            ssh_client.run_command('rm {}-2'.format(lfile))

    ssh_client.run_command('cp {} {}-2'.format(log_file, log_file))
    if strip_whitespace:
        ssh_client.run_command('sed -i  \'s/^ *//; s/ *$//; /^$/d; /^\s*$/d\' '
            '{}-2'.format(log_file))
    ssh_client.run_command('cat {}-2 >> {}'.format(log_file, dest_file))
    ssh_client.run_command('rm {}-2'.format(log_file))
    ssh_client.run_command('gzip {}{}.perf.log'.format(log_dir, log_prefix))

    ssh_client.get_file(dest_file_gz, local_file_name)
    ssh_client.run_command('rm -f {}'.format(dest_file_gz))


def convert_top_mem_to_mib(top_mem):
    """Takes a top memory unit from top_output.log and converts it to MiB"""
    if top_mem[-1:] == 'm':
        num = float(top_mem[:-1])
    elif top_mem[-1:] == 'g':
        num = float(top_mem[:-1]) * 1024
    else:
        num = float(top_mem) / 1024
    return num


def delete_all_method_from_queue_via_rails(ssh_client, method_name):
    """Cleans all of a specific method out of miq_queue table."""
    command = ('MiqQueue.where(\'method_name = \\\'' + method_name + '\\\'\').delete_all')
    ssh_client.run_rails_console(command, timeout=None)


def generate_benchmark_code(before_benchmark_code, bench_code):
    command = ('require \\\"miq-process\\\";'
               'ActiveRecord::Base.logger.level = 1;'
               'mrss_start = MiqProcess.processInfo()[:memory_usage];'
               'vmem_start = MiqProcess.processInfo[:memory_size];'
               'gc_start = GC.stat;'
               '' + before_benchmark_code + ''
               'GC.start;'
               'timing = Benchmark.realtime do;' + bench_code + 'end;'
               'GC.start;'
               'mrss_end = MiqProcess.processInfo()[:memory_usage];'
               'vmem_end = MiqProcess.processInfo[:memory_size];'
               'gc_end = GC.stat;'
               'mrss_change = mrss_end - mrss_start;'
               'vmem_change = vmem_end - vmem_start;'
               'puts \\\"#{mrss_start}, #{mrss_end}, #{mrss_change}\\\";'
               'puts \\\"#{vmem_start}, #{vmem_end}, #{vmem_change}\\\";'
               'puts \\\"#{gc_start}\\\";'
               'puts \\\"#{gc_end}\\\";'
               'puts \\\"Process Pid: #{Process.pid}\\\";'
               'timing')
    return command


def generate_providers_test(the_providers):
    providers_tested = ''
    for provider in the_providers:
        providers_tested = '{}{}, '.format(providers_tested,
            cfme_data['management_systems'][provider]['name'])
    providers_tested = providers_tested[0:-2]
    logger.info('Testing with {} Provider(s): {}'.format(len(the_providers), providers_tested))
    return providers_tested


def generate_statistics(the_list, decimals=2):
    """Returns comma seperated statistics over a list of numbers.

    Returns:  list of samples(runs), minimum, average, median, maximum,
              stddev, 90th(percentile),
              99th(percentile)
    """
    if len(the_list) == 0:
        return [0, 0, 0, 0, 0, 0, 0, 0]
    else:
        numpy_arr = numpy.array(the_list)
        minimum = round(numpy.amin(numpy_arr), decimals)
        average = round(numpy.average(numpy_arr), decimals)
        median = round(numpy.median(numpy_arr), decimals)
        maximum = round(numpy.amax(numpy_arr), decimals)
        stddev = round(numpy.std(numpy_arr), decimals)
        percentile90 = round(numpy.percentile(numpy_arr, 90), decimals)
        percentile99 = round(numpy.percentile(numpy_arr, 99), decimals)
        return [len(the_list), minimum, average, median, maximum, stddev, percentile90,
            percentile99]


def generate_test_name(providers_tested, the_providers):
    test_name = providers_tested
    if len(the_providers) > 1:
        test_name = '{}xProviders-{}'.format(len(the_providers),
            providers_tested.replace(', ', '-'))
    return test_name


def get_all_workload_memory_scenarios():
    providers = []
    accepted_sizes = ['medium', 'large']
    cap_and_util_providers = []
    cap_and_util_sizes = {}
    pro_smart_providers = []
    for provider in cfme_data['management_systems']:
        if 'benchmark_cap_and_util' in cfme_data['management_systems'][provider]['tags']:
            size = cfme_data['management_systems'][provider]['size']
            if size in accepted_sizes:
                if size not in cap_and_util_sizes:
                    cap_and_util_sizes[size] = []
                cap_and_util_sizes[size].append(provider)
                cap_and_util_providers.append(provider)
        if 'benchmark_provisioning' in cfme_data['management_systems'][provider]['tags']:
            pro_smart_providers.append(provider)
        if 'benchmark_smartstate' in cfme_data['management_systems'][provider]['tags']:
            if provider not in pro_smart_providers:
                pro_smart_providers.append(provider)
    # Pair each C&U provider with provision/smartstate provider(s)
    for provider in cap_and_util_providers:
        for num_providers in range(1, len(pro_smart_providers) + 1):
            for s_provider in range(0, len(pro_smart_providers) + 1 - num_providers):
                new_list = list(_ for _ in pro_smart_providers[s_provider:s_provider +
                    num_providers])
                new_list.append(provider)
                providers.append(new_list)
    # Pair each pair of C&U providers with provision/smartstate provider(s)
    for cu_providers_size in sorted(cap_and_util_sizes, reverse=True):
        for num_providers in range(1, len(pro_smart_providers) + 1):
            for s_provider in range(0, len(pro_smart_providers) + 1 - num_providers):
                new_list = list(_ for _ in pro_smart_providers[s_provider:s_provider +
                    num_providers])
                new_list.extend(cap_and_util_sizes[cu_providers_size])
                providers.append(new_list)
    return providers


def get_cap_and_util_memory_scenarios():
    providers = []
    sizes = {}
    for provider in cfme_data['management_systems']:
        if 'benchmark_cap_and_util' in cfme_data['management_systems'][provider]['tags']:
            providers.append([provider])
            size = cfme_data['management_systems'][provider]['size']
            if size not in sizes:
                sizes[size] = []
            sizes[size].append(provider)
    for size_ in sorted(sizes, reverse=True):
        if len(sizes[size_]) > 1:
            providers.append(sizes[size_])
    return providers


def get_provisioning_memory_scenarios():
    all_providers = []
    for provider in cfme_data['management_systems']:
        if 'benchmark_provisioning' in cfme_data['management_systems'][provider]['tags']:
            all_providers.append(provider)
    providers = []
    for num_providers in range(1, len(all_providers) + 1):
        for s_provider in range(0, len(all_providers) + 1 - num_providers):
            providers.append(list(_ for _ in all_providers[s_provider:s_provider + num_providers]))
    return providers


def get_smartstate_memory_scenarios():
    all_providers = []
    for provider in cfme_data['management_systems']:
        if 'benchmark_smartstate' in cfme_data['management_systems'][provider]['tags']:
            all_providers.append(provider)
    providers = []
    for num_providers in range(1, len(all_providers) + 1):
        for s_provider in range(0, len(all_providers) + 1 - num_providers):
            providers.append(list(_ for _ in all_providers[s_provider:s_provider + num_providers]))
    return providers


def get_benchmark_providers():
    """Gets all providers from cfme_data with tag 'benchmark' and not 'benchmark_provisioning'."""
    providers = []
    for provider in cfme_data['management_systems']:
        if ('benchmark' in cfme_data['management_systems'][provider]['tags'] and
                'benchmark_provisioning' not in cfme_data['management_systems'][provider]['tags']):
            providers.append(provider)
    return providers


def get_smartstate_benchmark_providers():
    """Gets all providers from cfme_data with tag 'benchmark_smartstate'."""
    providers = []
    for provider in cfme_data['management_systems']:
        if 'benchmark_smartstate' in cfme_data['management_systems'][provider]['tags']:
            providers.append(provider)
    return providers


def get_benchmark_vmware_providers():
    """Gets all providers from cfme_data with tag 'benchmark' and tag 'vmware'."""
    providers = []
    for provider in cfme_data['management_systems']:
        if ('benchmark' in cfme_data['management_systems'][provider]['tags']) and ('vmware' in
                cfme_data['management_systems'][provider]['tags']):
            providers.append(provider)
    return providers


def get_benchmark_rhevm_providers():
    """Gets all providers from cfme_data with tag 'benchmark' and tag 'rhevm'."""
    providers = []
    for provider in cfme_data['management_systems']:
        if ('benchmark' in cfme_data['management_systems'][provider]['tags']) and ('rhevm' in
                cfme_data['management_systems'][provider]['tags']):
            providers.append(provider)
    return providers


def get_benchmark_nobroker_providers():
    """Gets all providers from cfme_data with tag 'benchmark' and tag 'vmware'."""
    providers = []
    for provider in cfme_data['management_systems']:
        if ('benchmark' in cfme_data['management_systems'][provider]['tags']) and not ('vmware' in
                cfme_data['management_systems'][provider]['tags']):
            providers.append(provider)
    return providers


def get_benchmark_cfg_mgt_providers():
    """Gets all providers from cfme_data with tag 'benchmark' and tag 'vmware'."""
    providers = []
    for provider in cfme_data['configuration_managers']:
        if ('benchmark' in cfme_data['configuration_managers'][provider]['tags']):
            providers.append(provider)
    return providers


def get_worker_pid(worker_type):
    """Obtains the pid of the first worker with the worker_type specified"""
    ssh_client = SSHClient()
    if version.current_version().is_in_series('5.5'):
        excode, out = ssh_client.run_command('cd /var/www/miq/vmdb; rake evm:status 2> /dev/null | '
            'grep -m 1  \'{}\' | awk \'{{print $7}}\''.format(worker_type))
    else:
        excode, out = ssh_client.run_command('service evmserverd status 2> /dev/null | '
            'grep -m 1  \'{}\' | awk \'{{print $7}}\''.format(worker_type))
    worker_pid = str(out).strip()
    if out:
        logger.info('Obtained {} PID: {}'.format(worker_type, worker_pid))
    else:
        logger.error('Could not obtain {} PID, check evmserverd running or if specific role is'
            ' enabled...'.format(worker_type))
        assert out
    return worker_pid


def idle_time(s_time, msg):
    logger.info('Sleeping {}s for {}'.format(s_time, msg))
    time.sleep(s_time)


def init_server_roles(init_all_except_ui=False):
    """Mark all roles as False except for user_interface role."""
    roles = {}
    roles['automate'] = init_all_except_ui
    roles['database_operations'] = init_all_except_ui
    roles['database_synchronization'] = init_all_except_ui
    roles['ems_inventory'] = init_all_except_ui
    roles['ems_metrics_collector'] = init_all_except_ui
    roles['ems_metrics_coordinator'] = init_all_except_ui
    roles['ems_metrics_processor'] = init_all_except_ui
    roles['ems_operations'] = init_all_except_ui
    roles['event'] = init_all_except_ui
    roles['notifier'] = init_all_except_ui
    roles['scheduler'] = init_all_except_ui
    roles['reporting'] = init_all_except_ui
    roles['rhn_mirror'] = init_all_except_ui
    roles['smartproxy'] = init_all_except_ui
    roles['smartstate'] = init_all_except_ui
    roles['user_interface'] = True
    roles['web_services'] = init_all_except_ui
    return roles


def log_benchmark_statistics(values, feature, test, provider, measurement):
    """Dumps raw timing values and wites/appends statistics to benchmark-statistics.csv"""
    ver = version.current_version()

    csv_name = '{}-{}-{}-{}'.format(feature, test, provider, measurement)

    csv_path = log_path.join('csv_output')
    if not os.path.exists(str(csv_path)):
        os.mkdir(str(csv_path))

    # GC stat measurement is a ruby hash of values that changes depending on ruby version
    if isinstance(values[0], str):
        bench_file_path = csv_path.join('benchmark-{}.csv'.format(measurement))
        if bench_file_path.isfile():
            logger.debug('Appending to: benchmark-{}.csv'.format(measurement))
            outputfile = bench_file_path.open('a', ensure=True)
        else:
            logger.debug('Writing to: benchmark-{}.csv'.format(measurement))
            outputfile = bench_file_path.open('w', ensure=True)

        try:
            for value in values:
                outputfile.write('{},{},{},{}\n{}\n'.format(ver, feature, test, provider, value))
        finally:
            outputfile.close()

    else:  # Numeric Measurements
        # Dump Raw Values:
        csv_file_path = csv_path.join(csv_name + '.csv')
        with open(str(csv_file_path), 'w') as csv_file:
            csv_file.write(csv_name + '\n')
            for value in values:
                csv_file.write(str(value) + '\n')

        numpy_arr = numpy.array(values)
        minimum = round(numpy.amin(numpy_arr), 4)
        average = round(numpy.average(numpy_arr), 4)
        median = round(numpy.median(numpy_arr), 4)
        maximum = round(numpy.amax(numpy_arr), 4)
        stddev = round(numpy.std(numpy_arr), 4)
        percentile90 = round(numpy.percentile(numpy_arr, 90), 4)
        percentile99 = round(numpy.percentile(numpy_arr, 99), 4)

        # Write/Append to features benchmark csv
        csv_file_path = csv_path.join('benchmark-{}-statistics.csv'.format(measurement))
        if csv_file_path.isfile():
            logger.debug('Appending to: benchmark-{}-statistics.csv'.format(measurement))
            outputfile = csv_file_path.open('a', ensure=True)
            appending = True
        else:
            logger.debug('Writing to: benchmark-{}-statistics.csv'.format(measurement))
            outputfile = csv_file_path.open('w', ensure=True)
            appending = False

        try:
            csvfile = csv.writer(outputfile)
            if not appending:
                csvfile.writerow(('version', 'feature', 'test', 'provider', 'iterations', 'minimum',
                    'average', 'median', 'maximum', 'stddev', '90th', '99th'))
            csvfile.writerow((ver, feature, test, provider, len(values), minimum, average, median,
                maximum, stddev, percentile90, percentile99))
        finally:
            outputfile.close()

        logger.info('Stats (min/avg/med/max/stddev/90/99): {}'.format('/'.join([str(a)
            for a in [minimum, average, median, maximum, stddev, percentile90, percentile99]])))


def log_benchmark(benchmark_values):
    """Logs benchmark_timing values into benchmark statistics/output file."""
    logger.debug('Logging Values: {}'.format(benchmark_values))
    for feature in benchmark_values.keys():
        for test in benchmark_values[feature].keys():
            for provider in benchmark_values[feature][test].keys():
                for measurement in benchmark_values[feature][test][provider].keys():
                    log_benchmark_statistics(benchmark_values[feature][test][provider][measurement],
                        feature, test, provider, measurement)


def log_grafana_url(from_ts):
    to_ts = int(time.time() * 1000)
    if 'grafana' in perf_tests:
        g_ip = perf_tests['grafana']['ip_address']
        g_port = perf_tests['grafana']['port']
    else:
        g_ip = 'unset'
        g_port = '3000'
    if 'appliance_vm_name' not in env:
        node_name = 'undefined'
    else:
        node_name = env['appliance_vm_name'].replace('.', '')
    dash_name = 'cfme-general-system-performance'
    grafana_url = 'http://{}:{}/dashboard/db/{}?from={}&to={}&var-Node={}'.format(
        g_ip, g_port, dash_name, from_ts, to_ts, node_name)
    logger.info('Grafana URL: {}'.format(grafana_url))


def parse_benchmark_array(output, feature, test, provider):
    """Used with feature benchmarks to parse timing values from a command that was benchmarked with
    multiple iterations and thus created a ruby array of timing values.  Currently only the trailing
    ruby array output is parsed."""
    output_line = output.strip().split('\n')[-1]
    output_line = output_line.replace(']', '').replace('[', '')
    timings = [float(timing) for timing in output_line.split(',')]
    log_benchmark_statistics(timings, feature, test, provider, 'timing')


def parse_benchmark_output(output, feature, test, provider_name, iteration, benchmark_measurements):
    """Parses output (Memory, GC.count, Pid, Timing) from the benchmarks run under rails console:

    Format:
    RSS_Memory_start, RSS_Memory_End, RSS_Memory_change
    Virt_Memory_start, Virt_Memory_End, Virt_Memory_change
    Starting GC.stat Hash
    Ending GC.stat Hash
    Process.pid
    Benchmark_timing

    """

    lines = output.strip().split('\n')
    timing = float(lines[-1])
    process_pid = lines[-2].strip()
    gc_stat_end = str(lines[-3])
    gc_stat_start = str(lines[-4])
    gc_stat = gc_stat_start + '\n' + gc_stat_end
    v_memory = map(int, lines[-5].split(','))
    rss_memory = map(int, lines[-6].split(','))

    logger.info('Iteration: {}, Timing: {}, {}'.format(iteration, timing, process_pid))
    logger.info('RSS Memory start: {}, end: {}, change: {}'.format(rss_memory[0], rss_memory[1],
        rss_memory[2]))
    logger.info('Virt Memory start: {}, end: {}, change: {}'.format(v_memory[0], v_memory[1],
        v_memory[2]))
    logger.info('GC stat start: {}'.format(gc_stat_start))
    logger.info('GC stat end: {}'.format(gc_stat_end))
    logger.info('RSS Mem Total(Console + Benchmark) Used: {} MiB'.format(
        float(rss_memory[1]) / 1024 / 1024))
    logger.info('RSS Mem Change(Benchmark) Used: {} MiB'.format(float(rss_memory[2]) / 1024 / 1024))
    logger.info('Virt Mem Total(Console + Benchmark) Used: {} MiB'.format(
        float(v_memory[1]) / 1024 / 1024))
    logger.info('Virt Mem Change(Benchmark) Used: {} MiB'.format(float(v_memory[2]) / 1024 / 1024))

    append_value(benchmark_measurements, feature, test, provider_name, 'timing', timing)
    append_value(benchmark_measurements, feature, test, provider_name, 'rss_start', rss_memory[0])
    append_value(benchmark_measurements, feature, test, provider_name, 'rss_start_MiB',
        rss_memory[0] / 1024 / 1024)
    append_value(benchmark_measurements, feature, test, provider_name, 'rss_total', rss_memory[1])
    append_value(benchmark_measurements, feature, test, provider_name, 'rss_total_MiB',
        rss_memory[1] / 1024 / 1024)
    append_value(benchmark_measurements, feature, test, provider_name, 'rss_change', rss_memory[2])
    append_value(benchmark_measurements, feature, test, provider_name, 'rss_change_MiB',
        rss_memory[2] / 1024 / 1024)
    append_value(benchmark_measurements, feature, test, provider_name, 'vmem_start', v_memory[0])
    append_value(benchmark_measurements, feature, test, provider_name, 'vmem_start_MiB',
        v_memory[0] / 1024 / 1024)
    append_value(benchmark_measurements, feature, test, provider_name, 'vmem_total', v_memory[1])
    append_value(benchmark_measurements, feature, test, provider_name, 'vmem_total_MiB',
        v_memory[1] / 1024 / 1024)
    append_value(benchmark_measurements, feature, test, provider_name, 'vmem_change', v_memory[2])
    append_value(benchmark_measurements, feature, test, provider_name, 'vmem_change_MiB',
        v_memory[2] / 1024 / 1024)
    append_value(benchmark_measurements, feature, test, provider_name, 'gc_stat', gc_stat)


def pbench_install(ssh_client):
    logger.info('Installing pbench.')
    if not str(version.current_version()) is 'master':
        ip_a = IPAppliance(urlparse(env['base_url']).netloc)
        ip_a.update_rhel(reboot=False)
    pb_int_url = perf_tests['pbench']['pbench_internal_repo_file_url']
    pb_url = perf_tests['pbench']['pbench_repo_file_url']
    configtools_url = perf_tests['pbench']['configtools_repo_file_url']
    ssh_client.run_command('wget -O /etc/yum.repos.d/pbench-internal.repo {}'.format(pb_int_url))
    ssh_client.run_command('wget -O /etc/yum.repos.d/pbench.repo {}'.format(pb_url))
    ssh_client.run_command('wget -O /etc/yum.repos.d/configtools.repo {}'.format(configtools_url))
    ssh_client.run_command('yum install -y --nogpgcheck pbench-agent-internal')
    # 5.5 has smaller /var directory, lets use the /repo directory
    if ip_a.version >= "5.5":
        ssh_client.run_command('mkdir -p /repo/pbench-agent')
        ssh_client.run_command('mv /var/lib/pbench-agent/* /repo/pbench-agent')
        ssh_client.run_command('rm -rf /var/lib/pbench-agent')
        ssh_client.run_command('ln -s /repo/pbench-agent /var/lib/pbench-agent')


def pbench_start(ssh_client, test_run, test_iteration, sleep_time=5, tool_interval=1):
    if not perf_tests['pbench']['disable']:
        test_iteration = test_iteration.replace(' ', '_')
        exit_status, output = ssh_client.run_command('test -e /opt/pbench-agent/VERSION')
        if exit_status > 0:
            pbench_install(ssh_client)
        else:
            logger.debug('pbench already installed.')
        logger.info('Starting pbench')
        ssh_client.run_command('clear-tools; kill-tools')
        ssh_client.run_command('register-tool --name=mpstat -- --interval={}'.format(tool_interval))
        ssh_client.run_command('register-tool --name=iostat -- --interval={}'.format(tool_interval))
        ssh_client.run_command('register-tool --name=sar -- --interval={}'.format(tool_interval))
        ssh_client.run_command('register-tool --name=vmstat -- --interval={}'.format(tool_interval))
        ssh_client.run_command(
            'register-tool --name=pidstat -- --interval={}'.format(tool_interval))
        ssh_client.run_command('mkdir -p /var/lib/pbench-agent/{}/{}'.format(test_run,
            test_iteration))
        ssh_client.run_command('start-tools --dir=/var/lib/pbench-agent/{}/{} '
            '--iteration={}'.format(test_run, test_iteration, test_iteration))
        logger.debug('pbench sleeping: {}'.format(sleep_time))
        time.sleep(sleep_time)
    else:
        logger.debug('pbench start-tools skipped due to [\'pbench\'][\'disable\'] set to true.')


def pbench_stop(ssh_client, test_run, test_iteration, sleep_time=5, results=''):
    if not perf_tests['pbench']['disable']:
        test_iteration = test_iteration.replace(' ', '_')
        logger.debug('pbench sleeping: {}'.format(sleep_time))
        time.sleep(sleep_time)
        logger.info('Stopping pbench.')
        ssh_client.run_command('stop-tools --dir=/var/lib/pbench-agent/{}/{} --iteration={}'.format(
            test_run, test_iteration, test_iteration))
        logger.info('Adding Results to pbench directory tree')
        with log_path.join('benchmark_results').open('w') as pbench_results:
            pbench_results.write(results)
        dest_directory = '/var/lib/pbench-agent/{}/{}/'.format(test_run, test_iteration)
        ssh_client.put_file(str(log_path.join('benchmark_results')), dest_directory)
        ssh_client.put_file(str(log_path.join('appliance_version')), dest_directory)
        os.remove(str(log_path.join('benchmark_results')))
        logger.info('Post processing pbench.')
        ssh_client.run_command('postprocess-tools --dir=/var/lib/pbench-agent/{}/{}'
            ' --iteration={}'.format(test_run, test_iteration, test_iteration))
    else:
        logger.debug('pbench stop-tools skipped due to [\'pbench\'][\'disable\'] set to true.')


def pbench_move_results(ssh_client):
    if not perf_tests['pbench']['disable']:
        logger.info('Moving pbench results.')
        ssh_client.run_command('move-results', timeout=None)
    else:
        logger.debug('pbench move-results skipped due to [\'pbench\'][\'disable\'] set to true.')


def refresh_provider_via_rails(ssh_client, provider_name):
    """Executes a EmsRefresh on a specific provider via the rails console.  Provider must be added
    prior to executing."""
    command = ('e = ExtManagementSystem.find_by_name(\'' + provider_name + '\');'
               'EmsRefresh.refresh e')
    ssh_client.run_rails_console(command, timeout=None)


def set_cap_and_util_all_via_rails(ssh_client):
    """Turns on Collect for All Clusters and Collect for all Datastores without using the UI."""
    command = ('Metric::Targets.perf_capture_always = {:storage=>true, :host_and_cluster=>true};')
    ssh_client.run_rails_console(command, timeout=None)


def set_full_refresh_threshold(threshold=100):
    """Adjusts the full_refresh_threshold on an appliance.  The current default is 100."""
    logger.info('Setting full_refresh_threshold on appliance to {}'.format(threshold))
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['ems_refresh']['full_refresh_threshold'] = threshold
    ip_a.set_yaml_config("vmdb", yaml)


def set_rails_loglevel(level, validate_against_worker='MiqUiWorker'):
    """Sets the logging level for level_rails and detects when change occured."""
    ui_worker_pid = '#{}'.format(get_worker_pid(validate_against_worker))

    logger.info('Setting log level_rails on appliance to {}'.format(level))
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    if not str(yaml['log']['level_rails']).lower() == level.lower():
        logger.info('Opening /var/www/miq/vmdb/log/evm.log for tail')
        evm_tail = SSHTail('/var/www/miq/vmdb/log/evm.log')
        evm_tail.set_initial_file_end()

        yaml['log']['level_rails'] = level
        ip_a.set_yaml_config("vmdb", yaml)

        attempts = 0
        detected = False
        while (not detected and attempts < 60):
            logger.debug('Attempting to detect log level_rails change: {}'.format(attempts))
            for line in evm_tail:
                if ui_worker_pid in line:
                    if 'Log level for production.log has been changed to' in line:
                        # Detects a log level change but does not validate the log level
                        logger.info('Detected change to log level for production.log')
                        detected = True
                        break
            time.sleep(1)  # Allow more log lines to accumulate
            attempts += 1
        if not (attempts < 60):
            # Note the error in the logger but continue as the appliance could be slow at logging
            # that the log level changed
            logger.error('Could not detect log level_rails change.')
    else:
        logger.info('Log level_rails already set to {}'.format(level))


def set_vim_broker_memory_threshold(memory_value='2 GB'):
    """Sets VIMBroker's Memory threshold"""
    sel.force_navigate("cfg_settings_currentserver_workers")
    fill(
        connection_broker,
        dict(value=memory_value),
        action=form_buttons.save
    )


def set_generic_worker_memory_threshold(memory_value='400.megabytes'):
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['workers']['worker_base'][':queue_worker_base'][':generic_worker'][':memory_threshold'] = \
        memory_value
    ip_a.set_yaml_config("vmdb", yaml)


def set_priority_worker_memory_threshold(memory_value='400.megabytes'):
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['workers']['worker_base'][':queue_worker_base'][':priority_worker'][':memory_threshold'] =\
        memory_value
    ip_a.set_yaml_config("vmdb", yaml)


def set_refresh_core_worker_memory_threshold(memory_value='400.megabytes'):
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    if version.current_version().is_in_series('5.6'):
        yaml[':workers'][':worker_base'][':ems_refresh_core_worker'][':memory_threshold'] = \
            memory_value
    else:
        yaml['workers']['worker_base'][':ems_refresh_core_worker'][':memory_threshold'] = \
            memory_value
    yaml['workers']['worker_base'][':ems_refresh_core_worker'][':memory_threshold'] = memory_value
    ip_a.set_yaml_config("vmdb", yaml)


def set_replication_worker_memory_threshold(memory_value='200.megabytes'):
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['workers']['worker_base'][':replication_worker'][':memory_threshold'] = memory_value
    ip_a.set_yaml_config("vmdb", yaml)


def set_schedule_worker_memory_threshold(memory_value='300.megabytes'):
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['workers']['worker_base'][':schedule_worker'][':memory_threshold'] = memory_value
    ip_a.set_yaml_config("vmdb", yaml)


# Benchmark role settings:
def set_server_roles_benchmark():
    """Sets server roles after fixtures run for specific feature benchmarks."""
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['server']['role'] = ('ems_operations,user_interface')
    ip_a.set_yaml_config("vmdb", yaml)


def set_server_roles_benchmark_event():
    """Sets server roles after fixtures run for eventing feature benchmarks."""
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['server']['role'] = ('automate,ems_operations,user_interface')
    ip_a.set_yaml_config("vmdb", yaml)


def set_server_roles_benchmark_smartstate():
    """Sets server roles after fixtures run for smartstate feature benchmarks."""
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['server']['role'] = ('smartproxy,smartstate,ems_operations,user_interface')
    ip_a.set_yaml_config("vmdb", yaml)


# Workload role settings:
def set_server_roles_workload_idle():
    """Turns on all server roles used for idle workload including database_synchronization role."""
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['server']['role'] = ('automate,database_operations,database_synchronization,'
        'ems_inventory,ems_metrics_collector,ems_metrics_coordinator,ems_metrics_processor,'
        'ems_operations,event,notifier,reporting,rhn_mirror,scheduler,smartproxy,smartstate,'
        'user_interface,web_services')
    ip_a.set_yaml_config("vmdb", yaml)


def set_server_roles_workload_cap_and_util():
    """Sets server roles used for all C&U workloads."""
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['server']['role'] = ('automate,database_operations,ems_inventory,ems_metrics_collector'
        ',ems_metrics_coordinator,ems_metrics_processor,ems_operations,event,notifier,reporting'
        ',scheduler,user_interface,web_services')
    ip_a.set_yaml_config("vmdb", yaml)


def set_server_roles_workload_smartstate():
    """Sets server roles for Smartstate workload."""
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['server']['role'] = ('automate,database_operations,ems_inventory,ems_operations,event'
        ',notifier,reporting,scheduler,smartproxy,smartstate,user_interface,web_services')
    ip_a.set_yaml_config("vmdb", yaml)


def set_server_roles_workload_provisioning():
    """Sets server roles for Provisioning workload."""
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['server']['role'] = ('automate,database_operations,ems_inventory,ems_operations,event'
        ',notifier,reporting,scheduler,user_interface,web_services')
    ip_a.set_yaml_config("vmdb", yaml)


def set_server_roles_workload_all():
    """Turns on all server roles used for all workload memory measurement benchmark. Does not turn
    on datbase_synchronization role."""
    ip_a = IPAppliance(urlparse(env['base_url']).netloc)
    yaml = ip_a.get_yaml_config('vmdb')
    yaml['server']['role'] = ('automate,database_operations,ems_inventory,ems_metrics_collector'
        ',ems_metrics_coordinator,ems_metrics_processor,ems_operations,event,notifier,reporting'
        ',rhn_mirror,scheduler,smartproxy,smartstate,user_interface,web_services')
    ip_a.set_yaml_config("vmdb", yaml)


def start_evm_wait_for_ui(ssh_client):
    exit_status, output = ssh_client.run_command('service evmserverd start')
    logger.info('Waiting for WebUI.')
    pytest.store.current_appliance.wait_for_web_ui()
    quit()  # Closes browser out


def wait_for_vim_broker():
    """Waits for the VIMBroker worker to be ready by tailing evm.log for:

    'INFO -- : MIQ(VimBrokerWorker) Starting broker server...Complete'

    Verified works with 5.6 appliances.
    """
    logger.info('Opening /var/www/miq/vmdb/log/evm.log for tail')
    evm_tail = SSHTail('/var/www/miq/vmdb/log/evm.log')
    evm_tail.set_initial_file_end()

    attempts = 0
    detected = False
    max_attempts = 60
    while (not detected and attempts < max_attempts):
        logger.debug('Attempting to detect VimBrokerWorker ready: {}'.format(attempts))
        for line in evm_tail:
            if 'VimBrokerWorker' in line:
                if 'Starting broker server...Complete' in line:
                    logger.info('Detected VimBrokerWorker is ready.')
                    detected = True
                    break
        time.sleep(10)  # Allow more log lines to accumulate
        attempts += 1
    if not (attempts < max_attempts):
        logger.error('Could not detect VimBrokerWorker ready in 600s.')
