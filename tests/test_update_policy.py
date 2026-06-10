from __future__ import annotations

import unittest

from app.services.update_policy import build_update_plan


class UpdatePolicyTests(unittest.TestCase):
    def test_runtime_only_update_restarts_deckpilot(self) -> None:
        plan = build_update_plan(
            ['app/services/deck_controller.py', 'app/player/mpv_controller.py'],
            platform_name='linux',
            install_mode='systemd',
            automatic_reboot_available=True,
            update_available=True,
        )

        self.assertFalse(plan['reboot_required'])
        self.assertEqual(plan['restart_target'], 'deckpilot')

    def test_boot_screen_update_requires_pi_reboot(self) -> None:
        plan = build_update_plan(
            ['scripts/show_boot_ip.py'],
            platform_name='linux',
            install_mode='systemd',
            automatic_reboot_available=True,
            update_available=True,
        )

        self.assertTrue(plan['reboot_required'])
        self.assertEqual(plan['restart_target'], 'raspberry_pi')
        self.assertEqual(plan['reboot_trigger_files'], ['scripts/show_boot_ip.py'])

    def test_unit_definition_changes_recommend_bootstrap_refresh(self) -> None:
        plan = build_update_plan(
            ['scripts/bootstrap.sh', 'app/main.py'],
            platform_name='linux',
            install_mode='systemd',
            automatic_reboot_available=True,
            update_available=True,
        )

        self.assertFalse(plan['reboot_required'])
        self.assertEqual(plan['restart_target'], 'deckpilot')
        self.assertTrue(plan['bootstrap_refresh_recommended'])
        self.assertEqual(plan['system_unit_files'], ['scripts/bootstrap.sh'])
        self.assertIn('re-run', plan['restart_notice'])

    def test_runtime_change_does_not_recommend_bootstrap_refresh(self) -> None:
        plan = build_update_plan(
            ['app/main.py'],
            platform_name='linux',
            install_mode='systemd',
            automatic_reboot_available=True,
            update_available=True,
        )

        self.assertFalse(plan['bootstrap_refresh_recommended'])
        self.assertNotIn('re-run', plan['restart_notice'])

    def test_manual_install_does_not_recommend_bootstrap_refresh(self) -> None:
        plan = build_update_plan(
            ['deploy/pideck-open.service'],
            platform_name='darwin',
            install_mode='manual',
            automatic_reboot_available=False,
            update_available=True,
        )

        self.assertFalse(plan['bootstrap_refresh_recommended'])

    def test_unknown_remote_changes_keep_automatic_decision(self) -> None:
        plan = build_update_plan(
            [],
            platform_name='linux',
            install_mode='systemd',
            automatic_reboot_available=True,
            update_available=True,
        )

        self.assertIsNone(plan['reboot_required'])
        self.assertEqual(plan['restart_target'], 'auto')


if __name__ == '__main__':
    unittest.main()
