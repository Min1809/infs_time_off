# -*- coding: utf-8 -*-
{
    'name': "Leave Request",

    'summary': "Custom Leave Request and Time Off Management",

    'description': """
Long description of module's purpose
    """,

    'author': "INFS",
    'website': "https://www.infinityitsuccess.com.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'hr_holidays', 'mail'],

    # always loaded
    'data': [
        'security/infs_time_off_security.xml',
        'security/ir.model.access.csv',
        'views/views.xml',
        'views/templates.xml',
        'views/res_config_settings_views.xml',
        'views/hr_leave_type_views.xml',
        'views/hr_leave_accrual_level_views.xml',
        'views/hr_leave_allocation_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_leave_employee_balance_report_views.xml',
        'views/hr_leave_calendar_views.xml',
        'views/hr_leave_approval_views.xml',
        'views/mail_templates.xml',
        'data/cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'infs_time_off/static/src/dashboard/time_off_card_patch.js',
            'infs_time_off/static/src/dashboard/time_off_card_patch.xml',
        ],
    },
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
    'post_init_hook': 'post_init_hook',
}

