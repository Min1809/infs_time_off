# -*- coding: utf-8 -*-

from datetime import date

from freezegun import freeze_time

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from odoo.addons.hr_holidays.tests.common import TestHrHolidaysCommon


@tagged('post_install', '-at_install', 'accruals')
class TestCarryoverValidity(TestHrHolidaysCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.leave_type = cls.env['hr.leave.type'].create({
            'name': 'Paid Time Off - Carryover',
            'time_type': 'leave',
            'requires_allocation': 'yes',
            'allocation_validation_type': 'officer',
        })

    def _create_plan(self, carryover_has_validity, carryover_validity_count=2,
                     carryover_validity_type='month', postpone_max_days=10):
        return self.env['hr.leave.accrual.plan'].with_context(tracking_disable=True).create({
            'name': 'Accrual Plan For Carryover Test',
            'carryover_date': 'year_start',
            'level_ids': [(0, 0, {
                'added_value_type': 'day',
                'start_count': 1,
                'start_type': 'day',
                'added_value': 1,
                'frequency': 'daily',
                'cap_accrued_time': True,
                'maximum_leave': 1000,
                'action_with_unused_accruals': 'maximum',
                'postpone_max_days': postpone_max_days,
                'carryover_has_validity': carryover_has_validity,
                'carryover_validity_count': carryover_validity_count,
                'carryover_validity_type': carryover_validity_type,
            })],
        })

    def _create_allocation(self, accrual_plan):
        allocation = self.env['hr.leave.allocation'].with_user(self.user_hrmanager_id).with_context(tracking_disable=True).create({
            'name': 'Accrual allocation for employee',
            'date_from': date(2024, 11, 1),
            'accrual_plan_id': accrual_plan.id,
            'employee_id': self.employee_emp.id,
            'holiday_status_id': self.leave_type.id,
            'number_of_days': 0,
            'allocation_type': 'accrual',
        })
        allocation.action_validate()
        return allocation

    def test_carryover_creates_validity_allocation(self):
        accrual_plan = self._create_plan(True)
        with freeze_time('2024-11-01'):
            allocation = self._create_allocation(accrual_plan)
        with freeze_time('2025-01-02'):
            allocation._process_accrual_plans(date(2025, 1, 2), log=False)

        carryover = self.env['hr.leave.allocation'].search([
            ('carryover_source_allocation_id', '=', allocation.id),
        ])
        self.assertEqual(len(carryover), 1)
        self.assertEqual(carryover.state, 'validate')
        self.assertEqual(carryover.allocation_type, 'regular')
        self.assertAlmostEqual(carryover.number_of_days, 10.0, 2)
        self.assertEqual(carryover.date_from, date(2025, 1, 1))
        self.assertEqual(carryover.date_to, date(2025, 2, 28))
        # Source keeps only consumed leave (0) + the single day accrued after carry-over.
        self.assertAlmostEqual(allocation.number_of_days, 1.0, 2)

    def test_native_expiry_removes_carried_days(self):
        accrual_plan = self._create_plan(True)
        with freeze_time('2024-11-01'):
            allocation = self._create_allocation(accrual_plan)
        with freeze_time('2025-01-02'):
            allocation._process_accrual_plans(date(2025, 1, 2), log=False)

        # Before expiry: source (1 day) + carried (10 days) = 11 days.
        data = self.leave_type.get_allocation_data(self.employee_emp, '2025-02-01')
        self.assertAlmostEqual(data[self.employee_emp][0][1]['remaining_leaves'], 11.0, 1)

        # After the carried allocation's date_to (2025-03-01) only the source remains.
        data = self.leave_type.get_allocation_data(self.employee_emp, '2025-04-01')
        self.assertAlmostEqual(data[self.employee_emp][0][1]['remaining_leaves'], 1.0, 1)

    def test_postpone_max_days_cap_applies(self):
        accrual_plan = self._create_plan(True, postpone_max_days=5)
        with freeze_time('2024-11-01'):
            allocation = self._create_allocation(accrual_plan)
        with freeze_time('2025-01-02'):
            allocation._process_accrual_plans(date(2025, 1, 2), log=False)

        carryover = self.env['hr.leave.allocation'].search([
            ('carryover_source_allocation_id', '=', allocation.id),
        ])
        self.assertEqual(len(carryover), 1)
        self.assertAlmostEqual(carryover.number_of_days, 5.0, 2)

    def test_disabled_validity_keeps_native_behavior(self):
        accrual_plan = self._create_plan(False)
        with freeze_time('2024-11-01'):
            allocation = self._create_allocation(accrual_plan)
        with freeze_time('2025-01-02'):
            allocation._process_accrual_plans(date(2025, 1, 2), log=False)

        carryover = self.env['hr.leave.allocation'].search([
            ('carryover_source_allocation_id', '=', allocation.id),
        ])
        self.assertEqual(len(carryover), 0)
        # Native behavior: min(60, 10) + 0 = 10 at carry-over, then +1 day after = 11.
        self.assertAlmostEqual(allocation.number_of_days, 11.0, 2)

    def test_constraint_validity_count_positive(self):
        accrual_plan = self._create_plan(False, carryover_validity_count=0)
        level = accrual_plan.level_ids
        with self.assertRaises(ValidationError):
            level.write({
                'carryover_has_validity': True,
                'carryover_validity_count': 0,
            })

    def test_employee_remaining_leaves_excludes_expired(self):
        accrual_plan = self._create_plan(True)
        with freeze_time('2024-11-01'):
            allocation = self._create_allocation(accrual_plan)
        with freeze_time('2025-01-02'):
            allocation._process_accrual_plans(date(2025, 1, 2), log=False)

        self.employee_emp.invalidate_recordset(['remaining_leaves', 'leaves_count'])
        with freeze_time('2025-04-01'):
            self.assertAlmostEqual(self.employee_emp.remaining_leaves, 1.0, 2)

    def test_level_transition_splits_validity_allocation(self):
        accrual_plan = self.env['hr.leave.accrual.plan'].with_context(tracking_disable=True).create({
            'name': 'Accrual Plan - Level Transition Validity',
            'transition_mode': 'immediately',
            'level_ids': [
                (0, 0, {
                    'added_value_type': 'day',
                    'start_count': 0,
                    'start_type': 'day',
                    'added_value': 5,
                    'frequency': 'daily',
                    'cap_accrued_time': True,
                    'maximum_leave': 20,
                    'action_with_unused_accruals': 'maximum',
                    'postpone_max_days': 20,
                    'carryover_has_validity': True,
                    'carryover_validity_count': 1,
                    'carryover_validity_type': 'day',
                }),
                (0, 0, {
                    'added_value_type': 'day',
                    'start_count': 1,
                    'start_type': 'day',
                    'added_value': 2,
                    'frequency': 'daily',
                    'cap_accrued_time': True,
                    'maximum_leave': 100,
                    'action_with_unused_accruals': 'maximum',
                    'postpone_max_days': 20,
                    'carryover_has_validity': True,
                    'carryover_validity_count': 10,
                    'carryover_validity_type': 'day',
                }),
            ],
        })
        with freeze_time('2026-08-23'):
            allocation = self.env['hr.leave.allocation'].with_user(self.user_hrmanager_id).with_context(tracking_disable=True).create({
                'name': 'Accrual allocation for employee',
                'date_from': date(2026, 8, 23),
                'accrual_plan_id': accrual_plan.id,
                'employee_id': self.employee_emp.id,
                'holiday_status_id': self.leave_type.id,
                'number_of_days': 0,
                'allocation_type': 'accrual',
            })
            allocation.action_validate()
        with freeze_time('2026-08-25'):
            allocation._process_accrual_plans(date(2026, 8, 25), log=False)

        carryover = self.env['hr.leave.allocation'].search([
            ('carryover_source_allocation_id', '=', allocation.id),
        ])
        self.assertEqual(len(carryover), 1)
        self.assertAlmostEqual(carryover.number_of_days, 5.0, 2)
        self.assertEqual(carryover.date_from, date(2026, 8, 24))
        self.assertEqual(carryover.date_to, date(2026, 8, 24))
        # Only the 2 days accrued by the second level on 25 Aug remain.
        self.assertAlmostEqual(allocation.number_of_days, 2.0, 2)
        # On 25 Aug the first level's 5 days are already expired.
        data = self.leave_type.get_allocation_data(self.employee_emp, '2026-08-25')
        self.assertAlmostEqual(data[self.employee_emp][0][1]['remaining_leaves'], 2.0, 1)

    def test_hourly_yearly_carryover_with_validity(self):
        leave_type_hour = self.env['hr.leave.type'].create({
            'name': 'Paid Time Off - Hours',
            'time_type': 'leave',
            'requires_allocation': 'yes',
            'allocation_validation_type': 'officer',
            'request_unit': 'hour',
        })
        accrual_plan = self.env['hr.leave.accrual.plan'].with_context(tracking_disable=True).create({
            'name': 'Accrual Plan - Yearly Hourly',
            'carryover_date': 'other',
            'carryover_month': 'dec',
            'carryover_day': 31,
            'level_ids': [(0, 0, {
                'added_value_type': 'hour',
                'start_count': 0,
                'start_type': 'day',
                'added_value': 0.21918,
                'frequency': 'daily',
                'cap_accrued_time': True,
                'maximum_leave': 80,
                'action_with_unused_accruals': 'maximum',
                'postpone_max_days': 80,
                'carryover_has_validity': True,
                'carryover_validity_count': 12,
                'carryover_validity_type': 'month',
            })],
        })
        with freeze_time('2020-01-01'):
            allocation = self.env['hr.leave.allocation'].with_user(self.user_hrmanager_id).with_context(tracking_disable=True).create({
                'name': 'Accrual allocation - hours',
                'date_from': date(2020, 1, 1),
                'accrual_plan_id': accrual_plan.id,
                'employee_id': self.employee_emp.id,
                'holiday_status_id': leave_type_hour.id,
                'number_of_days': 0,
                'allocation_type': 'accrual',
            })
            allocation.action_validate()
        with freeze_time('2020-12-31'):
            allocation._process_accrual_plans(date(2020, 12, 31), log=False)

        carryover = self.env['hr.leave.allocation'].search([
            ('carryover_source_allocation_id', '=', allocation.id),
        ])
        self.assertEqual(len(carryover), 1)
        # 80 hours = 10 days at 8h/day, capped by the level.
        self.assertAlmostEqual(carryover.number_of_days, 10.0, 2)
        self.assertEqual(carryover.date_from, date(2020, 12, 31))
        # Valid for 12 months: available through 30 Dec 2021.
        self.assertEqual(carryover.date_to, date(2021, 12, 30))
        # The source accrual allocation is reset for the next year.
        self.assertAlmostEqual(allocation.number_of_days, 0.0, 2)
