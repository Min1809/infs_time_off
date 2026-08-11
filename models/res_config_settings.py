# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    is_carry_forward_expired = fields.Boolean(
        string="Carry Forward Expiry",
        config_parameter="infs_time_off.is_carry_forward_expired",
        help="Enable automatic expiry of carried-forward leaves.",
    )

    carry_forward_expired_date = fields.Datetime(
        string="Carry Forward Expiry Date",
        config_parameter="infs_time_off.carry_forward_expired_date",
        help="Fixed date on which carried-forward leaves will expire.",
    )

    carry_forward_expired_year = fields.Selection(
        string="Carry Forward Expiry Year",
        selection=[
            ("current", "Current Year"),
            ("next", "Next Year"),
        ],
        config_parameter="infs_time_off.carry_forward_expired_year",
        default="current",
        help="Whether carry-forward expiry references the last or current year.",
    )

    time_off_allocation_plan_id = fields.Many2one(
        "hr.leave.accrual.plan",
        string="Time Off Allocation Plan",
        help="Default accrual plan used for carry-forward allocations created by cron.",
    )

    time_off_type_id = fields.Many2one(
        "hr.leave.type",
        string="Time Off Type",
        help="Time Off Type used for carry-forward allocations created by cron.",
    )

    carry_forward_allocation_date_from = fields.Datetime(
        string="Allocation Start Date",
        config_parameter="infs_time_off.carry_forward_allocation_date_from",
        help="Validity Period start date (date_from) used when the cron creates carry-forward allocations.",
    )

    def set_values(self):
        super().set_values()
        self.env["ir.config_parameter"].sudo().set_param(
            "infs_time_off.time_off_allocation_plan_id",
            self.time_off_allocation_plan_id.id or "",
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "infs_time_off.time_off_type_id",
            self.time_off_type_id.id or "",
        )

    def get_values(self):
        res = super().get_values()
        plan_id = self.env["ir.config_parameter"].sudo().get_param(
            "infs_time_off.time_off_allocation_plan_id"
        )
        type_id = self.env["ir.config_parameter"].sudo().get_param(
            "infs_time_off.time_off_type_id"
        )
        res.update(
            time_off_allocation_plan_id=int(plan_id) if plan_id else False,
            time_off_type_id=int(type_id) if type_id else False,
        )
        return res
