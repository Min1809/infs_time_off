# -*- coding: utf-8 -*-

from . import controllers
from . import models


def post_init_hook(env):
    """Ensure user_groups_view is regenerated, menu groups are strictly set, and parent approver group is synced."""
    env['res.groups']._update_user_groups_view()
    env['hr.employee']._sync_parent_approver_group()
    menu = env.ref('infs_time_off.menu_hr_leave_waiting_my_approval', raise_if_not_found=False)
    group = env.ref('infs_time_off.group_leave_parent_approver', raise_if_not_found=False)
    if menu and group:
        menu.sudo().write({'groups_id': [(6, 0, [group.id])]})
