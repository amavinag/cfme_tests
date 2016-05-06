# -*- coding: utf-8 -*
"""UI performance tests on Services."""
from cfme.fixtures import pytest_selenium as sel
from utils.conf import perf_tests
from utils.pagestats import analyze_page_stat
from utils.pagestats import navigate_accordions
from utils.pagestats import pages_to_csv
from utils.pagestats import pages_to_statistics_csv
from utils.pagestats import perf_click
from utils.pagestats import standup_perf_ui
from utils.perf import log_grafana_url
from collections import OrderedDict
import time
import pytest
import re

my_services_filters = [
    re.compile(r'^POST \"\/service\/tree_select\/\?id\=[A-Za-z0-9\-\_]*\"$')]

catalogs_filters = [
    re.compile(r'^POST \"\/catalog\/tree_select\/\?id\=[A-Za-z0-9\-\_]*\"$')]

workloads_filters = [
    re.compile(r'^POST \"\/vm_or_template\/tree_select\/\?id\=[A-Za-z0-9\-\_]*\"$')]


@pytest.mark.perf_ui_services
@pytest.mark.usefixtures("cfme_log_level_rails_debug")
def test_perf_ui_services_my_services(ui_worker_pid, soft_assert):
    from_ts = int(time.time() * 1000)
    pages, prod_tail = standup_perf_ui(ui_worker_pid)

    pages.extend(perf_click(ui_worker_pid, prod_tail, True, sel.force_navigate,
        'my_services'))

    services_acc = OrderedDict((('Services', 'services'), ))

    pages.extend(navigate_accordions(services_acc, 'my_services', (perf_tests['ui']['page_check']
        ['services']['my_services']), ui_worker_pid, prod_tail))

    pages_to_csv(pages, 'perf_ui_services_my_services.csv')
    pages_to_statistics_csv(pages, my_services_filters, 'ui-statistics.csv')
    analyze_page_stat(pages)
    log_grafana_url(from_ts)


@pytest.mark.perf_ui_services
@pytest.mark.usefixtures("cfme_log_level_rails_debug")
def test_perf_ui_services_catalogs(ui_worker_pid, soft_assert):
    from_ts = int(time.time() * 1000)
    pages, prod_tail = standup_perf_ui(ui_worker_pid)

    pages.extend(perf_click(ui_worker_pid, prod_tail, True, sel.force_navigate,
        'services_catalogs'))

    catalogs_acc = OrderedDict((('Catalog Items', 'catalog_items'), ('Catalogs', 'catalogs'),
        ('Service Catalogs', 'service_catalogs')))

    pages.extend(navigate_accordions(catalogs_acc, 'services_catalogs',
        perf_tests['ui']['page_check']['services']['catalogs'], ui_worker_pid, prod_tail))

    pages_to_csv(pages, 'perf_ui_services_catalogs.csv')
    pages_to_statistics_csv(pages, my_services_filters, 'ui-statistics.csv')
    analyze_page_stat(pages)
    log_grafana_url(from_ts)


@pytest.mark.perf_ui_services
@pytest.mark.usefixtures("cfme_log_level_rails_debug")
def test_perf_ui_services_workloads(ui_worker_pid, soft_assert):
    from_ts = int(time.time() * 1000)
    pages, prod_tail = standup_perf_ui(ui_worker_pid)

    pages.extend(perf_click(ui_worker_pid, prod_tail, True, sel.force_navigate,
        'services_workloads'))

    workloads_acc = OrderedDict((('VMs & Instances', 'vms_instances'),
        ('Templates & Images', 'templates_images')))

    pages.extend(navigate_accordions(workloads_acc, 'services_workloads',
        perf_tests['ui']['page_check']['services']['workloads'], ui_worker_pid, prod_tail))

    pages_to_csv(pages, 'perf_ui_services_workloads.csv')
    pages_to_statistics_csv(pages, my_services_filters, 'ui-statistics.csv')
    analyze_page_stat(pages)
    log_grafana_url(from_ts)
