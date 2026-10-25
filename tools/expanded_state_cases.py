"""Independent host contracts: simulated safety, restart recovery, and scheduling."""

SAFETY_TESTS = '''import unittest
import random
from implementation import Controller
class Checks(unittest.TestCase):
 def test_timeout_boundary(self):
  c=Controller();self.assertFalse(c.update(0,'idle'));self.assertTrue(c.update(10,'start'));self.assertTrue(c.update(109,'idle'));self.assertFalse(c.update(110,'idle'))
 def test_fault_latches_and_reset_does_not_start(self):
  c=Controller();c.update(0,'start');self.assertFalse(c.update(1,'start',True));self.assertFalse(c.update(2,'start'));self.assertFalse(c.update(3,'reset',True));self.assertFalse(c.update(4,'start'));self.assertFalse(c.update(5,'reset'));self.assertTrue(c.update(6,'start'))
 def test_repeat_start_cannot_extend_timeout(self):
  c=Controller();c.update(0,'start')
  for now in range(1,100):self.assertTrue(c.update(now,'start'))
  self.assertFalse(c.update(100,'start'));self.assertTrue(c.update(101,'start'))
 def test_stop_and_wrap(self):
  c=Controller();c.update(0xfffffff0,'start');self.assertTrue(c.update(83,'idle'));self.assertFalse(c.update(84,'idle'));c.update(85,'start');self.assertFalse(c.update(86,'stop'))
 def test_random_reference(self):
  r=random.Random(193);c=Controller();latched=False;start=None;now=0
  for _ in range(2000):
   now+=r.randrange(1,30);event=r.choice(['start','stop','reset','idle']);fault=r.randrange(20)==0
   if fault:latched=True;start=None
   elif latched:
    if event=='reset':latched=False
   elif start is not None and now-start>=100:start=None
   elif event in ('stop','reset'):start=None
   elif event=='start' and start is None:start=now
   self.assertEqual(c.update(now,event,fault),start is not None)
'''

JOURNAL_TESTS = '''import unittest
import random
from implementation import recover
def record(seq,value):return (seq,value,(seq^value^0x5a5a)&0xffff,True)
class Checks(unittest.TestCase):
 def test_empty_and_latest(self):
  self.assertEqual(recover([]),0);self.assertEqual(recover([record(1,9),record(3,22),record(2,15)]),22)
 def test_torn_write(self):
  self.assertEqual(recover([record(4,10),(5,999,0,False)]),10)
 def test_corruption_and_invalid_types(self):
  self.assertEqual(recover([record(1,8),(2,99,0,True),None,(),('3',4,7,True),(True,1,2,True)]),8)
 def test_counter_wrap(self):
  self.assertEqual(recover([record(0xfffffffe,10),record(0xffffffff,20),record(0,30),record(1,40)]),40)
 def test_duplicate_first_wins(self):
  self.assertEqual(recover([record(1,10),record(1,20)]),10)
 def test_random_power_cut_positions(self):
  r=random.Random(537)
  for _ in range(200):
   n=r.randrange(1,60);base=r.randrange(0xffffffff);records=[record((base+i)&0xffffffff,i+1) for i in range(n)]
   self.assertEqual(recover(records+[((base+n)&0xffffffff,999,0,False)]),n)
'''

SCHEDULER_TESTS = '''import unittest
from implementation import Scheduler
class Checks(unittest.TestCase):
 def test_exact_and_catchup(self):
  s=Scheduler(10,0);self.assertEqual(s.poll(9),0);self.assertEqual(s.poll(10),1);self.assertEqual(s.poll(45),3);self.assertEqual(s.poll(49),0);self.assertEqual(s.poll(50),1)
 def test_no_drift_over_many_delays(self):
  s=Scheduler(7,0);total=0
  for now in range(1,10001,13):total+=s.poll(now);self.assertEqual(total,now//7)
 def test_wrap(self):
  s=Scheduler(10,0xfffffff0);self.assertEqual(s.poll(4),2);self.assertEqual(s.poll(13),0);self.assertEqual(s.poll(14),1)
 def test_same_timestamp(self):
  s=Scheduler(1,0);self.assertEqual(s.poll(5),5);self.assertEqual(s.poll(5),0)
 def test_invalid(self):
  for v in (0,-1,True,1.5,2147483648):
   with self.assertRaises(ValueError):Scheduler(v,0)
'''

