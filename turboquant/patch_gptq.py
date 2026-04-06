import re

path = "setup.py"
txt = open(path).read()

txt = re.sub(
    r"def _detect_torch_version\([\s\S]*?\n\n",
    'def _detect_torch_version():\n    return "2.7.1"\n\n',
    txt
)

txt = re.sub(
    r"def _detect_cuda_arch_list\([\s\S]*?\n\n",
    'def _detect_cuda_arch_list():\n    return "7.5;8.0;8.6;8.9;9.0"\n\n',
    txt
)

open(path, "w").write(txt)