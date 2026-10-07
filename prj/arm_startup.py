"""Reject ARM images linked with generic CRT instead of Zynq standalone startup."""
from pathlib import Path
import re


def verify_startup(link_map):
    text = Path(link_map).read_text(encoding='utf-8', errors='replace')
    # The linker map identifies the archive member that actually supplies _start.
    # A generic newlib crt0 can link successfully while skipping BSP timer setup
    # and replacing the exception/system stacks configured by boot.S.
    if re.search(r'[/\\]crt0\.o\b', text):
        raise ValueError('Generic ARM crt0 linked; rebuild using AMD Xilinx.spec: ' + str(link_map))
    for member in ('xil-crt0', 'cpu_init', 'boot', 'asm_vectors'):
        if not re.search(r'libxil\.a\([^)]*_' + re.escape(member) + r'\.o\)', text):
            raise ValueError('Missing Zynq BSP startup member ' + member + ': ' + str(link_map))
    return 'PASS'
