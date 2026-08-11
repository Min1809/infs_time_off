/** @odoo-module **/

import { TimeOffCard, TimeOffCardMobile } from "@hr_holidays/dashboard/time_off_card";

// Patch components to use our modified templates with duration_display support
TimeOffCard.template = "infs_time_off.TimeOffCard";
TimeOffCardMobile.template = "infs_time_off.TimeOffCardMobile";
