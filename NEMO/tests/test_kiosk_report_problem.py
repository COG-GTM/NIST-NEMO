from django.test import TestCase, override_settings
from django.urls import reverse

from NEMO.models import Account, Project, Task, Tool, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin, create_user_and_project


class KioskReportProblemTestCase(NEMOTestCaseMixin, TestCase):
    tool = None

    def setUp(self):
        self.owner = User.objects.create(username="owner", first_name="Tool", last_name="Owner")
        self.tool = Tool.objects.create(
            name="test_tool",
            _category="test",
            _location="office",
            _primary_owner=self.owner,
            visible=True,
            _operation_mode=Tool.OperationMode.REGULAR,
        )
        self.user, self.project = create_user_and_project(add_kiosk_permission=True)
        self.user.badge_number = 123456
        self.user.save()

    def _report_problem_data(self, force_shutdown=False):
        return {
            "tool": self.tool.id,
            "customer_id": self.user.id,
            "back": "back_to_start",
            "action": "create",
            "description": "Something is broken",
            "force_shutdown": force_shutdown,
            "safety_hazard": False,
            "urgency": Task.Urgency.NORMAL,
        }

    @override_settings(ALLOW_CONDITIONAL_URLS=True)
    def test_report_problem_with_conditional_urls_enabled(self):
        """When ALLOW_CONDITIONAL_URLS=True, problem reports should work normally."""
        self.login_as(self.user)
        data = self._report_problem_data(force_shutdown=False)
        response = self.client.post(reverse("report_problem_from_kiosk"), data)
        self.assertEqual(response.status_code, 302)
        task = Task.objects.last()
        self.assertIsNotNone(task)
        self.assertFalse(task.force_shutdown)

    @override_settings(ALLOW_CONDITIONAL_URLS=True)
    def test_report_problem_with_force_shutdown_on_campus(self):
        """When on-campus (ALLOW_CONDITIONAL_URLS=True), force_shutdown should be allowed."""
        self.login_as(self.user)
        data = self._report_problem_data(force_shutdown=True)
        response = self.client.post(reverse("report_problem_from_kiosk"), data)
        self.assertEqual(response.status_code, 302)
        task = Task.objects.last()
        self.assertIsNotNone(task)
        self.assertTrue(task.force_shutdown)

    @override_settings(ALLOW_CONDITIONAL_URLS=False)
    def test_report_problem_without_force_shutdown_off_campus(self):
        """When off-campus (ALLOW_CONDITIONAL_URLS=False), problem reports without
        force_shutdown should work normally."""
        self.login_as(self.user)
        data = self._report_problem_data(force_shutdown=False)
        response = self.client.post(reverse("report_problem_from_kiosk"), data)
        self.assertEqual(response.status_code, 302)
        task = Task.objects.last()
        self.assertIsNotNone(task)
        self.assertFalse(task.force_shutdown)

    @override_settings(ALLOW_CONDITIONAL_URLS=False)
    def test_report_problem_with_force_shutdown_off_campus_saves_task(self):
        """When off-campus (ALLOW_CONDITIONAL_URLS=False) and force_shutdown is requested,
        the task should still be saved but force_shutdown should be set to False."""
        self.login_as(self.user)
        data = self._report_problem_data(force_shutdown=True)
        response = self.client.post(reverse("report_problem_from_kiosk"), data)
        # Should redirect successfully (task saved), not render an error page
        self.assertEqual(response.status_code, 302)
        task = Task.objects.last()
        self.assertIsNotNone(task)
        # force_shutdown should be overridden to False when off-campus
        self.assertFalse(task.force_shutdown)
        self.assertEqual(task.problem_description, "Something is broken")

    @override_settings(ALLOW_CONDITIONAL_URLS=False)
    def test_report_problem_off_campus_force_shutdown_tool_stays_operational(self):
        """When off-campus with force_shutdown requested, the tool should remain operational
        since force_shutdown is suppressed."""
        self.tool._operational = True
        self.tool.save()
        self.login_as(self.user)
        data = self._report_problem_data(force_shutdown=True)
        response = self.client.post(reverse("report_problem_from_kiosk"), data)
        self.assertEqual(response.status_code, 302)
        self.tool.refresh_from_db()
        # Tool should remain operational since force_shutdown was suppressed
        self.assertTrue(self.tool.operational)

    @override_settings(ALLOW_CONDITIONAL_URLS=True)
    def test_report_problem_on_campus_force_shutdown_tool_goes_down(self):
        """When on-campus with force_shutdown requested, the tool should be shut down."""
        self.tool._operational = True
        self.tool.save()
        self.login_as(self.user)
        data = self._report_problem_data(force_shutdown=True)
        response = self.client.post(reverse("report_problem_from_kiosk"), data)
        self.assertEqual(response.status_code, 302)
        self.tool.refresh_from_db()
        # Tool should be shut down since force_shutdown is allowed on-campus
        self.assertFalse(self.tool.operational)

    def test_report_problem_invalid_form(self):
        """Invalid form data should return an error regardless of ALLOW_CONDITIONAL_URLS."""
        self.login_as(self.user)
        # Missing required 'description' field for create action
        data = {
            "tool": self.tool.id,
            "customer_id": self.user.id,
            "back": "back_to_start",
            "action": "create",
            "description": "",
            "force_shutdown": False,
            "safety_hazard": False,
            "urgency": Task.Urgency.NORMAL,
        }
        response = self.client.post(reverse("report_problem_from_kiosk"), data)
        # Should render the form with errors (200), not redirect
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Task.objects.count(), 0)

    @override_settings(ALLOW_CONDITIONAL_URLS=False)
    def test_kiosk_enable_tool_blocked_off_campus(self):
        """When off-campus (ALLOW_CONDITIONAL_URLS=False), kiosk enable_tool should be blocked."""
        self.login_as(self.user)
        data = {
            "tool_id": self.tool.id,
            "customer_id": self.user.id,
            "project_id": self.project.id,
        }
        response = self.client.post(reverse("enable_tool_from_kiosk"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tool control is only available on campus")

    @override_settings(ALLOW_CONDITIONAL_URLS=False)
    def test_kiosk_disable_tool_blocked_off_campus(self):
        """When off-campus (ALLOW_CONDITIONAL_URLS=False), kiosk disable_tool should be blocked."""
        self.login_as(self.user)
        data = {
            "tool_id": self.tool.id,
            "customer_id": self.user.id,
        }
        response = self.client.post(reverse("disable_tool_from_kiosk"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tool control is only available on campus")


class WebTaskCreationTestCase(NEMOTestCaseMixin, TestCase):
    """Tests for the web interface task creation (NEMO/views/tasks.py) with ALLOW_CONDITIONAL_URLS."""

    def setUp(self):
        self.owner = User.objects.create(username="owner", first_name="Tool", last_name="Owner", is_staff=True)
        self.tool = Tool.objects.create(
            name="test_tool",
            _category="test",
            _location="office",
            _primary_owner=self.owner,
            visible=True,
            _operation_mode=Tool.OperationMode.REGULAR,
        )
        self.user, self.project = create_user_and_project(is_staff=True)
        self.user.badge_number = 123456
        self.user.save()

    def _create_task_data(self, force_shutdown=False):
        return {
            "tool": self.tool.id,
            "urgency": Task.Urgency.NORMAL,
            "action": "create",
            "description": "Something is broken",
            "force_shutdown": force_shutdown,
            "safety_hazard": False,
        }

    @override_settings(ALLOW_CONDITIONAL_URLS=False)
    def test_web_task_creation_force_shutdown_suppressed_off_campus(self):
        """When off-campus (ALLOW_CONDITIONAL_URLS=False) and force_shutdown is requested,
        the task should be saved but force_shutdown should be suppressed to False."""
        self.login_as(self.user)
        data = self._create_task_data(force_shutdown=True)
        response = self.client.post(reverse("create_task"), data)
        # Should redirect (task saved), not render error page
        self.assertEqual(response.status_code, 302)
        task = Task.objects.last()
        self.assertIsNotNone(task)
        # force_shutdown should be suppressed to False when off-campus
        self.assertFalse(task.force_shutdown)

    @override_settings(ALLOW_CONDITIONAL_URLS=False)
    def test_web_task_creation_without_force_shutdown_off_campus(self):
        """When off-campus without force_shutdown, task should be saved normally."""
        self.login_as(self.user)
        data = self._create_task_data(force_shutdown=False)
        response = self.client.post(reverse("create_task"), data)
        self.assertEqual(response.status_code, 302)
        task = Task.objects.last()
        self.assertIsNotNone(task)
        self.assertFalse(task.force_shutdown)

    @override_settings(ALLOW_CONDITIONAL_URLS=True)
    def test_web_task_creation_force_shutdown_allowed_on_campus(self):
        """When on-campus (ALLOW_CONDITIONAL_URLS=True), force_shutdown should be allowed."""
        self.login_as(self.user)
        data = self._create_task_data(force_shutdown=True)
        response = self.client.post(reverse("create_task"), data)
        self.assertEqual(response.status_code, 302)
        task = Task.objects.last()
        self.assertIsNotNone(task)
        self.assertTrue(task.force_shutdown)
