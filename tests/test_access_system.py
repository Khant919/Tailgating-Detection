import unittest
import time

from src.access_system import AccessController


class AccessControllerTests(unittest.TestCase):
    def test_swipe_payload_is_stored_and_consumed(self):
        controller = AccessController(port=5001, swipe_timeout=5)
        client = controller.app.test_client()

        response = client.post(
            '/swipe',
            json={'employee_id': 'EMP1234', 'name': 'Alice Smith'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'ok')

        result = controller.check_for_tailgate()
        self.assertEqual(result['status'], 'authorized')
        self.assertEqual(result['employee']['employee_id'], 'EMP1234')
        self.assertEqual(result['employee']['name'], 'Alice Smith')

    def test_tailgate_returns_last_host_when_no_swipe_is_active(self):
        controller = AccessController(port=5002, swipe_timeout=1)
        client = controller.app.test_client()

        client.post('/swipe', json={'employee_id': 'EMP9999', 'name': 'Bob Jones'})
        first_result = controller.check_for_tailgate()
        self.assertEqual(first_result['status'], 'authorized')

        time.sleep(1.2)
        second_result = controller.check_for_tailgate()
        self.assertEqual(second_result['status'], 'tailgate')
        self.assertEqual(second_result['host_employee']['employee_id'], 'EMP9999')


if __name__ == '__main__':
    unittest.main()
