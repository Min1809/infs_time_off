# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AccrualPlanLevel(models.Model):
    _inherit = "hr.leave.accrual.level"

    carryover_has_validity = fields.Boolean(
        string="Carry-over Validity",
        help="Give the carried-over amount its own validity period so it expires automatically.",
    )

    carryover_validity_count = fields.Integer(
        string="Validity Period",
        default=1,
    )

    carryover_validity_type = fields.Selection(
        [('day', 'Days'),
         ('month', 'Months')],
        string="Validity Unit",
        default='month',
        required=True,
    )

    @api.constrains('carryover_has_validity', 'carryover_validity_count')
    def _check_carryover_validity_count(self):
        for level in self:
            if level.carryover_has_validity and level.carryover_validity_count <= 0:
                raise ValidationError(_(
                    "The carry-over validity period must be greater than 0."
                ))
