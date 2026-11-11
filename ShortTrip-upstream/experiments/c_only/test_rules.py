import unittest

try:
    from rules import audit, ticket_interval, meal_obligations
except ImportError:
    audit=ticket_interval=meal_obligations=None

def activity(kind,start,end,**extra):
    return dict(type=kind,start_time=start,end_time=end,**extra)

def plan(go,back,acts=(),lastday=1):
    days=[dict(day=1,activities=[go]+list(acts))]
    if lastday==1:
        days[0]['activities'].append(back)
    else:
        days.append(dict(day=lastday,activities=[back]))
    return dict(itinerary=days)

class Rules(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(audit,'Experimental rules not implemented')

    def test_noon_arrival_requires_lunch(self):
        p=plan(activity('train','08:00','12:00'),activity('train','19:00','21:00'))
        rows=meal_obligations(p)
        lunch=next(r for r in rows if r['kind']=='lunch')
        self.assertEqual(lunch['status'],'required')
        self.assertFalse(audit(p,1)['meal_pass'])

    def test_half_hour_remaining_is_traffic_exempt(self):
        p=plan(activity('train','08:00','13:30'),activity('train','19:00','21:00'))
        self.assertEqual(next(r for r in meal_obligations(p) if r['kind']=='lunch')['status'],'traffic_exempt')

    def test_partial_overlap_still_requires_meal(self):
        p=plan(activity('train','10:00','11:30'),activity('train','18:00','21:00'))
        self.assertEqual(next(r for r in meal_obligations(p) if r['kind']=='lunch')['status'],'required')

    def test_midnight_train_breakfast_required(self):
        p=plan(activity('train','22:00','08:00'),activity('train','19:00','21:00'),lastday=2)
        self.assertEqual(ticket_interval(p['itinerary'][0]['activities'][0],1)['end'],1920)
        self.assertEqual(next(r for r in meal_obligations(p) if r['day']==2 and r['kind']=='breakfast')['status'],'required')

    def test_equal_time_unknown_invalid(self):
        p=plan(activity('train','08:00','08:00'),activity('train','19:00','21:00'))
        self.assertFalse(audit(p,1)['date_pass'])

    def test_return_crosses_day_limit(self):
        p=plan(activity('train','06:00','07:00'),activity('train','22:00','08:00'))
        self.assertFalse(audit(p,1)['day_limit_pass'])

    def test_access_does_not_exempt(self):
        p=plan(activity('train','06:00','07:00'),activity('train','20:00','22:00',transports=[dict(start_time='11:00',end_time='19:00')]))
        self.assertEqual(next(r for r in meal_obligations(p) if r['kind']=='lunch')['status'],'required')

    def test_wrong_time_meal_does_not_pass(self):
        p=plan(activity('train','06:00','07:00'),activity('train','20:00','22:00'),[activity('lunch','15:00','16:00')])
        self.assertFalse(audit(p,1)['meal_pass'])

    def test_full_valid_meals(self):
        p=plan(activity('train','06:00','07:00'),activity('train','20:00','22:00'),[activity('breakfast','08:00','08:30'),activity('lunch','12:00','13:00'),activity('dinner','18:00','19:00')])
        self.assertTrue(audit(p,1)['all_pass'])

    def test_boundary_not_traffic_exemption(self):
        p=plan(activity('train','13:45','13:50'),activity('train','19:00','21:00'))
        self.assertEqual(next(r for r in meal_obligations(p) if r['kind']=='lunch')['status'],'boundary_not_applicable')

    def test_explicit_end_day_offset(self):
        self.assertEqual(ticket_interval(activity('train','08:00','09:00',end_day_offset=2),1)['end'],3420)

    def test_midnight_access_overlap_invalid(self):
        p=plan(activity('train','06:00','07:00'),activity('train','20:00','22:00'),[activity('attraction','10:00','11:00'),activity('lunch','12:00','13:00',transports=[dict(start_time='23:50',end_time='00:10')])])
        self.assertFalse(audit(p,1)['date_pass'])

    def test_midnight_access_gets_correct_actual_day(self):
        p=plan(activity('train','22:00','23:00'),activity('train','20:00','22:00'),lastday=2)
        p['itinerary'][0]['activities'].append(activity('attraction','23:05','23:40'))
        p['itinerary'][1]['activities'].insert(0,activity('attraction','00:20','01:00',transports=[dict(start_time='23:50',end_time='00:10')]))
        result=audit(p,2)
        self.assertTrue(result['date_pass'])
        self.assertEqual(result['access_timeline'][0]['start_day'],1)
        self.assertEqual(result['access_timeline'][0]['end_day'],2)

    def test_known_duration_over24hours(self):
        iv=ticket_interval(activity('train','08:00','10:30',duration_hours=26.5),1)
        self.assertEqual(iv['end_day'],2)

    def test_equal_clock_with_known24hours(self):
        iv=ticket_interval(activity('train','08:00','08:00',duration_hours=24),1)
        self.assertEqual(iv['end_day'],2)

    def test_catalog_duration_selects_date_without_rejecting_clock_noise(self):
        iv=ticket_interval(activity('train','17:20','23:14',duration_hours=6.03),1)
        self.assertEqual(iv['end_day'],1)
        self.assertEqual(iv['end'],1394)

    def test_large_duration_conflict_is_unknown(self):
        with self.assertRaises(ValueError):
            ticket_interval(activity('train','20:56','09:05',duration_hours=1.12),1)

if __name__=='__main__':
    unittest.main()
