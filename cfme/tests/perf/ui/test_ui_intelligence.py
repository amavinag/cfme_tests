# -*- coding: utf-8 -*
"""UI performance tests on Intelligence."""
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

reports_filters = [
    re.compile(r'^POST \"\/report\/tree_select\/\?id\=[A-Za-z0-9\-\_]*\"$')]

chargeback_filters = [
    re.compile(r'^POST \"\/chargeback\/tree_select\/\?id\=[A-Za-z0-9\-\_]*\"$')]


@pytest.mark.meta(blockers=[1174300])
@pytest.mark.perf_ui_intelligence
@pytest.mark.usefixtures("cfme_log_level_rails_debug")
def test_perf_ui_intelligence_reports(ui_worker_pid, soft_assert):
# def test_perf_ui_intelligence_reports():
    # tree_contents = [[u'All Dashboards', [u'Default Dashboard (default)', [u'All Groups', [u'EvmGroup-administrator', u'EvmGroup-approver']], u'Non-Default']]]
    # from utils.pagestats import generate_tree_paths
    # from utils.log import logger
    # paths = []
    # generate_tree_paths(tree_contents, [], paths)
    # logger.debug('tree_contents: {}'.format(tree_contents))
    # logger.debug('paths: {}'.format(paths))
    # logger.info('Found {} tree paths'.format(len(paths)))
    from_ts = int(time.time() * 1000)
    pages, prod_tail = standup_perf_ui(ui_worker_pid)

    pages.extend(perf_click(ui_worker_pid, prod_tail, True, sel.force_navigate,
        'reports'))

    reports_acc = OrderedDict((('Saved Reports', 'saved_reports'), ('Reports', 'reports'),
        ('Schedules', 'schedules'), ('Dashboards', 'dashboards'),
        ('Dashboard Widgets', 'dashboard_widgets'), ('Edit Report Menus', 'edit_report_menus'),
        ('Import/Export', 'import_export')))

    # reports_acc = OrderedDict()
    # reports_acc['Dashboards'] = 'dashboards'

    pages.extend(navigate_accordions(reports_acc, 'reports', (perf_tests['ui']['page_check']
        ['intelligence']['reports']), ui_worker_pid, prod_tail))

    pages_to_csv(pages, 'perf_ui_intelligence_reports.csv')
    pages_to_statistics_csv(pages, reports_filters, 'ui-statistics.csv')
    analyze_page_stat(pages)
    log_grafana_url(from_ts)


@pytest.mark.perf_ui_intelligence
@pytest.mark.usefixtures("cfme_log_level_rails_debug")
def test_perf_ui_intelligence_chargeback(ui_worker_pid, soft_assert):
    from_ts = int(time.time() * 1000)
    pages, prod_tail = standup_perf_ui(ui_worker_pid)

    pages.extend(perf_click(ui_worker_pid, prod_tail, True, sel.force_navigate,
        'chargeback'))

    charge_acc = OrderedDict((('Reports', 'reports'), ('Rates', 'rates'),
        ('Assignments', 'assignments')))

    pages.extend(navigate_accordions(charge_acc, 'chargeback', (perf_tests['ui']['page_check']
        ['intelligence']['chargeback']), ui_worker_pid, prod_tail))

    pages_to_csv(pages, 'perf_ui_intelligence_chargeback.csv')
    pages_to_statistics_csv(pages, chargeback_filters, 'ui-statistics.csv')
    analyze_page_stat(pages)
    log_grafana_url(from_ts)
