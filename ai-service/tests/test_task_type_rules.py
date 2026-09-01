import unittest

from app.services.diagnose_rules import (
    detect_task_type,
    should_force_missing_audience,
)

class TaskTypeRuleTest(unittest.TestCase):

    def test_meeting_summary_is_report(self):
        text = "\ud68c\uc758 \ub0b4\uc6a9 \uc815\ub9ac\ud574 \uc918"
        self.assertEqual(detect_task_type(text), "report")

    def test_meeting_minutes_is_report(self):
        text = "\ud68c\uc758\ub85d \uc791\uc131\ud574 \uc918"
        self.assertEqual(detect_task_type(text), "report")

    def test_meeting_email_remains_email(self):
        text = "\ud68c\uc758 \uc77c\uc815 \uc548\ub0b4 \uba54\uc77c \uc791\uc131\ud574 \uc918"
        self.assertEqual(detect_task_type(text), "email")

    def test_existing_weekly_report_rule_is_preserved(self):
        text = "\uc8fc\uac04\ubcf4\uace0\uc11c \uc791\uc131\ud574 \uc918"
        self.assertEqual(detect_task_type(text), "report")

    def test_meeting_summary_with_object_particle_is_report(self):
        text = "회의 내용을 정리해줘"
        self.assertEqual(detect_task_type(text), "report")

    def test_meeting_summary_with_object_particle_and_summary_is_report(self):
        text = "회의 내용을 요약해줘"
        self.assertEqual(detect_task_type(text), "report")

    def test_meeting_content_email_remains_email(self):
        text = "회의 내용을 메일로 보내줘"
        self.assertEqual(detect_task_type(text), "email")

    def test_team_chat_notification_is_notice(self):
        text = "개발팀 채팅방에 오늘 배포가 한 시간 늦어진다고 알려줘"
        self.assertEqual(detect_task_type(text), "notice")

    def test_messenger_notification_is_notice(self):
        text = "메신저로 개발팀에 테스트 완료 후 다시 공유한다고 알려줘"
        self.assertEqual(detect_task_type(text), "notice")

    def test_existing_email_rule_is_preserved(self):
        text = "김대리에게 일정 지연 메일을 작성해줘"
        self.assertEqual(detect_task_type(text), "email")

    def test_email_without_recipient_forces_missing_audience(self):
        text = "프로젝트 일정이 늦어진다고 메일 써줘"

        self.assertTrue(
            should_force_missing_audience(
                text,
                detect_task_type(text),
            )
        )

    def test_email_with_recipient_does_not_force_missing_audience(self):
        text = "김대리에게 프로젝트 일정이 늦어진다고 메일 써줘"

        self.assertFalse(
            should_force_missing_audience(
                text,
                detect_task_type(text),
            )
        )


if __name__ == "__main__":
    unittest.main()
