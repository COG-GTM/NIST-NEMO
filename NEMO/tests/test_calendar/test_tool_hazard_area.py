import calendar
from datetime import datetime, timedelta

from django.test import TransactionTestCase
from django.urls import reverse

from NEMO.models import Account, Area, Project, Reservation, ScheduledOutage, Tool, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin

HAZARD_RESERVED = "is a hazard area for this tool and is reserved by another user at this time"
HAZARD_OUTAGE = "is a hazard area for this tool and is closed for a scheduled outage at this time"


class ToolHazardAreaTestCase(NEMOTestCaseMixin, TransactionTestCase):
    def setUp(self):
        owner = User.objects.create(username="owner", first_name="Tool", last_name="Owner")
        self.building = Area.objects.create(name="Building")
        self.hazard_area = Area.objects.create(name="Laser Bay", parent_area=self.building)
        self.tool = Tool.objects.create(name="laser", primary_owner=owner, _category="Optics", _operational=True)
        self.tool.hazard_areas.add(self.hazard_area)
        account = Account.objects.create(name="account")
        project = Project.objects.create(name="project", account=account)
        self.consumer = User.objects.create(
            username="consumer", first_name="Con", last_name="Sumer", training_required=False
        )
        self.consumer.qualifications.add(self.tool)
        self.consumer.projects.add(project)
        self.other_user = User.objects.create(username="other", first_name="Other", last_name="User")
        self.staff = User.objects.create(username="staff", first_name="Staff", last_name="Member", is_staff=True)
        self.start = (datetime.now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        self.end = self.start + timedelta(hours=1)

    def reserve_tool(self, as_user: User, extra_data=None):
        data = {
            "start": calendar.timegm(self.start.utctimetuple()),
            "end": calendar.timegm(self.end.utctimetuple()),
            "item_id": self.tool.id,
            "item_type": "tool",
        }
        data.update(extra_data or {})
        self.login_as(as_user)
        return self.client.post(reverse("create_reservation"), data, follow=True)

    def reserve_area(self, user: User, start: datetime, end: datetime, area: Area = None):
        return Reservation.objects.create(
            area=area or self.hazard_area,
            user=user,
            creator=user,
            start=start.astimezone(),
            end=end.astimezone(),
            short_notice=False,
        )

    def create_outage(self, area: Area, start: datetime, end: datetime):
        return ScheduledOutage.objects.create(
            area=area, title="Outage", creator=self.staff, start=start.astimezone(), end=end.astimezone()
        )

    def tool_reservation_count(self):
        return Reservation.objects.filter(tool=self.tool, cancelled=False).count()

    def test_blocked_when_hazard_area_reserved_by_other_user(self):
        self.reserve_area(self.other_user, self.start + timedelta(minutes=30), self.end + timedelta(minutes=30))
        response = self.reserve_tool(self.consumer)
        self.assertContains(response, HAZARD_RESERVED)
        self.assertEqual(self.tool_reservation_count(), 0)

    def test_blocked_when_hazard_area_closed_for_outage(self):
        self.create_outage(self.hazard_area, self.start - timedelta(minutes=30), self.start + timedelta(minutes=30))
        response = self.reserve_tool(self.consumer)
        self.assertContains(response, HAZARD_OUTAGE)
        self.assertEqual(self.tool_reservation_count(), 0)

    def test_blocked_when_parent_of_hazard_area_closed_for_outage(self):
        self.create_outage(self.building, self.start, self.end)
        response = self.reserve_tool(self.consumer)
        self.assertContains(response, HAZARD_OUTAGE)
        self.assertEqual(self.tool_reservation_count(), 0)

    def test_staff_override_still_blocked_by_other_user_reservation(self):
        self.reserve_area(self.other_user, self.start, self.end)
        response = self.reserve_tool(self.staff, {"impersonate": self.consumer.id, "explicit_policy_override": "true"})
        self.assertContains(response, HAZARD_RESERVED)
        self.assertNotContains(response, "Override policy")
        self.assertEqual(self.tool_reservation_count(), 0)

    def test_staff_override_still_blocked_by_outage(self):
        self.create_outage(self.hazard_area, self.start, self.end)
        response = self.reserve_tool(self.staff, {"explicit_policy_override": "true"})
        self.assertContains(response, HAZARD_OUTAGE)
        self.assertNotContains(response, "Override policy")
        self.assertEqual(self.tool_reservation_count(), 0)

    def test_back_to_back_with_other_user_and_outage_allowed(self):
        self.reserve_area(self.other_user, self.start - timedelta(hours=1), self.start)
        self.reserve_area(self.other_user, self.end, self.end + timedelta(hours=1))
        self.create_outage(self.hazard_area, self.start - timedelta(hours=2), self.start)
        self.create_outage(self.hazard_area, self.end, self.end + timedelta(hours=2))
        response = self.reserve_tool(self.consumer)
        self.assertNotContains(response, HAZARD_RESERVED)
        self.assertNotContains(response, HAZARD_OUTAGE)
        self.assertEqual(self.tool_reservation_count(), 1)

    def test_own_hazard_area_reservation_allowed(self):
        self.reserve_area(self.consumer, self.start, self.end)
        response = self.reserve_tool(self.consumer)
        self.assertNotContains(response, HAZARD_RESERVED)
        self.assertEqual(self.tool_reservation_count(), 1)

    def test_moving_into_hazard_area_reservation_blocked(self):
        self.assertEqual(self.reserve_tool(self.consumer).status_code, 200)
        reservation = Reservation.objects.get(tool=self.tool)
        self.reserve_area(self.other_user, self.end, self.end + timedelta(hours=1))
        response = self.client.post(reverse("move_reservation"), {"delta": 30, "id": reservation.id}, follow=True)
        self.assertContains(response, HAZARD_RESERVED)
        reservation.refresh_from_db()
        self.assertFalse(reservation.cancelled)

    def test_child_tool_uses_parent_hazard_areas(self):
        child_tool = Tool.objects.create(name="laser child", parent_tool=self.tool, visible=True)
        self.assertEqual(list(child_tool.hazard_areas.all()), [self.hazard_area])
