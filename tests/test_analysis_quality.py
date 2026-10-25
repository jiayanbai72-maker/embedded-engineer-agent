import unittest
from copy import deepcopy
from embedded_agent.analysis_quality import calculate, reference, validate

SOURCE='每通道每秒10000样本、8通道、每样本16位、连续保存30天、仅16MB存储，禁止压缩和丢样'


class QualityTests(unittest.TestCase):
    def test_units_and_dimensions(self):
        self.assertEqual(calculate([{'value':1,'unit':'MB'}], 'B'),1000000)
        self.assertEqual(calculate([{'value':1,'unit':'MiB'}], 'B'),1048576)
        self.assertAlmostEqual(calculate([{'value':200,'unit':'mAh'},{'value':720,'unit':'h','op':'divide'}],'mA'),200/720)
        with self.assertRaises(ValueError):calculate([{'value':1,'unit':'MB'}],'s')
        with self.assertRaises(ValueError):calculate([{'value':0,'unit':'s','op':'divide'}],'B/s')
        for value in (True, 'NaN', 'Infinity', '1e90'):
            with self.assertRaises(ValueError):calculate([{'value':value,'unit':'B'}],'B')

    def test_source_math_and_binary_storage(self):
        r=reference(SOURCE)
        self.assertEqual(r['capacity_B'],414720000000)
        self.assertAlmostEqual(r['capacity_GiB'],386.23809814453125)
        self.assertAlmostEqual(r['allowed_B_s'],16000000/2592000)
        self.assertEqual(r['storage_seconds'],100)
        self.assertTrue(r['storage_conflict'])
        self.assertEqual(reference(SOURCE.replace('16MB','16MiB'))['storage_B'],16777216)

    def test_unknown_or_ambiguous_not_guessed(self):
        for desc in ('普通温度计，容量未知',SOURCE+'也可能4通道',SOURCE.replace('10000样本','0样本')):
            self.assertEqual(reference(desc)['status'],'not_applicable')

    def test_regression_wrong_gib_and_rate_rejected_without_mutation(self):
        for claim in ('30天所需原始容量约395.5 GiB','可持续数据率上限约0.52 kB/s'):
            req={'requirements':[{'description':claim}],'questions':[]}
            before=deepcopy(req)
            with self.assertRaisesRegex(ValueError,'独立分析检查'):validate(SOURCE,req,{})
            self.assertEqual(req,before)
        for claim in ('30天所需原始容量约386.238 GiB','可持续数据率上限≈6.17 B/s'):
            self.assertEqual(validate(SOURCE,{'description':claim},{})['status'],'passed_supported_checks')

    def test_temporal_and_redundant_question_regressions(self):
        desc='传感器超过5秒无新数据停机，两次浇水之间至少间隔60秒，重放包不能续命'
        for req in ({'constraints':[{'value':'无数据计数6s作为判定'}]},
                    {'requirements':[{'acceptance':'相邻两次启动间隔≥60s'}]},
                    {'questions':[{'blocking':True,'question':'超时从新帧起算，还是任何重放帧的时刻？'}]},
                    {'questions':[{'blocking':True,'question':'200ms超时是否从最后一次被接受的新序号指令接收时刻起算？'}]}):
            with self.assertRaises(ValueError):validate(desc,req,{})
        self.assertEqual(validate(desc,{'questions':[{'blocking':True,'question':'明确重新启动的指令码是什么？'}]}, {})['status'],'passed_supported_checks')

    def test_correct_alternative_capacity_not_rejected(self):
        validate(SOURCE,{'description':'若改为1通道30天所需容量约51.84 GB，必须用户确认'}, {})
        validate(SOURCE,{}, {'description':'候选使用512 GB存储卡，未核实'})

    def test_wrong_interlock_and_invented_synchrony(self):
        with self.assertRaisesRegex(ValueError,'互斥'):
            validate('只能一个阀开启', {'acceptance':'三路同时为开的次数为0'}, {})
        with self.assertRaisesRegex(ValueError,'同步'):
            validate(SOURCE,{'requirements':[{'origin':'explicit','description':'8通道同步采样'}]}, {})
        with self.assertRaisesRegex(ValueError,'同步'):
            validate(SOURCE,{'requirements':[{'origin':'explicit','description':'8通道同步采集'}]}, {})
        validate(SOURCE,{'requirements':[{'origin':'proposed','description':'建议同步采样，待确认'}]}, {})

if __name__=='__main__':unittest.main()
