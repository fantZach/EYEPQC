"""Verify an isolated Keccak build, capture one UART boot and audit its measurements."""
import argparse,hashlib,json,subprocess,time
from pathlib import Path
from datetime import datetime,timezone
import serial
def require(condition, message):
 if not condition:
  raise ValueError(message)

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--firmware',type=Path,required=True);p.add_argument('--variant',choices=['firmware_sw','firmware_hw'],required=True);p.add_argument('--label',required=True);a=p.parse_args()
require(a.label and Path(a.label).name==a.label and a.label not in ('.','..'), 'single run label required')
w=a.firmware.resolve();m=json.loads((w/'build_manifest.json').read_text(encoding='utf-8'));v=m['app_variants'][a.variant]
for obj in [*m['artifacts'].values(),*v['artifacts'].values()]:
 require(hashlib.sha256((w/obj['path']).read_bytes()).hexdigest()==obj['sha256'], 'manifest or run identity verification failed')
count=0
for key,base in [('bsp_generated_inputs_sha256',w),('vendored_mlkem_inputs_sha256',w/'vendor/mlkem'),('project_source_sha256',ROOT)]:
 for rel,expected in m[key].items():
  path=(base/rel).resolve();require(path.is_relative_to(base.resolve()), 'manifest path traversal')
  require(hashlib.sha256(path.read_bytes()).hexdigest()==expected, 'build input changed: '+rel)
  count+=1
for name,variant in m['app_variants'].items():
 for rel,expected in variant['generated_inputs_sha256'].items():
  require(hashlib.sha256((w/name/'include'/rel).read_bytes()).hexdigest()==expected, 'manifest or run identity verification failed')
  count+=1
 for obj in variant['artifacts'].values():
  require(hashlib.sha256((w/obj['path']).read_bytes()).hexdigest()==obj['sha256'], 'manifest or run identity verification failed')
  count+=1
for obj in m['artifacts'].values():
 require(hashlib.sha256((w/obj['path']).read_bytes()).hexdigest()==obj['sha256'], 'manifest or run identity verification failed')
 count+=1
require(hashlib.sha256((ROOT/m['xsa_repo_relative']).read_bytes()).hexdigest()==m['xsa_sha256'], 'manifest or run identity verification failed')
require(hashlib.sha256((w/'bsp/ps7_cortexa9_0/lib/libxil.a').read_bytes()).hexdigest()==m['bsp_archive_sha256'], 'manifest or run identity verification failed')
count+=2
folder=ROOT/'build/keccak_board_20261010'/a.label;folder.mkdir(parents=True)

raw=bytearray();start=time.monotonic()
with serial.Serial(port=None,baudrate=115200,timeout=0.1) as ser:
 ser.dtr=False;ser.rts=False;ser.port='COM14';ser.open();ser.reset_input_buffer()
 with (folder/'jtag_stdout.log').open('wb') as out,(folder/'jtag_stderr.log').open('wb') as err:
  proc=subprocess.Popen(['E:/fpg/2026.1/Vivado/bin/xsdb.bat',str(ROOT/'prj/run_keccak_benchmark_jtag.tcl'),str(w),a.variant],stdout=out,stderr=err)
  while time.monotonic()-start<120:
   block=ser.read(4096)
   if block:raw.extend(block)
   if b'KECCAK_BENCH_DONE' in raw and proc.poll() is not None:break
   if proc.poll() not in (None,0):break
  if proc.poll() is None:proc.kill();proc.wait()
  code=proc.returncode
(folder/'uart.log').write_bytes(raw)
text=raw.decode('utf-8',errors='replace')
record={'manifest_hash_checks':count,'status':'captured_complete' if code==0 and 'KECCAK_BENCH_DONE' in text else 'incomplete','variant':a.variant,'firmware_manifest_sha256':hashlib.sha256((w/'build_manifest.json').read_bytes()).hexdigest(),'elf_sha256':v['artifacts']['elf']['sha256'],'xsa_sha256':m['xsa_sha256'],'jtag_returncode':code,'elapsed_wall_seconds':time.monotonic()-start,'captured_utc':datetime.now(timezone.utc).isoformat(),'uart_sha256':hashlib.sha256(raw).hexdigest(),'uart_bytes':len(raw),'persistent_storage_written':False}
(folder/'capture_result.json').write_text(json.dumps(record,indent=2)+'\n')
from parse_keccak_board_benchmark import parse_log
if record['status']=='captured_complete':
 try:
  record['parsed']=parse_log(text.replace('\r',''),expected_counter_hz=m['cpu_clock_hz_from_new_xsa_bsp']//2,require_iteration_kat=True)
  require(record['parsed']['hardware_path_compiled']==v['hardware_path_compiled'], 'manifest or run identity verification failed')
  record['status']='passed'
 except (ValueError,AssertionError) as exc:
  record['status']='failed_audit';record['audit_error']=str(exc)
(folder/'capture_result.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record));print(text)
raise SystemExit(0 if record['status']=='passed' else 1)
