# -*- coding: utf-8 -*-
# from odoo import http


# class InfsTimeOff(http.Controller):
#     @http.route('/infs_time_off/infs_time_off', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/infs_time_off/infs_time_off/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('infs_time_off.listing', {
#             'root': '/infs_time_off/infs_time_off',
#             'objects': http.request.env['infs_time_off.infs_time_off'].search([]),
#         })

#     @http.route('/infs_time_off/infs_time_off/objects/<model("infs_time_off.infs_time_off"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('infs_time_off.object', {
#             'object': obj
#         })

