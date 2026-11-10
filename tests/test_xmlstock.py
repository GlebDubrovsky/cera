"""Offline tests for XMLStock request validation, client, and HTTP adapter."""

from __future__ import annotations

import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

import requests
from fastapi import HTTPException

from api.routers import xmlstock as web
from modules.xmlstock import XMLStockAPIError, XMLStockConfigurationError, XMLStockInputError, request_xmlstock
from modules.xmlstock.settings import get_settings
from modules.xmlstock.validation import validate_request


class XMLStockSettingsTests(unittest.TestCase):
    def test_reads_server_credentials_and_timeout(self) -> None:
        values = {'XMLSTOCK_USER': 'account-id', 'XMLSTOCK_KEY': 'private-key', 'XMLSTOCK_TIMEOUT_SECONDS': '12'}
        with patch.dict(os.environ, values, clear=True):
            settings = get_settings()
        self.assertEqual(settings.user, 'account-id')
        self.assertEqual(settings.key, 'private-key')
        self.assertEqual(settings.timeout_seconds, 12)

    def test_missing_credentials_are_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(XMLStockConfigurationError):
            get_settings()


class XMLStockValidationTests(unittest.TestCase):
    def test_wordstat_regions_tree_does_not_require_query(self) -> None:
        params, output_format, method = validate_request(
            'yandex_wordstat', {'pagetype': 'regionsTree'}, 'json', 'GET'
        )
        self.assertEqual(params, {'pagetype': 'regionsTree'})
        self.assertEqual((output_format, method), ('json', 'GET'))

    def test_wordstat_history_accepts_documented_filters(self) -> None:
        params, _, _ = validate_request(
            'yandex_wordstat',
            {'query': 'пример', 'pagetype': 'history', 'period': 'week', 'start': '01.01.2026',
             'end': '31.01.2026', 'device': 'desktop,mobile', 'regions': '213,-2'},
            'json', 'GET',
        )
        self.assertEqual(params['period'], 'week')
        self.assertEqual(params['regions'], '213,-2')

    def test_proxy_supports_post_but_not_json(self) -> None:
        _, _, method = validate_request('yandex_xml_proxy', {'query': 'фраза'}, 'xml', 'POST')
        self.assertEqual(method, 'POST')
        with self.assertRaises(XMLStockInputError):
            validate_request('yandex_xml_proxy', {'query': 'фраза'}, 'json', 'GET')

    def test_live_html_requires_turbo_mode(self) -> None:
        with self.assertRaises(XMLStockInputError):
            validate_request('yandex_live', {'query': 'фраза'}, 'html', 'GET')
        normalized, _, _ = validate_request(
            'yandex_live', {'query': 'фраза', 'tbm': 'turbo'}, 'html', 'GET'
        )
        self.assertEqual(normalized['tbm'], 'turbo')

    def test_google_range_is_accepted_and_unknown_parameters_are_rejected(self) -> None:
        tbs = 'cdr:1,cd_min:01/01/2026,cd_max:31/12/2026'
        normalized, _, _ = validate_request(
            'google_xml_search', {'query': 'python', 'tbs': tbs}, 'json', 'GET'
        )
        self.assertEqual(normalized['tbs'], tbs)
        with self.assertRaises(XMLStockInputError):
            validate_request('google_xml_search', {'query': 'python', 'extra': '1'}, 'json', 'GET')

    def test_invalid_numeric_parameters_are_rejected(self) -> None:
        with self.assertRaises(XMLStockInputError):
            validate_request('yandex_xml_proxy', {'query': 'фраза', 'groupby': '11'}, 'xml', 'GET')
        with self.assertRaises(XMLStockInputError):
            validate_request('yandex_wordstat', {'query': 'фраза', 'groupby': '2001'}, 'json', 'GET')


class XMLStockClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = {'XMLSTOCK_USER': 'account-id', 'XMLSTOCK_KEY': 'private-key'}

    def make_response(self, body: str = '<response>ok</response>', status_code: int = 200) -> Mock:
        response = Mock()
        response.content = body.encode()
        response.text = body
        response.status_code = status_code
        response.headers = {'content-type': 'application/xml'}
        return response

    def test_get_request_uses_fixed_endpoint_and_masks_credentials(self) -> None:
        response = self.make_response('<result>private-key account-id</result>')
        with patch.dict(os.environ, self.environment, clear=True), \
                patch('modules.xmlstock.service.requests.get', return_value=response) as get, \
                redirect_stdout(StringIO()) as output:
            result = request_xmlstock('google_xml_search', {'query': 'python'}, output_format='json')

        self.assertEqual(result['body'], '<result>[скрыто] [скрыто]</result>')
        self.assertEqual(result['status_code'], 200)
        self.assertEqual(get.call_args.args[0], 'https://xmlstock.com/google/json/')
        self.assertEqual(get.call_args.kwargs['params']['key'], 'private-key')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        self.assertNotIn('private-key', output.getvalue())

    def test_proxy_post_sends_form_parameters(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True), \
                patch('modules.xmlstock.service.requests.post', return_value=self.make_response()) as post, \
                redirect_stdout(StringIO()):
            result = request_xmlstock('yandex_xml_proxy', {'query': 'купить окна'}, method='POST')
        self.assertEqual(result['method'], 'POST')
        self.assertEqual(post.call_args.args[0], 'https://xmlstock.com/yandex/xml/')
        self.assertEqual(post.call_args.kwargs['data']['query'], 'купить окна')
        self.assertEqual(post.call_args.kwargs['data']['user'], 'account-id')

    def test_upstream_error_status_and_body_are_returned(self) -> None:
        response = self.make_response('<error>invalid query</error>', 422)
        with patch.dict(os.environ, self.environment, clear=True), \
                patch('modules.xmlstock.service.requests.get', return_value=response), \
                redirect_stdout(StringIO()):
            result = request_xmlstock('yandex_live', {'query': 'test'}, output_format='xml')
        self.assertEqual(result['status_code'], 422)
        self.assertIn('invalid query', result['body'])

    def test_network_errors_are_sanitized(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True), \
                patch('modules.xmlstock.service.requests.get', side_effect=requests.Timeout('private-key')), \
                redirect_stdout(StringIO()) as output:
            with self.assertRaises(XMLStockAPIError):
                request_xmlstock('yandex_wordstat', {'query': 'test'}, output_format='json')
        self.assertNotIn('private-key', output.getvalue())

    def test_invalid_input_does_not_make_network_request(self) -> None:
        with patch('modules.xmlstock.service.requests.get') as get:
            with self.assertRaises(XMLStockInputError):
                request_xmlstock('yandex_wordstat', {'query': 'test'}, output_format='xml')
        get.assert_not_called()


class XMLStockRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_calls_public_entrypoint_with_modes_and_parameters(self) -> None:
        expected = {'status_code': 200, 'body': 'ok'}
        request = web.XMLStockRequest(params={'query': 'test'}, output_format='json', method='GET')
        with patch('api.routers.xmlstock.request_xmlstock', return_value=expected) as requester:
            response = await web.execute_xmlstock_request('google_xml_search', request)
        self.assertEqual(response, expected)
        self.assertEqual(requester.call_args.kwargs['output_format'], 'json')

    async def test_route_hides_provider_diagnostics(self) -> None:
        request = web.XMLStockRequest(params={'query': 'test'})
        with patch('api.routers.xmlstock.request_xmlstock', side_effect=XMLStockAPIError('private detail')):
            with self.assertRaises(HTTPException) as error:
                await web.execute_xmlstock_request('google_xml_search', request)
        self.assertEqual(error.exception.status_code, 502)
        self.assertNotIn('private detail', error.exception.detail)


if __name__ == '__main__':
    unittest.main()
