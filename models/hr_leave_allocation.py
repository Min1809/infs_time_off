# -*- coding: utf-8 -*-

import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.resource.models.utils import HOURS_PER_DAY
from odoo.tools.date_utils import get_timedelta

_logger = logging.getLogger(__name__)


class HolidaysAllocation(models.Model):
    _inherit = "hr.leave.allocation"

    carryover_source_allocation_id = fields.Many2one(
        'hr.leave.allocation',
        string='Carry-over Source',
        copy=False,
        ondelete='set null',
    )
    carry_forward_generation_mode = fields.Selection(
        selection=[
            ("last_year", "Previous Year Only"),
            ("current_year", "Current Year Only"),
            ("all", "All Prior Years"),
        ],
        string="Carry Forward Generation Mode",
        default=lambda self: self.env["ir.config_parameter"].sudo().get_param(
            "infs_time_off.carry_forward_generation_mode", "last_year"
        ),
        help="Defines the scope for carry-forward allocation creation.",
    )

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

    @api.onchange('date_from', 'accrual_plan_id', 'date_to', 'employee_id', 'holiday_type', 'mode_company_id')
    def _onchange_date_from(self):
        """Simulate the accrual preview in 'By Company' mode too.

        The standard implementation short-circuits as soon as there is no
        single ``employee_id`` (which is the case for company allocations),
        leaving the "Allocation" autocalculation at 0. For company mode we
        run the same simulation on a representative employee of the company
        and put the result back on the batch allocation.
        """
        if (
            self.allocation_type == 'accrual'
            and self.holiday_type == 'company'
            and not self.employee_id
        ):
            if not self.date_from or self.state == 'validate' or not self.accrual_plan_id or not self.mode_company_id:
                self.number_of_days = 0
                return

            representative = self.env['hr.employee'].search(
                [('company_id', '=', self.mode_company_id.id)],
                order='id',
                limit=1,
            )
            if not representative:
                self.number_of_days = 0
                return

            fake_allocation = self.env['hr.leave.allocation'].new({
                'employee_id': representative.id,
                'holiday_status_id': self.holiday_status_id.id,
                'accrual_plan_id': self.accrual_plan_id.id,
                'allocation_type': 'accrual',
                'date_from': self.date_from,
                'date_to': self.date_to,
                'lastcall': self.date_from,
                'nextcall': False,
                'already_accrued': False,
                'number_of_days': 0.0,
                'number_of_days_display': 0.0,
                'number_of_hours_display': 0.0,
                'leaves_taken': 0.0,
            })
            date_to = min(self.date_to, date.today()) if self.date_to else False
            fake_allocation.sudo()._process_accrual_plans(date_to, log=False)
            self.number_of_days = fake_allocation.number_of_days
            fake_allocation.invalidate_recordset()
            return

        return super()._onchange_date_from()

    def _prepare_holiday_values(self, employees):
        vals_list = super()._prepare_holiday_values(employees)
        # For accrual allocations created in batch mode (company/department/
        # category) each child accrues independently through the cron based on
        # its own employee. Start them from date_from with 0 days so the cron
        # accrues the whole validity period without double-counting the parent
        # preview.
        if self.allocation_type == 'accrual' and self.holiday_type != 'employee':
            for vals in vals_list:
                vals.update({
                    'number_of_days': 0,
                    'lastcall': self.date_from,
                    'nextcall': False,
                })
        return vals_list

    def _action_validate_create_childs(self):
        res = super()._action_validate_create_childs()
        # Accrue the batch children immediately using their own employee
        # calendar, so they don't show 0 hours until the daily accrual cron
        # runs. The create flow sets nextcall relative to today; reset it so
        # the simulation starts from date_from.
        for allocation in self:
            children = allocation.linked_request_ids.filtered(
                lambda c: c.allocation_type == 'accrual'
            )
            if not children:
                continue
            children.lastcall = allocation.date_from
            children.nextcall = False
            date_to = min(allocation.date_to, date.today()) if allocation.date_to else False
            children._process_accrual_plans(date_to, log=False)
        return res

    def _get_other_allocated_days(self, employee, leave_type):
        """Return total active allocated days/hours for the employee on this leave type, excluding self."""
        if not employee or not leave_type:
            return 0.0
        allocations = self.env['hr.leave.allocation'].sudo().search([
            ('employee_id', '=', employee.id),
            ('holiday_status_id', '=', leave_type.id),
            ('state', '=', 'validate'),
            ('id', '!=', self.id or 0),
        ]).filtered(lambda a: not a.date_to or a.date_to >= fields.Date.today())
        field_name = 'number_of_hours_display' if leave_type.request_unit == 'hour' else 'number_of_days'
        return sum(allocations.mapped(field_name))

    def _add_days_to_allocation(self, current_level, current_level_maximum_leave, leaves_taken, period_start, period_end):
        super()._add_days_to_allocation(current_level, current_level_maximum_leave, leaves_taken, period_start, period_end)
        # Enforce Leave Type Max Cap
        if self.holiday_status_id.has_max_cap and self.holiday_status_id.max_cap > 0 and self.employee_id:
            other_days = self._get_other_allocated_days(self.employee_id, self.holiday_status_id)
            max_allowed = max(0.0, self.holiday_status_id.max_cap - other_days)
            self.number_of_days = min(self.number_of_days, max_allowed + leaves_taken)

    def action_validate(self):
        for allocation in self:
            if (
                allocation.holiday_type == 'employee'
                and allocation.employee_id
                and allocation.holiday_status_id.has_max_cap
                and allocation.holiday_status_id.max_cap > 0
            ):
                other_days = allocation._get_other_allocated_days(allocation.employee_id, allocation.holiday_status_id)
                max_allowed = max(0.0, allocation.holiday_status_id.max_cap - other_days)
                field_name = 'number_of_hours_display' if allocation.holiday_status_id.request_unit == 'hour' else 'number_of_days'
                current_days = getattr(allocation, field_name)
                unit_label = _('hours') if allocation.holiday_status_id.request_unit == 'hour' else _('days')
                if current_days > max_allowed:
                    if max_allowed <= 0:
                        raise UserError(_(
                            "Employee %(employee)s has already reached the maximum allocation cap of %(cap)s %(unit)s for %(type)s.",
                            employee=allocation.employee_id.name,
                            cap=allocation.holiday_status_id.max_cap,
                            unit=unit_label,
                            type=allocation.holiday_status_id.name,
                        ))
                    setattr(allocation, field_name, max_allowed)
                    allocation.number_of_days = max_allowed
                    allocation.message_post(body=_(
                        "Allocation amount was automatically capped to %(capped)s %(unit)s to comply with the Max Cap (%(cap)s %(unit)s) of %(type)s.",
                        capped=max_allowed,
                        unit=unit_label,
                        cap=allocation.holiday_status_id.max_cap,
                        type=allocation.holiday_status_id.name,
                    ))
        return super().action_validate()

    @api.onchange('holiday_status_id', 'employee_id', 'number_of_days_display')
    def _onchange_max_cap_warning(self):
        if (
            self.employee_id
            and self.holiday_status_id
            and self.holiday_status_id.has_max_cap
            and self.holiday_status_id.max_cap > 0
        ):
            other_days = self._get_other_allocated_days(self.employee_id, self.holiday_status_id)
            max_allowed = max(0.0, self.holiday_status_id.max_cap - other_days)
            field_name = 'number_of_hours_display' if self.holiday_status_id.request_unit == 'hour' else 'number_of_days_display'
            current_days = getattr(self, field_name)
            unit_label = _('hours') if self.holiday_status_id.request_unit == 'hour' else _('days')
            if current_days > max_allowed:
                return {
                    'warning': {
                        'title': _("Max Cap Exceeded"),
                        'message': _(
                            "The maximum allocation cap for %(type)s is %(cap)s %(unit)s. This employee already has %(allocated)s %(unit)s allocated. Only %(allowed)s %(unit)s can be added.",
                            type=self.holiday_status_id.name,
                            cap=self.holiday_status_id.max_cap,
                            unit=unit_label,
                            allocated=other_days,
                            allowed=max_allowed,
                        )
                    }
                }

    @api.model
    def _cron_create_carry_forward_allocations_per_employee(self):
        """Cron: Create yearly carry-forward allocations for each active employee.

        Uses the accrual plan and expiry date from res.config.settings to create
        one allocation per employee (holiday_type='employee').
        - If the employee has an hr.contract start date: sets date_from to the
          contract start date and auto-validates the allocation.
        - If the employee has NO contract or NO contract start date: falls back to
          today as date_from and leaves the allocation unvalidated (to approve).
        """
        params = self.env["ir.config_parameter"].sudo()
        is_expired = params.get_param("infs_time_off.is_carry_forward_expired") == "True"
        if not is_expired:
            _logger.info("Carry forward expired is disabled, skipping employee cron.")
            return

        plan_id = params.get_param("infs_time_off.time_off_allocation_plan_id")
        if not plan_id or not str(plan_id).isdigit():
            _logger.info("No allocation plan configured in settings, skipping employee cron.")
            return

        plan = self.env["hr.leave.accrual.plan"].browse(int(plan_id)).exists()
        if not plan:
            _logger.info("Accrual plan with id=%s not found, skipping employee cron.", plan_id)
            return

        type_id = params.get_param("infs_time_off.time_off_type_id")
        if not type_id or not str(type_id).isdigit():
            _logger.info("No time off type configured in settings, skipping employee cron.")
            return

        time_off_type = self.env["hr.leave.type"].browse(int(type_id)).exists()
        if not time_off_type:
            _logger.info("Time off type with id=%s not found, skipping employee cron.", type_id)
            return

        today = date.today()
        mode = params.get_param("infs_time_off.carry_forward_generation_mode", "last_year")

        employees = self.env["hr.employee"].sudo().search([("active", "=", True)])
        if not employees:
            _logger.info("No active employees found, skipping employee cron.")
            return

        for employee in employees:
            allocation, message = self._generate_carry_forward_allocation_for_employee(
                employee, plan, time_off_type, mode, today
            )
            if not allocation:
                _logger.info("Skipping employee %s: %s", employee.name, message)
            else:
                _logger.info("Generated carry-forward allocation for employee %s: %s", employee.name, allocation.name)

    @api.model
    def _generate_carry_forward_allocation_for_employee(self, employee, plan, time_off_type, mode, today):
        """Create and process carry-forward allocation for a single employee.

        Checks if an active allocation already exists for this employee + plan + time_off_type,
        and skips creation if one is found.
        Optimizes simulation performance by fast-forwarding to the required year.

        Returns tuple (allocation, message).
        """
        company = employee.company_id or self.env.company
        if plan.company_id and plan.company_id.id != company.id:
            return False, _("Accrual plan '%s' belongs to a different company.") % plan.name
        if time_off_type.company_id and time_off_type.company_id.id != company.id:
            return False, _("Time off type '%s' belongs to a different company.") % time_off_type.name

        # Check if an active allocation already exists for this employee with the same plan and type
        existing = self.sudo().search([
            ("employee_id", "=", employee.id),
            ("holiday_status_id", "=", time_off_type.id),
            ("accrual_plan_id", "=", plan.id),
            ("state", "in", ["confirm", "validate"]),
        ], limit=1)
        if existing:
            return False, _("Allocation '%s' already exists for %s (Plan: %s, Type: %s).") % (
                existing.name, employee.name, plan.name, time_off_type.name
            )

        # Determine contract start date from hr.contract
        has_contract_start = False
        contract_start_date = False
        if "hr.contract" in self.env:
            if hasattr(employee, "first_contract_date") and employee.first_contract_date:
                contract_start_date = employee.first_contract_date
            elif hasattr(employee, "contract_id") and employee.contract_id and employee.contract_id.date_start:
                contract_start_date = employee.contract_id.date_start
            if not contract_start_date:
                contract = self.env["hr.contract"].sudo().search([
                    ("employee_id", "=", employee.id),
                    ("state", "!=", "cancel"),
                    ("date_start", "!=", False),
                ], order="date_start asc", limit=1)
                if contract and contract.date_start:
                    contract_start_date = contract.date_start

        if contract_start_date:
            has_contract_start = True
            date_from = contract_start_date
        else:
            has_contract_start = False
            date_from = today

        _logger.info(
            "Creating carry-forward allocation for employee=%s (mode=%s, has_contract=%s): plan=%s, time_off_type=%s, "
            "date_from=%s",
            employee.name, mode, has_contract_start, plan.name, time_off_type.name, date_from,
        )

        allocation = self.sudo().with_company(company).create({
            "name": "%s - Carry Forward - %s" % (today.year, employee.name),
            "private_name": "Carry Forward",
            "holiday_status_id": time_off_type.id,
            "accrual_plan_id": plan.id,
            "holiday_type": "employee",
            "employee_id": employee.id,
            "allocation_type": "accrual",
            "number_of_days": 0,
            "date_from": date_from,
            "date_to": False,
            "carry_forward_generation_mode": mode,
            "state": "confirm",
        })

        if has_contract_start:
            allocation.sudo().action_validate()
            # Fast-forward simulation start date based on generation mode
            # Seniority level is always computed accurately from allocation.date_from (contract start date)
            if mode == "current_year":
                start_sim_date = max(date_from, date(today.year, 1, 1))
            elif mode == "last_year":
                start_sim_date = max(date_from, date(today.year - 1, 1, 1))
            else:
                start_sim_date = date_from

            allocation.lastcall = start_sim_date
            allocation.nextcall = False
            allocation._process_accrual_plans(today, log=False)
            _logger.info(
                "Created and validated carry-forward allocation for employee %s: %s (simulated from %s to %s)",
                employee.name, allocation.name, start_sim_date, today,
            )
        else:
            _logger.info(
                "Created unvalidated carry-forward allocation for employee %s (no contract start date found, date_from=today): %s",
                employee.name, allocation.name,
            )

        return allocation, _("Successfully created allocation '%s'.") % allocation.name



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
        if not plan_id or not str(plan_id).isdigit():
            _logger.info("No allocation plan configured in settings, skipping cron.")
            return

        plan = self.env["hr.leave.accrual.plan"].browse(int(plan_id)).exists()
        if not plan:
            _logger.info("Accrual plan with id=%s not found, skipping cron.", plan_id)
            return

        type_id = params.get_param("infs_time_off.time_off_type_id")
        if not type_id or not str(type_id).isdigit():
            _logger.info("No time off type configured in settings, skipping cron.")
            return

        time_off_type = self.env["hr.leave.type"].browse(int(type_id)).exists()
        if not time_off_type:
            _logger.info("Time off type with id=%s not found, skipping cron.", type_id)
            return

        expiry_date = self._get_carry_forward_expiry_date()
        today = date.today()
        mode = params.get_param("infs_time_off.carry_forward_generation_mode", "last_year")

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
                "carry_forward_generation_mode": mode,
                "state": "confirm",
            })
            allocation.sudo().action_validate()
            _logger.info("Created carry-forward allocation for %s: %s", company.name, allocation.name)

    def _create_carryover_allocation(self, level, amount_days, carryover_date):
        """Move the carried-over amount into a new validity-bound allocation.

        Creates a validated ``regular`` allocation whose ``date_to`` is the
        carry-over date plus the validity period configured on the level, so the
        carried balance expires natively. The source allocation keeps only the
        already-consumed leave.
        """
        self.ensure_one()
        if isinstance(self.id, models.NewId):
            # Unsaved record (e.g. the onchange preview): keep native behavior
            # and avoid creating records as a side effect.
            return self.env['hr.leave.allocation']

        # "Valid for N days/months" counts the carry-over date as the first
        # day, so the carried balance expires the day after the validity ends.
        if level.carryover_validity_type == 'day':
            date_to = carryover_date + relativedelta(days=level.carryover_validity_count - 1)
        else:
            date_to = carryover_date + relativedelta(months=level.carryover_validity_count, days=-1)

        # Idempotency: don't create a duplicate on retroactive reprocessing.
        existing = self.env['hr.leave.allocation'].sudo().search([
            ('carryover_source_allocation_id', '=', self.id),
            ('holiday_status_id', '=', self.holiday_status_id.id),
            ('date_from', '=', carryover_date),
        ], limit=1)
        if existing:
            return existing

        allocation = self.env['hr.leave.allocation'].sudo().with_context(
            mail_notify_force_send=False,
            mail_activity_automation_skip=True,
        ).create({
            'name': _("Carry-over - %(employee)s (%(year)s)") % {
                'employee': self.employee_id.name or '',
                'year': carryover_date.year,
            },
            'private_name': _("Carry-over"),
            'employee_id': self.employee_id.id,
            'holiday_type': 'employee',
            'holiday_status_id': self.holiday_status_id.id,
            'allocation_type': 'regular',
            'number_of_days': amount_days,
            'date_from': carryover_date,
            'date_to': date_to,
            'state': 'confirm',
            'notes': _("Carried over from %(source)s. Valid until %(date_to)s.") % {
                'source': self.name or _("accrual allocation"),
                'date_to': fields.Date.to_string(date_to),
            },
            'carryover_source_allocation_id': self.id,
        })
        allocation.action_validate()
        return allocation

    def _process_accrual_plans(self, date_to=False, force_period=False, log=True):
        """
        This method is part of the cron's process.
        The goal of this method is to retroactively apply accrual plan levels and progress from nextcall to date_to or today.
        If force_period is set, the accrual will run until date_to in a prorated way (used for end of year accrual actions).

        Overridden to split the capped carried-over amount into a separate
        validity-bound allocation when the level has carry-over validity enabled.
        """
        date_to = date_to or fields.Date.today()
        already_accrued = {allocation.id: allocation.already_accrued or (allocation.number_of_days != 0 and allocation.accrual_plan_id.accrued_gain_time == 'start') for allocation in self}
        first_allocation = _("""This allocation have already ran once, any modification won't be effective to the days allocated to the employee. If you need to change the configuration of the allocation, delete and create a new one.""")
        for allocation in self:
            level_ids = allocation.accrual_plan_id.level_ids.sorted('sequence')
            if not level_ids:
                continue
            # "cache" leaves taken, as it gets recomputed every time allocation.number_of_days is assigned to. Without this,
            # every loop will take 1+ second. It can be removed if computes don't chain in a way to always reassign accrual plan
            # even if the value doesn't change. This is the best performance atm.
            first_level = level_ids[0]
            first_level_start_date = allocation.date_from + get_timedelta(first_level.start_count, first_level.start_type)
            leaves_taken = allocation.leaves_taken if allocation.holiday_status_id.request_unit in ["day", "half_day"] else allocation.leaves_taken / (allocation.employee_id.sudo().resource_id.calendar_id.hours_per_day or HOURS_PER_DAY)
            allocation.already_accrued = already_accrued[allocation.id]
            # first time the plan is run, initialize nextcall and take carryover / level transition into account
            if not allocation.nextcall:
                # Accrual plan is not configured properly or has not started
                if date_to < first_level_start_date:
                    continue
                allocation.lastcall = max(allocation.lastcall, first_level_start_date)
                (init_level, init_level_idx) = allocation._get_current_accrual_plan_level_id(allocation.lastcall)
                current_plan_level = init_level or first_level
                allocation.nextcall = current_plan_level._get_next_date(allocation.lastcall)
                # adjust nextcall for carryover
                carryover_date = allocation._get_carryover_date(allocation.nextcall)
                allocation.nextcall = min(carryover_date, allocation.nextcall)
                # adjust nextcall for level_transition
                if init_level_idx >= 0 and init_level_idx < len(level_ids) - 1:
                    next_level_start_date = allocation.date_from + get_timedelta(level_ids[init_level_idx + 1].start_count, level_ids[init_level_idx + 1].start_type)
                    allocation.nextcall = min(next_level_start_date, allocation.nextcall)
                elif len(level_ids) > 1:
                    second_level_start_date = allocation.date_from + get_timedelta(level_ids[1].start_count, level_ids[1].start_type)
                    if allocation.lastcall < second_level_start_date:
                        allocation.nextcall = min(second_level_start_date, allocation.nextcall)
                if log:
                    allocation._message_log(body=first_allocation)
            (current_level, current_level_idx) = (False, 0)
            current_level_maximum_leave = 0.0
            previous_level = False
            # all subsequent runs, at every loop:
            # get current level and normal period boundaries, then set nextcall, adjusted for level transition and carryover
            # add days, trimmed if there is a maximum_leave
            while allocation.nextcall <= date_to:
                (current_level, current_level_idx) = allocation._get_current_accrual_plan_level_id(allocation.nextcall)
                if not current_level:
                    break
                # Carry-over validity at milestone transitions: when the plan
                # moves to a new level, move the previous level's accrued days
                # into a separate allocation that expires after that level's
                # validity period.
                if (previous_level and current_level != previous_level
                        and previous_level.carryover_has_validity
                        and previous_level.action_with_unused_accruals == 'maximum'):
                    allocated_days_left = allocation.number_of_days - leaves_taken
                    postpone_max_days = previous_level.postpone_max_days if previous_level.added_value_type == 'day' else previous_level.postpone_max_days / (allocation.employee_id.sudo().resource_id.calendar_id.hours_per_day or HOURS_PER_DAY)
                    allocation_max_days = min(postpone_max_days, allocated_days_left)
                    if allocation_max_days > 0:
                        if allocation.state == 'validate':
                            mode = allocation.carry_forward_generation_mode or 'last_year'
                            should_create = (
                                mode == 'all'
                                or (mode == 'last_year' and allocation.lastcall.year >= (date_to.year - 1))
                                or (mode == 'current_year' and allocation.lastcall.year >= date_to.year)
                            )
                            if should_create:
                                allocation._create_carryover_allocation(previous_level, allocation_max_days, allocation.lastcall)
                        allocation.number_of_days = leaves_taken
                if current_level.cap_accrued_time:
                    current_level_maximum_leave = current_level.maximum_leave if current_level.added_value_type == "day" else current_level.maximum_leave / (allocation.employee_id.sudo().resource_id.calendar_id.hours_per_day or HOURS_PER_DAY)
                nextcall = current_level._get_next_date(allocation.nextcall)
                # Since _get_previous_date returns the given date if it corresponds to a call date
                # this will always return lastcall except possibly on the first call
                # this is used to prorate the first number of days given to the employee
                period_start = current_level._get_previous_date(allocation.lastcall)
                period_end = current_level._get_next_date(allocation.lastcall)
                # There are 2 cases where nextcall could be closer than the normal period:
                # 1. Passing from one level to another, if mode is set to 'immediately'
                if current_level_idx < (len(level_ids) - 1) and allocation.accrual_plan_id.transition_mode == 'immediately':
                    next_level = level_ids[current_level_idx + 1]
                    current_level_last_date = allocation.date_from + get_timedelta(next_level.start_count, next_level.start_type)
                    if allocation.nextcall != current_level_last_date:
                        nextcall = min(nextcall, current_level_last_date)
                # 2. On carry-over date
                carryover_date = allocation._get_carryover_date(allocation.nextcall)
                if allocation.nextcall < carryover_date < nextcall:
                    nextcall = min(nextcall, carryover_date)
                if not allocation.already_accrued:
                    allocation._add_days_to_allocation(current_level, current_level_maximum_leave, leaves_taken, period_start, period_end)
                # if it's the carry-over date, adjust days using current level's carry-over policy, then continue
                if allocation.nextcall == carryover_date:
                    if current_level.action_with_unused_accruals in ['lost', 'maximum']:
                        allocated_days_left = allocation.number_of_days - leaves_taken
                        allocation_max_days = 0 # default if unused_accrual are lost
                        if current_level.action_with_unused_accruals == 'maximum':
                            postpone_max_days = current_level.postpone_max_days if current_level.added_value_type == 'day' else current_level.postpone_max_days / (allocation.employee_id.sudo().resource_id.calendar_id.hours_per_day or HOURS_PER_DAY)
                            allocation_max_days = min(postpone_max_days, allocated_days_left)
                        if current_level.carryover_has_validity and allocation_max_days > 0:
                            if allocation.state == 'validate':
                                mode = allocation.carry_forward_generation_mode or 'last_year'
                                should_create = (
                                    mode == 'all'
                                    or (mode == 'last_year' and carryover_date.year >= (date_to.year - 1))
                                    or (mode == 'current_year' and carryover_date.year >= date_to.year)
                                )
                                if should_create:
                                    allocation._create_carryover_allocation(current_level, allocation_max_days, carryover_date)
                            allocation.number_of_days = leaves_taken
                        else:
                            allocation.number_of_days = min(allocation.number_of_days, allocation_max_days) + leaves_taken

                allocation.lastcall = allocation.nextcall
                allocation.nextcall = nextcall
                allocation.already_accrued = False
                previous_level = current_level
                if force_period and allocation.nextcall > date_to:
                    allocation.nextcall = date_to
                    force_period = False

            # if plan.accrued_gain_time == 'start', process next period and set flag 'already_accrued', this will skip adding days
            # once, preventing double allocation.
            if allocation.accrual_plan_id.accrued_gain_time == 'start':
                # check that we are at the start of a period, not on a carry-over or level transition date
                level_start = {level._get_level_transition_date(allocation.date_from): level for level in allocation.accrual_plan_id.level_ids}
                current_level = level_start.get(allocation.lastcall) or current_level or allocation.accrual_plan_id.level_ids[0]
                period_start = current_level._get_previous_date(allocation.lastcall)
                if current_level.cap_accrued_time:
                    current_level_maximum_leave = current_level.maximum_leave if current_level.added_value_type == "day" else current_level.maximum_leave / (allocation.employee_id.sudo().resource_id.calendar_id.hours_per_day or HOURS_PER_DAY)
                allocation._add_days_to_allocation(current_level, current_level_maximum_leave, leaves_taken, period_start, allocation.nextcall)
                allocation.already_accrued = True
