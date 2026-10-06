"""M05 routing/ownership checks, not a replacement for actual DMA/DDR tests."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_m02 import tool
from iverilog_runner import compile_iverilog
import importlib.util
import struct
from test_m04 import vivado_tool, run
ROOT=Path(__file__).resolve().parents[2]
class M05(unittest.TestCase):
    def test_native_integration_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            shutil.copyfile(ROOT/'src/rtl/camera/ov5640_jpeg.mem',work/'ov5640_jpeg.mem')
            sources=[*sorted((ROOT/'src/rtl/camera').glob('*.sv')),
                     ROOT/'src/rtl/common/axis_byte_packer.sv',ROOT/'src/rtl/common/axis_capture_route.sv',
                     ROOT/'sim/tb/tb_camera_dma_top.sv']
            xvlog=vivado_tool('xvlog')
            glbl=Path(xvlog).parent.parent/'data/verilog/src/glbl.v'
            run([xvlog,'--sv',*[str(s) for s in sources],str(glbl)],work)
            run([vivado_tool('xelab'),'tb_camera_dma_top','glbl','-L','xpm','-s','m05_native'],work)
            output=run([vivado_tool('xsim'),'m05_native','--runall'],work)
            self.assertIn('M05_NATIVE_PASS',output)
            print(next(line for line in output.splitlines() if 'M05_NATIVE_PASS' in line))

    def test_completed_owned_frame(self):
        spec=importlib.util.spec_from_file_location('m05_dma',ROOT/'src/host/m05_dma.py')
        host=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(host)
        image=b'\xff\xd8\x01\x02\xff\xd9'
        checksum=2166136261
        for byte in image: checksum=((checksum^byte)*16777619)&0xffffffff
        fields=dict(magic=0x35414d44,state=2,address=0x200000,length=6,checksum=checksum)
        blob=struct.pack('<32I',*(fields.get(key,0) for key in host.FIELDS))
        result=host.reply(blob)
        owned={'dma_frames':dict(address=0x200000,size=131200)}
        self.assertEqual(host.jpeg(image+b'\x00\x00',result,owned),image)
        for invalid in (blob[:-1],bytes(128)):
            with self.assertRaises(ValueError): host.reply(invalid)
        for data,change in ((image,{}),(image+b'\x00\x00',{'address':0x300000}),
                            (image+b'\x00\x00',{'length':65537}),
                            (image+b'\x00\x00',{'checksum':0}),
                            (b'xx'+image[2:]+b'\x00\x00',{})):
            with self.assertRaises(ValueError): host.jpeg(data,result|change,owned)

    def test_route_and_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            executable=work/'route.vvp'
            compile_iverilog([tool('iverilog'),'-g2012','-s','tb_axis_capture_route','-o',str(executable),
                str(ROOT/'src/rtl/common/axis_capture_route.sv'),str(ROOT/'sim/tb/tb_axis_capture_route.sv')], executable)
            out=subprocess.check_output([tool('vvp'),str(executable)],text=True,timeout=10)
            self.assertIn('AXIS_ROUTE_PASS',out)
            gcc=shutil.which('gcc') or 'C:/msys64/ucrt64/bin/gcc.exe'
            executable=work/'buffers.exe'
            subprocess.run([gcc,'-std=c99','-Wall','-Wextra','-Werror','-pedantic',
                '-I',str(ROOT/'src/ps/include'),str(ROOT/'sim/tb/test_dma_buffers.c'),'-o',str(executable)],check=True)
            out+=subprocess.check_output([str(executable)],text=True,timeout=10)
            self.assertIn('DMA_BUFFERS_PASS rounds=10000',out)
            print(out,end='')
if __name__=='__main__': unittest.main(verbosity=2)
