# -*- coding: utf-8 -*-

from . import controllers
from . import models


def post_init_hook(env):
    """Ensure user_groups_view is regenerated after module installation or upgrade."""
    env['res.groups']._update_user_groups_view()
