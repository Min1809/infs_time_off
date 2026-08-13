# -*- coding: utf-8 -*-

import logging
from datetime import date

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HolidaysAllocation(models.Model):
    _inherit = "hr.leave.allocation"

    @api.model
    def _get_carry_forward_expiry_date(self):
        """Return the carry-forward expiry date from res.config.settings.

        Combines the month/day from carry_forward_expired_date with
        the year determined by carry_forward_expired_year.

        Returns False if the feature is disabled or no date is configured.
        """
        params = self.env["ir.config_parameter"].sudo()
        is_expired = params.get_param("infs_time_off.is_carry_forward_expired") == "True"
        if not is_expired:
            return False

        expired_date_str = params.get_param("infs_time_off.carry_forward_expired_date")
        if not expired_date_str:
            return False

        expired_year = params.get_param("infs_time_off.carry_forward_expired_year", "current")
        config_date = fields.Datetime.from_string(expired_date_str).date()
        today = date.today()

        if expired_year == "next":
            year = today.year + 1
        else:
            year = today.year

        return date(year, config_date.month, config_date.day)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("date_to"):
                expiry_date = self._get_carry_forward_expiry_date()
                if expiry_date:
                    vals["date_to"] = expiry_date
        return super().create(vals_list)
    

    # @api.model
    # def _cron_create_carry_forward_allocations(self):
    #     """Cron: Create yearly carry-forward allocations for all active employees.

    #     Runs on January 1st. Uses the accrual plan and expiry date from
    #     res.config.settings to create allocations with date_from = Jan 1.
    #     """
    #     params = self.env["ir.config_parameter"].sudo()
    #     is_expired = params.get_param("infs_time_off.is_carry_forward_expired") == "True"
    #     if not is_expired:
    #         _logger.info("Carry forward expired is disabled, skipping cron.")
    #         return

    #     plan_id = params.get_param("infs_time_off.time_off_allocation_plan_id")
    #     _logger.info("Cron: read plan_id from config = %r", plan_id)
    #     if not plan_id or plan_id == "False":
    #         _logger.info("No allocation plan configured in settings, skipping cron.")
    #         return

    #     plan = self.env["hr.leave.accrual.plan"].browse(int(plan_id)).exists()
    #     _logger.info("Cron: looked up plan = %s", plan)
    #     if not plan:
    #         _logger.info("Accrual plan with id=%s not found, skipping cron.", plan_id)
    #         return

    #     type_id = params.get_param("infs_time_off.time_off_type_id")
    #     _logger.info("Cron: read time_off_type_id from config = %r", type_id)
    #     if not type_id or type_id == "False":
    #         _logger.info("No time off type configured in settings, skipping cron.")
    #         return

    #     time_off_type = self.env["hr.leave.type"].browse(int(type_id)).exists()
    #     _logger.info("Cron: looked up time_off_type = %s", time_off_type.name if time_off_type else "N/A")
    #     if not time_off_type:
    #         _logger.info("Time off type with id=%s not found, skipping cron.", type_id)
    #         return

    #     expiry_date = self._get_carry_forward_expiry_date()
    #     today = date.today()

    #     date_from_str = params.get_param("infs_time_off.carry_forward_allocation_date_from")
    #     if date_from_str:
    #         date_from = fields.Datetime.from_string(date_from_str).date()
    #     else:
    #         date_from = today

    #     companies = self.env["res.company"].sudo().search([])
    #     if not companies:
    #         _logger.info("No companies found, skipping cron.")
    #         return

    #     employees = self.env["hr.employee"].sudo().search([("active", "=", True)])
    #     if not employees:
    #         _logger.info("No active employees found, skipping cron.")
    #         return

    #     _logger.info(
    #         "Creating one carry-forward allocation: plan=%s, time_off_type=%s, date_from=%s, date_to=%s, employees=%s",
    #         plan.name, time_off_type.name, date_from, expiry_date, len(employees),
    #     )

    #     allocation = self.sudo().create({
    #         "name": "%s - Carry Forward" % today.year,
    #         "holiday_status_id": time_off_type.id,
    #         "accrual_plan_id": plan.id,
    #         "allocation_type": "accrual",
    #         "multi_employee": True,
    #         "number_of_days": 0,
    #         "date_from": date_from,
    #         "date_to": expiry_date,
    #         "state": "confirm",
    #     })
    #     # Set employee_ids and number_of_days after creation to avoid
    #     # computed-field overrides during the create flow.
    #     allocation.sudo().write({
    #         "employee_ids": [(6, 0, employees.ids)],
    #         "number_of_days": 0,
    #     })
    #     _logger.info("Created carry-forward allocation: %s", allocation.name)
    #     # Validate allocation automatically
    #     allocation.sudo().action_validate()



    @api.model
    def _cron_create_carry_forward_allocations(self):
        """Cron: Create yearly carry-forward allocations per company.

        Runs on January 1st. Uses the accrual plan and expiry date from
        res.config.settings to create one company-wide allocation
        (holiday_type='company') per company.
        """
        params = self.env["ir.config_parameter"].sudo()
        is_expired = params.get_param("infs_time_off.is_carry_forward_expired") == "True"
        if not is_expired:
            _logger.info("Carry forward expired is disabled, skipping cron.")
            return

        plan_id = params.get_param("infs_time_off.time_off_allocation_plan_id")
        if not plan_id or plan_id == "False":
            _logger.info("No allocation plan configured in settings, skipping cron.")
            return

        plan = self.env["hr.leave.accrual.plan"].browse(int(plan_id)).exists()
        if not plan:
            _logger.info("Accrual plan with id=%s not found, skipping cron.", plan_id)
            return

        type_id = params.get_param("infs_time_off.time_off_type_id")
        if not type_id or type_id == "False":
            _logger.info("No time off type configured in settings, skipping cron.")
            return

        time_off_type = self.env["hr.leave.type"].browse(int(type_id)).exists()
        if not time_off_type:
            _logger.info("Time off type with id=%s not found, skipping cron.", type_id)
            return

        expiry_date = self._get_carry_forward_expiry_date()
        today = date.today()

        date_from_str = params.get_param("infs_time_off.carry_forward_allocation_date_from")
        if date_from_str:
            date_from = fields.Datetime.from_string(date_from_str).date()
        else:
            date_from = today

        companies = self.env["res.company"].sudo().search([])
        if not companies:
            _logger.info("No companies found, skipping cron.")
            return

        for company in companies:
            # Skip companies where the configured plan/type don't apply.
            # company_id = False on plan/type means "available to all companies".
            if plan.company_id and plan.company_id.id != company.id:
                _logger.info(
                    "Skipping company %s: accrual plan '%s' belongs to a different company.",
                    company.name, plan.name,
                )
                continue
            if time_off_type.company_id and time_off_type.company_id.id != company.id:
                _logger.info(
                    "Skipping company %s: time off type '%s' belongs to a different company.",
                    company.name, time_off_type.name,
                )
                continue

            _logger.info(
                "Creating carry-forward allocation for company=%s: plan=%s, time_off_type=%s, "
                "date_from=%s, date_to=%s",
                company.name, plan.name, time_off_type.name, date_from, expiry_date,
            )

            allocation = self.sudo().with_company(company).create({
                "name": "%s - Carry Forward - %s" % (today.year, company.name),
                "private_name": "Carry Forward",
                "holiday_status_id": time_off_type.id,
                "accrual_plan_id": plan.id,
                "holiday_type": "company",
                "mode_company_id": company.id,
                "allocation_type": "accrual",
                "number_of_days": 0,
                "date_from": date_from,
                "date_to": expiry_date,
                "state": "confirm",
            })
            allocation.sudo().action_validate()
            _logger.info("Created carry-forward allocation for %s: %s", company.name, allocation.name)
