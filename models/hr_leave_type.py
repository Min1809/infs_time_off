# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime

from odoo import api, fields, models
from odoo.addons.resource.models.utils import HOURS_PER_DAY


class HolidaysLeaveType(models.Model):
    _inherit = "hr.leave.type"

    has_max_cap = fields.Boolean(
        string="Limit Maximum Allocation",
        help="If checked, total active allocated leaves for an employee under this time off type cannot exceed Max Cap.",
    )
    max_cap = fields.Float(
        string="Max Cap",
        help="Maximum total active allocation allowed for an employee under this time off type across all allocations (direct and accrual).",
    )

    def get_allocation_data(self, employees, target_date=None):
        """Override to add duration_display and per-allocation expiry details."""
        allocation_data = super().get_allocation_data(employees, target_date)

        # Normalize target_date the same way as the original method.
        if target_date and isinstance(target_date, str):
            target_date = datetime.fromisoformat(target_date).date()
        elif target_date and isinstance(target_date, datetime):
            target_date = target_date.date()
        elif not target_date:
            target_date = fields.Date.today()

        # Recompute per-allocation consumed leaves to build expiry details.
        allocations_leaves_consumed, _extra = employees.with_context(
            ignored_leave_ids=self.env.context.get('ignored_leave_ids')
        )._get_consumed_leaves(self, target_date)

        for employee in allocation_data:
            for leave_type_data in allocation_data[employee]:
                try:
                    # leave_type_data is a tuple: (name, data_dict, requires_allocation, leave_type_id)
                    data = leave_type_data[1] if len(leave_type_data) > 1 else {}
                    leave_type_id = leave_type_data[3] if len(leave_type_data) > 3 else False
                    leave_type = self.browse(leave_type_id)

                    # Enforce max_cap on displayed remaining leaves
                    if leave_type.has_max_cap and leave_type.max_cap > 0:
                        if data.get("virtual_remaining_leaves", 0) > leave_type.max_cap:
                            data["virtual_remaining_leaves"] = leave_type.max_cap
                        if data.get("remaining_leaves", 0) > leave_type.max_cap:
                            data["remaining_leaves"] = leave_type.max_cap

                    if data.get("request_unit") in ("day", "half_day"):
                        duration = data.get("virtual_remaining_leaves", 0)
                        data["duration_display"] = self._format_days_hours(duration)
                    else:
                        # For hour-based types, keep as hours
                        data["duration_display"] = "%.2f hours" % data.get("virtual_remaining_leaves", 0)

                    # Build per-allocation validity details.
                    details = []
                    for allocation, alloc_data in allocations_leaves_consumed[employee][leave_type].items():
                        if not allocation or not allocation.date_to:
                            continue
                        if allocation.date_to < target_date:
                            continue
                        remaining = alloc_data.get('virtual_remaining_leaves', 0)
                        if remaining <= 0:
                            continue
                        if data.get("request_unit") in ("day", "half_day"):
                            remaining_display = self._format_days_hours(remaining)
                        else:
                            remaining_display = "%.2f hours" % remaining
                        details.append({
                            'remaining_display': remaining_display,
                            'expire': allocation.date_to.strftime('%d-%m-%Y'),
                        })
                    data["allocation_details"] = details
                except Exception:
                    # If anything goes wrong, just continue without the extra fields.
                    pass

        return allocation_data

    def _format_days_hours(self, total_days):
        """Convert a float days value to 'X days Y hours' format.

        e.g. 4.5 days → '4 days 4 hours' (assuming 8-hour work day)
        """
        days = int(total_days)
        decimal = total_days - days
        hours = round(decimal * HOURS_PER_DAY)

        if hours == 0:
            return "%d days" % days
        return "%d days %d hours" % (days, hours)
