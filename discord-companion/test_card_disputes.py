from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from card_disputes import event_disputes, matches_event
from setup_discord import SetupError
from sync_discord import (ACTIVE_PROMOTIONS, DatabaseReader, card_payloads, fetch_data,
                          header_payload, publish_cycle, snapshot)

NOW = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)
EVENT = {"event_id": 42, "event_name": "BKFC 95 NEWARK HERRING vs DODSON",
         "event_date": "2026-10-17", "event_status": "upcoming", "promotions": {"name": "BKFC"}}
ISSUE = {"code": "CARD_SOURCE_OMISSION", "event_id": 42, "event_name": EVENT["event_name"],
         "event_date": "2026-10-17", "fight_ids": [9580, 9581]}


def fights():
    pairs = [(716, 1320, 'Jamel Herring', 1321, 'John Dodson'),
             (717, 1322, "Tony 'Loco' Soto", 1323, 'Anthony Pike'),
             (718, 1324, 'Gabrielle Roman', 1325, 'Brooke Evans'),
             (9245, 5381, 'Santo Curatolo', 5382, 'Anthony Yost'),
             (9247, 5385, 'Dalvin Blair', 5386, 'Paris Boyd'),
             (9498, 1398, 'Jimmie Rivera', 5634, 'Brandon Meyer'),
             (9499, 5635, 'Mike Medrano', 5636, 'Rob Emerson'),
             (9500, 5637, 'Phil Caracappa', 5638, 'Cole Cameron'),
             (9543, 5696, 'Dylan Pitt', 5380, 'Nicholas Saragosa'),
             (9580, 5754, 'Irakli Ghvinjilia', 5755, 'Jonathan Quiroz'),
             (9581, 5756, 'Jeff Lentz', 5757, 'Eduardo Peralta'),
             (9582, 5758, 'Noah Getahoun', 5759, 'Dustin Bailey')]
    return [{"fight_id": fid, "event_id": 42, "fight_order": i, "fight_status": "scheduled",
             "fighter_a_id": a, "fighter_b_id": b, "fighter_a": {"fighter_id": a, "full_name": an},
             "fighter_b": {"fighter_id": b, "full_name": bn}} for i, (fid, a, an, b, bn) in enumerate(pairs, 1)]


class MemoryPublisher:
    def __init__(self):
        self.state = {"events": {}, "posts": {}}
        self.setup = {"channels": {p: p for p in ACTIVE_PROMOTIONS} | {
            'upcoming': 'upcoming', 'archive': 'archive', 'this-week': 'index', 'archive-index': 'old-index'},
            "messages": {}}
        self.posts, self.blocks, self.calls = {}, {}, []

    def event_channel(self, event):
        self.state['events'].setdefault(str(event['event_id']), {})
        self.state['events'][str(event['event_id'])]['channel_id'] = str(event['event_id'])
        return {'id': str(event['event_id'])}

    def post(self, key, channel, payload, **kwargs):
        self.posts[key] = deepcopy(payload)

    def block(self, key, channel, payload, **kwargs):
        self.blocks[key] = deepcopy(payload)
        self.calls.append(key)

    def move(self, *args): pass
    def save(self): pass


