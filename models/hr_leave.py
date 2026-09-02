# -*- coding: utf-8 -*-

import logging

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HolidaysRequest(models.Model):
    _inherit = "hr.leave"

    # ------------------------------------------------------------
    # Disable default notifications (we send custom emails instead)
    # ------------------------------------------------------------

    def activity_update(self):
        """Override to suppress default activity-based email notifications."""
        return True

    def _track_subtype(self, init_values):
        """Override to suppress automatic tracking notification emails."""
        return False

    # ------------------------------------------------------------
    # Custom email sending
    # ------------------------------------------------------------

    def _send_leave_email(self, template_xmlid, recipient_partner_ids):
        """Send a leave notification email using the specified mail template."""
        template = self.env.ref("infs_time_off.%s" % template_xmlid, raise_if_not_found=False)
        if not template or not recipient_partner_ids:
            _logger.warning(
                "SKIP LEAVE EMAIL: template=%s or recipient_partner_ids=%s missing",
                template_xmlid,
                recipient_partner_ids,
            )
            return

        partners = self.env["res.partner"].sudo().browse(recipient_partner_ids).exists()
        if not partners:
            _logger.warning("SKIP LEAVE EMAIL: no existing partner found for IDs %s", recipient_partner_ids)
            return

        # Deduplicate by email to prevent sending twice to the same person
        seen = set()
        unique = self.env["res.partner"].sudo()
        for p in partners:
            email = p.email_normalized or p.email
            if email and email not in seen:
                seen.add(email)
                unique |= p

        if not unique:
            _logger.warning(
                "SKIP LEAVE EMAIL: partners %s (IDs: %s) have no valid email address",
                partners.mapped("name"),
                partners.ids,
            )
            return

        emails = ",".join(unique.mapped("email"))

        # Retrieve configured mail server and sender address from settings
        params = self.env["ir.config_parameter"].sudo()
        server_param = params.get_param("infs_time_off.time_off_mail_server_id")
        email_from_param = params.get_param("infs_time_off.time_off_notification_email_from")

        mail_server_id = int(server_param) if server_param and str(server_param).isdigit() else False
        mail_server = self.env["ir.mail_server"].sudo().browse(mail_server_id).exists() if mail_server_id else False

        for leave in self:
            email_values = {
                "recipient_ids": [(6, 0, unique.ids)],
                "email_to": False,
                "auto_delete": False,  # Retain in Settings > Technical > Emails for tracking
            }

            if mail_server:
                email_values["mail_server_id"] = mail_server.id

            # Determine sender email address
            sender_email = (
                email_from_param
                or (mail_server and (mail_server.smtp_user or mail_server.from_filter))
                or (leave.employee_company_id and leave.employee_company_id.partner_id.email)
                or (leave.company_id and leave.company_id.partner_id.email)
            )
            if sender_email:
                email_values["email_from"] = sender_email

            _logger.info(
                "SENDING LEAVE EMAIL: template=%s, leave_id=%s, server=%s, from=%s, to=%s, emails=%s",
                template_xmlid,
                leave.id,
                mail_server.name if mail_server else "Default",
                email_values.get("email_from", "N/A"),
                unique.mapped("name"),
                emails,
            )

            try:
                mail_id = template.sudo().send_mail(
                    leave.id,
                    force_send=True,
                    raise_exception=True,
                    email_values=email_values,
                )
                _logger.info("LEAVE EMAIL SENT SUCCESSFULLY: mail_id=%s, leave_id=%s", mail_id, leave.id)
            except Exception as e:
                _logger.exception(
                    "FAILED TO SEND LEAVE EMAIL: template=%s, leave_id=%s, error=%s",
                    template_xmlid,
                    leave.id,
                    str(e),
                )

    def _get_approver_partners(self):
        """Return the appropriate approver partner(s) based on validation type and current state."""
        self.ensure_one()
        partners = self.env["res.partner"].sudo()

        if self.validation_type == "manager" or (
            self.validation_type == "both" and self.state in ("confirm", "draft")
        ):
            # First approver: Time Off Approver (res.users) or Manager (hr.employee)
            if self.employee_id.leave_manager_id:
                # leave_manager_id is a res.users record
                partners |= self.employee_id.leave_manager_id.partner_id
            elif self.employee_id.parent_id:
                # parent_id is an hr.employee record
                emp_manager = self.employee_id.parent_id
                if emp_manager.work_contact_id:
                    partners |= emp_manager.work_contact_id
                elif emp_manager.user_id:
                    partners |= emp_manager.user_id.partner_id

        elif self.validation_type == "hr" or (
            self.validation_type == "both" and self.state == "validate1"
        ):
            # Second/officer approver
            if self.holiday_status_id.responsible_ids:
                for user in self.holiday_status_id.responsible_ids:
                    partners |= user.partner_id

        return partners

    def _notify_leave_submitted(self):
        """Send submission notification to the appropriate approver."""
        _logger.info(
            "NOTIFY LEAVE SUBMITTED: leave_ids=%s, states=%s, validation_types=%s",
            self.ids,
            self.mapped("state"),
            self.mapped("validation_type"),
        )
        for leave in self.filtered(lambda l: l.validation_type != "no_validation"):
            partners = leave._get_approver_partners()
            if partners:
                leave._send_leave_email("mail_template_leave_submitted", partners.ids)

    @api.model_create_multi
    def create(self, vals_list):
        states_in = [v.get("state", "N/A") for v in vals_list]
        _logger.info("CREATE LEAVE: states=%s", states_in)
        leaves = super().create(vals_list)
        _logger.info("CREATE LEAVE DONE: ids=%s, states=%s", leaves.ids, leaves.mapped("state"))
        leaves.filtered(lambda l: l.state == "confirm")._notify_leave_submitted()
        return leaves

    def write(self, vals):
        old_states = {leave.id: leave.state for leave in self}
        _logger.info("WRITE LEAVE: ids=%s, old_states=%s, vals=%s", self.ids, old_states, vals)
        res = super().write(vals)
        if vals.get("state") == "confirm":
            newly_confirmed = self.filtered(
                lambda l: old_states.get(l.id) != "confirm"
            )
            _logger.info(
                "WRITE CONFIRM CHECK: newly_confirmed=%s, old_states=%s",
                newly_confirmed.ids,
                {l.id: old_states.get(l.id) for l in newly_confirmed},
            )
            newly_confirmed._notify_leave_submitted()
        return res

    def action_approve(self, check_state=True):
        res = super().action_approve(check_state=check_state)

        # For 'both' validation type: after first approval, notify second approver
        for leave in self.filtered(lambda l: l.validation_type == "both" and l.state == "validate1"):
            partners = leave._get_approver_partners()
            if partners:
                leave._send_leave_email("mail_template_leave_second_approval", partners.ids)

        return res

    def action_validate(self):
        res = super().action_validate()

        # Notify employee that leave is approved
        for leave in self:
            employee_partner = leave.employee_id.work_contact_id or (
                leave.employee_id.user_id and leave.employee_id.user_id.partner_id
            )
            if employee_partner:
                leave._send_leave_email(
                    "mail_template_leave_approved", [employee_partner.id]
                )

        return res

    def action_refuse(self):
        res = super().action_refuse()

        # Notify employee that leave is refused
        for leave in self:
            employee_partner = leave.employee_id.work_contact_id or (
                leave.employee_id.user_id and leave.employee_id.user_id.partner_id
            )
            if employee_partner:
                leave._send_leave_email(
                    "mail_template_leave_refused", [employee_partner.id]
                )

        return res
