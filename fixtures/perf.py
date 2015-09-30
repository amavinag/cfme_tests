"""Fixtures specifically for performance tests."""
from utils.appliance import IPAppliance
from utils.browser import quit
from utils.log import logger
from utils.perf import get_benchmark_providers
from utils.perf import get_worker_pid
from utils.perf import pbench_move_results
from utils.perf import set_rails_loglevel
from utils.perf import set_vim_broker_memory_threshold
from utils.ssh import SSHClient
from utils import db
from utils import providers
from utils import version
import pytest


@pytest.fixture(scope='module')
def benchmark_providers():
    """Adds all benchmark providers to an appliance."""
    bench_providers = get_benchmark_providers()
    for provider in bench_providers:
        providers.setup_provider(provider, validate=False)


@pytest.yield_fixture(scope='session')
def cfme_log_level_rails_debug():
    """Sets the log level for rails to debug and back to info."""
    set_rails_loglevel('debug')
    yield
    set_rails_loglevel('info')


@pytest.fixture(scope='function')
def clean_appliance(wait_for_ui=True):
    """Cleans an appliance database back to original state"""
    logger.info("Cleaning appliance")
    ssh_client = SSHClient()
    ssh_client.run_command('service evmserverd stop')
    ssh_client.run_command('sync; sync; echo 3 > /proc/sys/vm/drop_caches')
    ssh_client.run_command('service collectd stop')
    ssh_client.run_command('service {}-postgresql restart'.format(db.scl_name()))
    # 5.6 requires DISABLE_DATABASE_ENVIRONMENT_CHECK=1
    ssh_client.run_command(
        'cd /var/www/miq/vmdb;DISABLE_DATABASE_ENVIRONMENT_CHECK=1 bin/rake evm:db:reset')
    ssh_client.run_rake_command('db:seed')
    ssh_client.run_command('service collectd start')
    exit_status, output = ssh_client.run_command('service evmserverd start')
    if wait_for_ui:
        logger.info("Waiting for WebUI.")
        pytest.store.current_appliance.wait_for_web_ui()
        quit()  # Closes browser out to avoid error with future UI navigation


@pytest.fixture(scope="function")
def clear_all_caches():
    """Clears appliance OS caches and clears postgres cache through postgres restart"""
    clear_os_caches()
    clear_postgres_cache()


@pytest.fixture(scope="function")
def clear_os_caches():
    """Clears appliance OS caches"""
    logger.info('Dropping OS caches...')
    ssh_client = SSHClient()
    exit_status, output = ssh_client.run_command('sync; sync; echo 3 > /proc/sys/vm/drop_caches')


@pytest.fixture(scope="function")
def clear_postgres_cache():
    """Clears postgres cache through postgres restart"""
    logger.info('Dropping Postgres cache...')
    ssh_client = SSHClient()
    ssh_client.run_command('service collectd stop')
    ssh_client.run_command('service {}-postgresql restart'.format(db.scl_name()))
    ssh_client.run_command('service collectd start')


@pytest.yield_fixture(scope='module')
def end_pbench_move_results():
    """Fixture that ensures benchmark timings are written/appended to benchmark-statistics.csv."""
    yield
    ssh_client = SSHClient()
    pbench_move_results(ssh_client)


@pytest.yield_fixture(scope='module')
def patch_broker_cache_scope():
    """Fixture for patching VimBrokerWorker's cache scope to cache_scope_ems_refresh regardless of
    whether Inventory role is enabled."""
    set_patch_broker_cache_scope(True)
    yield
    set_patch_broker_cache_scope(False)


@pytest.yield_fixture(scope='module')
def patch_rails_console_use_vim_broker():
    """Fixture for patching /var/www/miq/vmdb/app/models/ems_refresh.rb to allow using vim broker
    from rails console for refresh benchmark tests."""
    set_patch_rails_console_use_vim_broker(True)
    yield
    set_patch_rails_console_use_vim_broker(False)


@pytest.yield_fixture(scope='module')
def ui_worker_pid():
    yield get_worker_pid('MiqUiWorker')


def set_patch_rails_console_use_vim_broker(use_vim_broker):
    """Patches /var/www/miq/vmdb/app/models/ems_refresh.rb to allow using vim broker from rails
    console for refresh benchmark tests."""
    ems_refresh_file = '/var/www/miq/vmdb/app/models/ems_refresh.rb'
    ssh_client = SSHClient()
    if use_vim_broker:
        ssh_client.run_command('sed -i \'s/def self.init_console(use_vim_broker = false)/'
            'def self.init_console(use_vim_broker = true)/g\' {}'.format(ems_refresh_file))
    else:
        ssh_client.run_command('sed -i \'s/def self.init_console(use_vim_broker = true)/'
            'def self.init_console(use_vim_broker = false)/g\' {}'.format(ems_refresh_file))


def set_patch_broker_cache_scope(cache_scope_ems_refresh):
    """Patches VimBrokerWorker cache scope to cache_scope_ems_refresh regardless of whether
    Inventory role is enabled.  No need to restart evmserverd service as this is performed before an
    appliance is cleaned via perf fixture clean_appliance in refresh benchmarks.
    """
    vim_broker_file = version.pick({
        version.LOWEST: '/var/www/miq/vmdb/lib/workers/vim_broker_worker.rb',
        "5.5": '/var/www/miq/vmdb/app/models/miq_vim_broker_worker/runner.rb'})
    ssh_client = SSHClient()
    if cache_scope_ems_refresh:
        ssh_client.run_command('sed -i \'s/@active_roles.include?("ems_inventory") ?'
            ' :cache_scope_ems_refresh : :cache_scope_core/@active_roles.include?("ems_inventory")'
            ' ? :cache_scope_ems_refresh : :cache_scope_ems_refresh/g\' {}'.format(vim_broker_file))
    else:
        ssh_client.run_command('sed -i \'s/@active_roles.include?("ems_inventory") ?'
            ' :cache_scope_ems_refresh : :cache_scope_ems_refresh/'
            '@active_roles.include?("ems_inventory") ? :cache_scope_ems_refresh :'
            ' :cache_scope_core/g\' {}'.format(vim_broker_file))


@pytest.yield_fixture(scope="function")
def vim_broker_3_gb_threshold():
    set_vim_broker_memory_threshold('3 GB')
    yield
    set_vim_broker_memory_threshold()
