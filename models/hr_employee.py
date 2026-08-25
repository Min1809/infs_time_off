# -*- coding: utf-8 -*-

from datetime import datetime

from odoo import fields, models


class HolidaysEmployee(models.Model):
    _inherit = "hr.employee"

    def _get_consumed_leaves(self, leave_types, target_date=False, ignore_future=False):
        """Exclude expired allocations from the computed balances.

        The native implementation keeps the remaining leaves of expired
        allocations in the per-allocation dictionaries and lets each caller
        filter them out. This override zeroes them at the source so every
        consumer (leave type balance, employee counters, dashboard) excludes
        allocations whose validity period has already ended.
        """
        allocations_leaves_consumed, extra = super()._get_consumed_leaves(
            leave_types, target_date, ignore_future)

        if not target_date:
            target_date = fields.Date.today()
        elif isinstance(target_date, str):
            target_date = fields.Date.from_string(target_date)
        elif isinstance(target_date, datetime):
            target_date = target_date.date()

        for employee in allocations_leaves_consumed:
            for leave_type in allocations_leaves_consumed[employee]:
                for allocation, data in allocations_leaves_consumed[employee][leave_type].items():
                    if allocation and allocation.date_to and allocation.date_to < target_date:
                        data['virtual_remaining_leaves'] = 0.0
                        data['remaining_leaves'] = 0.0
                        data['accrual_bonus'] = 0.0

        return allocations_leaves_consumed, extra

    def _get_remaining_leaves(self):
        """Return the remaining leaves per employee, excluding expired allocations.

        Overrides the native SQL which sums every validated allocation without
        taking ``date_to`` into account, so expired allocations (e.g. carried-over
        allocations with a validity period) are not part of the total balance.
        """
        self._cr.execute("""
            SELECT
                sum(h.number_of_days) AS days,
                h.employee_id
            FROM
                (
                    SELECT holiday_status_id, number_of_days,
                        state, employee_id, date_to
                    FROM hr_leave_allocation
                    UNION ALL
                    SELECT holiday_status_id, (number_of_days * -1) as number_of_days,
                        state, employee_id, NULL AS date_to
                    FROM hr_leave
                ) h
                join hr_leave_type s ON (s.id = h.holiday_status_id)
            WHERE
                s.active = true AND h.state = 'validate' AND
                s.requires_allocation = 'yes' AND
                (h.date_to IS NULL OR h.date_to >= %s) AND
                h.employee_id in %s
            GROUP BY h.employee_id""", (fields.Date.today(), tuple(self.ids)))
        return {row['employee_id']: row['days'] for row in self._cr.dictfetchall()}