INTEGRATION_TESTS = '''import unittest
from implementation import System
def frame(cmd):return bytes([0xaa,cmd,cmd^0x5a,0x55])
class Checks(unittest.TestCase):
 def test_split_and_watchdog(self):
  s=System();self.assertFalse(s.update(0,b'\\xaa'));self.assertTrue(s.update(10,frame(1)[1:]));self.assertTrue(s.update(109,b''));self.assertFalse(s.update(110,b''))
 def test_physical_fault_wins_over_serial(self):
  s=System();self.assertFalse(s.update(0,frame(1),True));self.assertFalse(s.update(1,frame(3)+frame(1),True));self.assertFalse(s.update(2,frame(1)));self.assertFalse(s.update(3,frame(3)+frame(1)));self.assertTrue(s.update(4,frame(1)))
 def test_stop_wins_batch_order(self):
  for data in (frame(1)+frame(2),frame(2)+frame(1)):
   self.assertFalse(System().update(0,data))
 def test_corrupt_commands_ignored(self):
  s=System();self.assertFalse(s.update(0,bytes([0xaa,1,0,0x55])));self.assertTrue(s.update(1,frame(1)));self.assertTrue(s.update(50,frame(99)));self.assertFalse(s.update(101,frame(1)))
 def test_repeated_start_does_not_refresh(self):
  s=System();s.update(0,frame(1))
  for now in range(1,100):self.assertTrue(s.update(now,frame(1)))
  self.assertFalse(s.update(100,frame(1)))
'''

CASES = {
 'serial_safety_integration': (INTEGRATION_TESTS, '实现System.update(now_ms,data:bytes,fault=False)返回使能bool，初始关闭，串口分片缓冲。协议4字节AA cmd (cmd XOR 5A) 55，校验错丢一个字节重同步，合法帧消费4字节；未知cmd忽略；cmd1启动、2停止、3复位。每次解析全部收到帧，安全优先级：物理fault立即锁存关闭；原已锁存时本次只允许无fault且包含复位命令解除锁存，仍关闭不启动；正常运行elapsed>=100ms关闭且本次不启动；否则本批任意停止或复位优先关闭（无论帧顺序）；否则有启动且当前关闭才启动；运行中启动不刷新100ms计时。uint32模差计时，单次跨度<2^31。不访问外部状态。'),
 'safety_interlock': (SAFETY_TESTS, '实现Controller.update(now,event,fault=False)返回电机使能bool，初始关闭。uint32毫秒，模差处理回绕；start启动最长100ms，运行中重复start不得延期。优先级：fault立即关闭并锁存；已锁存时只有fault=False且reset解除锁存且本次仍关闭；正常运行满100ms优先关闭且本次不处理start；否则stop/reset关闭；闲置start启动；其余保持。不做硬件操作。'),
 'journal_recovery': (JOURNAL_TESTS, '实现recover(records)返回恢复的value或无有效记录返回0。纯内存模拟掉电日志，不访问文件。有效记录是4项tuple/list (seq,value,checksum,committed)，seq严格int 0..2^32-1，value严格int 0..9999，checksum严格int等于(seq XOR value XOR 0x5a5a)&0xffff，committed必须是True。其他记录忽略。新旧按uint32序列模差：0<((candidate-current)&0xffffffff)<2^31表示较新；相同seq保留首次。有效序列跨度保证<2^31。'),
 'periodic_scheduler': (SCHEDULER_TESTS, '实现Scheduler(period_ms,start_ms)，period必须严格int且1<=period<2^31，否则ValueError。poll(now)返回自上次已消费截止点以来到期次数（整数，允许一次多次追赶），始终基于原始周期不漂移；重复时间返回0。uint32时钟，用模差处理回绕，单次跨度<2^31；构造时不算立即到期。禁止外部操作。'),
}
