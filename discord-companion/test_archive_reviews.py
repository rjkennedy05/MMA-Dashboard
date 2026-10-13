from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from test_card_disputes import MemoryPublisher
from sync_discord import publish_cycle


class Publisher(MemoryPublisher):
    def __init__(self):
        super().__init__()
        self.moves=[]
        self.state['archive_categories']=['archive']
    def channel(self,cid): return {'id':cid,'parent_id':'archive' if cid=='622' else 'upcoming'}
    def archive_destination(self): return 'archive'
    def move(self,channel,destination): self.moves.append((channel['id'],destination))


class ArchiveReviewTests(unittest.TestCase):
    def test_past_unresolved_card_archives_without_grading_or_losing_matchups(self):
        publisher=Publisher()
        old={'event_id':622,'event_name':'ONE 174','event_date':'2026-10-09',
             'event_status':'completed','promotions':{'name':'ONE'}}
        current={**old,'event_id':623,'event_name':'ONE 175','event_date':'2026-10-16','event_status':'upcoming'}
        rows=[{'fight_id':9507,'event_id':622,'fight_status':'scheduled','fighter_a_id':11,'fighter_b_id':12,
               'fighter_a':{'full_name':'A'},'fighter_b':{'full_name':'B'}}]
        publisher.state['events']['622']={'event':old,'channel_id':'622','archived':False}
        data={'events':[old,current],'fights':rows,'research':[],'odds':[],'links':[],'bets':None,
              'card_disputes':[],'checked_event_ids':[]}
        before=deepcopy(data)
        with patch('sync_discord.publish_bets'):
            publish_cycle(publisher,data,datetime(2026,10,13,13,tzinfo=timezone.utc))
        self.assertTrue(publisher.state['events']['622']['archived'])
        self.assertTrue(publisher.state['events']['622']['pending_results'])
        self.assertNotIn('ONE 174',str(publisher.blocks['weekly-index']))
        self.assertIn('ONE 174',str(publisher.blocks['archive-index']))
        self.assertIn('await review',str(publisher.blocks['archive-index']))
        self.assertEqual(data,before)
        resolved={**data,'fights':[{**rows[0],'fight_status':'completed','winner_id':11}],'checked_event_ids':[622]}
        with patch('sync_discord.publish_bets'):
            publish_cycle(publisher,resolved,datetime(2026,10,13,13,tzinfo=timezone.utc))
        self.assertFalse(publisher.state['events']['622']['pending_results'])
