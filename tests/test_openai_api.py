"""Offline tests for the OpenAI-compatible client and REST adapter."""

from __future__ import annotations

import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch
from uuid import uuid4

import requests
from fastapi import HTTPException

from api.routers import openai_api as web
from modules.openai_api import OpenAIAPIError, OpenAIConfigurationError, OpenAIInputError, chat_completion
from modules.openai_api.settings import get_settings
from shared.log_stream import stream_session


class OpenAISettingsTests(unittest.TestCase):
    def test_reads_key_and_uses_openai_default_base_url(self) -> None:
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key', 'OPENAI_MODEL': 'test-model'}, clear=True):
            settings = get_settings()
        self.assertEqual(settings.api_key, 'test-key')
        self.assertEqual(settings.base_url, 'https://api.openai.com/v1')
        self.assertEqual(settings.default_model, 'test-model')
        self.assertEqual(settings.timeout_seconds, 60)

    def test_missing_key_is_rejected(self) -> None:
        with patch.dict(os.environ, {'OPENAI_MODEL': 'test-model'}, clear=True):
            with self.assertRaises(OpenAIConfigurationError):
                get_settings()

    def test_missing_model_is_rejected(self) -> None:
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}, clear=True):
            with self.assertRaises(OpenAIConfigurationError):
                get_settings()

    def test_non_https_api_address_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {'OPENAI_API_KEY': 'test-key', 'OPENAI_MODEL': 'test-model', 'OPENAI_BASE_URL': 'http://api.example'},
            clear=True,
        ):
            with self.assertRaises(OpenAIConfigurationError):
                get_settings()


class OpenAIClientTests(unittest.TestCase):
    def test_sends_openai_compatible_request_and_returns_json(self) -> None:
        expected = {'id': 'completion-id', 'choices': [{'message': {'role': 'assistant', 'content': 'hello'}}]}
        response = Mock()
        response.json.return_value = expected
        environment = {
            'OPENAI_API_KEY': 'test-key',
            'OPENAI_BASE_URL': 'https://provider.example/v1',
            'OPENAI_MODEL': 'test-model',
        }
        with patch.dict(os.environ, environment, clear=True), \
                patch('modules.openai_api.service.requests.post', return_value=response) as post, \
                redirect_stdout(StringIO()):
            result = chat_completion(
                [{'role': 'user', 'content': 'hi'}], temperature=0.4, max_tokens=25, top_p=0.9,
            )

        self.assertEqual(result, expected)
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], 'https://provider.example/v1/chat/completions')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test-key')
        self.assertEqual(kwargs['json']['model'], 'test-model')
        self.assertEqual(kwargs['json']['messages'], [{'role': 'user', 'content': 'hi'}])
        self.assertEqual(kwargs['json']['stream'], False)
        self.assertEqual(kwargs['json']['max_tokens'], 25)
        self.assertNotIn('reasoning', kwargs['json'])
        self.assertNotIn('reasoning_effort', kwargs['json'])
        self.assertEqual(kwargs['timeout'], 60)

    def test_can_disable_reasoning(self) -> None:
        response = Mock()
        response.json.return_value = {'choices': [{'message': {'content': 'hello'}}]}
        environment = {'OPENAI_API_KEY': 'test-key', 'OPENAI_MODEL': 'test-model'}
        with patch.dict(os.environ, environment, clear=True), \
                patch('modules.openai_api.service.requests.post', return_value=response) as post, \
                redirect_stdout(StringIO()):
            chat_completion([{'role': 'user', 'content': 'hi'}], reasoning_enabled=False)

        self.assertEqual(post.call_args.kwargs['json']['reasoning'], {'enabled': False})
        self.assertNotIn('reasoning_effort', post.call_args.kwargs['json'])

    def test_can_enable_reasoning(self) -> None:
        response = Mock()
        response.json.return_value = {'choices': [{'message': {'content': 'hello'}}]}
        environment = {'OPENAI_API_KEY': 'test-key', 'OPENAI_MODEL': 'test-model'}
        with patch.dict(os.environ, environment, clear=True), \
                patch('modules.openai_api.service.requests.post', return_value=response) as post, \
                redirect_stdout(StringIO()):
            chat_completion([{'role': 'user', 'content': 'hi'}], reasoning_enabled=True)

        self.assertEqual(post.call_args.kwargs['json']['reasoning'], {'enabled': True})

    def test_invalid_input_does_not_make_request(self) -> None:
        with patch('modules.openai_api.service.requests.post') as post:
            with self.assertRaises(OpenAIInputError):
                chat_completion([{'role': 'admin', 'content': 'hi'}])
        post.assert_not_called()

    def test_network_failure_does_not_leak_request_details(self) -> None:
        environment = {'OPENAI_API_KEY': 'private-key', 'OPENAI_MODEL': 'test-model'}
        with patch.dict(os.environ, environment, clear=True), \
                patch('modules.openai_api.service.requests.post', side_effect=requests.RequestException('private detail')), \
                redirect_stdout(StringIO()) as output:
            with self.assertRaises(OpenAIAPIError) as error:
                chat_completion([{'role': 'user', 'content': 'private prompt'}])
        self.assertNotIn('private-key', str(error.exception))
        self.assertNotIn('private prompt', output.getvalue())
        self.assertNotIn('private detail', output.getvalue())

    def test_invalid_provider_json_is_rejected(self) -> None:
        response = Mock()
        response.json.side_effect = ValueError('not json')
        environment = {'OPENAI_API_KEY': 'test-key', 'OPENAI_MODEL': 'test-model'}
        with patch.dict(os.environ, environment, clear=True), \
                patch('modules.openai_api.service.requests.post', return_value=response), \
                redirect_stdout(StringIO()):
            with self.assertRaises(OpenAIAPIError):
                chat_completion([{'role': 'user', 'content': 'hi'}])


class OpenAIRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_calls_public_module_entrypoint_without_client_token(self) -> None:
        expected = {'choices': [{'message': {'content': 'hello'}}]}
        request = web.ChatCompletionRequest(
            messages=[web.ChatMessage(role='user', content='hi')], reasoning_enabled=True,
        )
        with patch('api.routers.openai_api.chat_completion', return_value=expected) as completion:
            response = await web.create_chat_completion(request)
        self.assertEqual(response, expected)
        self.assertTrue(completion.call_args.kwargs['reasoning_enabled'])

    async def test_route_sends_module_prints_to_sse_session(self) -> None:
        log_id = uuid4()
        expected = {'choices': [{'message': {'content': 'hello'}}]}

        def print_progress(*args: object, **kwargs: object) -> dict[str, object]:
            print('[OPENAI_API][TEST][SUCCESS] progress reached SSE', flush=True)
            return expected

        request = web.ChatCompletionRequest(
            messages=[web.ChatMessage(role='user', content='hi')],
            log_id=log_id,
        )
        with patch('api.routers.openai_api.chat_completion', side_effect=print_progress):
            response = await web.create_chat_completion(request)

        events = [event async for event in stream_session(str(log_id))]
        self.assertEqual(response, expected)
        self.assertTrue(any('progress reached SSE' in event for event in events))
        self.assertTrue(any('event: done' in event for event in events))

    async def test_route_hides_provider_error_details(self) -> None:
        request = web.ChatCompletionRequest(messages=[web.ChatMessage(role='user', content='hi')])
        with patch('api.routers.openai_api.chat_completion', side_effect=OpenAIAPIError('private provider detail')):
            with self.assertRaises(HTTPException) as error:
                await web.create_chat_completion(request)
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn('private provider detail', error.exception.detail)


if __name__ == '__main__':
    unittest.main()
