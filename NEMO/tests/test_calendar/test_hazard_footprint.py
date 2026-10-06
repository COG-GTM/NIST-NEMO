import calendar
from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from NEMO.models import Account, Area, Project, Reservation, ScheduledOutage, Tool, User
from NEMO.tests.test_utilities import NEMOTestCaseMixin

RESERVED_MESSAGE = "hazard footprint includes the {}, which is reserved by someone else at this time."
OUTAGE_MESSAGE = "hazard footprint includes the {}, which has a scheduled outage at this time."


class HazardFootprintTestCase(NEMOTestCaseMixin, TestCase):
    def setUp(self):
        owner = User.objects.create(username="owner", first_name="Tool", last_name="Owner")
        self.range_area = Area.objects.create(name="North Range")
        self.sub_area = Area.objects.create(name="Road 7", parent_area=self.range_area)
        self.other_area = Area.objects.create(name="South Range")
        self.tool = Tool.objects.create(name="launcher", primary_owner=owner)
        self.tool._hazard_footprint.add(self.range_area)
        account = Account.objects.create(name="account1")
        project = Project.objects.create(name="project1", account=account)
        self.user = User.objects.create(
            username="operator", first_name="Range", last_name="Operator", training_required=False
        )
        self.user.qualifications.add(self.tool)
        self.user.projects.add(project)
        self.other_user = User.objects.create(username="convoy", first_name="Convoy", last_name="Lead")
        self.staff = User.objects.create(
            username="staff", first_name="Staff", last_name="Member", is_staff=True, training_required=False
        )
        self.start = timezone.now().replace(second=0, microsecond=0) + timedelta(hours=2)
        self.end = self.start + timedelta(hours=1)

    def reserve_area(self, area, start, end, user=None):
        user = user or self.other_user
        return Reservation.objects.create(area=area, start=start, end=end, user=user, creator=user, short_notice=False)

    def add_outage(self, area, start, end):
        return ScheduledOutage.objects.create(area=area, start=start, end=end, creator=self.staff, title="Closure")

    @staticmethod
    def server_timestamp(value: datetime) -> int:
        # The calendar view reads UNIX timestamps as wall-clock time in the server's timezone.
        return calendar.timegm(timezone.localtime(value).replace(tzinfo=None).utctimetuple())

    def book_tool(self, start: datetime = None, end: datetime = None, user: User = None):
        self.login_as(user or self.user)
        data = {
            "start": self.server_timestamp(start or self.start),
            "end": self.server_timestamp(end or self.end),
            "item_id": self.tool.id,
            "item_type": "tool",
        }
        return self.client.post(reverse("create_reservation"), data, follow=True)

    def tool_reservation_count(self):
        return Reservation.objects.filter(tool=self.tool, cancelled=False).count()

    def test_overlapping_area_reservation_by_someone_else_blocks(self):
        self.reserve_area(self.range_area, self.start + timedelta(minutes=30), self.end + timedelta(minutes=30))
        response = self.book_tool()
        self.assertContains(response, RESERVED_MESSAGE.format(self.range_area), status_code=200)
        self.assertEqual(self.tool_reservation_count(), 0)

    def test_overlapping_sub_area_reservation_blocks(self):
        self.reserve_area(self.sub_area, self.start - timedelta(minutes=30), self.start + timedelta(minutes=1))
        response = self.book_tool()
        self.assertContains(response, RESERVED_MESSAGE.format(self.range_area), status_code=200)
        self.assertEqual(self.tool_reservation_count(), 0)

    def test_identical_start_times_block(self):
        self.reserve_area(self.range_area, self.start, self.start + timedelta(minutes=15))
        response = self.book_tool()
        self.assertContains(response, RESERVED_MESSAGE.format(self.range_area), status_code=200)
        self.assertEqual(self.tool_reservation_count(), 0)

    def test_back_to_back_reservations_are_allowed(self):
        self.reserve_area(self.range_area, self.start - timedelta(hours=1), self.start)
        self.reserve_area(self.range_area, self.end, self.end + timedelta(hours=1))
        self.add_outage(self.range_area, self.end, self.end + timedelta(hours=2))
        response = self.book_tool()
        self.assertNotContains(response, "hazard footprint", status_code=200)
        self.assertEqual(self.tool_reservation_count(), 1)

    def test_scheduled_outage_on_footprint_area_blocks(self):
        self.add_outage(self.sub_area, self.start + timedelta(minutes=10), self.start + timedelta(minutes=20))
        response = self.book_tool()
        self.assertContains(response, OUTAGE_MESSAGE.format(self.range_area), status_code=200)
        self.assertEqual(self.tool_reservation_count(), 0)

    def test_own_area_reservation_does_not_block(self):
        self.reserve_area(self.range_area, self.start, self.end, user=self.user)
        response = self.book_tool()
        self.assertNotContains(response, "hazard footprint", status_code=200)
        self.assertEqual(self.tool_reservation_count(), 1)

    def test_area_outside_footprint_does_not_block(self):
        self.reserve_area(self.other_area, self.start, self.end)
        self.add_outage(self.other_area, self.start, self.end)
        response = self.book_tool()
        self.assertNotContains(response, "hazard footprint", status_code=200)
        self.assertEqual(self.tool_reservation_count(), 1)

    def test_staff_cannot_bypass_footprint_conflict(self):
        self.staff.qualifications.add(self.tool)
        self.staff.projects.add(Project.objects.get(name="project1"))
        self.reserve_area(self.range_area, self.start, self.end)
        response = self.book_tool(user=self.staff)
        self.assertContains(response, RESERVED_MESSAGE.format(self.range_area), status_code=200)
        self.assertEqual(self.tool_reservation_count(), 0)
