# -*- coding: utf-8 -*-

# from odoo import models, fields, api


# class infs_time_off(models.Model):
#     _name = 'infs_time_off.infs_time_off'
#     _description = 'infs_time_off.infs_time_off'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

