import unittest
from unittest.mock import patch
from types import SimpleNamespace
from api.providers.the_odds_api import client

class ClientConfigTests(unittest.TestCase):
    def test_odds_reads_require_only_the_provider_key_and_no_database_client(self):
        response=SimpleNamespace(content=b'[]',headers={},raise_for_status=lambda:None)
        with patch.dict('os.environ',{'THE_ODDS_API_KEY':'offline-key'},clear=True),patch.object(client.requests,'get',return_value=response) as get:
            rows,_=client.get_current_mma_moneylines()
        self.assertEqual(rows,[])
        self.assertFalse(hasattr(client,'supabase'))
        self.assertEqual(get.call_args.kwargs['params']['apiKey'],'offline-key')
