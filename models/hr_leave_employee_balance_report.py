# -*- coding: utf-8 -*-

from odoo import api, fields, models, tools, _
from odoo.addons.resource.models.utils import HOURS_PER_DAY


class LeaveEmployeeBalanceReport(models.Model):
    _name = "hr.leave.employee.balance.report"
    _description = "Employee Time Off Balance Report"
    _auto = False
    _order = "employee_id, holiday_status_id"

    employee_id = fields.Many2one('hr.employee', string="Employee", readonly=True)
    department_id = fields.Many2one('hr.department', string="Department", readonly=True)
    company_id = fields.Many2one('res.company', string="Company", readonly=True)
    active_employee = fields.Boolean(string="Active Employee", readonly=True)
    holiday_status_id = fields.Many2one("hr.leave.type", string="Time Off Type", readonly=True)
    allocated_days = fields.Float(string="Allocated (Days)", readonly=True, group_operator="sum")
    leaves_taken = fields.Float(string="Taken (Days)", readonly=True, group_operator="sum")
    leaves_planned = fields.Float(string="Planned (Days)", readonly=True, group_operator="sum")
    remaining_leaves = fields.Float(string="Remaining Balance (Days)", readonly=True, group_operator="sum")
    virtual_remaining_leaves = fields.Float(string="Virtual Remaining (Days)", readonly=True, group_operator="sum")
    remaining_display = fields.Char(string="Balance Display", compute="_compute_remaining_display", readonly=True)
    has_max_cap = fields.Boolean(string="Limit Max Cap", readonly=True)
    max_cap = fields.Float(string="Max Cap", readonly=True)
    closest_allocation_expire = fields.Date(string="Closest Expiry Date", readonly=True)
    request_unit = fields.Selection(related="holiday_status_id.request_unit", readonly=True)

    @api.depends('remaining_leaves', 'holiday_status_id.request_unit')
    def _compute_remaining_display(self):
        for record in self:
            if record.request_unit == 'hour':
                record.remaining_display = "%.2f hours" % (record.remaining_leaves * HOURS_PER_DAY)
            else:
                days = int(record.remaining_leaves)
                decimal = record.remaining_leaves - days
                hours = round(decimal * HOURS_PER_DAY)
                if hours == 0:
                    record.remaining_display = "%d days" % days
                else:
                    record.remaining_display = "%d days %d hours" % (days, hours)

    def init(self):
        tools.drop_view_if_exists(self._cr, 'hr_leave_employee_balance_report')
        self._cr.execute("""
            CREATE or REPLACE view hr_leave_employee_balance_report as (
                WITH active_allocations AS (
                    SELECT
                        a.employee_id,
                        a.holiday_status_id,
                        SUM(CASE WHEN a.state = 'validate' AND (a.date_to IS NULL OR a.date_to >= CURRENT_DATE) THEN a.number_of_days ELSE 0 END) AS allocated_days,
                        MIN(CASE WHEN a.state = 'validate' AND a.date_to >= CURRENT_DATE THEN a.date_to ELSE NULL END) AS closest_allocation_expire
                    FROM hr_leave_allocation a
                    WHERE a.active = true AND a.state = 'validate'
                    GROUP BY a.employee_id, a.holiday_status_id
                ),
                active_leaves AS (
                    SELECT
                        l.employee_id,
                        l.holiday_status_id,
                        SUM(CASE WHEN l.state = 'validate' THEN l.number_of_days ELSE 0 END) AS taken_days,
                        SUM(CASE WHEN l.state IN ('confirm', 'validate1') THEN l.number_of_days ELSE 0 END) AS planned_days
                    FROM hr_leave l
                    WHERE l.active = true AND l.state IN ('validate', 'confirm', 'validate1')
                    GROUP BY l.employee_id, l.holiday_status_id
                ),
                emp_leave_types AS (
                    SELECT DISTINCT
                        e.id AS employee_id,
                        e.department_id,
                        e.company_id,
                        e.active AS active_employee,
                        t.id AS holiday_status_id,
                        t.has_max_cap,
                        t.max_cap,
                        t.request_unit
                    FROM hr_employee e
                    CROSS JOIN hr_leave_type t
                    WHERE t.active = true
                      AND t.requires_allocation = 'yes'
                      AND (t.company_id IS NULL OR t.company_id = e.company_id)
                )
                SELECT
                    row_number() OVER (ORDER BY elt.employee_id, elt.holiday_status_id) AS id,
                    elt.employee_id,
                    elt.department_id,
                    elt.company_id,
                    elt.active_employee,
                    elt.holiday_status_id,
                    COALESCE(aa.allocated_days, 0) AS allocated_days,
                    COALESCE(al.taken_days, 0) AS leaves_taken,
                    COALESCE(al.planned_days, 0) AS leaves_planned,
                    CASE
                        WHEN elt.has_max_cap = true AND elt.max_cap > 0
                        THEN LEAST(GREATEST(COALESCE(aa.allocated_days, 0) - COALESCE(al.taken_days, 0), 0), elt.max_cap)
                        ELSE GREATEST(COALESCE(aa.allocated_days, 0) - COALESCE(al.taken_days, 0), 0)
                    END AS remaining_leaves,
                    CASE
                        WHEN elt.has_max_cap = true AND elt.max_cap > 0
                        THEN LEAST(GREATEST(COALESCE(aa.allocated_days, 0) - COALESCE(al.taken_days, 0) - COALESCE(al.planned_days, 0), 0), elt.max_cap)
                        ELSE GREATEST(COALESCE(aa.allocated_days, 0) - COALESCE(al.taken_days, 0) - COALESCE(al.planned_days, 0), 0)
                    END AS virtual_remaining_leaves,
                    elt.has_max_cap,
                    elt.max_cap,
                    aa.closest_allocation_expire
                FROM emp_leave_types elt
                LEFT JOIN active_allocations aa ON aa.employee_id = elt.employee_id AND aa.holiday_status_id = elt.holiday_status_id
                LEFT JOIN active_leaves al ON al.employee_id = elt.employee_id AND al.holiday_status_id = elt.holiday_status_id
            );
        """)

    def action_view_allocations(self):
        self.ensure_one()
        return {
            'name': _('Allocations: %s - %s') % (self.employee_id.name, self.holiday_status_id.name),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.leave.allocation',
            'view_mode': 'tree,form',
            'domain': [('employee_id', '=', self.employee_id.id), ('holiday_status_id', '=', self.holiday_status_id.id)],
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_holiday_status_id': self.holiday_status_id.id,
                'default_holiday_type': 'employee',
            },
        }

    def action_view_leaves(self):
        self.ensure_one()
        return {
            'name': _('Time Off Requests: %s - %s') % (self.employee_id.name, self.holiday_status_id.name),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.leave',
            'view_mode': 'tree,form,calendar',
            'domain': [('employee_id', '=', self.employee_id.id), ('holiday_status_id', '=', self.holiday_status_id.id)],
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_holiday_status_id': self.holiday_status_id.id,
                'default_holiday_type': 'employee',
            },
        }
