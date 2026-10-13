from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from api.sync.result_followup import ResultFollowupCache, select_followups, include_followups


class MissedResultTests(unittest.TestCase):
    def test_lfa_followup_uses_the_existing_detailed_url_and_a_valid_calendar_date(self):
        from api.providers.lfa.normalizer import dashboard_event_date, sherdog_event_url
        with tempfile.TemporaryDirectory() as path:
            cache = ResultFollowupCache(Path(path)/'state.json', datetime(2026,10,13,13,tzinfo=timezone.utc))
            result = select_followups([{'event_id':9,'event_name':'LFA 250','event_date':'2026-10-09',
                'promotions':{'name':'LFA'}}], [{'event_id':9,'fight_status':'scheduled'}],
                [{'entity_type':'event','internal_id':9,'source_id':9,'external_id':'lfa-250',
                  'external_url':'https://www.sherdog.com/events/LFA-250-99999'}], {9:'LFA Official / Sherdog'}, cache)
            event=result['lfa'][0]
            self.assertEqual(dashboard_event_date(event).isoformat(),'2026-10-09')
            self.assertEqual(sherdog_event_url(event),'https://www.sherdog.com/events/LFA-250-99999')

    def test_retry_limits_and_backoff_do_not_repeatedly_load_old_or_resolved_cards(self):
        with tempfile.TemporaryDirectory() as path:
            now=datetime(2026,10,13,13,tzinfo=timezone.utc)
            cache=ResultFollowupCache(Path(path)/'state.json',now)
            events=[{'event_id':i,'event_name':f'Card {i}','event_date':'2026-10-06',
                     'promotions':{'name':'UFC'}} for i in range(1,11)]
            fights=[{'event_id':i,'fight_status':'scheduled'} for i in range(1,11)]
            maps=[{'entity_type':'event','internal_id':i,'source_id':7,'external_id':str(i)} for i in range(1,11)]
            queued=select_followups(events,fights,maps,{7:'ESPN MMA'},cache,limit=3)
            self.assertEqual(sum(len(rows) for rows in queued.values()),3)
            cache.mark(1,failed=True)
            retry=ResultFollowupCache(cache.path,now)
            self.assertFalse(retry.due(1))
            from datetime import timedelta
            retry.now=now+timedelta(minutes=31)
            self.assertTrue(retry.due(1))

    def test_prior_week_cards_are_selected_without_reloading_finished_history(self):
        with tempfile.TemporaryDirectory() as path:
            cache = ResultFollowupCache(Path(path)/'state.json', datetime(2026,10,13,13,tzinfo=timezone.utc))
            events = [dict(event_id=83,event_name='DWCS Week 9',event_date='2026-10-06',
                event_start_time='2026-10-06T23:00:00Z',promotions={'name':'DWCS'}),
                dict(event_id=104,event_name='BKFC Bethlehem',event_date='2026-10-09',
                event_start_time='2026-10-10T00:00:00Z',promotions={'name':'BKFC'}),
                dict(event_id=622,event_name='ONE 174',event_date='2026-10-09',
                event_start_time='2026-10-09T11:30:00Z',promotions={'name':'ONE'}),
                dict(event_id=1,event_name='Completed',event_date='2026-10-08',promotions={'name':'UFC'})]
            fights = [dict(event_id=e['event_id'],fight_status='scheduled') for e in events[:-1]]
            fights.append(dict(event_id=1,fight_status='completed',winner_id=11))
            maps = [dict(entity_type='event',internal_id=e['event_id'],source_id=s,external_id=x)
                    for e,s,x in ((events[0],7,'600060740'),(events[1],10,'bkfc-fight-night-bethlehem'),
                                  (events[2],8,'one-friday-fights-174'),(events[3],7,'done'))]
            result = select_followups(events,fights,maps,{7:'ESPN MMA',10:'BKFC Official / MMAReg',8:'ONE Championship Official'},cache)
            self.assertEqual({s['_followup_event_id'] for q in result.values() for s in q},{83,104,622})
            cache.mark(622,source_complete=True)
            next_run = select_followups(events,fights,maps,{7:'ESPN MMA',10:'BKFC Official / MMAReg',8:'ONE Championship Official'},cache)
            self.assertNotIn('one_championship',next_run)

    def test_queue_is_bounded_and_merge_never_duplicates_the_listing(self):
        args = SimpleNamespace(result_followups={'bkfc':[{'external_id':'card','_followup_event_id':104}]})
        all_events,events=include_followups(args,'bkfc',[{'external_id':'card','name':'Correct'}],[{'external_id':'card'}])
        self.assertEqual(len(all_events),1);self.assertEqual(len(events),1)
        self.assertEqual(events[0]['name'],'Correct')
        self.assertEqual(events[0]['_followup_event_id'],104)