class DisputeDisplayTests(unittest.TestCase):
    def test_bkfc_posts_all_saved_fights_and_marks_only_the_two_omissions(self):
        rows = fights()
        before = deepcopy(rows)
        payload = card_payloads(rows, disputes=[ISSUE])
        embed = payload[0]['embeds'][0]
        self.assertEqual(len(embed['fields']), 12)
        self.assertIn('Data dispute', embed['description'])
        marked = [f for f in embed['fields'] if f['name'].endswith('*')]
        self.assertEqual(len(marked), 2)
        self.assertIn('Irakli Ghvinjilia vs Jonathan Quiroz', marked[0]['value'])
        self.assertIn('Jeff Lentz vs Eduardo Peralta', marked[1]['value'])
        self.assertIn('Not on the latest source card', marked[0]['value'])
        self.assertEqual(rows, before)
        self.assertTrue(all(f['fight_status'] == 'scheduled' for f in rows))

    def test_event_header_warns_and_undisputed_cards_stay_unmarked(self):
        flagged = header_payload(EVENT, [], {}, [ISSUE])['embeds'][0]
        self.assertTrue(flagged['title'].endswith('*'))
        self.assertIn('Data dispute', flagged['description'])
        clean = card_payloads(fights())
        self.assertNotIn('Data dispute', str(clean))

    def test_warnings_are_scoped_to_the_saved_event_id(self):
        other = {**EVENT, 'event_id': 99}
        self.assertFalse(matches_event(ISSUE, other, fights()))
        legacy = {k: v for k, v in ISSUE.items() if k != 'event_id'}
        legacy['event_date'] = '2026-10-18'
        self.assertTrue(matches_event(legacy, EVENT, fights()))

    def test_an_unchecked_card_keeps_its_prior_warning_until_a_fresh_check(self):
        state = {'events': {'42': {'data_disputes': [ISSUE]}}}
        self.assertEqual(event_disputes({'card_disputes': [], 'checked_event_ids': [99]}, state, EVENT, fights()), [ISSUE])
        self.assertEqual(event_disputes({'card_disputes': [], 'checked_event_ids': [42]}, state, EVENT, fights()), [])

    def test_complete_publish_cycle_posts_warned_bkfc_and_clean_ufc_and_clears_on_review(self):
        publisher = MemoryPublisher()
        ufc = {'event_id': 99, 'event_name': 'UFC Upcoming Card', 'event_date': '2026-10-13',
               'event_status': 'upcoming', 'promotions': {'name': 'UFC'}}
        data = {'events': [EVENT, ufc], 'fights': fights(), 'research': [], 'odds': [],
                'links': [], 'bets': None, 'card_disputes': [ISSUE], 'checked_event_ids': [42, 99]}
        before = deepcopy(data)
        with patch('sync_discord.publish_bets'):
            publish_cycle(publisher, data, NOW)
            self.assertIn('Data dispute', str(publisher.blocks['event:42:card']))
            self.assertNotIn('Data dispute', str(publisher.blocks['event:99:card']))
            index = publisher.blocks['weekly-index'][0]['embeds'][0]['fields']
            self.assertTrue(next(f for f in index if 'BKFC' in f['name'])['name'].endswith('*'))
            self.assertFalse(next(f for f in index if 'UFC' in f['name'])['name'].endswith('*'))
            cached = {**data, 'card_disputes': [], 'checked_event_ids': [99]}
            publish_cycle(publisher, cached, NOW)
            self.assertIn('Data dispute', str(publisher.blocks['event:42:card']))
            reviewed = {**data, 'card_disputes': [], 'checked_event_ids': [42, 99]}
            publish_cycle(publisher, reviewed, NOW)
        self.assertNotIn('Data dispute', str(publisher.blocks['event:42:card']))
        self.assertEqual(publisher.state['events']['42']['data_disputes'], [])
        self.assertIn('Data dispute cleared', str(publisher.blocks))
        self.assertEqual(data, before)

    def test_an_older_bot_contract_or_missing_metadata_cannot_silently_publish(self):
        reader = DatabaseReader.__new__(DatabaseReader)
        for contract in ({'schema_version': 2, 'ready': True}, {'schema_version': 3, 'ready': True}):
            row = {'data_sync_run_id': 1, 'status': 'partial', 'finished_at': NOW.isoformat(),
                   'summary': {'run_mode': 'daily', 'requested_scope': 'all', 'publishable': True,
                               'publication_readiness': contract}}
            reader.rows = lambda *args: [row]
            with self.assertRaises(SetupError):
                reader.wait_for_daily_sync(NOW, timeout_seconds=0)

    def test_a_completed_daily_run_with_disputes_is_accepted(self):
        reader = DatabaseReader.__new__(DatabaseReader)
        row = {'data_sync_run_id': 1, 'status': 'partial', 'finished_at': NOW.isoformat(),
               'summary': {'run_mode': 'daily', 'requested_scope': 'all', 'publishable': True,
                           'publication_readiness': {'schema_version': 3, 'ready': True,
                                                    'disputes': [ISSUE], 'checked_event_ids': [42]}}}
        reader.rows = lambda *args: [row]
        self.assertEqual(reader.wait_for_daily_sync(NOW, timeout_seconds=0), row)

    def test_snapshot_read_carries_saved_review_metadata_into_the_posted_card(self):
        reader = DatabaseReader.__new__(DatabaseReader)
        reader.bet_owner_id = None
        row = {'data_sync_run_id': 1, 'status': 'partial', 'finished_at': NOW.isoformat(),
               'summary': {'publishable': True, 'publication_readiness': {'schema_version': 3,
                          'ready': True, 'disputes': [ISSUE], 'checked_event_ids': [42]}}}
        reader.latest_daily_sync = lambda *args: row
        reader.control_rpc = lambda *args: {'events': [EVENT], 'fights': fights()}
        data = fetch_data(reader, NOW, {})
        self.assertEqual(data['card_disputes'], [ISSUE])
        self.assertEqual(data['checked_event_ids'], [42])
        publisher = MemoryPublisher()
        with patch('sync_discord.publish_bets'):
            publish_cycle(publisher, data, NOW)
        self.assertIn('Irakli Ghvinjilia vs Jonathan Quiroz', str(publisher.blocks['event:42:card']))
        self.assertIn('Not on the latest source card', str(publisher.blocks['event:42:card']))

    def test_warning_metadata_and_snapshot_must_come_from_the_same_run(self):
        reader = DatabaseReader.__new__(DatabaseReader)
        reader.bet_owner_id = None
        base = {'status': 'partial', 'finished_at': NOW.isoformat(), 'summary': {'publishable': True,
                'publication_readiness': {'schema_version': 3, 'ready': True,
                                         'disputes': [ISSUE], 'checked_event_ids': [42]}}}
        rows = iter([{**base, 'data_sync_run_id': 1}, {**base, 'data_sync_run_id': 2}])
        reader.latest_daily_sync = lambda *args: next(rows)
        reader.control_rpc = lambda *args: {}
        with self.assertRaisesRegex(SetupError, 'data changed'):
            fetch_data(reader, NOW, {})

    def test_a_newer_unready_run_cannot_replace_an_earlier_successful_handshake(self):
        reader = DatabaseReader.__new__(DatabaseReader)
        reader.latest_daily_sync = lambda *args: {'status': 'failed', 'finished_at': NOW.isoformat(),
            'summary': {'publishable': False, 'publication_readiness': {'schema_version': 3,
                'ready': False, 'disputes': [], 'checked_event_ids': []}}}
        reader.control_rpc = lambda *args: self.fail('An unready snapshot must not be published')
        with self.assertRaisesRegex(SetupError, 'latest full dashboard refresh is not ready'):
            fetch_data(reader, NOW, {})


if __name__ == '__main__':
    unittest.main()
