# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import api, fields, models
from odoo.addons.resource.models.utils import HOURS_PER_DAY


class HolidaysLeaveType(models.Model):
    _inherit = "hr.leave.type"

    def get_allocation_data(self, employees, target_date=None):
        """Override to add duration_display field with 'X days Y hours' format."""
        allocation_data = super().get_allocation_data(employees, target_date)

        for employee in allocation_data:
            for leave_type_data in allocation_data[employee]:
                try:
                    # leave_type_data is a tuple: (name, data_dict, requires_allocation, leave_type_id)
                    data = leave_type_data[1] if len(leave_type_data) > 1 else {}
                    if data.get("request_unit") in ("day", "half_day"):
                        duration = data.get("virtual_remaining_leaves", 0)
                        data["duration_display"] = self._format_days_hours(duration)
                    else:
                        # For hour-based types, keep as hours
                        data["duration_display"] = "%.2f hours" % data.get("virtual_remaining_leaves", 0)
                except Exception:
                    # If anything goes wrong, just continue without duration_display
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
