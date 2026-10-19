import unittest,tempfile,subprocess,shutil,os,json
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
class Harness(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='统一包 空格 '); self.root=Path(self.tmp.name)/'项目';shutil.copytree(SOURCE,self.root,ignore=shutil.ignore_patterns('.git'))
  self.run_cmd('git','init','-q');self.run_cmd('git','config','user.email','test@example.invalid');self.run_cmd('git','config','user.name','Fixture');self.run_cmd('git','config','commit.gpgsign','false')
 def tearDown(self):self.tmp.cleanup()
 def run_cmd(self,*cmd):return subprocess.run(cmd,cwd=self.root,capture_output=True,text=True)
 def check(self):return self.run_cmd('python3','工具/提交检查.py')
 def stage(self,name,text):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);self.run_cmd('git','add','--',name)
 def test_copy_and_hook_commit(self):
  self.assertEqual(self.run_cmd('python3','工具/维护.py','check').returncode,0)
  self.assertEqual(self.run_cmd('python3','工具/维护.py','install-hook').returncode,0)
  self.stage('正常 中文.txt','hello');self.assertEqual(self.run_cmd('git','commit','-qm','fixture').returncode,0)
  self.stage('.env','TEST=x');self.assertNotEqual(self.run_cmd('git','commit','-qm','blocked').returncode,0)
 def test_secret_redacted(self):
  fake='ghp_'+'F'*30;self.stage('带 空格.txt',fake);r=self.check();self.assertNotEqual(r.returncode,0);self.assertNotIn(fake,r.stdout+r.stderr)
 def test_env_example(self):
  self.stage('.env.example','API_KEY=your-key');self.assertEqual(self.check().returncode,0)
 def test_index_not_worktree(self):
  self.stage('code.txt','sk-proj-'+'X'*25);(self.root/'code.txt').write_text('safe');self.assertNotEqual(self.check().returncode,0)
 def test_delete_env_allowed(self):
  self.stage('.env','test');self.run_cmd('git','commit','-qm','fixture');self.run_cmd('git','rm','.env');self.assertEqual(self.check().returncode,0)
 def test_preserve_existing_hook(self):
  p=self.root/'.git/hooks/pre-commit';p.write_text('# old\n');r=self.run_cmd('python3','工具/维护.py','install-hook');self.assertEqual(r.returncode,2);self.assertEqual(p.read_text(),'# old\n')
 def test_preserve_custom_hook_path(self):
  self.run_cmd('git','config','core.hooksPath','custom');self.assertEqual(self.run_cmd('python3','工具/维护.py','install-hook').returncode,2)
 def test_refuse_generated_edit(self):
  p=self.root/'.agents/skills/sky-build/SKILL.md';p.write_text('user work');self.assertNotEqual(self.run_cmd('python3','工具/维护.py','sync').returncode,0);self.assertEqual(p.read_text(),'user work')
 def test_source_sync(self):
  p=self.root/'维护源/技能/sky-build/SKILL.md';p.write_text(p.read_text()+'\nsource edit\n');self.assertEqual(self.run_cmd('python3','工具/维护.py','sync').returncode,0);self.assertEqual(self.run_cmd('python3','工具/维护.py','check').returncode,0)
 def test_typecheck_failure(self):
  self.stage('package.json',json.dumps({'scripts':{'typecheck':'node -e "process.exit(1)"'}}));self.assertNotEqual(self.check().returncode,0)
 def test_typecheck_success(self):
  self.stage('package.json',json.dumps({'scripts':{'typecheck':'node -e "process.exit(0)"'}}));self.assertEqual(self.check().returncode,0)
 def test_legacy_entries_block_check_and_sync(self):
  for name in ('.claude/CLAUDE.md','.codex/hooks.json','.codex/hooks/old.sh','.claude/hooks/old.sh','.codex/evolution/signals.jsonl'):
   with self.subTest(name=name):
    p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('legacy')
    for action in ('check','sync'):
     self.assertNotEqual(self.run_cmd('python3','工具/维护.py',action).returncode,0)
    self.assertEqual(p.read_text(),'legacy');p.unlink()
    if name.endswith('old.sh') or name.endswith('signals.jsonl'):p.parent.rmdir()
 def test_host_hook_settings_block(self):
  for name in ('.claude/settings.json','.claude/settings.local.json'):
   p=self.root/name;p.write_text(json.dumps({'hooks':{'PreToolUse':[]}}))
   self.assertNotEqual(self.run_cmd('python3','工具/维护.py','check').returncode,0);p.unlink()
 def test_non_hook_settings_preserved(self):
  p=self.root/'.claude/settings.json';p.write_text(json.dumps({'permissions':{'deny':[]}}))
  self.assertEqual(self.run_cmd('python3','工具/维护.py','check').returncode,0);self.assertTrue(p.exists())
 def test_unknown_skill_blocked(self):
  p=self.root/'.claude/skills/old/SKILL.md';p.parent.mkdir();p.write_text('old')
  self.assertNotEqual(self.run_cmd('python3','工具/维护.py','check').returncode,0)
 def test_version_mismatch(self):
  p=self.root/'版本.json';p.write_text(json.dumps({'版本':'0.0.0'}))
  self.assertNotEqual(self.run_cmd('python3','工具/维护.py','check').returncode,0)
 def test_plain_talk_and_handoff_rules(self):
  agents=(self.root/'AGENTS.md').read_text();template=(self.root/'维护源/项目交接模板.md').read_text()
  for word in ('做了什么','对你有什么影响','要你做什么','PPT','PDF','Word','Excel','AI','HTML','MB','三样一起给','自动接力','技术附录（给 Agent）','用户已确认（2026-10-11）','「xhigh」（比最高少一级）','只用于汇报和总结','已有项目接续时报进度属于进度汇报，按三段','（以当前软件显示为准）','说给用户时先换白话','不必三段','还没上线','[开发循环]'):
   with self.subTest(word=word):self.assertIn(word,agents)
  for head in ('## 给用户','## 技术附录（给 Agent）'):
   with self.subTest(head=head):self.assertIn(head,template)
  self.assertLess(template.index('## 给用户'),template.index('## 技术附录（给 Agent）'))
 def test_dev_loop_rules(self):
  agents=(self.root/'AGENTS.md').read_text();build=(self.root/'.claude/skills/sky-build/SKILL.md').read_text();review=(self.root/'.claude/skills/sky-review/SKILL.md').read_text()
  plan=(self.root/'.agents/skills/sky-plan/templates/开发计划.md').read_text();handoff=(self.root/'维护源/项目交接模板.md').read_text()
  for word in ('[开发循环]','开工前确认','便宜档','聪明档','返修第 3 次（聪明档）','不重置次数','一路做完开发计划里的全部阶段','必须停下来找用户','开发循环不扩大授权','用户 2026-10-19 拍板（原话）','派工/','两边怎么派','照样走 sky-review','“已验证”只在 sky-review 通过后打','每多一轮都要他重新点头','不再派子代理'):
   with self.subTest(word=word):self.assertIn(word,agents)
  for text,word in ((build,'[开工前确认开发循环]'),(build,'[派工单怎么写（开发循环开着时）]'),(review,'返修阶梯'),(review,'不另用上面的“三次”'),(build,'派工单开头写明执行子代理的身份'),(plan,'- 开发循环：'),(handoff,'- 开发循环：')):
   with self.subTest(word=word):self.assertIn(word,text)
  self.assertLess(agents.index('[开发循环]'),agents.index('[技能]'))
if __name__=='__main__':unittest.main(verbosity=2)

