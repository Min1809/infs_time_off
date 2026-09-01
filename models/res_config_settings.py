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

    carry_forward_generation_mode = fields.Selection(
        selection=[
            ("last_year", "Previous Year Only"),
            ("current_year", "Current Year Only"),
            ("all", "All Prior Years"),
        ],
        string="Carry Forward Generation Mode",
        config_parameter="infs_time_off.carry_forward_generation_mode",
        default="last_year",
        help="Defines which carry-forward allocations to generate (allocation start date is always the employee's contract start date to compute correct accrual seniority):\n"
             "- Previous Year Only: Creates carry-forward allocations only for the previous year.\n"
             "- Current Year Only: Accrues at current seniority level without generating carry-forwards from prior years.\n"
             "- All Prior Years: Generates carry-forward allocations for all historical years.",
    )

    time_off_mail_server_id = fields.Many2one(
        "ir.mail_server",
        string="Time Off Outgoing Mail Server",
        help="Explicitly route all Time Off notification emails through this outgoing mail server.",
    )

    time_off_notification_email_from = fields.Char(
        string="Time Off Sender Email Address",
        config_parameter="infs_time_off.time_off_notification_email_from",
        help="Custom 'From' email address used for Time Off notification emails (e.g. crm@infinitytisuccess.com). If empty, the mail server SMTP user or company email is used.",
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
        self.env["ir.config_parameter"].sudo().set_param(
            "infs_time_off.time_off_mail_server_id",
            self.time_off_mail_server_id.id or "",
        )

    def get_values(self):
        res = super().get_values()
        params = self.env["ir.config_parameter"].sudo()

        plan_id = params.get_param("infs_time_off.time_off_allocation_plan_id")
        type_id = params.get_param("infs_time_off.time_off_type_id")
        mail_server_id = params.get_param("infs_time_off.time_off_mail_server_id")

        plan = False
        if plan_id and str(plan_id).isdigit():
            plan = self.env["hr.leave.accrual.plan"].browse(int(plan_id)).exists()
            if not plan:
                params.set_param("infs_time_off.time_off_allocation_plan_id", "")

        time_off_type = False
        if type_id and str(type_id).isdigit():
            time_off_type = self.env["hr.leave.type"].browse(int(type_id)).exists()
            if not time_off_type:
                params.set_param("infs_time_off.time_off_type_id", "")

        mail_server = False
        if mail_server_id and str(mail_server_id).isdigit():
            mail_server = self.env["ir.mail_server"].browse(int(mail_server_id)).exists()
            if not mail_server:
                params.set_param("infs_time_off.time_off_mail_server_id", "")

        res.update(
            time_off_allocation_plan_id=plan.id if plan else False,
            time_off_type_id=time_off_type.id if time_off_type else False,
            time_off_mail_server_id=mail_server.id if mail_server else False,
        )
        return res
