# -*- coding: utf-8 -*-

from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HolidaysEmployee(models.Model):
    _inherit = "hr.employee"

    def action_generate_carry_forward_allocation(self):
        """Generate carry-forward allocation for this specific employee using settings config."""
        self.ensure_one()
        params = self.env["ir.config_parameter"].sudo()
        plan_id = params.get_param("infs_time_off.time_off_allocation_plan_id")
        type_id = params.get_param("infs_time_off.time_off_type_id")

        if not plan_id or not str(plan_id).isdigit():
            raise UserError(_("Please configure the Time Off Allocation Plan in Settings > Time Off first."))
        plan = self.env["hr.leave.accrual.plan"].browse(int(plan_id)).exists()
        if not plan:
            raise UserError(_("Configured accrual plan (ID %s) not found.") % plan_id)

        if not type_id or not str(type_id).isdigit():
            raise UserError(_("Please configure the Time Off Type in Settings > Time Off first."))
        time_off_type = self.env["hr.leave.type"].browse(int(type_id)).exists()
        if not time_off_type:
            raise UserError(_("Configured time off type (ID %s) not found.") % type_id)

        mode = params.get_param("infs_time_off.carry_forward_generation_mode", "last_year")
        today = fields.Date.today()

        allocation, message = self.env["hr.leave.allocation"]._generate_carry_forward_allocation_for_employee(
            self, plan, time_off_type, mode, today
        )
        if not allocation:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Allocation Already Exists"),
                    "message": message,
                    "type": "warning",
                    "sticky": False,
                },
            }

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Success"),
                "message": _("Carry forward allocation '%s' successfully created for %s.") % (allocation.name, self.name),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window",
                    "res_model": "hr.leave.allocation",
                    "res_id": allocation.id,
                    "views": [[False, "form"]],
                    "target": "current",
                },
            },
        }

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
        """Return the remaining leaves per employee, excluding expired allocations and respecting max_cap.

        Overrides the native SQL which sums every validated allocation without
        taking ``date_to`` into account, so expired allocations (e.g. carried-over
        allocations with a validity period) are not part of the total balance.
        Also enforces ``max_cap`` if configured on the time off type.
        """
        if not self.ids:
            return {}
        self._cr.execute("""
            SELECT
                sum(
                    CASE
                        WHEN s.has_max_cap = true AND s.max_cap > 0
                        THEN LEAST(h_total.days, s.max_cap)
                        ELSE h_total.days
                    END
                ) AS days,
                h_total.employee_id
            FROM
                (
                    SELECT
                        h.holiday_status_id,
                        h.employee_id,
                        sum(h.number_of_days) AS days
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
                    WHERE
                        h.employee_id in %s AND
                        (h.date_to IS NULL OR h.date_to >= %s) AND
                        h.state = 'validate'
                    GROUP BY h.holiday_status_id, h.employee_id
                ) h_total
                JOIN hr_leave_type s ON (s.id = h_total.holiday_status_id)
            WHERE
                s.active = true AND
                s.requires_allocation = 'yes'
            GROUP BY h_total.employee_id""", (tuple(self.ids), fields.Date.today()))
        return {row['employee_id']: row['days'] for row in self._cr.dictfetchall()}

    @api.model
    def _sync_parent_approver_group(self):
        """Ensure only users who are parent_id.user_id of active employees belong to group_leave_parent_approver."""
        group = self.env.ref("infs_time_off.group_leave_parent_approver", raise_if_not_found=False)
        if not group:
            return

        # Find all user IDs that are parent_id.user_id of active employees
        employees = self.sudo().search([("active", "=", True), ("parent_id.user_id", "!=", False)])
        manager_user_ids = list(set(employees.mapped("parent_id.user_id.id")))

        # Strictly replace group members with active direct managers
        group.sudo().write({"users": [(6, 0, manager_user_ids)]})

    def _register_hook(self):
        super()._register_hook()
        try:
            self._sync_parent_approver_group()
        except Exception:
            pass

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        if any("parent_id" in v or "user_id" in v for v in vals_list):
            self._sync_parent_approver_group()
        return employees

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ("parent_id", "user_id", "active")):
            self._sync_parent_approver_group()
        return res

    def unlink(self):
        res = super().unlink()
        self._sync_parent_approver_group()
        return res
