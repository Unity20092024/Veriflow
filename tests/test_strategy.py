import unittest
from dataclasses import replace
from veriflow.connectors import AccessDenied, CollectionError, Review
from veriflow.strategy import (
    preferences, select_unique, review_fingerprint, task_priority,
    resolve_discovered_product, queue_research, link_identity,
    bounded_task,
)


def review(key, text=None):
    return Review(key,'product','Software',text or 'Authentic review '+key,5,5,
                  '2026-11-15','https://example.org/review/'+key,'unused')


class Result:
    def __init__(self, rows=None, row=None):
        self.rows,self.row = rows or [],row
    def fetchall(self):
        return self.rows
    def fetchone(self):
        return self.row


class StrategyTests(unittest.TestCase):
    def test_default_and_optional_modes(self):
        self.assertEqual(preferences(),('breadth_first',5))
        self.assertEqual(preferences('balanced'),('balanced',10))
        self.assertEqual(preferences('depth_first'),('depth_first',30))
        self.assertEqual(preferences('depth_first','500'),('depth_first',500))
        for mode,target in [('bad',5),('breadth_first',0),('balanced',True),
                            ('balanced','abc'),('balanced',2.2),('balanced',10001)]:
            with self.assertRaises(CollectionError):
                preferences(mode,target)

    def test_duplicates_do_not_consume_small_unique_target(self):
        old = review('old')
        old_fingerprint,_ = review_fingerprint('product-id',old)
        selected,duplicates = select_unique(
            [old,old,review('one'),review('one'),review('two'),review('three')],
            [{'fingerprint':old_fingerprint,'external_id':'old','original_url':old.original_url}],
            'product-id',2)
        self.assertEqual([r['external_id'] for r in selected],['one','two'])
        self.assertEqual(duplicates,3)
        self.assertIn('review_text',selected[0])
        self.assertNotIn('text',selected[0])

    def test_full_page_does_not_override_breadth_target(self):
        selected,_ = select_unique([review(str(i)) for i in range(100)],[],'product',5)
        self.assertEqual(len(selected),5)

    def test_later_deeper_job_has_no_permanent_five_review_cap(self):
        selected,_ = select_unique([review(str(i)) for i in range(100)],[],'product',30)
        self.assertEqual(len(selected),30)

    def test_zero_allowance_does_not_queue_records(self):
        self.assertEqual(select_unique([review('one')],[],'product',0)[0],[])

    def test_licensed_authors_are_not_collapsed(self):
        one = replace(review('one'),license_metadata={
            'public_credit':'Author One','attribution_url':'https://example.org/one'})
        two = replace(one,external_id='two',original_url='https://example.org/two',
                      license_metadata={'public_credit':'Author Two',
                                        'attribution_url':'https://example.org/two'})
        self.assertNotEqual(review_fingerprint('product',one)[0],
                            review_fingerprint('product',two)[0])

    def test_breadth_then_category_rotation(self):
        self.assertLess(task_priority('breadth_first',0,5,1),
                        task_priority('breadth_first',1,0,2))
        self.assertLess(task_priority('breadth_first',0,0,2),
                        task_priority('breadth_first',0,5,1))
        self.assertLess(task_priority('balanced',4,0,2),
                        task_priority('balanced',5,0,1))
        self.assertLess(task_priority('depth_first',8,3,2),
                        task_priority('depth_first',1,0,1))

    def test_exact_normalized_and_confirmed_alias_identity(self):
        class DB:
            def execute(self,*args):
                return Result(rows=[{'name':'  Ｆｉｒｅｆｏｘ  ','root_id':'root'},
                                    {'name':'Mozilla Firefox','root_id':'root'}])
        self.assertEqual(resolve_discovered_product(DB(),'firefox'),'root')
        self.assertEqual(resolve_discovered_product(DB(),'Mozilla Firefox'),'root')
        self.assertIsNone(resolve_discovered_product(DB(),'Different product'))

    def test_ambiguous_names_are_not_guessed(self):
        class DB:
            def execute(self,*args):
                return Result(rows=[{'name':'Product','root_id':'one'},
                                    {'name':'PRODUCT','root_id':'two'}])
        with self.assertRaises(AccessDenied):
            resolve_discovered_product(DB(),'product')

    def test_zero_evidence_never_enters_research(self):
        class DB:
            writes = 0
            def execute(self,sql,*args):
                if sql.startswith('UPDATE'):
                    self.writes += 1
                return Result(row={'reviews':0})
        db=DB()
        with self.assertRaises(AccessDenied):
            queue_research(db,'00000000-0000-4000-8000-000000000001')
        self.assertEqual(db.writes,0)

    def test_self_link_cannot_corrupt_identity(self):
        with self.assertRaises(CollectionError):
            link_identity(None,'00000000-0000-4000-8000-000000000001',
                          '00000000-0000-4000-8000-000000000001')

    def test_bounded_discovery_and_breadth_rotation(self):
        class DB:
            def execute(self,sql,*args):
                return Result(rows=[
                    {'id':1,'kind':'review','evidence_count':4,'category_coverage':4},
                    {'id':2,'kind':'listing','evidence_count':0,'category_coverage':0},
                ])
        self.assertEqual(bounded_task(DB(),'new','breadth_first',5)['id'],2)
        self.assertEqual(bounded_task(DB(),'new','depth_first',30)['id'],1)

    def test_bounded_target_retires_only_new_strategy_tasks(self):
        class DB:
            writes = []
            def execute(self,sql,params=()):
                if sql.startswith('UPDATE'):
                    self.writes.append(params[0])
                    return Result()
                return Result(rows=[
                    {'id':1,'kind':'review','evidence_count':5,'category_coverage':1},
                    {'id':2,'kind':'review','evidence_count':1,'category_coverage':1},
                ])
        db=DB()
        self.assertEqual(bounded_task(db,'new','breadth_first',5)['id'],2)
        self.assertEqual(db.writes,[1])


if __name__ == '__main__':
    unittest.main()
