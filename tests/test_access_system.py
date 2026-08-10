import unittest
import time

from src.access_system import AccessController


class AccessControllerTests(unittest.TestCase):
    def test_swipe_payload_is_stored_and_consumed(self):
        controller = AccessController(port=5001, swipe_timeout=5)
        client = controller._app.test_client()

        response = client.post(
            '/swipe',
            json={'employee_id': 'EMP1234', 'name': 'Alice Smith'},
            headers={'x-api-key': 'dev-secret-api-key-12345'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'ok')

        result = controller.check_for_tailgate()
        self.assertEqual(result['status'], 'authorized')
        self.assertEqual(result['employee']['employee_id'], 'EMP1234')
        self.assertEqual(result['employee']['name'], 'Alice Smith')

    def test_tailgate_returns_last_host_when_no_swipe_is_active(self):
        controller = AccessController(port=5002, swipe_timeout=1)
        client = controller._app.test_client()

        client.post(
            '/swipe', 
            json={'employee_id': 'EMP9999', 'name': 'Bob Jones'},
            headers={'x-api-key': 'dev-secret-api-key-12345'}
        )
        first_result = controller.check_for_tailgate()
        self.assertEqual(first_result['status'], 'authorized')

        time.sleep(1.2)
        second_result = controller.check_for_tailgate()
        self.assertEqual(second_result['status'], 'tailgate')
        self.assertEqual(second_result['host_employee']['employee_id'], 'EMP9999')

    def test_swipe_jwt_token_validation(self):
        import jwt
        from config import JWT_SECRET
        
        controller = AccessController(port=5003, swipe_timeout=5)
        client = controller._app.test_client()

        # 1. Test valid JWT authentication
        payload = {'employee_id': 'EMP001', 'name': 'Alice Smith'}
        token = jwt.encode(payload, JWT_SECRET, algorithm='HS256')
        
        response = client.post(
            '/swipe',
            headers={'Authorization': f'Bearer {token}'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'ok')
        
        result = controller.check_for_tailgate()
        self.assertEqual(result['status'], 'authorized')
        self.assertEqual(result['employee']['employee_id'], 'EMP001')
        self.assertEqual(result['employee']['name'], 'Alice Smith')

        # 2. Test invalid JWT signature authentication
        bad_token = jwt.encode(payload, "wrong-secret-key", algorithm='HS256')
        response_bad = client.post(
            '/swipe',
            headers={'Authorization': f'Bearer {bad_token}'}
        )
        self.assertEqual(response_bad.status_code, 401)
        self.assertEqual(response_bad.get_json()['status'], 'error')


if __name__ == '__main__':
    unittest.main()
