import unittest
from unittest.mock import patch

from test_online import FakeSupabase
from app import create_app


class PromptConnectionRegression(unittest.TestCase):
    def setUp(self):
        self.store = FakeSupabase()
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-session-secret-32-characters-long',
                               'MASTER_KEY': 'test-master-secret-32-characters-long',
                               'ALLOWED_EMAILS': 'alice@example.com'}, self.store)
        self.client = self.app.test_client()
        self.engine = self.app.extensions['studio_engine']
        csrf = self.request('/auth/csrf').json['csrf']
        self.csrf = self.request('/auth/login', {'email': 'alice@example.com',
                                                'password': 'test-password-only'}, csrf).json['csrf']
        settings = self.request('/api/state').json['settings']
        settings['prompt'].update(url='https://elysiumai.net/v1', model='google/gemini-4-neon-ag')
        self.request('/api/settings', {'settings': settings, 'keys': {'prompt': 'test-private-key'}}, self.csrf)

    def request(self, path, body=None, csrf=''):
        return self.client.open(path, base_url='https://studio.example',
                                method='POST' if body is not None else 'GET', json=body,
                                headers={'Origin': 'https://studio.example', 'X-Studio-Request': 'local',
                                         'X-CSRF-Token': csrf})

    def check(self):
        return self.request('/api/test-connection', {'provider': 'prompt'}, self.csrf)

    def test_reasoning_probe_has_room_for_thinking_and_keeps_selected_model(self):
        def reasoning_api(url, key, payload=None, timeout=None):
            self.assertEqual(url, 'https://elysiumai.net/v1/chat/completions')
            self.assertEqual(key, 'test-private-key')
            self.assertEqual(payload['model'], 'google/gemini-4-neon-ag')
            self.assertNotIn('reasoning_effort', payload)
            self.assertLessEqual(payload['max_tokens'], 8192)
            if payload['max_tokens'] < 2048:
                raise self.engine.ProviderError('output budget exhausted', 400, 'output_budget_exhausted')
            return {'choices': [{'message': {'content': 'OK'}, 'finish_reason': 'stop'}]}
        with patch.object(self.engine, 'api_request', side_effect=reasoning_api) as api:
            result = self.check()
        self.assertEqual(result.status_code, 200, result.json)
        self.assertTrue(result.json['ok'])
        api.assert_called_once()
        self.assertNotIn('test-private-key', result.get_data(as_text=True))

    def test_empty_reasoning_and_filtered_responses_are_not_reported_connected(self):
        for reason in ('length', 'content_filter'):
            with self.subTest(reason=reason), patch.object(self.engine, 'api_request', return_value={
                'choices': [{'message': {'content': None, 'reasoning_content': 'thinking'}, 'finish_reason': reason}]
            }):
                result = self.check()
                self.assertEqual(result.status_code, 400, result.json)
                self.assertIn('не вернула текст', result.json['error'])

    def test_provider_errors_keep_diagnostic_details_without_paid_retries(self):
        for code, status in [('output_budget_exhausted', 400), ('invalid_api_key', 401)]:
            error = self.engine.ProviderError('HTTP ' + str(status) + ' · ' + code, status, code, 'test-request-id')
            with self.subTest(code=code), patch.object(self.engine, 'api_request', side_effect=error) as api:
                result = self.check()
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json['code'], code)
                self.assertEqual(result.json['http_status'], status)
                self.assertEqual(result.json['request_id'], 'test-request-id')
                if code == 'output_budget_exhausted':
                    self.assertIn('лимит одного ответа', result.json['error'])
                api.assert_called_once()

    def test_text_parts_are_accepted_as_a_real_answer(self):
        with patch.object(self.engine, 'api_request', return_value={
            'choices': [{'message': {'content': [{'type': 'text', 'text': 'OK'}]}, 'finish_reason': 'stop'}]
        }):
            self.assertEqual(self.check().status_code, 200)


if __name__ == '__main__':
    unittest.main()
